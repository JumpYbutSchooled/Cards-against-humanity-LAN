import threading
import time

import pygame

from . import ui
from .app import Scene
from .net import GAME_PORT, Browser, Client, Server, clean_code, relay_base
from .session import ClientSession, HostSession
from .ui import Button, TextInput, V, WHITE, GRAY, DIM, ACCENT, RED, PANEL_HI

LIST_Y = 404
ROW_H = 54


class LanScene(Scene):
    """Multiplayer hub: host, join by room code (online relay), or join a LAN game."""

    def __init__(self, app, message=None):
        super().__init__(app)
        st = app.settings
        self.name = TextInput((40, 132, 360, 46), st.get("name", ""), "Your name", 18, 18,
                              on_change=lambda t: st.__setitem__("name", t))
        self.host_btn = Button((64, 566, 336, 56), "Host Game", self.host, "accent", 21)
        self.packs_btn = Button((64, 478, 336, 38), "Customize packs...", self.on_packs, "secondary", 15)
        from .scene_packs import PresetChips
        self.chips = PresetChips(app, 64, 316, 336, self.on_preset, cols=2)
        self.code = TextInput((472, 268, 440, 62), "", "ROOM CODE", 8, 30)
        self.join_code_btn = Button((926, 268, 290, 62), "Join", self.join_code, "accent", 22)
        self.ip = TextInput((574, 588, 410, 40), st.get("last_ip", ""), "IP address, e.g. 192.168.1.23", 40, 15)
        self.join_ip_btn = Button((996, 588, 220, 40), "Join by IP", lambda: self.join(self.ip.text), "secondary",
                                  15)
        self.back = Button((40, 654, 160, 50), "Back", self.go_back, "ghost", 18)
        self.fixed = self.buttons(self.host_btn, self.packs_btn, self.join_code_btn, self.join_ip_btn, self.back)
        self.browser = Browser()
        self.game_btns = {}
        self.games = []
        self.preset = None
        self.error = message
        self.connecting = None
        self.t = 0.0
        self.online = relay_base() is not None

    # ---------------------------------------------------------- actions
    def player_name(self):
        return self.name.text.strip() or "Player"

    def go_back(self):
        self.browser.close()
        from .scene_menu import MenuScene
        self.app.switch(MenuScene(self.app))

    def on_preset(self, packs, name):
        self.app.settings["packs"] = packs
        self.app.save()

    def on_packs(self):
        from .scene_packs import PacksScene
        self.browser.close()
        self.app.switch(PacksScene(self.app, back=lambda: LanScene(self.app)))

    def host(self):
        if self.connecting:
            return
        try:
            server = Server(self.app.library, self.player_name(), self.app.settings, online=self.online)
        except OSError as e:
            self.error = f"Couldn't start hosting: {e}"
            return
        self.app.save()
        self.browser.close()
        from .scene_lobby import LobbyScene
        self.app.switch(LobbyScene(self.app, HostSession(server)))

    def join_code(self):
        code = clean_code(self.code.text)
        if len(code) < 4:
            self.error = "Type the 4-letter room code from the host's screen."
            return
        if not self.online:
            self.error = "Online play isn't set up in this version yet."
            return
        self._start(code, lambda name: [lambda: Client(name, room=code)])

    def join(self, address, port=None, alt=None, code=None):
        address = address.strip()
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

        def attempts(name):
            out = [lambda a=a: Client(name, host=a, port=port) for a in [address] + ([alt] if alt and alt != address
                                                                                       else [])]
            if code and self.online:  # LAN blocked? the same game is also reachable through the relay
                out.append(lambda: Client(name, room=code))
            return out
        self._start(address, attempts)

    def _start(self, label, make_attempts):
        if self.connecting:
            return
        self.app.save()
        self.error = None
        holder = {"client": None, "error": None, "started": time.time(), "label": label}
        tries = make_attempts(self.player_name())

        def run():
            last = None
            for attempt in tries:
                try:
                    holder["client"] = attempt()
                    return
                except OSError as e:
                    last = e
            holder["error"] = f"Couldn't connect ({last})." if last else "Couldn't connect."
        threading.Thread(target=run, daemon=True).start()
        self.connecting = holder

    # ---------------------------------------------------------- events
    def handle(self, ev):
        for inp, submit in ((self.name, None), (self.code, self.join_code), (self.ip, lambda: self.join(self.ip.text))):
            was_focused = inp.focused
            if inp.handle(ev) and ev.type != pygame.MOUSEBUTTONDOWN:
                if submit and was_focused and ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN,
                                                                                      pygame.K_KP_ENTER):
                    submit()
                return
        if self.code.focused or self.code.text:
            up = clean_code(self.code.text)
            if up != self.code.text:
                self.code.text = up
        for b in self.fixed + list(self.game_btns.values()):
            if b.handle(ev):
                return
        if self.chips.handle(ev):
            return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.go_back()

    def update(self, dt):
        self.t += dt
        for inp in (self.name, self.code, self.ip):
            inp.update(dt)
        games = self.browser.list()[:3]
        keys = set()
        for i, g in enumerate(games):
            key = g.get("id") or (g["ip"], g["port"])
            keys.add(key)
            b = self.game_btns.get(key)
            if b is None:
                b = Button((1096, 0, 120, 38), "Join",
                           lambda g=g: self.join(g["ip"], g["port"], g.get("alt_ip"), g.get("code")), "primary", 15)
                b.sounds = self.app.sounds
                self.game_btns[key] = b
            b.rect.y = LIST_Y + i * ROW_H + 8
            b.enabled = g.get("v") == 2
        for k in list(self.game_btns):
            if k not in keys:
                del self.game_btns[k]
        self.games = games
        self.join_code_btn.enabled = len(clean_code(self.code.text)) >= 4 and not self.connecting
        for b in self.fixed + list(self.game_btns.values()):
            b.update(dt)
        from .presets import match_name
        self.preset = match_name(self.app.library, self.app.settings["packs"], self.app.settings)
        self.chips.update(dt, self.preset)

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
                elif time.time() - c["started"] > 12:
                    self.error = "The host didn't answer."
                    client.close()
                    self.connecting = None

    # ---------------------------------------------------------- draw
    def draw(self, surf):
        ui.draw_text(surf, "Multiplayer", 40, WHITE, (40, 22), "topleft")
        ui.draw_text(surf, "Everyone on their own computer. Room codes work on any network - school Wi-Fi, "
                     "different houses, hotspots.", 15, GRAY, (42, 70), "topleft", bold=False)
        ui.draw_text(surf, "Your name", 14, GRAY, (42, 122), "bottomleft", bold=False)
        self.name.draw(surf)

        ui.draw_panel(surf, (40, 200, 384, 440))
        ui.draw_text(surf, "Host a game", 22, WHITE, (64, 232), "midleft")
        sub = "You'll get a room code to share." if self.online else "Online play not set up - LAN only."
        ui.draw_text(surf, sub, 14, GRAY, (64, 262), "midleft", bold=False)
        ui.draw_text(surf, "Card packs", 16, WHITE, (64, 298), "midleft")
        self.chips.draw(surf)
        b, w = self.app.library.counts(self.app.settings["packs"])
        n = len(self.app.settings["packs"])
        label = getattr(self, "preset", None) or "Custom mix"
        ui.draw_text(surf, f"{label}: {n} packs · {b + w:,} cards", 13, ACCENT if self.preset else GRAY,
                     (64, 456), "midleft", bold=False)
        self.packs_btn.draw(surf)
        ui.draw_text(surf, "You can change these in the lobby too.", 12, DIM, (64, 540), "midleft", bold=False)
        self.host_btn.draw(surf)

        ui.draw_panel(surf, (448, 200, 792, 440))
        ui.draw_text(surf, "Join a game", 22, WHITE, (472, 232), "midleft")
        self.code.draw(surf)
        self.join_code_btn.draw(surf)

        ui.draw_text(surf, "On the same home network", 15, WHITE, (472, 382), "midleft")
        if not self.games:
            dots = "." * (1 + int(self.t * 2) % 3)
            ui.draw_text(surf, f"No LAN games found{dots}  (school networks usually block this - use the code)", 13,
                         DIM, (472, 420), "midleft", bold=False)
        for i, g in enumerate(self.games):
            y = LIST_Y + i * ROW_H
            r = V.rect((464, y, 760, ROW_H - 6))
            surf.blit(ui.rounded_px(r.w, r.h, V.s(10), PANEL_HI), r)
            ui.draw_text(surf, ui.ellipsize(g.get("title", "Game"), 16, 420), 16, WHITE, (482, y + 16), "midleft")
            status = "in lobby" if g.get("phase") == "lobby" else "in progress"
            code = f"  ·  code {g['code']}" if g.get("code") else ""
            ui.draw_text(surf, f"{g['ip']}  ·  {g.get('players', 0)} players  ·  {status}{code}", 12, GRAY,
                         (482, y + 35), "midleft", bold=False)
            if g.get("v") != 2:
                ui.draw_text(surf, "different version", 13, RED, (1084, y + 24), "midright", bold=False)
        for b in self.game_btns.values():
            b.draw(surf)
        ui.draw_text(surf, "Or by IP:", 14, GRAY, (472, 608), "midleft", bold=False)
        self.ip.draw(surf)
        self.join_ip_btn.draw(surf)

        self.back.draw(surf)
        if self.connecting:
            dots = "." * (1 + int(self.t * 3) % 3)
            ui.draw_text(surf, f"Connecting to {self.connecting['label']}{dots}", 16, ACCENT, (230, 679), "midleft",
                         bold=False)
        elif self.error:
            ui.draw_text(surf, ui.ellipsize(self.error, 15, 1000, False), 15, RED, (230, 679), "midleft",
                         bold=False)
