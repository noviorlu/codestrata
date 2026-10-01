"""测试用的假 pyzmq：只有 hook 认的模块路径（zmq.sugar.socket.Socket 的 send / send_multipart / recv_multipart），
底下用管道收发，给 test_events_truth 的「谁把数据交给谁」用。照 pyzmq 的样子：send_multipart 逐帧调 send（中间的帧带
SNDMORE）；ROUTER 发的时候第一帧是对方的身份、不发出去，收的时候前面多一帧对方的身份——vLLM 就是这么用的
（orchestrator 的 ROUTER 发请求、stage 的 DEALER 收；输出先 send(第一帧, SNDMORE) 再 send_multipart(其余的)）。
不在 fake_repo 里：它是仓库外的代码。"""
from zmq.sugar.socket import DEALER, PULL, PUSH, ROUTER, SNDMORE, Socket  # noqa: F401
