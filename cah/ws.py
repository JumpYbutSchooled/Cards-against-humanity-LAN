"""Minimal WebSocket client (RFC 6455) on the standard library - enough for the relay.

Only what we need: text messages, ping/pong, close codes. TLS uses the system's
certificate store, so it also works behind school/company HTTPS filters.
"""
import base64
import os
import socket
import ssl
import struct
import threading
from urllib.parse import urlparse


class HandshakeError(OSError):
    pass


def _mask(data, key):
    n = len(data)
    if not n:
        return b""
    k = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(k, "big")).to_bytes(n, "big")


class WebSocket:
    def __init__(self, url, timeout=10):
        u = urlparse(url)
        secure = u.scheme == "wss"
        host = u.hostname
        port = u.port or (443 if secure else 80)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        sock = socket.create_connection((host, port), timeout=timeout)
        if secure:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: cah-game\r\n\r\n")
        sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise HandshakeError("The server closed the connection during the handshake.")
            buf += chunk
            if len(buf) > 65536:
                raise HandshakeError("Bad handshake response.")
        head, self._buf = buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101" not in status:
            raise HandshakeError(f"Server refused the connection ({status.strip()}).")
        sock.settimeout(None)
        self.sock = sock
        self._lock = threading.Lock()
        self.closed = False
        self.close_code = None
        self.close_reason = ""

    def _send_frame(self, opcode, payload):
        n = len(payload)
        head = bytearray([0x80 | opcode])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        key = os.urandom(4)
        with self._lock:
            self.sock.sendall(bytes(head) + key + _mask(payload, key))

    def send(self, text):
        if self.closed:
            raise OSError("WebSocket is closed")
        self._send_frame(0x1, text.encode("utf-8"))

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("Connection lost")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
        """Next text message, or None once the connection has closed."""
        parts = []
        try:
            while True:
                b1, b2 = self._read(2)
                op = b1 & 0x0F
                n = b2 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._read(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", self._read(8))[0]
                key = self._read(4) if b2 & 0x80 else None
                payload = self._read(n)
                if key:
                    payload = _mask(payload, key)
                if op == 0x9:  # ping
                    self._send_frame(0xA, payload)
                elif op == 0xA:  # pong
                    pass
                elif op == 0x8:  # close
                    self.close_code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 1005
                    self.close_reason = payload[2:].decode("utf-8", "replace")
                    try:
                        self._send_frame(0x8, payload[:2])
                    except OSError:
                        pass
                    self._shutdown()
                    return None
                else:
                    parts.append(payload)
                    if b1 & 0x80:
                        return b"".join(parts).decode("utf-8", "replace")
        except (OSError, ValueError):
            self._shutdown()
            return None

    def close(self, code=1000, reason=""):
        if not self.closed:
            try:
                self._send_frame(0x8, struct.pack(">H", code) + reason.encode("utf-8")[:120])
            except OSError:
                pass
        self._shutdown()

    def _shutdown(self):
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
