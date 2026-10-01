import os

SNDMORE = 2
DEALER, ROUTER, PULL, PUSH = 5, 6, 7, 8


class Socket:
    """一头读、一头写的管道：一条消息是 [总长 4 字节][各段：长度 4 字节 + 内容]"""

    def __init__(self, rfd=None, wfd=None, type=DEALER):
        self.rfd, self.wfd, self.type = rfd, wfd, type
        self._more = []

    def send(self, data, flags=0, copy=True, track=False):
        self._more.append(bytes(data))
        if flags & SNDMORE:
            return None
        parts, self._more = self._more, []
        if self.type == ROUTER:
            parts = parts[1:]                     # 身份帧只用来选对方，不发出去
        body = b"".join(len(p).to_bytes(4, "little") + p for p in parts)
        os.write(self.wfd, len(body).to_bytes(4, "little") + body)
        return None

    def send_multipart(self, msg_parts, flags=0, copy=True, track=False):
        for p in msg_parts[:-1]:
            self.send(p, SNDMORE | flags, copy=copy)
        return self.send(msg_parts[-1], flags, copy=copy)

    def _read(self, n):
        out = b""
        while len(out) < n:
            out += os.read(self.rfd, n - len(out))
        return out

    def recv_multipart(self, flags=0, copy=True, track=False):
        body = self._read(int.from_bytes(self._read(4), "little"))
        parts, i = [], 0
        while i < len(body):
            n = int.from_bytes(body[i:i + 4], "little")
            parts.append(body[i + 4:i + 4 + n])
            i += 4 + n
        return ([b"peer-0"] if self.type == ROUTER else []) + parts
