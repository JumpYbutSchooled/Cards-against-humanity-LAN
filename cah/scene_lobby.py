import random

import pygame

from . import ui
from .app import Scene
from .net import GAME_PORT, local_ips
from .scene_setup import BOT_NAMES
from .ui import Button, Segmented, Stepper, V, WHITE, GRAY, DIM, ACCENT, RED, PANEL_HI

ROW_Y, ROW_H = 166, 46


class LobbyScene(Scene):
    def __init__(self, app, session):
        super().__init__(app)
        self.session = session
        app.session = session
        self.host = session.is_host
        st = app.settings
        self.v = session.view()
        self.kick_btns = {}
        self.ips = local_ips() if self.host else []
        self.leave_btn = Button((40, 654, 160, 50), "Leave", self.leave, "ghost", 18)
        self.start = Button((1010, 654, 230, 50), "Start Game", self.on_start, "accent", 20)
        self.add_bot = Button((580, 112, 130, 38), "+ Bot", self.on_add_bot, "secondary", 15)
        self.packs_btn = Button((800, 428, 410, 42), "Customize packs...", self.on_packs, "secondary", 16)
        self.points = Stepper((800, 158, 410, 50), "Points to win", st.get("points", 7), 1, 25,
                              on_change=self.on_points, sounds=app.sounds)
        self.hand = Stepper((800, 214, 410, 50), "Cards in hand", st.get("hand", 10), 5, 15,
                            on_change=self.on_hand, sounds=app.sounds)
        from .scene_packs import PresetChips
        self.chips = PresetChips(app, 800, 318, 410, self.on_preset)
        modes = ["off", "host", "all"]
        self.voice = Segmented((1046, 114, 174, 34), ["Off", "Host", "All"],
                               modes.index(st.get("tts_mode", "off")) if st.get("tts_mode") in modes else 0,
                               self.on_voice, 13, app.sounds)
        if self.host:
            self.on_voice(self.voice.index, quiet=True)
        if self.host:  # the lobby starts with the host's saved packs; tag custom presets by name
            self.apply_packs(list(st["packs"]))
        self.fixed = self.buttons(self.leave_btn, self.start, self.add_bot, self.packs_btn)
        self.start.visible = self.add_bot.visible = self.packs_btn.visible = self.host
        self.t = 0.0

    # ---------------------------------------------------------- host actions
    def srv(self, fn):
        return self.session.server.host(fn)

    def on_add_bot(self):
        taken = {p["name"] for p in self.v["players"]}
        name = next((n for n in BOT_NAMES if n not in taken), f"Bot {random.randint(10, 99)}")
        self.srv(lambda e: e.add_player(name, bot=True))

    def on_points(self, v):
        self.app.settings["points"] = v
        self.srv(lambda e: e.configure(points=v))

    def on_hand(self, v):
        self.app.settings["hand"] = v
        self.srv(lambda e: e.configure(hand=v))

    def on_voice(self, i, quiet=False):
        mode = ["off", "host", "all"][i]
        self.app.settings["tts_mode"] = mode
        self.srv(lambda e: e.configure(tts=mode))
        if mode != "off" and not quiet:
            from .tts import speaker
            speaker().say("Robot voice on.")

    def apply_packs(self, packs):
        from .presets import match_name
        name = match_name(self.app.library, packs, self.app.settings) or ""
        self.srv(lambda e: e.configure(packs=packs, preset=name))

    def on_preset(self, packs, name):
        self.app.settings["packs"] = packs
        self.app.save()
        self.apply_packs(packs)

    def on_packs(self):
        from .scene_packs import PacksScene

        def back():
            self.apply_packs(list(self.app.settings["packs"]))
            return self
        self.app.switch(PacksScene(self.app, back=back))

    def on_start(self):
        if self.srv(lambda e: e.start_problem()) is None:
            self.app.save()
            self.srv(lambda e: e.start())

    def kick(self, pid):
        self.session.server.kick(pid)

    def leave(self):
        self.session.leave()
        self.app.session = None
        from .scene_lan import LanScene
        self.app.switch(LanScene(self.app))

    # ---------------------------------------------------------- loop
    def handle(self, ev):
        widgets = self.fixed + list(self.kick_btns.values())
        if self.host:
            widgets += [self.points, self.hand, self.chips, self.voice]
        for w in widgets:
            if w.handle(ev):
                return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.leave()

    def update(self, dt):
        self.t += dt
        if self.session.error:
            self.session.leave()
            self.app.session = None
            from .scene_lan import LanScene
            self.app.switch(LanScene(self.app, self.session.error))
            return
        v = self.session.view()
        if v is None:
            return
        self.v = v
        if v["phase"] != "lobby":
            from .scene_game import GameScene
            self.app.switch(GameScene(self.app, self.session))
            return
        if self.host:
            problem = self.srv(lambda e: e.start_problem())
            self.start.enabled = problem is None
            self.problem = problem
            self.add_bot.enabled = len(v["players"]) < 10
            ids = set()
            for i, p in enumerate(v["players"]):
                if p["host"]:
                    continue
                ids.add(p["id"])
                b = self.kick_btns.get(p["id"])
                if b is None:
                    b = Button((620, 0, 90, 38), "Remove", lambda pid=p["id"]: self.kick(pid), "danger", 14)
                    b.sounds = self.app.sounds
                    self.kick_btns[p["id"]] = b
                b.rect.y = ROW_Y + i * ROW_H
            for k in list(self.kick_btns):
                if k not in ids:
                    del self.kick_btns[k]
            self.points.update(dt)
            self.hand.update(dt)
            self.chips.update(dt, v["config"].get("preset"))
            self.voice.update(dt)
        for b in self.fixed + list(self.kick_btns.values()):
            b.update(dt)

    def draw(self, surf):
        v = self.v
        if v is None:
            ui.draw_text(surf, "Connecting...", 24, GRAY, (640, 360))
            return
        host_p = next((p for p in v["players"] if p["host"]), None)
        title = "Your game" if self.host else f"{host_p['name'] if host_p else 'Host'}'s game"
        ui.draw_text(surf, title, 40, WHITE, (40, 22), "topleft")
        sub = ("Waiting for players to join. Start when everyone's in." if self.host else
               "You're in! Waiting for the host to start the game" + "." * (1 + int(self.t * 2) % 3))
        ui.draw_text(surf, sub, 15, GRAY, (42, 70), "topleft", bold=False)

        ui.draw_panel(surf, (24, 100, 712, 540))
        ui.draw_text(surf, "Players", 22, WHITE, (48, 131), "midleft")
        ui.draw_text(surf, f"{len(v['players'])} / 10", 14, GRAY, (150, 132), "midleft", bold=False)
        self.add_bot.draw(surf)
        me = self.session.me
        for i, p in enumerate(v["players"]):
            y = ROW_Y + i * ROW_H
            r = V.rect((48, y, 560 if self.host else 662, 38))
            surf.blit(ui.rounded_px(r.w, r.h, V.s(10), PANEL_HI if p["id"] == me else (36, 36, 42)), r)
            pygame.draw.circle(surf, (50, 50, 58) if p["id"] != me else ACCENT, V.pt(70, y + 19), V.s(12))
            ui.draw_text(surf, str(i + 1), 13, WHITE if p["id"] != me else (20, 20, 20), (70, y + 19.5))
            ui.draw_text(surf, ui.ellipsize(p["name"], 17, 330), 17, WHITE, (94, y + 19), "midleft")
            tags = []
            if p["id"] == me:
                tags.append("you")
            if p["host"]:
                tags.append("host")
            if p["bot"]:
                tags.append("bot")
            ui.draw_text(surf, " · ".join(tags), 14, ACCENT if p["id"] == me else GRAY,
                         ((588 if self.host else 690), y + 19), "midright", bold=False)
        for b in self.kick_btns.values():
            b.draw(surf)

        ui.draw_panel(surf, (770, 100, 470, 540))
        ui.draw_text(surf, "Rules", 22, WHITE, (800, 131), "midleft")
        cfg = v["config"]
        ui.draw_text(surf, "Robot voice", 14, GRAY, (1036, 131), "midright", bold=False)
        if self.host:
            self.voice.draw(surf)
        else:
            label = {"off": "Off", "host": "Host PC", "all": "On"}.get(cfg.get("tts", "off"), "Off")
            ui.draw_text(surf, label, 16, ACCENT if cfg.get("tts", "off") != "off" else WHITE, (1046, 131),
                         "midleft")
        if self.host:
            self.points.draw(surf)
            self.hand.draw(surf)
        else:
            ui.draw_text(surf, "Points to win", 18, WHITE, (800, 183), "midleft")
            ui.draw_text(surf, str(cfg["points"]), 22, WHITE, (1190, 183), "midright")
            ui.draw_text(surf, "Cards in hand", 18, WHITE, (800, 239), "midleft")
            ui.draw_text(surf, str(cfg["hand"]), 22, WHITE, (1190, 239), "midright")
        ui.draw_text(surf, "Card packs", 22, WHITE, (800, 296), "midleft")
        n = cfg["packs"]
        preset = cfg.get("preset") or "Custom mix"
        if self.host:
            self.chips.draw(surf)
        else:
            ui.draw_text(surf, preset, 30, ACCENT, (800, 350), "midleft")
        ui.draw_text(surf, f"{preset}:  {n} pack{'s' if n != 1 else ''}  ·  {cfg['black']:,} black  ·  "
                     f"{cfg['white']:,} white", 14, GRAY, (800, 410), "midleft", bold=False)
        self.packs_btn.draw(surf)
        if self.host:
            srv = self.session.server
            relay = srv.relay
            ui.draw_text(surf, "How friends join", 17, WHITE, (800, 494), "midleft")
            if relay and relay.status == "online":
                ui.draw_text(surf, "Multiplayer > type this room code:", 14, GRAY, (800, 518), "midleft", bold=False)
                ui.draw_text(surf, " ".join(relay.code), 44, ACCENT, (800, 560), "midleft")
            elif relay and relay.status == "connecting":
                dots = "." * (1 + int(self.t * 2) % 3)
                ui.draw_text(surf, f"Getting a room code{dots}", 18, GRAY, (800, 550), "midleft", bold=False)
            else:
                msg = "Online play unavailable - check the internet." if relay else "Online play not set up."
                ui.draw_text(surf, msg, 14, RED, (800, 518), "midleft", bold=False)
            if srv.port and self.ips:
                suffix = "" if srv.port == GAME_PORT else f":{srv.port}"
                ui.draw_text(surf, f"Same home network? LAN address: {self.ips[0]}{suffix}", 13, DIM, (800, 612),
                             "midleft", bold=False)
        else:
            ui.draw_text(surf, "The host picks the packs and rules.", 14, DIM, (800, 440), "midleft", bold=False)

        self.leave_btn.draw(surf)
        self.start.draw(surf)
        if self.host and getattr(self, "problem", None):
            ui.draw_text(surf, self.problem, 15, RED, (990, 679), "midright", bold=False)
