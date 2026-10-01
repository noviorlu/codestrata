"""测试用的假 pyzmq：只有 hook 认的模块路径（zmq.sugar.socket.Socket 的 send_multipart / recv_multipart），
底下用管道收发，给 test_events_truth 的「谁把数据交给谁」用。不在 fake_repo 里：它是仓库外的代码。"""
from zmq.sugar.socket import Socket  # noqa: F401
