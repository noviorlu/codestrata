"""GPU 录制端（trace --gpu）的导入端：cu-<pid>-<t0>.log → 计数和 span。

每个 kernel 挂到发起它的那次调用上：GPU 录制端记下了启动调用（cudaLaunchKernel、cuLaunchKernel…）在哪个系统线程上、什么时候；
hook 的 U 行把系统线程号对回线程号（keys.json 的 native），在那条线程的 span 里找启动那一刻正在跑的最里层的
仓库函数，它就是调用方（用户 10-02 定的：不经静态的 C 链去补）。

被调方（kernel）的键：
  仓库里定义的 kernel（扫描端标了 k = kernel 的符号，按限定名对）     <文件>:<定义行>，和 Python 函数一样
  仓库外的（PyTorch、cuBLAS、Triton……）                               ?gpu/<名字>:0，都落到「GPU · 仓库外」这个虚拟节点上（cut.VIRTUAL_GPU）
名字是 CUPTI 给的还原后的名字去掉返回类型、模板参数、参数表（`void at::native::reduce_kernel<…>(…)` → `at::native::reduce_kernel`）。

产出（attach 返回）：
  rows    {pid: [span 行]}：和 CPU 的 span 同一种 9 列，t0 是**启动时刻**（时间顺序按发起排），dur 到 GPU 上跑完，
          tid 是发起它的线程、parent 是那一刻正在跑的 span、depth 比它深一层；第 10 列 [设备, 流, 晚了多少 µs 才开始在 GPU 上跑]
  counts  {阶段: {funcs, func_edges, func_lines, gpu_us}}：按启动时刻落进阶段；调用行是 0（不知道是哪一行：没录 Python 调进原生代码的那一跳）；
          gpu_us {kernel 键: 在 GPU 上一共跑了多少 µs}
  names   {键: 限定名}
  summary {kernels: {键: {n, gpu_us}}, unattached: 找不到调用方的 kernel 数, dropped: CUPTI 丢掉的记录数, procs: [pid]}
"""
from __future__ import annotations

import bisect
from pathlib import Path

from . import cut as _cut

VIRTUAL_PREFIX = _cut.VIRTUAL_GPU + "/"


def is_log(p: Path) -> bool:
    return p.name.startswith("cu-") and p.name.endswith(".log")


def parse(path: Path) -> dict:
    """读一个 cu 日志：{pid, t0, kernels: [(起, 止, 设备, 流, 关联号, 名字)], api: {关联号: (起, 止, 系统线程号)}, dropped}。坏行跳过"""
    out = {"pid": None, "t0": None, "kernels": [], "api": {}, "dropped": 0}
    try:
        pid_s, t0_s = path.name[len("cu-"):-len(".log")].split("-")[:2]
        out["pid"], out["t0"] = int(pid_s), int(t0_s)
    except ValueError:
        pass
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if not ln.endswith("\n"):
                continue
            try:
                head, _, rest = ln.rstrip("\n").partition("\t")
                p = head.split()
                if p[0] == "K":
                    name = rest.split("\t")[-1] if rest else "?"
                    out["kernels"].append((int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), name))
                elif p[0] == "A":
                    out["api"][int(p[4])] = (int(p[1]), int(p[2]), int(p[3]))
                elif p[0] == "D":
                    out["dropped"] += int(p[1])
                elif p[0] == "H":
                    out["pid"], out["t0"] = int(p[1]), int(p[2])
            except (IndexError, ValueError):
                continue
    return out


def kernel_name(demangled: str) -> str:
    """还原后的名字 → 限定名：去掉返回类型、模板参数、参数表"""
    s = demangled.strip()
    out, depth = [], 0
    for ch in s:                                  # 去掉 <…>（可以嵌套）
        if ch == "<":
            depth += 1
        elif ch == ">" and depth:
            depth -= 1
        elif not depth:
            out.append(ch)
    s = "".join(out)
    if s.endswith(")"):                           # 去掉最外层的参数表 (…)
        depth = 0
        for i in range(len(s) - 1, -1, -1):
            depth += s[i] == ")"
            depth -= s[i] == "("
            if depth == 0:
                s = s[:i]
                break
    s = s.strip()
    depth, cut_at = 0, -1                         # 返回类型：`void ns::k` → `ns::k`；括号里的空格（`(anonymous namespace)`）不算
    for i, ch in enumerate(s):
        depth += (ch == "(") - (ch == ")")
        if ch == " " and depth == 0:
            cut_at = i
    s = s[cut_at + 1:]
    return s or demangled


def resolver(symbols: dict):
    """名字 → (键, 限定名)：仓库里 k = kernel 的符号按限定名（或结尾一段相同）对上；对不上就是仓库外的虚拟键"""
    by_n: dict[str, str] = {}
    by_tail: dict[str, list] = {}
    for key, s in (symbols or {}).items():
        if s.get("k") == "kernel":
            loc = f"{s['f']}:{s['l']}"
            by_n[s["n"]] = loc
            by_tail.setdefault(s["n"].rsplit("::", 1)[-1], []).append((s["n"], loc))
    cache: dict[str, tuple[str, str]] = {}

    def resolve(name: str) -> tuple[str, str]:
        hit = cache.get(name)
        if hit:
            return hit
        q = kernel_name(name)
        if q in by_n:
            hit = (by_n[q], q)
        else:
            cands = [x for x in by_tail.get(q.rsplit("::", 1)[-1], []) if x[0].endswith("::" + q) or q.endswith("::" + x[0])]
            hit = (cands[0][1], cands[0][0]) if len(cands) == 1 else (f"{VIRTUAL_PREFIX}{q}:0", q)
        cache[name] = hit
        return hit
    return resolve


class _Active:
    """一条线程上某一时刻正在跑的最里层的 span。线程上的 span 是嵌套的（调用栈），按开始时刻排好后，从 t 往前找到的
    第一个还没结束的就是最里层的"""

    def __init__(self, rows: list):
        self.by_tid: dict[int, tuple[list, list]] = {}
        tmp: dict[int, list] = {}
        for i, r in enumerate(rows):
            if r is None:
                continue
            end = r[0] + r[1] if r[1] >= 0 else float("inf")
            tmp.setdefault(r[2], []).append((r[0], end, i))
        for tid, xs in tmp.items():
            xs.sort()
            self.by_tid[tid] = ([x[0] for x in xs], xs)

    def at(self, tid: int, t: float) -> int | None:
        hit = self.by_tid.get(tid)
        if not hit:
            return None
        starts, xs = hit
        i = bisect.bisect_right(starts, t) - 1
        while i >= 0:
            if xs[i][1] >= t:
                return xs[i][2]
            i -= 1
        return None


def attach(logs: list[Path], mono0_ns: int | None, pid_rows, keys: list[str], native: dict,
           resolve, phase_at) -> dict:
    """把 GPU 日志挂到 CPU 的 span 上。pid_rows(pid) → 这个进程的 span 行；keys 是 keys.json 的键表（会往后加 kernel 的键）；
    native 是 keys.json 的 native；resolve 见 resolver；phase_at(t_us) → 那一刻的阶段名"""
    kidx = {k: i for i, k in enumerate(keys)}
    out = {"rows": {}, "counts": {}, "names": {}, "summary": {"kernels": {}, "unattached": 0, "dropped": 0, "procs": []}}
    base = mono0_ns or 0
    for path in sorted(logs, key=lambda p: p.name):
        log = parse(path)
        out["summary"]["dropped"] += log["dropped"]
        pid = log["pid"]
        if pid is None or not log["kernels"]:
            continue
        out["summary"]["procs"].append(pid)
        rows = pid_rows(pid)
        active = _Active(rows)
        tid_of = {v: int(k) for k, v in (native.get(str(pid)) or {}).items()}
        new = out["rows"].setdefault(pid, [])
        for start, end, dev, stream, corr, name in log["kernels"]:
            key, qname = resolve(name)
            out["names"][key] = qname
            st = out["summary"]["kernels"].setdefault(key, {"n": 0, "gpu_us": 0})
            st["n"] += 1
            st["gpu_us"] += max(0, (end - start) // 1000)
            api = log["api"].get(corr)
            tid = tid_of.get(api[2]) if api else None
            t_launch = (api[0] - base) // 1000 if api else None
            parent = active.at(tid, t_launch) if tid is not None else None
            if parent is None:
                out["summary"]["unattached"] += 1
                continue
            p = rows[parent]
            caller = keys[p[5]]
            if key not in kidx:
                kidx[key] = len(keys)
                keys.append(key)
            t_end = (end - base) // 1000
            new.append([t_launch, max(0, t_end - t_launch), tid, p[3] + 1, p[5], kidx[key], 1, 0, parent,
                        [dev, stream, max(0, (start - base) // 1000 - t_launch)]])
            ph = out["counts"].setdefault(phase_at(t_launch), {"funcs": {}, "func_edges": {}, "func_lines": {}, "gpu_us": {}})
            ph["gpu_us"][key] = ph["gpu_us"].get(key, 0) + max(0, (end - start) // 1000)
            pair = f"{caller}|{key}"
            ph["funcs"][key] = ph["funcs"].get(key, 0) + 1
            ph["func_edges"][pair] = ph["func_edges"].get(pair, 0) + 1
            lk = f"{pair}|0"
            ph["func_lines"][lk] = ph["func_lines"].get(lk, 0) + 1
    return out
