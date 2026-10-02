"""GPU 录制端（trace --gpu）的导入端：cu-<pid>-<t0>.log → 计数和 span。

两件事分开，后一件不拖累前一件：
  计数（counts）  每个 kernel 都算：次数、GPU 上跑了多久，按发起的时刻（没录到启动调用的按开始跑的时刻）落进阶段。
                  只看 cu 日志，不靠时序事件——时序事件到了行数上限、整理失败、根本没录，kernel 的次数和 GPU 时间照样是全的。
  调用方（attach） 发起它的那次启动调用（cudaLaunchKernel、cuLaunchKernel、cudaGraphLaunch…）在哪个系统线程上、什么时候；
                  events.pair 重放事件时在那一刻看这个线程真实的调用栈，栈顶（正在执行、没挂起的）那个仓库函数就是调用方
                  （用户 10-02 定的：不经静态的 C 链去补）。看不到的（启动的线程上那一刻没有仓库函数、在事件截断之后、没录事件）
                  只算次数，没有调用边，记进 unattached。

被调方（kernel）的键：
  仓库里定义的 kernel（扫描端标了 k = kernel 的符号，按限定名对）     <文件>:<定义行>，和 Python 函数一样
  仓库外的（PyTorch、cuBLAS、Triton……）                               ?gpu/<名字>:0，都落到「GPU · 仓库外」这个虚拟节点上（cut.VIRTUAL_GPU）
名字是 CUPTI 给的还原后的名字去掉返回类型、模板参数、参数表（`void at::native::reduce_kernel<…>(…)` → `at::native::reduce_kernel`）。

用法（runs）：g = Gpu(日志, mono0_ns, resolver(符号表), phase_at)；g.counts() 加进计数；events.build(…, gpu=g) 重放时
按 g.probes 找调用方、调 g.attach 拿 GPU 的行；之后 g.edges 是调用边的计数、g.summary() 是摘要。
"""
from __future__ import annotations

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


def _ph() -> dict:
    return {"funcs": {}, "func_edges": {}, "func_lines": {}, "gpu_us": {}}


class Gpu:
    """一个 run 的全部 GPU 日志。kernels：[(编号, pid, 起 ns, 止 ns, 设备, 流, 键, 启动调用 (起 ns, 系统线程号) 或 None)]"""

    def __init__(self, logs: list[Path], mono0_ns: int | None, resolve, phase_at):
        self.base = mono0_ns or 0
        self.phase_at = phase_at
        self.names: dict[str, str] = {}
        self.kernels: list[tuple] = []
        self.dropped = 0
        for path in sorted(logs, key=lambda p: p.name):
            log = parse(path)
            self.dropped += log["dropped"]
            if log["pid"] is None:
                continue
            for start, end, dev, stream, corr, name in log["kernels"]:
                key, qname = resolve(name)
                self.names[key] = qname
                api = log["api"].get(corr)
                self.kernels.append((len(self.kernels), log["pid"], start, end, dev, stream, key,
                                     (api[0], api[2]) if api else None))
        self.found: dict[int, tuple] = {}         # 编号 → (调用方键, 发起它的线程号, 父 span 的号, 父 span 的深度)：attach 填
        self.edges: dict[str, dict] = {}          # 阶段 → {func_edges, func_lines}：attach 填，events.build 成功之后才加进计数

    def _t_us(self, k: tuple) -> int:
        """发起的时刻（µs，相对 run 起点）；没录到启动调用的用开始跑的时刻"""
        return ((k[7][0] if k[7] else k[2]) - self.base) // 1000

    def counts(self) -> dict:
        """{阶段: {funcs: {kernel 键: 次数}, gpu_us: {kernel 键: µs}}}：每个 kernel 都算，不管找没找到调用方"""
        out: dict[str, dict] = {}
        for k in self.kernels:
            ph = out.setdefault(self.phase_at(self._t_us(k)), {"funcs": {}, "gpu_us": {}})
            key = k[6]
            ph["funcs"][key] = ph["funcs"].get(key, 0) + 1
            ph["gpu_us"][key] = ph["gpu_us"].get(key, 0) + max(0, (k[3] - k[2]) // 1000)
        return out

    def probes(self) -> dict[int, list]:
        """{pid: [(启动调用的时刻 ns（monotonic，绝对）, 系统线程号, 编号)]}：events.pair 重放时在这些时刻看栈"""
        out: dict[int, list] = {}
        for k in self.kernels:
            if k[7]:
                out.setdefault(k[1], []).append((k[7][0], k[7][1], k[0]))
        return out

    def attach(self, found: dict, keys: list[str], kidx: dict) -> dict:
        """found：{编号: (调用方键, 线程号, 父 span 的号, 父 span 的深度)}（events.build 重放出来的）→ {pid: [GPU 的行]}。
        行是 [发起时刻, 到跑完的时长, 线程号, 深度, 调用方键下标, kernel 键下标, 1, 0, 父 span 的号, [设备, 流, 晚了多少 µs]]，
        keys / kidx 由这里往后加 kernel 的键。调用边按阶段记进 self.edges，调用行一律是 0（不知道是哪一行）"""
        self.found = found
        rows: dict[int, list] = {}
        for k in self.kernels:
            hit = found.get(k[0])
            if hit is None:
                continue
            caller, tid, parent, depth = hit
            key = k[6]
            if key not in kidx:
                kidx[key] = len(keys)
                keys.append(key)
            t = self._t_us(k)
            rows.setdefault(k[1], []).append(
                [t, max(0, (k[3] - self.base) // 1000 - t), tid, depth + 1, kidx[caller], kidx[key], 1, 0, parent,
                 [k[4], k[5], max(0, (k[2] - self.base) // 1000 - t)]])
            ph = self.edges.setdefault(self.phase_at(t), {"func_edges": {}, "func_lines": {}})
            pair = f"{caller}|{key}"
            ph["func_edges"][pair] = ph["func_edges"].get(pair, 0) + 1
            ph["func_lines"][f"{pair}|0"] = ph["func_lines"].get(f"{pair}|0", 0) + 1
        return rows

    def summary(self) -> dict:
        """run.json 的 gpu：{n_kernels, n_names, gpu_us, unattached（没找到调用方的，只算次数）, dropped, procs}"""
        return {"n_kernels": len(self.kernels), "n_names": len({k[6] for k in self.kernels}),
                "gpu_us": sum(max(0, (k[3] - k[2]) // 1000) for k in self.kernels),
                "unattached": len(self.kernels) - len(self.found), "dropped": self.dropped,
                "procs": sorted({k[1] for k in self.kernels})}

    def kernel_table(self) -> dict:
        """{kernel 键: {n, gpu_us}}：整个 run 的（events 的 index.json 里存一份）"""
        out: dict[str, dict] = {}
        for k in self.kernels:
            x = out.setdefault(k[6], {"n": 0, "gpu_us": 0})
            x["n"] += 1
            x["gpu_us"] += max(0, (k[3] - k[2]) // 1000)
        return out
