"""主菜单（codestrata app）的测试：projects（清单、状态、浏览、补全）、jobs（录制表单、后台任务）、
app（HTTP：鉴权、扫描、录制、打开图）。在 CPU 假仓库上跑真的 scan / trace / serve。

    .venv/bin/python tests/test_app.py             # 全部
    .venv/bin/python tests/test_app.py http        # 只跑名字里带这些词的
"""
from __future__ import annotations

import http.client
import json
import shutil
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from common import FAKE, PY, cs, fresh, run_tests, tmpdir  # noqa: E402

from codestrata import app as app_mod  # noqa: E402
from codestrata import payload, projects, runs  # noqa: E402
from codestrata.jobs import Busy, JobManager, TraceSpec, scan_argv  # noqa: E402

PHASE = ["generate", "fakesvc.offline:Engine.generate"]
OFFLINE = f"{PY} -m fakesvc.offline"
# 先跑一点仓库里的代码、再等很久：用来测「停止」（录到了东西，run 收好是 partial，不是 failed）
SLOW = f"{PY} -c 'from fakesvc import work; work.init_model(); import time; time.sleep(60)'"


def unscanned() -> Path:
    d = tmpdir("cs-app-") / "repo"
    shutil.copytree(FAKE, d)
    return d


def wait(job, timeout: float = 120):
    end = time.time() + timeout
    while job.running:
        assert time.time() < end, f"任务 {job.id} {timeout}s 没结束：{list(job.lines)[-20:]}"
        time.sleep(0.1)
    return job


# ---------------------------------------------------------------- projects

def test_registry():
    reg = projects.Registry(tmpdir("cs-app-") / "cfg" / "projects.json")
    a, b = unscanned(), unscanned()
    assert reg.list() == []
    assert reg.add(a) == a.resolve() and reg.add(b) == b.resolve()
    assert reg.paths() == [b.resolve(), a.resolve()], reg.paths()          # 最近加的在前
    reg.add(a)                                                             # 已在清单里：挪到最前，不重复
    assert reg.paths() == [a.resolve(), b.resolve()]
    reg.touch(b)
    assert reg.paths()[0] == b.resolve() and reg.has(a.resolve())
    # 换一个 Registry 读同一个文件：持久化了
    assert projects.Registry(reg.path).paths() == [b.resolve(), a.resolve()]
    assert reg.remove(a.resolve()) and not reg.remove(a.resolve()) and reg.paths() == [b.resolve()]
    for bad in (a / "fakesvc" / "work.py", a / "nope"):
        try:
            reg.add(bad)
        except ValueError as e:
            assert "不是一个目录" in str(e)
        else:
            raise AssertionError(f"不是目录也加进去了：{bad}")
    projects.status(b)                                                     # 看状态也不碰仓库（不建 .codestrata/runs）
    assert not (a / ".codestrata").exists() and not (b / ".codestrata").exists()


def test_status_browse_symbols():
    raw, repo = unscanned(), fresh()
    s = projects.status(raw)
    assert s["exists"] and s["index"] is None and s["n_runs"] == 0, s
    s = projects.status(repo)
    assert s["index"]["n_files"] >= 5 and s["lag"] == 0, s
    (repo / "fakesvc" / "work.py").write_text((repo / "fakesvc" / "work.py").read_text() + "\n# changed\n")
    assert projects.status(repo)["lag"] == 1
    cs("trace", repo, "--case", "st", "--", PY, "-m", "fakesvc.offline")
    s = projects.status(repo)
    assert s["n_runs"] == 1 and s["runs"][0]["case"] == "st" and s["runs"][0]["status"] == "ok", s["runs"]
    assert projects.status(repo / "gone")["exists"] is False
    # runs/ 是软链、指向的盘没挂上：卡片上说一声，不能让整个项目列表出错
    dang = unscanned()
    (dang / ".codestrata").mkdir()
    (dang / ".codestrata" / "runs").symlink_to(dang / "not-mounted")
    s = projects.status(dang)
    assert s["runs_error"] and "软链" in s["runs_error"] and s["n_runs"] == 0, s

    b = projects.browse(str(repo.parent))
    names = {d["name"]: d for d in b["dirs"]}
    assert names["repo"]["scanned"] and b["parent"] == str(repo.parent.parent), b
    b = projects.browse(str(repo))
    assert b["here"]["scanned"] and ".codestrata" not in {d["name"] for d in b["dirs"]}, b   # 隐藏目录不列
    for bad in (str(repo / "fakesvc" / "work.py"), str(repo / "nope")):
        try:
            projects.browse(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"不是目录也列了：{bad}")

    got = projects.find_symbols(repo, "generate")
    assert got and got[0] == "fakesvc.offline:Engine.generate", got               # 名字正好是 q 的排前面
    assert projects.find_symbols(repo, "") == [] and projects.find_symbols(raw, "generate") == []
    # 正在重新 scan：symbols.json 写了一半，补全返回空，不报错
    half = unscanned()
    cs("scan", half)
    sp = half / ".codestrata" / "symbols.json"
    sp.write_text(sp.read_text()[:1000])
    assert projects.find_symbols(half, "generate") == []


# ---------------------------------------------------------------- jobs

def test_trace_spec():
    repo = fresh()
    syms = payload.load_index(repo)["symbols"]
    ok = TraceSpec(repo=str(repo), case="demo", command=OFFLINE, phases=[PHASE], env={"A": "1"})
    ok.validate(syms)
    for spec, want in [(TraceSpec(repo=str(repo), case="a b", command=OFFLINE), "case 名"),
                       (TraceSpec(repo=str(repo), case="x", command="  "), "要给出命令"),
                       (TraceSpec(repo=str(repo), case="x", command="python 'unclosed"), "解析不了"),
                       (TraceSpec(repo=str(repo), case="x", command=OFFLINE, phases=[["start", PHASE[1]]]), "start"),
                       (TraceSpec(repo=str(repo), case="x", command=OFFLINE,
                                  phases=[["g", "fakesvc.offline:Engin.generate"]]), "Engine.generate"),   # 带候选
                       (TraceSpec(repo=str(repo), case="x", command=OFFLINE, timeout=0), "超时")]:
        try:
            spec.validate(syms)
        except ValueError as e:
            assert want in str(e), (want, str(e))
        else:
            raise AssertionError(f"应该报错（{want}）：{spec}")
    for bad in ({"phases": "x"}, {"env": ["A=1"]}, {"timeout": "abc"}):
        try:
            TraceSpec.from_json({"case": "x", "command": OFFLINE, **bad})
        except ValueError:
            pass
        else:
            raise AssertionError(f"类型不对也收了：{bad}")
    # 值一律写成 --x=值：以 - 开头的备注不会被当成选项；命令按 shell 规则切
    s = TraceSpec(repo=str(repo), case="c", command=f"{OFFLINE} --flag 'a b'", phases=[PHASE],
                  env={"K": "v=1"}, timeout=30, events=False, note="-n", attach=["x.yaml"])
    assert s.argv() == [PY, "-u", "-m", "codestrata", "trace", str(repo), "--case=c", "--timeout=30",
                        f"--phase={PHASE[0]}={PHASE[1]}", "--env=K=v=1", "--attach=x.yaml", "--note=-n",
                        "--", PY, "-m", "fakesvc.offline", "--flag", "a b"], s.argv()
    # 复刻：从一个录下的 run 还原的表单，再录一次，录制参数和原来一样
    cs("trace", repo, "--case", "orig", "--events", "--timeout", "60", "--env", "FOO=bar", "--tag", "model=x",
       "--stop-grace", "5", "--roots", "fakesvc", "--phase", "=".join(PHASE), "--", PY, "-m", "fakesvc.offline")
    orig = next(r for r in runs.catalog(repo) if r["case"] == "orig")
    spec = TraceSpec.from_run(repo, orig)
    assert spec.command == f"{PY} -m fakesvc.offline" and spec.phases == [PHASE] and spec.env == {"FOO": "bar"}, spec
    assert spec.events and spec.timeout == 60 and TraceSpec.from_json(spec.to_json()) == spec
    assert spec.tags == ["model=x"] and spec.stop_grace == 5 and spec.roots == ["fakesvc"], spec
    spec.validate(syms)
    job = wait(JobManager().start("trace", str(repo), spec.argv()))
    assert job.returncode == 0, list(job.lines)
    again = next(r for r in runs.catalog(repo) if r["case"] == "orig" and r["id"] != orig["id"])
    for k in ("cmd", "env", "tags"):
        assert again[k] == orig[k], (k, again[k], orig[k])
    for k in ("timeout", "stop_grace", "roots", "events", "phase_at"):
        assert again["rec"][k] == orig["rec"][k], (k, again["rec"][k], orig["rec"][k])
    # 秒数原样写（:g 会把大数截成 6 位有效数字）
    assert "--timeout=1234567" in TraceSpec(repo=str(repo), case="t", command="x", timeout=1234567).argv()


def test_job_manager():
    raw = unscanned()
    done = []

    def on_done(job):                     # 在任务标成结束之前调：这时它还算「在跑」，写的说明会进输出
        done.append((job, job.running))
        job.add("回调写的一行")
    jm = JobManager(on_done=on_done)
    job = jm.start("scan", str(raw), scan_argv(raw))
    try:
        jm.start("scan", str(raw), scan_argv(raw))
    except Busy:
        pass
    else:
        raise AssertionError("同一个仓库同时起了两个任务")
    assert jm.active(str(raw)) is job
    wait(job)
    assert job.returncode == 0 and done == [(job, True)] and jm.active(str(raw)) is None
    snap = job.snapshot()
    assert snap["lines"][-1] == "回调写的一行", snap["lines"][-3:]
    assert snap["n"] == len(snap["lines"]) > 0 and any("扫描" in x for x in snap["lines"]), snap
    tail = job.snapshot(since=snap["n"] - 2)
    assert tail["from"] == snap["n"] - 2 and tail["lines"] == snap["lines"][-2:]
    assert (raw / ".codestrata" / "index.json").is_file()
    # 停：SIGINT 给 codestrata trace，它按三级顺序停掉被录的命令、把 run 收好
    long = jm.start("trace", str(raw), TraceSpec(repo=str(raw), case="long", command=SLOW).argv())
    time.sleep(2)
    t0 = time.time()
    assert jm.stop(long.id)
    wait(long, 40)
    assert time.time() - t0 < 30 and long.stopping and not jm.stop(long.id)
    r = next(r for r in runs.catalog(raw) if r["case"] == "long")
    assert r["status"] in ("ok", "partial") and r["stop"] == "interrupt" and r["summary"]["n_funcs"] > 0, r
    # 仓库目录没了：起不来，报 JobError（不是没头没尾的 OSError）
    from codestrata.jobs import JobError
    try:
        jm.start("scan", str(raw / "gone"), scan_argv(raw / "gone"))
    except JobError as e:
        assert not isinstance(e, Busy) and "起不来" in str(e)
    else:
        raise AssertionError("目录不在也起了任务")
    # 输出只留最后 MAX_LINES 行，行号照样往上数
    from codestrata import jobs as jobs_mod
    many = JobManager().start("scan", str(raw),           # 不带回调：回调会多写一行
                              [PY, "-c", f"print('\\n'.join(map(str, range({jobs_mod.MAX_LINES + 50}))))"])
    wait(many)
    s = many.snapshot(0)
    assert s["n"] == jobs_mod.MAX_LINES + 50 and s["from"] == 50 and s["lines"][0] == "50", (s["n"], s["from"])
    # 已经结束的任务每个仓库只留最近 KEEP_DONE 个
    for _ in range(jobs_mod.KEEP_DONE + 2):
        wait(jm.start("scan", str(raw), [PY, "-c", "pass"]))
    jm.start("scan", str(raw), [PY, "-c", "pass"])
    assert len(jm.for_repo(str(raw))) == jobs_mod.KEEP_DONE + 1, len(jm.for_repo(str(raw)))


# ---------------------------------------------------------------- app（HTTP）

class Client:
    def __init__(self, port: int, token: str | None = None):
        self.port, self.cookie = port, (f"{app_mod.COOKIE}={token}" if token else None)

    def req(self, method: str, path: str, body=None, host: str | None = None, header: bool = True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if self.cookie:
            h["Cookie"] = self.cookie
        if header:
            h[app_mod.HEADER] = "1"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw), r
        except ValueError:
            return r.status, raw.decode("utf-8", "replace"), r

    def job(self, snap: dict, timeout: float = 120) -> dict:
        end, lines = time.time() + timeout, []
        while True:
            st, j, _ = self.req("GET", f"/api/jobs/{snap['id']}?since={len(lines)}")
            assert st == 200, j
            lines += j["lines"]
            if not j["running"]:
                return {**j, "lines": lines}
            assert time.time() < end, lines[-20:]
            time.sleep(0.2)


def test_app_http():
    from codestrata.viewers import free_port
    port = free_port()
    a = app_mod.make_app(port, config=tmpdir("cs-app-") / "cfg")
    app_mod.AppHandler.app = a
    srv = ThreadingHTTPServer(("127.0.0.1", port), app_mod.AppHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    raw = unscanned()
    try:
        anon, c = Client(port), Client(port, a.token)
        # 鉴权：Host 不对、没 cookie、没 X-Codestrata 头，一律 403
        assert c.req("GET", "/api/projects", host="evil.example:80")[0] == 403
        assert anon.req("GET", "/api/projects")[0] == 403
        assert c.req("GET", "/api/projects", header=False)[0] == 403
        assert Client(port, "wrong").req("GET", "/api/projects")[0] == 403
        assert Client(port, "é").req("GET", "/api/projects")[0] == 403              # 非 ASCII：拒绝，不断连接
        assert anon.req("GET", "/?t=%C3%A9")[0] == 200
        # 127.0.0.1 上别的服务设的、格式古怪的 cookie 排在前面，照样认得出口令
        weird = Client(port)
        weird.cookie = f'k={{"a":1}}; x=y z; {app_mod.COOKIE}={a.token}'
        assert weird.req("GET", "/api/projects")[0] == 200
        assert c.req("POST", "/api/nope", {})[1] == {"error": "not found"}
        # 用启动时的链接打开一次：设 cookie、跳回 /；之后 / 就是主菜单
        st, _, r = anon.req("GET", f"/?t={a.token}")
        assert st == 303 and r.getheader("Location") == "/" and "SameSite=Strict" in r.getheader("Set-Cookie")
        assert "请用启动" in anon.req("GET", "/")[1] and 'id="addBtn"' in c.req("GET", "/")[1]
        # 加项目；不在清单里的仓库不能扫、不能录、不能开
        assert c.req("POST", "/api/scan", {"repo": str(raw)})[0] == 404
        st, card, _ = c.req("POST", "/api/projects", {"path": str(raw)})
        assert st == 200 and card["index"] is None and card["job"] is None, card
        assert c.req("POST", "/api/projects", {"path": str(raw / "nope")})[0] == 400
        assert c.req("POST", "/api/open", {"repo": str(raw)})[0] == 500           # 没 scan 过：serve 起不来，报原因
        # 扫描
        st, snap, _ = c.req("POST", "/api/scan", {"repo": str(raw)})
        assert st == 200 and snap["kind"] == "scan", snap
        assert c.req("POST", "/api/scan", {"repo": str(raw)})[0] == 409            # 同一个仓库同时只跑一个
        assert c.req("POST", "/api/trace", {"repo": str(raw), "case": "t", "command": OFFLINE})[0] == 409
        # 有任务在跑时先回 409，不去读（可能正被扫描重写的）索引、不校验表单
        assert c.req("POST", "/api/trace", {"repo": str(raw), "case": "t", "command": OFFLINE,
                                           "phases": [["g", "fakesvc.offline:Nope.x"]]})[0] == 409
        j = c.job(snap)
        assert j["returncode"] == 0 and any("扫描" in x for x in j["lines"]), j
        st, cards, _ = c.req("GET", "/api/projects")
        assert cards[0]["index"]["n_files"] >= 5 and cards[0]["job"]["returncode"] == 0, cards
        # 补全、录制（表单错了当场报；对了就起任务）、从 run 还原表单
        assert c.req("GET", f"/api/symbols?repo={raw}&q=generate")[1][0] == PHASE[1]
        st, e, _ = c.req("POST", "/api/trace", {"repo": str(raw), "case": "t", "command": OFFLINE,
                                               "phases": [["g", "fakesvc.offline:Nope.x"]]})
        assert st == 400 and "Nope" in e["error"], e
        st, snap, _ = c.req("POST", "/api/trace", {"repo": str(raw), "case": "t", "command": OFFLINE,
                                                  "phases": [PHASE], "env": {"FOO": "1"}})
        assert st == 200, snap
        assert c.job(snap)["returncode"] == 0
        st, cards, _ = c.req("GET", "/api/projects")
        rid = cards[0]["runs"][0]["id"]
        assert cards[0]["n_runs"] == 1 and cards[0]["runs"][0]["phases"] == ["start", "generate"], cards[0]["runs"]
        st, t, _ = c.req("GET", f"/api/template?repo={raw}&run={rid}")
        assert t["command"] == OFFLINE and t["phases"] == [PHASE] and t["env"] == {"FOO": "1"}, t
        assert c.req("GET", f"/api/template?repo={raw}")[1]["case"] == "demo"
        # 打开图：起 serve（带 --home），页面能拿到主菜单地址
        st, o, _ = c.req("POST", "/api/open", {"repo": str(raw)})
        assert st == 200 and o["url"].startswith("http://127.0.0.1:"), o
        vport = int(o["url"].rsplit(":", 1)[1].strip("/"))
        assert _get_json(vport, "/api/app") == {"home": f"http://127.0.0.1:{port}/"}
        assert _status(vport, "GET", "/api/app", host="evil.example") == 403          # 图服务自己也挡 DNS rebinding
        assert c.req("POST", "/api/open", {"repo": str(raw)})[1]["url"] == o["url"]     # 再点一次：复用
        assert "fakesvc.newmod" not in _node_ids(vport)
        # 重新扫描：图服务在原端口重启、读到新的 index（开着的标签刷新一下就是新的）
        (raw / "fakesvc" / "newmod.py").write_text("def f():\n    return 1\n")
        c.job(c.req("POST", "/api/scan", {"repo": str(raw)})[1])
        assert "fakesvc.newmod" in _node_ids(vport)
        # 有任务在跑的项目不能移除；移除后图服务也停了，仓库里的东西都还在
        long = c.req("POST", "/api/trace", {"repo": str(raw), "case": "long",
                                            "command": SLOW})[1]
        assert c.req("DELETE", f"/api/projects?path={raw}")[0] == 409
        c.req("POST", f"/api/jobs/{long['id']}/stop", {})
        c.job(long, 40)
        st, rm, _ = c.req("DELETE", f"/api/projects?path={raw}")
        assert st == 200 and rm["removed"] and c.req("GET", "/api/projects")[1] == []
        assert not _listening(vport) and (raw / ".codestrata" / "index.json").is_file()
    finally:
        srv.shutdown()
        a.jobs.stop_all()
        a.viewers.stop_all()


def _listening(port: int) -> bool:
    try:
        _get_json(port, "/api/app")
        return True
    except OSError:
        return False


def _node_ids(port: int) -> set:
    """图服务默认切面上的节点；fake 仓库小，默认全展开到文件"""
    return {n["id"] for n in _get_json(port, "/api/graph")["graph"]["nodes"]}


def _status(port: int, method: str, path: str, body: bytes | None = None, host: str | None = None) -> int:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers={"Host": host or f"127.0.0.1:{port}"})
    st = c.getresponse().status
    c.close()
    return st


def test_serve_guard_and_home():
    """直接 serve（不是主菜单起的）：/api/app 的 home 是 null；Host 不对 403；写解读的 body 要是对象"""
    import subprocess
    from codestrata.viewers import free_port
    repo, port = fresh(), free_port()
    p = subprocess.Popen([PY, "-m", "codestrata", "serve", str(repo), "--port", str(port)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.time() + 30
        while not _listening(port):
            assert time.time() < end and p.poll() is None, "serve 没起来"
            time.sleep(0.2)
        assert _get_json(port, "/api/app") == {"home": None}
        assert _status(port, "GET", "/", host="evil.example:80") == 403
        assert _status(port, "PUT", "/api/notes/_overview", body=b"[1]") == 400
    finally:
        p.terminate()
        p.wait(10)


def test_cli_app():
    """codestrata app 本身：打印带口令的地址、用它登录；SIGTERM 时正常退出，由它起的图服务一起停掉"""
    import os
    import signal
    import subprocess
    from codestrata.viewers import free_port
    repo, port, cfg = fresh(), free_port(), tmpdir("cs-app-")
    p = subprocess.Popen([PY, "-m", "codestrata", "app", "--port", str(port), "--no-browser"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, "XDG_CONFIG_HOME": str(cfg)})
    try:
        line = p.stdout.readline()
        assert f"http://127.0.0.1:{port}/?t=" in line, line
        token = line.strip().rsplit("t=", 1)[1]
        c = Client(port, token)
        assert c.req("POST", "/api/projects", {"path": str(repo)})[0] == 200
        st, o, _ = c.req("POST", "/api/open", {"repo": str(repo)})
        assert st == 200, o
        vport = int(o["url"].rsplit(":", 1)[1].strip("/"))
        assert _listening(vport)
        assert (cfg / "codestrata" / "app-token").stat().st_mode & 0o077 == 0     # 口令文件只有自己能读
    finally:
        p.send_signal(signal.SIGTERM)
        out = p.communicate(timeout=60)[0]
    assert p.returncode == 0, out
    assert not _listening(vport), "主菜单退出了，它起的图服务还在"


def _get_json(port: int, path: str):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path)
    r = c.getresponse()
    body = json.loads(r.read())
    c.close()
    return body


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
