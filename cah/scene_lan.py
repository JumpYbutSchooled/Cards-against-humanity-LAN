import threading
import time

import pygame

from . import ui
from .app import Scene
from .net import GAME_PORT, Browser, Client, Server
from .session import ClientSession, HostSession
from .ui import Button, TextInput, V, WHITE, GRAY, DIM, ACCENT, RED, PANEL_HI

LIST_Y = 268
ROW_H = 62


class LanScene(Scene):
    def __init__(self, app, message=None):
        super().__init__(app)
        st = app.settings
        self.name = TextInput((40, 132, 360, 46), st.get("name", ""), "Your name", 18, 18,
                              on_change=lambda t: st.__setitem__("name", t))
        self.host_btn = Button((64, 420, 320, 58), "Host Game", self.host, "accent", 21)
        self.ip = TextInput((464, 584, 520, 46), st.get("last_ip", ""), "Host IP address, e.g. 192.168.1.23", 40,
                            17)
        self.join_ip_btn = Button((996, 584, 220, 46), "Join", lambda: self.join(self.ip.text), "primary", 18)
        self.back = Button((40, 654, 160, 50), "Back", self.go_back, "ghost", 18)
        self.fixed = self.buttons(self.host_btn, self.join_ip_btn, self.back)
        self.browser = Browser()
        self.game_btns = {}
        self.games = []
        self.error = message
        self.connecting = None  # (thread result holder)
        self.t = 0.0

    # ---------------------------------------------------------- actions
    def player_name(self):
        n = self.name.text.strip()
        return n or "Player"

    def go_back(self):
        self.browser.close()
        from .scene_menu import MenuScene
        self.app.switch(MenuScene(self.app))

    def host(self):
        if self.connecting:
            return
        try:
            server = Server(self.app.library, self.player_name(), self.app.settings)
        except OSError as e:
            self.error = f"Couldn't start hosting: {e}"
            return
        self.app.save()
        self.browser.close()
        from .scene_lobby import LobbyScene
        self.app.switch(LobbyScene(self.app, HostSession(server)))

    def join(self, address, port=None, alt=None):
        address = address.strip()
        if not address or self.connecting:
            if not address:
                self.error = "Type the host's IP address first."
            return
        if port is None:
            port = GAME_PORT
            if ":" in address:
                address, _, p = address.rpartition(":")
                try:
                    port = int(p)
                except ValueError:
                    self.error = "That address doesn't look right."
                    return
        self.app.settings["last_ip"] = address if port == GAME_PORT else f"{address}:{port}"
        self.app.save()
        self.error = None
        holder = {"client": None, "error": None, "started": time.time(), "addr": address}

        name = self.player_name()

        def run():
            last = None
            for addr in [address] + ([alt] if alt and alt != address else []):
                try:
                    holder["client"] = Client(addr, port, name)
                    return
                except OSError as e:
                    last = e
            holder["error"] = ("Couldn't reach that host - check the IP and that you're on the same network"
                               f" ({last}).")
        threading.Thread(target=run, daemon=True).start()
        self.connecting = holder

    # ---------------------------------------------------------- events
    def handle(self, ev):
        if self.name.handle(ev) and ev.type != pygame.MOUSEBUTTONDOWN:
            return
        if self.ip.handle(ev) and ev.type != pygame.MOUSEBUTTONDOWN:
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.join(self.ip.text)
            return
        for b in self.fixed + list(self.game_btns.values()):
            if b.handle(ev):
                return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.go_back()

    def update(self, dt):
        self.t += dt
        self.name.update(dt)
        self.ip.update(dt)
        games = self.browser.list()
        keys = set()
        for i, g in enumerate(games[:5]):
            key = (g["ip"], g["port"])
            keys.add(key)
            b = self.game_btns.get(key)
            if b is None:
                b = Button((1080, 0, 130, 42), "Join", lambda g=g: self.join(g["ip"], g["port"], g.get("alt_ip")),
                           "primary", 16)
                b.sounds = self.app.sounds
                self.game_btns[key] = b
            b.rect.y = LIST_Y + i * ROW_H + 10
            b.enabled = g.get("v") == 1
        for k in list(self.game_btns):
            if k not in keys:
                del self.game_btns[k]
        self.games = games[:5]
        for b in self.fixed + list(self.game_btns.values()):
            b.update(dt)

        c = self.connecting
        if c:
            client = c["client"]
            if c["error"]:
                self.error = c["error"]
                self.connecting = None
            elif client is not None:
                if client.error:
                    self.error = client.error
                    client.close()
                    self.connecting = None
                elif client.pid is not None and client.state is not None:
                    self.browser.close()
                    session = ClientSession(client)
                    if client.state["phase"] == "lobby":
                        from .scene_lobby import LobbyScene
                        self.app.switch(LobbyScene(self.app, session))
                    else:
                        from .scene_game import GameScene
                        self.app.switch(GameScene(self.app, session))
                    self.connecting = None
                elif time.time() - c["started"] > 8:
                    self.error = "The host didn't answer."
                    client.close()
                    self.connecting = None

    # ---------------------------------------------------------- draw
    def draw(self, surf):
        ui.draw_text(surf, "LAN Game", 40, WHITE, (40, 22), "topleft")
        ui.draw_text(surf, "Play together on the same Wi-Fi or home network - everyone on their own computer.", 15,
                     GRAY, (42, 70), "topleft", bold=False)
        ui.draw_text(surf, "Your name", 14, GRAY, (42, 122), "bottomleft", bold=False)
        self.name.draw(surf)

        ui.draw_panel(surf, (40, 200, 384, 440))
        ui.draw_text(surf, "Host a game", 22, WHITE, (64, 232), "midleft")
        lines = ["Start a game on this computer.", "Friends on your network can join it,",
                 "and you can fill empty seats with bots.", "",
                 "Windows may ask whether Python can use", "the network - choose Allow (Private)."]
        for i, t in enumerate(lines):
            ui.draw_text(surf, t, 15, GRAY if i < 3 else DIM, (64, 274 + i * 22), "midleft", bold=False)
        self.host_btn.draw(surf)

        ui.draw_panel(surf, (448, 200, 792, 440))
        ui.draw_text(surf, "Join a game", 22, WHITE, (472, 232), "midleft")
        if not self.games:
            dots = "." * (1 + int(self.t * 2) % 3)
            ui.draw_text(surf, f"Looking for games on your network{dots}", 17, GRAY, (844, 380), bold=False)
            if self.browser.error:
                ui.draw_text(surf, "(Auto-discovery is unavailable - use the IP address below.)", 13, DIM,
                             (844, 408), bold=False)
        for i, g in enumerate(self.games):
            y = LIST_Y + i * ROW_H
            r = V.rect((464, y, 760, ROW_H - 8))
            surf.blit(ui.rounded_px(r.w, r.h, V.s(10), PANEL_HI), r)
            ui.draw_text(surf, ui.ellipsize(g.get("title", "Game"), 18, 520), 18, WHITE, (484, y + 18), "midleft")
            status = "in lobby" if g.get("phase") == "lobby" else "game in progress"
            port = "" if g["port"] == GAME_PORT else f":{g['port']}"
            ui.draw_text(surf, f"{g['ip']}{port}  ·  {g.get('players', 0)} players  ·  {status}", 13, GRAY,
                         (484, y + 40), "midleft", bold=False)
            if g.get("v") != 1:
                ui.draw_text(surf, "different version", 13, RED, (1070, y + 27), "midright", bold=False)
        for b in self.game_btns.values():
            b.draw(surf)
        ui.draw_text(surf, "Not listed? Ask the host for the IP shown in their lobby:", 14, GRAY, (472, 566),
                     "midleft", bold=False)
        self.ip.draw(surf)
        self.join_ip_btn.draw(surf)

        self.back.draw(surf)
        if self.connecting:
            dots = "." * (1 + int(self.t * 3) % 3)
            ui.draw_text(surf, f"Connecting to {self.connecting['addr']}{dots}", 16, ACCENT, (230, 679), "midleft",
                         bold=False)
        elif self.error:
            ui.draw_text(surf, ui.ellipsize(self.error, 15, 1000, False), 15, RED, (230, 679), "midleft",
                         bold=False)
