"""Multiplayer networking: host server, clients, LAN discovery and the online relay.

Two ways in, same game messages:
  * Online (room code): everyone connects OUT to a relay on Cloudflare over wss:// (port 443),
    the same idea as Epic's relay in Baldi's multiplayer. Works on school Wi-Fi, between houses,
    behind firewalls - nobody needs an open port.
  * LAN: direct TCP to the host on port 47474, with UDP broadcast discovery. Only works on
    networks that allow devices to talk to each other (most homes, not most schools).

Game protocol (JSON messages, newline-delimited on TCP, one per frame on the relay):
  client -> host: {"t": "hello", "name", "v"} then {"t": "act", "a": ..., ...}
  host -> client: {"t": "welcome", "pid"} / {"t": "state", "s": snapshot} / {"t": "bye", "msg"}
"""
import json
import os
import queue
import random
import socket
import threading
import time

from .engine import Engine
from .ws import WebSocket

PROTOCOL = 3
GAME_PORT = 47474
DISCOVERY_PORT = 47475
BEACON = "CAH-LAN"
RELAY_URL = "wss://cah-relay.magnusbradley16.workers.dev"  # relay/ in this repo, on Cloudflare Workers
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I/O, they look like 1/0
RECONNECT_FOR = 30.0  # seconds a client keeps trying after a dropout


def relay_base():
    url = os.environ.get("CAH_RELAY") or RELAY_URL
    return None if "REPLACE_ME" in url else url.rstrip("/")


def room_url(code, role):
    return f"{relay_base()}/room/{code}?role={role}"


def new_code():
    return "".join(random.choice(CODE_CHARS) for _ in range(4))


def clean_code(text):
    return "".join(ch for ch in text.upper() if ch.isalnum())[:8]


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


# ====================================================================== transports
# Every transport has: send(obj), lines() -> iterator of dicts, close(), alive, close_code.

class Conn:
    """A TCP socket with newline framing."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""
        self.lock = threading.Lock()
        self.alive = True
        self.close_code = None

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
        for fn in (lambda: self.sock.shutdown(socket.SHUT_RDWR), self.sock.close):
            try:
                fn()
            except OSError:
                pass


class WsConn:
    """Client side of the relay: one WebSocket, game messages in and out unchanged."""

    def __init__(self, url):
        self.ws = WebSocket(url)
        self.alive = True
        threading.Thread(target=self._keepalive, daemon=True).start()

    @property
    def close_code(self):
        return self.ws.close_code

    @property
    def close_reason(self):
        return self.ws.close_reason

    def _keepalive(self):
        while self.alive and not self.ws.closed:
            time.sleep(20)
            try:
                self.ws.send("ping")
            except OSError:
                break

    def send(self, obj):
        try:
            self.ws.send(json.dumps(obj, separators=(",", ":")))
        except OSError:
            self.alive = False

    def lines(self):
        while self.alive:
            msg = self.ws.recv()
            if msg is None:
                break
            if msg == "pong":
                continue
            try:
                yield json.loads(msg)
            except ValueError:
                pass
        self.alive = False

    def close(self):
        self.alive = False
        self.ws.close()


class RelayConn:
    """Host side: one player reached through the relay. Fed by RelayHost."""

    def __init__(self, relay, cid):
        self.relay = relay
        self.cid = cid
        self.q = queue.Queue()
        self.alive = True
        self.close_code = None

    def feed(self, msg):
        self.q.put(msg)

    def send(self, obj):
        if self.alive:
            self.relay.send({"t": "to", "cid": self.cid, "m": obj})

    def lines(self):
        while True:
            msg = self.q.get()
            if msg is None:
                break
            yield msg
        self.alive = False

    def close(self):
        if self.alive:
            self.alive = False
            self.relay.send({"t": "kick", "cid": self.cid})
        self.q.put(None)


class RelayHost:
    """Keeps the host registered on the relay under a room code, reconnecting if it drops."""

    def __init__(self, server):
        self.server = server
        self.code = new_code()
        self.status = "connecting"  # connecting | online | offline
        self.error = ""
        self.ws = None
        self.conns = {}
        self.send_lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, obj):
        ws = self.ws
        if ws is None:
            return
        try:
            ws.send(json.dumps(obj, separators=(",", ":")))
        except OSError:
            pass

    def _run(self):
        delay = 1.0
        while self.server.running:
            try:
                ws = WebSocket(room_url(self.code, "host"))
            except OSError as e:
                self.status = "offline"
                self.error = str(e)
                time.sleep(min(delay, 10))
                delay *= 1.6
                continue
            self.ws = ws
            first = True
            ka = threading.Thread(target=self._keepalive, args=(ws,), daemon=True)
            ka.start()
            while self.server.running:
                msg = ws.recv()
                if msg is None:
                    break
                if first:
                    self.status, self.error, delay, first = "online", "", 1.0, False
                if msg == "pong":
                    continue
                try:
                    d = json.loads(msg)
                except ValueError:
                    continue
                self._handle(d)
            self.ws = None
            if ws.close_code == 4009 and first:
                self.code = new_code()  # someone else has this code; pick another
                continue
            self._drop_all()
            if self.server.running:
                self.status = "connecting"
                time.sleep(1.0)
        self._drop_all()

    def _keepalive(self, ws):
        # Also the first message we send, so an idle lobby still proves the room is live.
        while not ws.closed and self.server.running:
            try:
                ws.send("ping")
            except OSError:
                break
            time.sleep(20)

    def _handle(self, d):
        t = d.get("t")
        cid = d.get("cid")
        if t == "join":
            conn = RelayConn(self, cid)
            self.conns[cid] = conn
            self.server.spawn(conn)
        elif t == "from":
            conn = self.conns.get(cid)
            if conn:
                try:
                    msg = json.loads(d.get("m", ""))
                except ValueError:
                    return
                if isinstance(msg, dict):
                    conn.feed(msg)
        elif t == "leave":
            conn = self.conns.pop(cid, None)
            if conn:
                conn.alive = False
                self.server.drop(conn)  # synchronously, so a quick rejoin can reclaim the seat
                conn.feed(None)

    def _drop_all(self):
        for conn in list(self.conns.values()):
            conn.alive = False
            self.server.drop(conn)
            conn.feed(None)
        self.conns.clear()

    def close(self):
        ws = self.ws
        if ws:
            ws.close()


# ====================================================================== server

class Server:
    def __init__(self, library, host_name, settings, online=True, lan=True):
        self.engine = Engine(library, settings["packs"], settings.get("points", 7), settings.get("hand", 10))
        self.engine.configure(tts=settings.get("tts_mode", "off"))
        self.lock = threading.RLock()
        self.host_pid = self.engine.add_player(host_name, host=True)
        self.clients = {}  # conn -> pid
        self.running = True
        self.title = f"{self.engine.get(self.host_pid)['name']}'s game"
        self.game_id = f"{random.getrandbits(48):012x}"
        self._sent_version = -1
        self.port = None
        self.lan_error = None
        self.listener = None
        if lan:
            try:
                self._listen()
            except OSError as e:
                self.lan_error = str(e)
        self.relay = RelayHost(self) if (online and relay_base()) else None
        threads = [self._tick_loop]
        if self.listener:
            threads += [self._accept_loop, self._beacon_loop]
        for target in threads:
            threading.Thread(target=target, daemon=True).start()

    @property
    def room_code(self):
        return self.relay.code if self.relay else None

    def _listen(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows: SO_REUSEADDR would let a second game on this PC share the port silently, and
            # players could land in the wrong game. Exclusive use makes the second host move to the next port.
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        for port in range(GAME_PORT, GAME_PORT + 10):
            try:
                self.listener.bind(("", port))
                self.port = port
                break
            except OSError:
                continue
        if self.port is None:
            self.listener.close()
            self.listener = None
            raise OSError("No free port for LAN hosting")
        self.listener.listen(16)
        self.listener.settimeout(0.5)

    # ---------------------------------------------------------- connections
    def spawn(self, conn):
        threading.Thread(target=self._client_loop, args=(conn,), daemon=True).start()

    def drop(self, conn):
        """Forget a connection; its player leaves the lobby or turns into a bot mid-game."""
        with self.lock:
            pid = self.clients.pop(conn, None)
            if pid is not None and self.running:
                self.engine.remove_player(pid)

    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.spawn(Conn(sock))

    def _client_loop(self, conn):
        pid = None
        try:
            for msg in conn.lines():
                if pid is None:
                    if msg.get("t") != "hello":
                        break
                    if msg.get("v") != PROTOCOL:
                        conn.send({"t": "bye", "msg": "Different game version - restart both games to update."})
                        break
                    with self.lock:
                        if not conn.alive:
                            break
                        pid, err = self._join(msg.get("name", "Player"))
                        if err:
                            conn.send({"t": "bye", "msg": err})
                            break
                        self.clients[conn] = pid
                        conn.send({"t": "welcome", "pid": pid})
                        conn.send({"t": "state", "s": self.engine.view(pid)})
                    continue
                if msg.get("t") == "act":
                    with self.lock:
                        if self.clients.get(conn) == pid:
                            self.engine.act(pid, msg)
        finally:
            self.drop(conn)
            conn.close()

    def _join(self, name):
        e = self.engine
        # Rejoining an in-progress game (or after a dropout) reclaims your old seat.
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
                       "phase": self.engine.phase, "code": self.room_code}
            data = json.dumps(msg).encode("utf-8")
            targets = {"255.255.255.255", "127.0.0.1"}
            for ip in ips:
                targets.add(".".join(ip.split(".")[:3] + ["255"]))
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
                    self.clients.pop(conn, None)
                    conn.send({"t": "bye", "msg": "The host removed you from the game."})
                    conn.close()
            p = self.engine.get(pid)
            if p:
                self.engine.players.remove(p)
                self.engine.touch()

    def close(self):
        if not self.running:
            return
        with self.lock:
            for conn in list(self.clients):
                conn.send({"t": "bye", "msg": "The host closed the game."})
            conns = list(self.clients)
            self.clients.clear()
            self.running = False
        time.sleep(0.15)  # let the goodbyes go out before the sockets close
        for conn in conns:
            conn.close()
        if self.relay:
            self.relay.close()
        if self.listener:
            try:
                self.listener.close()
            except OSError:
                pass


# ====================================================================== client

class Client:
    """Connects by room code (relay) or LAN address, and quietly reconnects after dropouts."""

    def __init__(self, name, room=None, host=None, port=GAME_PORT):
        self.name = name
        self.room = room
        self.addr = (host, port)
        self.pid = None
        self.state = None
        self.error = None
        self.closed = False
        self.reconnecting = False
        self.conn = self._connect()
        threading.Thread(target=self._loop, daemon=True).start()

    def _connect(self):
        if self.room:
            if not relay_base():
                raise OSError("Online play isn't set up in this version.")
            conn = WsConn(room_url(self.room, "client"))
        else:
            sock = socket.create_connection(self.addr, timeout=5)
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn = Conn(sock)
        conn.send({"t": "hello", "name": self.name, "v": PROTOCOL})
        return conn

    def _loop(self):
        deadline = None
        while not self.closed:
            got_any = False
            for msg in self.conn.lines():
                got_any = True
                t = msg.get("t")
                if t == "welcome":
                    self.pid = msg.get("pid")
                    self.reconnecting = False
                    deadline = None
                elif t == "state":
                    self.state = msg.get("s")
                elif t == "bye":
                    self.error = msg.get("msg", "Disconnected.")
            if self.closed or self.error:
                break
            code = self.conn.close_code
            if code == 4004 and self.pid is None:
                self.error = "No game with that code - check it with the host."
                break
            if code == 4005:
                self.error = "That game is full."
                break
            if code == 4003:
                self.error = "The host removed you from the game."
                break
            if self.pid is None and not got_any:
                self.error = "The host didn't answer."
                break
            # A dropout (ours, or the host's relay link): keep retrying, then rejoin under the same name.
            if deadline is None:
                deadline = time.time() + RECONNECT_FOR
            self.reconnecting = True
            if not self._reconnect(deadline):
                break
        self.closed = True

    def _reconnect(self, deadline):
        while time.time() < deadline and not self.closed:
            time.sleep(1.5)
            try:
                self.conn = self._connect()
                return True
            except OSError:
                continue
        if not self.closed:
            self.error = "Lost connection to the host."
        return False

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
