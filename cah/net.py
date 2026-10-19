"""LAN multiplayer: a host server, a client, and UDP discovery.

Protocol: newline-delimited JSON over TCP.
  client -> host: {"t": "hello", "name", "v"} then {"t": "act", "a": ..., ...}
  host -> client: {"t": "welcome", "pid"} / {"t": "state", "s": snapshot} / {"t": "bye", "msg"}
The host also broadcasts a small UDP beacon so games appear in the Join list.
"""
import json
import queue
import random
import socket
import threading
import time

from .engine import Engine

PROTOCOL = 1
GAME_PORT = 47474
DISCOVERY_PORT = 47475
BEACON = "CAH-LAN"


def primary_ip():
    """The address of the adapter with the default route (the real Wi-Fi/Ethernet, not VM adapters)."""
    for probe in ("8.8.8.8", "10.255.255.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((probe, 80))  # UDP connect sends nothing; it just picks a route
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith(("127.", "0.", "169.254.")):
                return ip
        except OSError:
            pass
    return None


def local_ips():
    """All LAN addresses, the real (default-route) one first."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    main = primary_ip()
    ips = [ip for ip in ips if not ip.startswith(("127.", "169.254.")) and ip != main]
    return ([main] if main else []) + sorted(ips)


class Conn:
    """A socket with line framing and a send lock."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""
        self.lock = threading.Lock()
        self.alive = True

    def send(self, obj):
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
        with self.lock:
            try:
                self.sock.sendall(data)
            except OSError:
                self.alive = False

    def lines(self):
        while self.alive:
            try:
                chunk = self.sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            self.buf += chunk
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                if line.strip():
                    try:
                        yield json.loads(line.decode("utf-8"))
                    except ValueError:
                        pass
            if len(self.buf) > 1_000_000:
                break
        self.alive = False

    def close(self):
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class Server:
    def __init__(self, library, host_name, settings):
        self.engine = Engine(library, settings["packs"], settings.get("points", 7), settings.get("hand", 10))
        self.lock = threading.RLock()
        self.host_pid = self.engine.add_player(host_name, host=True)
        self.clients = {}  # Conn -> pid
        self.running = True
        self.title = f"{self.engine.get(self.host_pid)['name']}'s game"
        self.game_id = f"{random.getrandbits(48):012x}"
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.port = None
        for port in range(GAME_PORT, GAME_PORT + 10):
            try:
                self.listener.bind(("", port))
                self.port = port
                break
            except OSError:
                continue
        if self.port is None:
            raise OSError("No free port for hosting")
        self.listener.listen(16)
        self.listener.settimeout(0.5)
        self._sent_version = -1
        for target in (self._accept_loop, self._tick_loop, self._beacon_loop):
            threading.Thread(target=target, daemon=True).start()

    # ---------------------------------------------------------- threads
    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=self._client_loop, args=(Conn(sock),), daemon=True).start()

    def _client_loop(self, conn):
        pid = None
        try:
            for msg in conn.lines():
                if pid is None:
                    if msg.get("t") != "hello":
                        break
                    if msg.get("v") != PROTOCOL:
                        conn.send({"t": "bye", "msg": "Different game version - update both computers."})
                        break
                    pid, err = self._join(msg.get("name", "Player"))
                    if err:
                        conn.send({"t": "bye", "msg": err})
                        break
                    with self.lock:
                        self.clients[conn] = pid
                        conn.send({"t": "welcome", "pid": pid})
                        conn.send({"t": "state", "s": self.engine.view(pid)})
                    continue
                if msg.get("t") == "act":
                    with self.lock:
                        self.engine.act(pid, msg)
        finally:
            with self.lock:
                self.clients.pop(conn, None)
                if pid is not None and self.running:
                    self.engine.remove_player(pid)
            conn.close()

    def _join(self, name):
        with self.lock:
            e = self.engine
            # Rejoining an in-progress game reclaims your old seat.
            for p in e.players:
                if p["away"] and not p["bot"] and p["name"].lower() == str(name).strip().lower():
                    e.set_away(p["id"], False)
                    return p["id"], None
            if len(e.players) >= 10:
                return None, "That game is full."
            return e.add_player(str(name)), None

    def _tick_loop(self):
        last = time.perf_counter()
        while self.running:
            time.sleep(1 / 30)
            now = time.perf_counter()
            with self.lock:
                self.engine.tick(now - last)
                if self.engine.version != self._sent_version:
                    self._sent_version = self.engine.version
                    for conn, pid in list(self.clients.items()):
                        conn.send({"t": "state", "s": self.engine.view(pid)})
            last = now

    def _beacon_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.running:
            ips = local_ips()
            with self.lock:
                msg = {"beacon": BEACON, "v": PROTOCOL, "id": self.game_id, "title": self.title, "port": self.port,
                       "ip": ips[0] if ips else None, "players": len(self.engine.players),
                       "phase": self.engine.phase}
            data = json.dumps(msg).encode("utf-8")
            targets = {"255.255.255.255", "127.0.0.1"}
            for ip in ips:
                parts = ip.split(".")
                targets.add(".".join(parts[:3] + ["255"]))
            for t in targets:
                try:
                    sock.sendto(data, (t, DISCOVERY_PORT))
                except OSError:
                    pass
            time.sleep(1.0)
        sock.close()

    # ---------------------------------------------------------- host API
    def view(self, pid=None):
        with self.lock:
            return self.engine.view(self.host_pid if pid is None else pid)

    def act(self, action):
        with self.lock:
            return self.engine.act(self.host_pid, action)

    def host(self, fn, *args):
        """Runs fn(engine, *args) under the lock - for lobby management."""
        with self.lock:
            return fn(self.engine, *args)

    def kick(self, pid):
        with self.lock:
            for conn, cpid in list(self.clients.items()):
                if cpid == pid:
                    conn.send({"t": "bye", "msg": "The host removed you from the game."})
                    conn.close()
            p = self.engine.get(pid)
            if p:
                self.engine.players.remove(p)
                self.engine.touch()

    def close(self):
        if not self.running:
            return
        self.running = False
        with self.lock:
            for conn in list(self.clients):
                conn.send({"t": "bye", "msg": "The host closed the game."})
                conn.close()
            self.clients.clear()
        try:
            self.listener.close()
        except OSError:
            pass


class Client:
    def __init__(self, host, port, name):
        self.pid = None
        self.state = None
        self.error = None
        self.closed = False
        self.events = queue.Queue()
        sock = socket.create_connection((host, port), timeout=4)
        sock.settimeout(None)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.conn = Conn(sock)
        self.conn.send({"t": "hello", "name": name, "v": PROTOCOL})
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        for msg in self.conn.lines():
            t = msg.get("t")
            if t == "welcome":
                self.pid = msg.get("pid")
            elif t == "state":
                self.state = msg.get("s")
            elif t == "bye":
                self.error = msg.get("msg", "Disconnected.")
        if not self.closed and not self.error:
            self.error = "Lost connection to the host."
        self.closed = True

    def view(self, pid=None):
        return self.state

    def act(self, action):
        self.conn.send({"t": "act", **action})

    def close(self):
        self.closed = True
        self.conn.close()


class Browser:
    """Listens for host beacons on the LAN."""

    def __init__(self):
        self.games = {}
        self.running = True
        self.error = None
        self.lock = threading.Lock()
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("", DISCOVERY_PORT))
            self.sock.settimeout(0.5)
            threading.Thread(target=self._loop, daemon=True).start()
        except OSError as e:
            self.error = str(e)
            self.running = False

    def _loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if msg.get("beacon") != BEACON:
                continue
            # One entry per game (a host with VM/virtual adapters is heard on several addresses).
            # Connect to the host's advertised main address; fall back to where the packet came from.
            ip = msg.get("ip") or addr[0]
            key = msg.get("id") or (addr[0], msg.get("port", GAME_PORT))
            with self.lock:
                self.games[key] = dict(msg, ip=ip, alt_ip=addr[0], seen=time.time())

    def list(self):
        now = time.time()
        with self.lock:
            return sorted((g for g in self.games.values() if now - g["seen"] < 3.5), key=lambda g: g["title"])

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
