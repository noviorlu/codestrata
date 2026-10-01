import os


class Socket:
    """一头读、一头写的管道：一条消息是 [总长 4 字节][各段：长度 4 字节 + 内容]"""

    def __init__(self, rfd=None, wfd=None):
        self.rfd, self.wfd = rfd, wfd

    def send_multipart(self, msg_parts, copy=True):
        body = b"".join(len(p).to_bytes(4, "little") + bytes(p) for p in msg_parts)
        os.write(self.wfd, len(body).to_bytes(4, "little") + body)

    def _read(self, n):
        out = b""
        while len(out) < n:
            out += os.read(self.rfd, n - len(out))
        return out

    def recv_multipart(self, copy=True):
        body = self._read(int.from_bytes(self._read(4), "little"))
        parts, i = [], 0
        while i < len(body):
            n = int.from_bytes(body[i:i + 4], "little")
            parts.append(body[i + 4:i + 4 + n])
            i += 4 + n
        return parts
