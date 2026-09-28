#!/usr/bin/env bash
# codestrata trace 的测试 case（CPU）：形状照着 duplex-agents 的 trace_case.sh——
# setsid 起服务 → 等就绪 → 写 PHASE serving → 发请求 → 写 PHASE shutdown → trap 里整组 SIGINT 停服务。
#
#   FAKE_HANG=1       发完请求后卡住（测超时 / Ctrl+C）
#   FAKE_NO_TRAP=1    不停服务就退出（测残留进程）
#   FAKE_IGNORE_INT=1 服务忽略 SIGINT（测升级到 SIGTERM）
set -u
PY=${PY:-python3}
PORT=${PORT:-$((20000 + RANDOM % 20000))}
READY=$(mktemp -u /tmp/fakesvc-ready.XXXXXX)

setsid "$PY" -m fakesvc.server --port "$PORT" --ready "$READY" &
PID=$!

stop_group() {
  kill -0 "$PID" 2>/dev/null || return 0
  kill -INT -- "-$PID" 2>/dev/null || true
  for _ in $(seq 1 50); do kill -0 "$PID" 2>/dev/null || break; sleep 0.1; done
  kill -0 "$PID" 2>/dev/null && { kill -TERM -- "-$PID" 2>/dev/null || true; sleep 2; }
  kill -0 "$PID" 2>/dev/null && kill -KILL -- "-$PID" 2>/dev/null
  rm -f "$READY"
}
[[ "${FAKE_NO_TRAP:-}" == 1 ]] || trap stop_group EXIT

phase() { [[ -n "${CODESTRATA_OUT:-}" ]] && { echo "$1" > "$CODESTRATA_OUT/PHASE"; sleep 1.5; } || true; }

for _ in $(seq 1 100); do [[ -s "$READY" ]] && break; sleep 0.1; done
[[ -s "$READY" ]] || { echo "服务没起来" >&2; exit 1; }
phase serving
"$PY" -m fakesvc.client --port "$PORT" --n 3 || exit 1
[[ "${FAKE_HANG:-}" == 1 ]] && { phase hang; sleep 1000; }   # 请求都处理完了才卡住（测试等这个阶段）
phase shutdown
