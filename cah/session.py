"""Uniform interface the game/lobby screens talk to, whether the engine is local, hosted, or remote."""


class LocalSession:
    """Hot-seat: the engine runs in this process and every human shares the screen."""
    local = True
    net = False
    is_host = False
    error = None
    me = None

    def __init__(self, engine):
        self.engine = engine

    def tick(self, dt):
        self.engine.tick(dt)

    def view(self, pid=None):
        return self.engine.view(pid)

    def act(self, pid, action):
        return self.engine.act(pid, action)

    def leave(self):
        pass


class HostSession:
    local = False
    net = True
    is_host = True

    def __init__(self, server):
        self.server = server
        self.me = server.host_pid

    @property
    def error(self):
        return None if self.server.running else "Game closed."

    def tick(self, dt):
        pass  # the server thread ticks the engine

    def view(self, pid=None):
        return self.server.view()

    def act(self, pid, action):
        return self.server.act(action)

    def leave(self):
        self.server.close()


class ClientSession:
    local = False
    net = True
    is_host = False

    def __init__(self, client):
        self.client = client

    @property
    def me(self):
        return self.client.pid

    @property
    def error(self):
        return self.client.error

    def tick(self, dt):
        pass

    def view(self, pid=None):
        return self.client.state

    def act(self, pid, action):
        self.client.act(action)

    def leave(self):
        self.client.close()
