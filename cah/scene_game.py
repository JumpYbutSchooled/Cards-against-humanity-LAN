"""The table. Renders engine snapshots and animates whatever changed between them.

Works for hot-seat (LocalSession: the "seat" moves between humans behind a cover
screen), and for LAN host/client (the seat is always you).
"""
import math
import random

import pygame

from . import ui
from .app import Scene
from .cards import BlackCard, WhiteCard, fill
from .engine import Engine
from .render import CardSprite, CARD_RATIO
from .session import LocalSession
from .ui import Button, V, WHITE, GRAY, DIM, INK, ACCENT, PANEL, GREEN

BLACK_POS = (150, 250)
BLACK_W = 196
HAND_W = 128
HAND_CX = 530
TABLE = pygame.Rect(285, 84, 745, 372)
PANEL_TOP = (285, 96, 745, 230)
PANEL_BOTTOM = (285, 470, 745, 168)
SIDEBAR_X = 1046
CONFETTI = [(255, 199, 44), (246, 246, 244), (240, 92, 92), (96, 214, 140), (110, 160, 255), (220, 120, 255)]


def start_local_game(app):
    st = app.settings
    e = Engine(app.library, st["packs"], st.get("points", 7), st.get("hand", 10), local=True)
    for p in st["players"]:
        e.add_player(p["name"], bot=p["bot"])
    e.start()
    return GameScene(app, LocalSession(e))


class Group:
    def __init__(self):
        self.sprites = []
        self.revealed = False
        self.pid = None
        self.hover = 0.0
        self.read = 0.0
        self.out = False
        self.outa = 0.0
        self.label_a = 0.0
        self.center = (TABLE.centerx, TABLE.centery)
        self.label_y = TABLE.centery

    def contains(self, p):
        return any(s.contains(p) for s in self.sprites)


class GameScene(Scene):
    def __init__(self, app, session):
        super().__init__(app)
        self.session = session
        app.session = session if session.net else None
        self.v = None
        self.seat = None
        self.unlocked = None
        self.cover = 0.0
        self.cover_target = 0.0
        self.cover_for = None
        self.hand_owner = -1
        self.hand_sprites = []
        self.selected = []
        self.hovered_card = None
        self.groups = []
        self.hover_group = None
        self.black_sprite = None
        self.black_age = 0.0
        self.flying = []
        self.particles = []
        self.banner = None
        self.round_seen = 0
        self.phase_seen = None
        self.winner_seen = None
        self.scores = {}
        self.bump = {}
        self.paused = False
        self.pause_a = 0.0
        self.over_a = 0.0
        self.over_t = 0.0
        self.err_a = 0.0
        self.status = ""

        net, host = session.net, session.is_host
        self.action = Button((530, 346, 260, 52), "", None, "accent", 19)
        self.reveal_all = Button((462, 654, 190, 46), "Reveal all", self.do_reveal_all, "secondary", 16)
        self.elim_btn = Button((447, 652, 200, 50), "Eliminate", self.eliminate, "danger", 18)
        self.coin_btn = Button((447, 652, 200, 50), "Coin flip", self.coinflip, "secondary", 18)
        self.elim_btn.visible = self.coin_btn.visible = False
        self.coin_anim = None  # (round, pair, result, started_at) while the coin spins on screen
        self.spoken = {}
        self.menu_btn = Button((24, 18, 96, 38), "Menu", self.toggle_pause, "ghost", 15)
        leave_label = "End game for everyone" if host else ("Leave game" if net else "Main menu")
        self.p_resume = Button((490, 0, 300, 56), "Resume", self.toggle_pause, "primary", 20)
        self.p_packs = Button((490, 0, 300, 52), "Change card packs", self.open_packs, "secondary", 18)
        self.p_voice = Button((490, 0, 300, 52), "", self.cycle_voice, "secondary", 18)
        self.p_restart = Button((490, 0, 300, 52), "Restart game", self.restart, "secondary", 18)
        self.p_leave = Button((490, 0, 300, 52), leave_label, self.leave, "ghost", 18)
        self.p_restart.visible = not net
        self.p_packs.visible = host or not net  # the host (or a local game) controls the packs
        self.p_voice.visible = host or not net
        y = 296
        for b in (self.p_resume, self.p_packs, self.p_voice, self.p_restart, self.p_leave):
            if b.visible:
                b.rect.y = y
                y += b.rect.h + 10
        self.pause_h = y - 296 + 100
        again = "Back to lobby" if host else "Play again"
        self.o_again = Button((440, 560, 190, 54), again, self.restart, "accent", 19)
        self.o_again.visible = not (net and not host)
        self.o_menu = Button((650, 560, 190, 54), "End game" if host else ("Leave" if net else "Main menu"),
                             self.leave, "secondary", 19)
        self.err_btn = Button((540, 400, 200, 52), "Back to menu", self.leave, "primary", 18)
        self.buttons(self.action, self.reveal_all, self.elim_btn, self.coin_btn, self.menu_btn, self.p_resume,
                     self.p_packs, self.p_voice, self.p_restart, self.p_leave, self.o_again, self.o_menu, self.err_btn)

    # ================================================================ helpers
    def player(self, pid):
        if not self.v:
            return None
        return next((p for p in self.v["players"] if p["id"] == pid), None)

    def name(self, pid, you=True):
        if you and self.session.net and pid == self.session.me:
            return "You"
        p = self.player(pid)
        return p["name"] if p else "?"

    @property
    def multi_human(self):
        if not self.session.local or not self.v:
            return False
        return sum(1 for p in self.v["players"] if not p["bot"]) > 1

    @property
    def pick(self):
        return self.v["black"]["pick"] if self.v and self.v["black"] else 1

    def covered(self):
        return self.cover_target > 0.5

    def waiting_names(self):
        v = self.v
        return [p["name"] for p in v["players"] if p["in_round"] and p["id"] != v["czar"] and not p["played"]]

    def can_play(self):
        v = self.v
        if not v or v["phase"] != "play" or self.seat is None or self.seat == v["czar"] or self.covered():
            return False
        me = self.player(self.seat)
        return bool(me and me["in_round"] and not me["played"] and self.hand_sprites)

    def is_judging(self):
        v = self.v
        return bool(v and v["phase"] == "judge" and self.seat == v["czar"] and not self.covered())

    # ================================================================ seat / cover (hot-seat only)
    def compute_seat(self, pub):
        humans = [p for p in pub["players"] if not p["bot"] and not p["away"]]
        if sum(1 for p in pub["players"] if not p["bot"]) <= 1:
            return humans[0]["id"] if humans else None
        ph = pub["phase"]
        if ph == "play":
            todo = [p for p in humans if p["in_round"] and p["id"] != pub["czar"] and not p["played"]]
            return todo[0]["id"] if todo else None
        if ph == "judge":
            czar = next((p for p in humans if p["id"] == pub["czar"]), None)
            return czar["id"] if czar else None
        return None

    def unlock(self):
        self.unlocked = self.cover_for
        self.cover_target = 0.0

    # ================================================================ actions
    def play_selected(self):
        need = min(self.pick, len(self.hand_sprites))
        if len(self.selected) != need or not self.can_play():
            return
        idxs = [self.hand_sprites.index(s) for s in self.selected]
        self.session.act(self.seat, {"a": "submit", "cards": idxs, "round": self.v["round"]})
        for i, s in enumerate(self.selected):  # optimistic: fly to the table now
            s.move(657 + i * 20, 230, 0.55)
            s.talpha, s.tglow, s.badge, s.speed = 0, 0, None, 9
            self.flying.append(s)
            self.hand_sprites.remove(s)
        self.selected = []
        self.app.sounds.play("card")

    def toggle_card(self, s):
        if not self.can_play():
            return
        if s in self.selected:
            self.selected.remove(s)
            self.app.sounds.play("deselect")
        else:
            if len(self.selected) >= self.pick:
                if self.pick != 1:
                    return
                self.selected = []
            self.selected.append(s)
            self.app.sounds.play("select")

    def do_reveal_all(self):
        if self.is_judging():
            self.session.act(self.seat, {"a": "reveal_all", "round": self.v["round"]})

    def award(self):
        if self.is_judging() and self.v["focus"] is not None:
            self.session.act(self.seat, {"a": "award", "i": self.v["focus"], "round": self.v["round"]})

    def next_round(self):
        if self.v and self.v["can_next"]:
            pid = self.seat if self.seat is not None else self.session.me
            if pid is None:  # hot-seat with nobody "seated": any human may continue
                pid = next((p["id"] for p in self.v["players"] if not p["bot"]), self.v["players"][0]["id"])
            self.session.act(pid, {"a": "next", "round": self.v["round"]})

    def restart(self):
        if self.session.local:
            self.app.switch(start_local_game(self.app))
        elif self.session.is_host:
            self.session.server.host(lambda e: e.to_lobby())

    def leave(self):
        self.session.leave()
        self.app.session = None
        from .scene_menu import MenuScene
        self.app.switch(MenuScene(self.app))

    def toggle_pause(self):
        self.paused = not self.paused

    def eliminate(self):
        v = self.v
        if self.is_judging() and v["focus"] is not None:
            self.session.act(self.seat, {"a": "eliminate", "i": v["focus"], "round": v["round"]})
            self.app.sounds.play("deselect")

    def coinflip(self):
        if self.is_judging():
            self.session.act(self.seat, {"a": "coinflip", "round": self.v["round"]})

    # ---------------------------------------------------------------- robot voice
    VOICE_MODES = ["off", "host", "all"]
    VOICE_LABEL = {"off": "Robot voice: Off", "host": "Robot voice: Host PC", "all": "Robot voice: Everyone"}

    def voice_mode(self):
        if self.session.local:
            return "all" if self.app.settings.get("tts_local") else "off"
        return (self.v or {}).get("config", {}).get("tts", "off")

    def cycle_voice(self):
        if self.session.local:
            on = not self.app.settings.get("tts_local")
            self.app.settings["tts_local"] = on
            self.app.save()
            if on:
                self.say("Robot voice on.")
        elif self.session.is_host:
            modes = self.VOICE_MODES
            nxt = modes[(modes.index(self.voice_mode()) + 1) % len(modes)]
            self.app.settings["tts_mode"] = nxt
            self.session.server.host(lambda e: e.configure(tts=nxt))
            if nxt != "off":
                self.say("Robot voice on.")

    def voice_here(self):
        mode = self.voice_mode()
        return mode == "all" or (mode == "host" and self.session.is_host)

    def say(self, text):
        from .tts import speaker
        speaker().say(text)

    def speak_once(self, key, text):
        """Speak each moment once (state snapshots repeat; the voice shouldn't)."""
        if self.voice_here() and self.spoken.get(key[0]) != key:
            self.spoken[key[0]] = key
            self.say(text)

    def open_packs(self):
        """Host / local game: change packs mid-game; new cards come from the new packs from now on."""
        from .scene_packs import PacksScene

        def back():
            packs = list(self.app.settings["packs"])
            if self.session.local:
                self.session.engine.configure(packs=packs)
            elif self.session.is_host:
                from .presets import match_name
                name = match_name(self.app.library, packs, self.app.settings) or ""
                self.session.server.host(lambda e: e.configure(packs=packs, preset=name))
            self.paused = False
            return self
        self.app.switch(PacksScene(self.app, back=back))

    # ================================================================ syncing snapshots -> sprites
    def sync(self, v):
        r = v["round"]
        if v["black"] and r != self.round_seen:
            self.new_round_visuals(v)
        hand_visible = (self.seat is not None and v["phase"] in ("intro", "play") and not self.covered())
        owner = self.seat if hand_visible else None
        if owner != self.hand_owner:
            self.drop_hand()
            self.hand_owner = owner
        if owner is not None:
            self.sync_hand(v["hand"], v["mine"])

        if v["phase"] in ("judge", "result") and v["subs"]:
            if len(self.groups) != len(v["subs"]):
                self.build_groups(v)
            for i, (g, sub) in enumerate(zip(self.groups, v["subs"])):
                if sub["cards"] and not g.revealed:
                    g.revealed = True
                    for j, s in enumerate(g.sprites):
                        c = sub["cards"][j] if j < len(sub["cards"]) else {"t": "", "p": ""}
                        s.text, s.pack = c["t"], c["p"]
                        s.card = WhiteCard(c["t"], c["p"])
                        s.tflip = 0.0
                        s.delay = j * 0.08
                g.pid = sub["pid"]
                g.out = bool(sub.get("out"))
                for s in g.sprites:
                    s.tglow = 1.0 if (v["focus"] == i and not g.out) else 0.0
                    s.tdim = 1.0 if (g.out or (v["winner"] is not None and i != v["winner"])) else 0.0
            coin = v.get("coin")
            if coin and (self.coin_anim is None or self.coin_anim["round"] != r):
                self.coin_anim = {"round": r, "pair": coin["pair"], "result": coin["result"], "t": 0.0,
                                  "landed": False}
                self.app.sounds.play("whoosh")
                self.speak_once(("coin", r), "Coin flip!")
            if v["phase"] == "judge" and v.get("reading") is not None:
                sub = v["subs"][v["reading"]]
                if sub["cards"]:
                    segs = fill(v["black"]["t"], [c["t"] for c in sub["cards"]], 0, 0)
                    self.speak_once(("read", r, v["reading"]), "".join(t for t, _ in segs))
            if v["phase"] == "result" and v["winner"] is not None:
                wp = v["subs"][v["winner"]]["pid"]
                self.speak_once(("win", r), f"{self.name(wp, False)} wins the round!")
            if v["winner"] is not None and self.winner_seen != (r, v["winner"]):
                self.winner_seen = (r, v["winner"])
                self.app.sounds.play("point")
                g = self.groups[v["winner"]]
                self.burst(g.center[0], g.center[1], 60)
        elif self.groups and v["phase"] not in ("judge", "result"):
            self.fly_out_groups()

        for p in v["players"]:
            old = self.scores.get(p["id"])
            if old is not None and p["score"] > old:
                self.bump[p["id"]] = 1.0
            self.scores[p["id"]] = p["score"]

        if self.banner and v["phase"] not in ("intro", "play"):
            self.banner[2] = max(self.banner[2], 2.2)  # fast round: fade the banner out of the way
        if v["phase"] != self.phase_seen:
            if v["phase"] == "gameover":
                self.app.sounds.play("win")
                self.burst(640, 140, 90)
            elif v["phase"] == "judge":
                self.app.sounds.play("deal")
            self.phase_seen = v["phase"]

    def new_round_visuals(self, v):
        if self.black_sprite:
            bs = self.black_sprite
            bs.move(-200, bs.ty - 30)
            bs.talpha, bs.speed = 0, 7
            self.flying.append(bs)
        self.fly_out_groups()
        b = v["black"]
        card = BlackCard(b["t"], b["pick"], b["p"])
        bs = CardSprite("black", card, -160, BLACK_POS[1] - 40, BLACK_W, face_up=False, pick=card.pick)
        bs.text = card.display
        bs.angle = 12
        bs.move(*BLACK_POS, delay=0.15)
        bs.speed = 8
        bs.on_flip = lambda: self.app.sounds.play("flip")
        self.black_sprite = bs
        self.black_age = 0.0
        self.round_seen = v["round"]
        self.selected = []
        self.winner_seen = None
        self.coin_anim = None
        self.speak_once(("black", v["round"]), b["t"])
        if v["phase"] == "intro":
            czar = v["czar"]
            sub = "You're the Card Czar" if (self.session.net and czar == self.session.me) else \
                f"{self.name(czar, False)} is the Card Czar"
            self.banner = [f"Round {v['round']}", sub, 0.0]
        self.app.sounds.play("card")

    def drop_hand(self):
        for s in self.hand_sprites:
            s.move(s.tx, 900)
            s.talpha, s.tglow, s.badge, s.speed = 0, 0, None, 9
            self.flying.append(s)
        self.hand_sprites = []
        self.selected = []

    def sync_hand(self, cards, mine):
        existing = {s.text: s for s in self.hand_sprites}
        out, new = [], 0
        for c in cards:
            s = existing.pop(c["t"], None)
            if s is None:
                s = CardSprite("white", WhiteCard(c["t"], c["p"]), HAND_CX + (new - 5) * 30, 900, HAND_W)
                s.delay = 0.08 + new * 0.045
                new += 1
            out.append(s)
        mine_t = {c["t"] for c in mine}
        for s in existing.values():
            if s.text in mine_t:
                s.move(657, 230, 0.55)
            else:
                s.move(s.tx, 900)
            s.talpha, s.tglow, s.badge, s.speed = 0, 0, None, 9
            self.flying.append(s)
        if new:
            self.app.sounds.play("deal")
        self.hand_sprites = out
        self.selected = [s for s in self.selected if s in out]

    def build_groups(self, v):
        self.fly_out_groups()
        for i, sub in enumerate(v["subs"]):
            g = Group()
            for j in range(sub["n"]):
                s = CardSprite("white", WhiteCard("", ""), TABLE.centerx, TABLE.centery, 120, face_up=False)
                s.scale = 0.5
                s.delay = 0.1 + i * 0.07 + j * 0.03
                s.on_flip = lambda: self.app.sounds.play("flip")
                g.sprites.append(s)
            self.groups.append(g)
        self.layout_groups()

    def fly_out_groups(self):
        for g in self.groups:
            for s in g.sprites:
                s.move(s.tx + 900, s.ty - 40, 0.8)
                s.talpha, s.tglow, s.speed = 0, 0, 6
                self.flying.append(s)
        self.groups = []

    # ================================================================ layout
    def layout_hand(self):
        sprites = self.hand_sprites
        n = len(sprites)
        if not n:
            self.hovered_card = None
            return
        width = 960
        spacing = min(HAND_W + 10, (width - HAND_W) / max(1, n - 1))
        base = []
        for i in range(n):
            off = i - (n - 1) / 2
            base.append((HAND_CX + off * spacing, 616 + (off / max(1, n / 2)) ** 2 * 12))
        # Hit-test resting positions (plus the lifted area) so hovering doesn't flicker between cards.
        mouse = ui.mouse_pos()
        hovered = None
        if not self.paused:
            ch = HAND_W * CARD_RATIO
            for i in reversed(range(n)):
                x, y = base[i]
                lift = 92 if sprites[i] in self.selected else 34
                if pygame.Rect(x - HAND_W / 2, y - ch / 2 - lift, HAND_W, ch + lift).collidepoint(mouse):
                    hovered = sprites[i]
                    break
        self.hovered_card = hovered
        playable = self.can_play()
        czar = self.v and self.seat == self.v["czar"]
        for i, s in enumerate(sprites):
            x, y = base[i]
            scale = 1.0
            if s in self.selected:
                y -= 58
                scale = 1.06
                s.tglow = 1.0
                s.badge = self.selected.index(s) + 1 if self.pick > 1 else None
            else:
                s.tglow = 0.0
                s.badge = None
            if s is hovered:
                y -= 34 if playable else 20
                scale = 1.14 if playable else 1.08
            s.tdim = 0.55 if czar else 0.0
            s.move(x, y, scale)

    def draw_order(self):
        order = list(self.hand_sprites)
        if self.hovered_card in order:
            order.remove(self.hovered_card)
            order.append(self.hovered_card)
        return order

    def layout_groups(self):
        n = len(self.groups)
        if not n:
            return
        pick = max(len(g.sprites) for g in self.groups) or 1
        label_h, gap = 24, 18
        best = None
        for cols in range(1, n + 1):
            rows = math.ceil(n / cols)
            w1 = (TABLE.w - (cols - 1) * gap) / (cols * (1 + 0.5 * (pick - 1)))
            w2 = ((TABLE.h - (rows - 1) * gap) / rows - label_h) / CARD_RATIO
            w = min(w1, w2, 150)
            if best is None or w > best[0] + 0.5:
                best = (w, cols, rows)
        w, cols, rows = best
        h = w * CARD_RATIO
        gw = w * (1 + 0.5 * (pick - 1))
        total_h = rows * (h + label_h) + (rows - 1) * gap
        y0 = TABLE.y + (TABLE.h - total_h) / 2 + h / 2
        for i, g in enumerate(self.groups):
            r, c = divmod(i, cols)
            in_row = min(cols, n - r * cols)
            row_w = in_row * gw + (in_row - 1) * gap
            gx = TABLE.centerx - row_w / 2 + c * (gw + gap) + w / 2
            gy = y0 + r * (h + label_h + gap)
            g.center = (gx + (gw - w) / 2, gy)
            g.label_y = gy + h / 2 + 14
            lift = 6 * g.hover + 12 * g.read - 10 * g.outa
            for j, s in enumerate(g.sprites):
                s.resize(w)
                s.move(gx + j * w * 0.5, gy - lift, 1.0 + 0.03 * g.hover + 0.04 * g.read - 0.1 * g.outa)

    # ================================================================ effects
    def burst(self, x, y, n):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            sp = random.uniform(120, 420)
            self.particles.append({"x": x, "y": y, "vx": math.cos(a) * sp, "vy": math.sin(a) * sp - 220,
                                   "r": random.uniform(0, math.tau), "vr": random.uniform(-8, 8),
                                   "s": random.uniform(5, 10), "c": random.choice(CONFETTI),
                                   "life": random.uniform(2.2, 3.6)})

    def rain(self, dt):
        for _ in range(int(70 * dt) + (random.random() < (70 * dt) % 1)):
            self.particles.append({"x": random.uniform(0, ui.DW), "y": -20, "vx": random.uniform(-50, 50),
                                   "vy": random.uniform(60, 180), "r": random.uniform(0, math.tau),
                                   "vr": random.uniform(-6, 6), "s": random.uniform(5, 9),
                                   "c": random.choice(CONFETTI), "life": 9, "g": 40})

    def update_particles(self, dt):
        for p in self.particles:
            p["vy"] = min(p["vy"] + p.get("g", 520) * dt, 260)
            p["vx"] *= math.exp(-1.6 * dt)
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["r"] += p["vr"] * dt
            p["life"] -= dt
        self.particles = [p for p in self.particles if p["life"] > 0 and p["y"] < ui.DH + 30]

    def draw_particles(self, surf):
        for p in self.particles:
            s = p["s"]
            k = abs(math.cos(p["r"] * 1.3))
            cr, sr = math.cos(p["r"]), math.sin(p["r"])
            pts = []
            for ax, ay in ((-1, -0.5), (1, -0.5), (1, 0.5), (-1, 0.5)):
                ax *= s
                ay *= s * (0.3 + 0.7 * k)
                pts.append(V.pt(p["x"] + ax * cr - ay * sr, p["y"] + ax * sr + ay * cr))
            pygame.draw.polygon(surf, p["c"], pts)

    # ================================================================ events
    def handle(self, ev):
        if self.session.error and not self.session.local:
            self.err_btn.handle(ev)
            return
        v = self.v
        if v and v["phase"] == "gameover":
            for b in (self.o_again, self.o_menu):
                if b.handle(ev):
                    return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                self.o_menu.click()
            return
        if self.paused:
            for b in (self.p_resume, self.p_packs, self.p_voice, self.p_restart, self.p_leave):
                if b.handle(ev):
                    return
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                self.toggle_pause()
            return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.toggle_pause()
            return
        if self.menu_btn.handle(ev) or self.action.handle(ev) or self.reveal_all.handle(ev) or \
                self.elim_btn.handle(ev) or self.coin_btn.handle(ev):
            return
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_DELETE, pygame.K_x) and self.elim_btn.visible:
            self.eliminate()
            return
        if v is None or self.covered():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                if self.action.visible and self.action.enabled:
                    self.action.click()
            return
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                if self.action.visible and self.action.enabled:
                    self.action.click()
            elif pygame.K_0 <= ev.key <= pygame.K_9:
                i = (ev.key - pygame.K_1) % 10
                if i < len(self.hand_sprites):
                    self.toggle_card(self.hand_sprites[i])
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = V.to_design(ev.pos)
            if self.hovered_card is not None:
                self.toggle_card(self.hovered_card)
            elif self.is_judging():
                for i, g in enumerate(self.groups):
                    if g.contains(p):
                        sub = v["subs"][i]
                        if sub["cards"] is None:
                            self.session.act(self.seat, {"a": "reveal", "i": i, "round": v["round"]})
                        else:  # read it again / mark it as your pick
                            self.session.act(self.seat, {"a": "focus", "i": i, "round": v["round"]})
                            self.app.sounds.play("select")
                        break

    # ================================================================ update
    def update(self, dt):
        for b in (self.action, self.reveal_all, self.elim_btn, self.coin_btn, self.menu_btn, self.p_resume,
                  self.p_packs, self.p_voice, self.p_restart, self.p_leave, self.o_again, self.o_menu, self.err_btn):
            b.update(dt)
        self.p_voice.label = self.VOICE_LABEL[self.voice_mode()]
        err = self.session.error and not self.session.local
        self.err_a = ui.approach(self.err_a, 1.0 if err else 0.0, 10, dt)
        self.pause_a = ui.approach(self.pause_a, 1.0 if self.paused else 0.0, 14, dt)
        self.update_particles(dt)
        for k in list(self.bump):
            self.bump[k] = ui.approach(self.bump[k], 0.0, 3, dt)
        if self.banner:
            self.banner[2] += dt
            if self.banner[2] > 2.6:
                self.banner = None
        if err:
            return

        if self.session.local:
            if not self.paused:
                self.session.tick(dt)
            seat = self.compute_seat(self.session.view(None))
        else:
            seat = self.session.me
        v = self.session.view(seat)
        if v is None:
            return
        if v["phase"] == "lobby":
            if self.session.net:
                from .scene_lobby import LobbyScene
                self.app.switch(LobbyScene(self.app, self.session))
            return
        self.v = v

        # Hot-seat cover screen whenever the seat passes to a different human.
        if self.multi_human and seat is not None and seat != self.unlocked:
            if self.cover_for != seat or self.cover_target < 0.5:
                self.cover_for = seat
                self.cover_target = 1.0
                self.app.sounds.play("whoosh")
        elif seat is None:
            self.cover_target = 0.0
            self.unlocked = None
        self.seat = seat
        self.cover = ui.approach(self.cover, self.cover_target, 10, dt)
        self.over_a = ui.approach(self.over_a, 1.0 if v["phase"] == "gameover" else 0.0, 6, dt)
        self.over_t = self.over_t + dt if v["phase"] == "gameover" else 0.0
        if v["phase"] == "gameover" and self.over_t < 3.5:
            self.rain(dt)

        self.sync(v)

        if self.coin_anim:
            self.coin_anim["t"] += dt
            heads, _, landed = self.coin_state()
            if landed and not self.coin_anim["landed"]:
                self.coin_anim["landed"] = True
                self.app.sounds.play("flip")
                self.speak_once(("coinres", self.coin_anim["round"]), "Heads!" if heads else "Tails!")

        if self.black_sprite:
            self.black_age += dt
            if self.black_sprite.tflip > 0.5 and self.black_age > 0.7:
                self.black_sprite.tflip = 0.0
        self.layout_hand()
        if self.groups:
            m = ui.mouse_pos()
            self.hover_group = None
            if not self.paused and v["phase"] in ("judge", "result"):
                self.hover_group = next((g for g in self.groups if g.contains(m)), None)
            reading = v.get("reading") if v["phase"] == "judge" else None
            for i, g in enumerate(self.groups):
                hov = g is self.hover_group and self.is_judging()
                g.hover = ui.approach(g.hover, 1.0 if hov else 0.0, 14, dt)
                g.read = ui.approach(g.read, 1.0 if i == reading else 0.0, 10, dt)
                g.outa = ui.approach(g.outa, 1.0 if g.out else 0.0, 9, dt)
                g.label_a = ui.approach(g.label_a, 1.0 if v["phase"] == "result" else 0.0, 6, dt)
            self.layout_groups()

        for s in ([self.black_sprite] if self.black_sprite else []) + self.hand_sprites + self.flying + \
                [s for g in self.groups for s in g.sprites]:
            s.update(dt)
        self.flying = [s for s in self.flying if s.alpha > 3]
        self.update_action()

    def update_action(self):
        v = self.v
        ph = v["phase"]
        a = self.action
        self.reveal_all.visible = False
        self.elim_btn.visible = self.coin_btn.visible = False
        a.visible = True
        a.style = "accent"
        if self.covered():
            who = self.name(self.cover_for, False)
            label = f"I'm {who} - show me the cards" if self.cover_for == v["czar"] else f"I'm {who} - show my hand"
            w = max(300, ui.text_width(label, 19) + 60)
            a.label, a.callback, a.enabled, a.style = label, self.unlock, True, "primary"
            a.rect = pygame.Rect(640 - w / 2, 430, w, 58)
            self.status = ""
            return
        waiting = self.waiting_names()
        if ph == "play" and self.can_play():
            need = min(self.pick, len(self.hand_sprites))
            n = len(self.selected)
            a.label = (f"Play card{'s' if need > 1 else ''}" if n == need else
                       f"Pick {need - n} more card{'s' if need - n > 1 else ''}")
            a.callback, a.enabled = self.play_selected, n == need
            a.rect = pygame.Rect(530, 346, 260, 52)
            who = f"{self.name(self.seat, False)}, play" if self.multi_human else "Play"
            self.status = f"{who} {self.pick} card{'s' if self.pick > 1 else ''}"
        elif self.is_judging() and v.get("coin"):
            a.visible = False
            self.status = "Flipping a coin..."
        elif self.is_judging():
            all_rev = all(s["cards"] is not None for s in v["subs"])
            left = sum(1 for s in v["subs"] if not s.get("out"))
            self.reveal_all.visible = not all_rev
            self.elim_btn.visible = all_rev and left > 2
            self.elim_btn.enabled = v["focus"] is not None
            self.coin_btn.visible = all_rev and left == 2
            a.label, a.callback = "Award point", self.award
            a.enabled = all_rev and v["focus"] is not None
            a.rect = pygame.Rect(667, 652, 200, 50) if all_rev else pygame.Rect(668, 652, 220, 50)
            if not all_rev:
                self.status = "Flip the cards one by one and read them out"
            elif left > 2:
                self.status = "Pick a card, then Eliminate it (or Award it the point)"
            else:
                self.status = "Final two! Pick the winner - or flip a coin"
        elif ph == "result" and v["can_next"]:
            a.label = "Final results" if v["final"] else "Next round"
            a.callback, a.enabled = self.next_round, True
            a.rect = pygame.Rect(530, 652, 220, 50)
            self.status = ""
        else:
            a.visible = False
            if ph == "play":
                if self.seat is not None and self.seat == v["czar"]:
                    self.status = "You're the Card Czar - waiting for " + ", ".join(waiting) if waiting else ""
                elif waiting:
                    self.status = "Waiting for " + ", ".join(waiting)
                else:
                    self.status = ""
            elif ph == "judge":
                self.status = "Coin flip!" if v.get("coin") else f"{self.name(v['czar'], False)} is judging..."
            elif ph == "result":
                self.status = f"Waiting for {self.name(v['czar'], False)} to continue..."
            else:
                self.status = ""
        if len(self.status) > 70:
            self.status = self.status[:67] + "..."

    # ================================================================ draw
    def draw(self, surf):
        v = self.v
        if v is None:
            ui.draw_text(surf, "Connecting...", 26, GRAY, (640, 360))
            self.draw_error(surf)
            return
        self.draw_topbar(surf)
        self.draw_scores(surf)
        ph = v["phase"]

        if ph in ("intro", "play"):
            answers = [s.text for s in self.selected] or [c["t"] for c in v["mine"]]
            self.draw_sentence(surf, PANEL_TOP, answers, None)
        elif ph in ("judge", "result") and self.coin_showing():
            pass  # the coin takes over the bottom panel (drawn later, on top of the cards' shadows)
        elif ph in ("judge", "result"):
            # Everyone sees the same thing at the same time: whatever the Czar is reading out.
            g_i = v["winner"] if ph == "result" else v.get("reading")
            czar = "You're" if self.is_judging() else f"{self.name(v['czar'], False)} is"
            if g_i is not None and g_i < len(v["subs"]) and v["subs"][g_i]["cards"]:
                if ph == "result":
                    wp = v["subs"][g_i]["pid"]
                    title = "You win the round!" if (self.session.net and wp == self.session.me) else \
                        f"{self.name(wp, False)} wins the round!"
                else:
                    title = f"{czar} reading card {g_i + 1} of {len(v['subs'])}"
                self.draw_sentence(surf, PANEL_BOTTOM, [c["t"] for c in v["subs"][g_i]["cards"]], title)
            else:
                # Nothing flipped yet: the black card with its blanks, big, to read out first.
                title = "Read the card out loud, then flip the answers" if self.is_judging() else \
                    f"{czar} reading the card..."
                self.draw_sentence(surf, PANEL_BOTTOM, [], title)

        if self.black_sprite:
            self.black_sprite.draw(surf)
            if ph != "gameover":
                czar_name = self.name(v["czar"])
                ui.draw_text(surf, "Card Czar", 13, GRAY, (BLACK_POS[0], BLACK_POS[1] + 160), bold=False)
                ui.draw_crown(surf, (BLACK_POS[0] - ui.text_width(czar_name, 17) / 2 - 14, BLACK_POS[1] + 182), 16)
                ui.draw_text(surf, czar_name, 17, WHITE, (BLACK_POS[0], BLACK_POS[1] + 182))

        for gi, g in enumerate(self.groups):
            for s in g.sprites:
                s.draw(surf)
            if g.outa > 0.05:  # eliminated
                x, y = g.center
                r = V.rect((x - 46, y - 20, 92, 40))
                surf.blit(ui.rounded_px(r.w, r.h, r.h // 2, (150, 30, 36), int(235 * g.outa)), r)
                ui.draw_text(surf, "OUT", 22, WHITE, (x, y + 1), alpha=255 * g.outa)
            if self.coin_anim and gi in self.coin_anim["pair"]:
                heads_card = gi == self.coin_anim["pair"][0]
                won = self.coin_state()[2] and gi == self.coin_anim["result"]
                top = g.center[1] - (g.sprites[0].h / 2 if g.sprites else 80) - 20
                r = V.rect((g.center[0] - 54, top - 15, 108, 30))
                surf.blit(ui.rounded_px(r.w, r.h, r.h // 2, ACCENT if won else (40, 40, 46)), r)
                ui.draw_text(surf, "HEADS" if heads_card else "TAILS", 15, INK if won else WHITE,
                             (g.center[0], top))
            if g.label_a > 0.02 and g.pid is not None:
                win = v["winner"] is not None and self.groups.index(g) == v["winner"]
                ui.draw_text(surf, self.name(g.pid), 15, ACCENT if win else GRAY, (g.center[0], g.label_y),
                             alpha=255 * g.label_a)
        for s in self.draw_order():
            s.draw(surf)
        for s in self.flying:
            s.draw(surf)

        if ph != "gameover" and not self.covered():
            self.action.draw(surf)
            self.reveal_all.draw(surf)
            self.elim_btn.draw(surf)
            self.coin_btn.draw(surf)
        if self.coin_anim:
            self.draw_coin(surf)
        if self.banner:
            self.draw_banner(surf)
        if self.cover > 0.01:
            self.draw_cover(surf)
        if self.pause_a > 0.01:
            self.draw_pause(surf)
        if self.over_a > 0.01:
            self.draw_gameover(surf)
        else:
            self.draw_particles(surf)
        self.draw_error(surf)

    COIN_SPIN = 2.6

    def coin_face(self, heads, px):
        key = ("coin", heads, px)
        img = self._coin_cache.get(key) if hasattr(self, "_coin_cache") else None
        if img is None:
            if not hasattr(self, "_coin_cache"):
                self._coin_cache = {}
            ss = 3
            big = pygame.Surface((px * 2 * ss, px * 2 * ss), pygame.SRCALPHA)
            c = px * ss
            rim, face, ink = ((200, 150, 20), ACCENT, (110, 78, 0)) if heads else \
                ((150, 150, 158), (214, 214, 220), (80, 80, 88))
            pygame.draw.circle(big, rim, (c, c), c)
            pygame.draw.circle(big, face, (c, c), int(c * 0.86))
            pygame.draw.circle(big, rim, (c, c), int(c * 0.72), max(2, ss * 2))
            img = pygame.transform.smoothscale(big, (px * 2, px * 2))
            label = ui.text_surf_px("H" if heads else "T", int(px * 1.0), ink)
            img.blit(label, label.get_rect(center=(px, px + px // 20)))
            self._coin_cache[key] = img
        return img

    def coin_showing(self):
        return bool(self.coin_anim) and self.coin_anim["t"] < self.COIN_SPIN + 1.8

    def coin_state(self):
        """(face showing is heads, width factor 0..1, landed) for the current spin."""
        c = self.coin_anim
        heads_wins = c["result"] == c["pair"][0]
        k = ui.ease_out(min(1.0, c["t"] / self.COIN_SPIN))
        turns = 16 if heads_wins else 17  # half-turns; even count lands on heads
        angle = turns * math.pi * k
        return int(angle / math.pi) % 2 == 0, abs(math.cos(angle)), k >= 1.0

    def draw_coin(self, surf):
        # The coin takes over the bottom panel, so both finalist cards stay visible above it.
        c = self.coin_anim
        heads, fx, landed = self.coin_state()
        px, py, pw, ph = PANEL_BOTTOM
        fade_out = max(0.0, min(1.0, (self.COIN_SPIN + 1.8 - c["t"]) / 0.4))  # gone soon after landing
        if fade_out <= 0:
            return
        a = min(1.0, c["t"] / 0.25) * fade_out
        ui.draw_panel(surf, PANEL_BOTTOM, alpha=235, shadow=True)
        cx, cy = px + pw / 2 - 150, py + ph / 2
        bounce = -abs(math.sin(min(1.0, c["t"] / self.COIN_SPIN) * math.pi)) * 26
        face = self.coin_face(heads, V.s(58))
        w = max(2, int(face.get_width() * max(0.06, fx)))
        img = pygame.transform.smoothscale(face, (w, face.get_height()))
        if a < 1:
            img.set_alpha(int(255 * a))
        surf.blit(img, img.get_rect(center=V.pt(cx, cy + bounce)))
        tx = cx + 100
        if landed:
            word = "HEADS!" if heads else "TAILS!"
            ui.draw_text(surf, word, 44, ACCENT if heads else WHITE, (tx, cy - 12), "midleft", alpha=255 * a)
            ui.draw_text(surf, "That card wins the round.", 16, GRAY, (tx, cy + 28), "midleft", bold=False,
                         alpha=255 * a)
        else:
            ui.draw_text(surf, "Coin flip...", 34, WHITE, (tx, cy - 12), "midleft", alpha=255 * a)
            ui.draw_text(surf, "Heads or tails - the cards above are labelled.", 15, GRAY, (tx, cy + 26),
                         "midleft", bold=False, alpha=255 * a)

    def draw_topbar(self, surf):
        self.menu_btn.draw(surf)
        ui.draw_text(surf, f"Round {self.v['round']}", 18, WHITE, (138, 37), "midleft")
        if self.status:
            ui.draw_text(surf, self.status, 20, WHITE, (657, 46))
        if self.pick > 1 and self.v["phase"] == "play" and self.can_play():
            ui.draw_text(surf, f"PICK {self.pick}", 14, ACCENT, (657, 72))

    def draw_scores(self, surf):
        v = self.v
        n = len(v["players"])
        ui.draw_panel(surf, (SIDEBAR_X, 18, 216, 58 + n * 44))
        ui.draw_text(surf, "Scores", 17, WHITE, (SIDEBAR_X + 18, 44), "midleft")
        ui.draw_text(surf, f"first to {v['goal']}", 13, GRAY, (SIDEBAR_X + 198, 45), "midright", bold=False)
        ph = v["phase"]
        for i, p in enumerate(v["players"]):
            y = 74 + i * 44
            bump = self.bump.get(p["id"], 0.0)
            active = (p["id"] == self.seat and ph == "play" and not p["played"] and p["id"] != v["czar"]) or \
                (self.session.net and p["id"] == self.session.me)
            if active or bump > 0.02:
                r = V.rect((SIDEBAR_X + 8, y, 200, 40))
                k = round(max(bump, 0.45 if active else 0) * 8) / 8
                surf.blit(ui.rounded_px(r.w, r.h, V.s(10), ui.lerp_color(PANEL, (90, 72, 20), k)), r)
            x = SIDEBAR_X + 20
            if p["id"] == v["czar"]:
                ui.draw_crown(surf, (x + 6, y + 20), 16)
            elif ph in ("intro", "play") and p["played"]:
                ui.draw_check(surf, (x + 6, y + 20), 16, 1.0, GREEN)
            elif ph == "play" and p["in_round"]:
                pygame.draw.circle(surf, DIM, V.pt(x + 6, y + 20), V.s(3))
            col = GRAY if p["away"] else WHITE
            ui.draw_text(surf, ui.ellipsize(p["name"], 15, 120), 15, col, (x + 22, y + 15), "midleft")
            tag = "away - bot plays" if p["away"] else ("bot" if p["bot"] else
                                                        ("you" if self.session.net and p["id"] == self.session.me
                                                         else ("host" if p["host"] else "human")))
            ui.draw_text(surf, tag, 11, DIM, (x + 22, y + 31), "midleft", bold=False)
            ui.draw_text(surf, str(p["score"]), 22 + 8 * bump, ui.lerp_color(WHITE, ACCENT, bump),
                         (SIDEBAR_X + 196, y + 20), "midright")

    def draw_sentence(self, surf, rect, answers, title):
        x, y, w, h = rect
        ui.draw_panel(surf, rect, alpha=225)
        top = y + 16
        if title:
            ui.draw_text(surf, title.upper(), 15, ACCENT, (x + w / 2, y + 22))
            top = y + 38
        segs = fill(self.v["black"]["t"], answers, WHITE, ACCENT)
        ui.draw_rich(surf, segs, (x + 26, top, w - 52, y + h - top - 14), 30, 13)

    def draw_banner(self, surf):
        title, sub, t = self.banner
        a = min(1.0, t / 0.25) * min(1.0, max(0.0, (2.6 - t) / 0.4))
        k = ui.ease_out(t / 0.45)
        r = V.rect((0, 290, ui.DW, 140))
        band = pygame.Rect(0, r.y, surf.get_width(), r.h)
        clip = surf.get_clip()
        surf.set_clip(band)
        ui.dim_screen(surf, 190 * a)
        surf.set_clip(clip)
        ui.draw_text(surf, title, 54, WHITE, (640 - 40 * (1 - k), 342), alpha=255 * a)
        ui.draw_text(surf, sub, 22, ACCENT, (640 + 40 * (1 - k), 396), bold=False, alpha=255 * a)

    def draw_cover(self, surf):
        k = ui.ease_out(self.cover)
        ui.dim_screen(surf, 250 * k, (8, 8, 10))
        if self.cover_for is None:
            return
        dy = -30 * (1 - k)
        a = 255 * k
        name = self.name(self.cover_for, False)
        if self.v and self.cover_for == self.v["czar"]:
            ui.draw_crown(surf, (640, 180 + dy), 34)
            ui.draw_text(surf, "Card Czar time", 20, ACCENT, (640, 220 + dy), alpha=a)
            sub = "Everyone has played. Pass the computer to the Czar to judge."
        else:
            ui.draw_text(surf, "Pass the computer to", 20, GRAY, (640, 220 + dy), bold=False, alpha=a)
            sub = "Everyone else, no peeking."
        ui.draw_text(surf, name, 64, WHITE, (640, 290 + dy), alpha=a)
        ui.draw_text(surf, sub, 17, GRAY, (640, 360 + dy), bold=False, alpha=a)
        if self.covered():
            self.action.draw(surf)

    def draw_pause(self, surf):
        k = ui.ease_out(self.pause_a)
        ui.dim_screen(surf, 170 * k)
        ui.draw_panel(surf, (440, 200 + 20 * (1 - k), 400, self.pause_h + 20), fade=k)
        ui.draw_text(surf, "Paused" if not self.session.net else "Menu", 34, WHITE, (640, 252 + 20 * (1 - k)),
                     alpha=255 * k)
        for b in (self.p_resume, self.p_packs, self.p_voice, self.p_restart, self.p_leave):
            b.draw(surf)
        if self.session.net:
            ui.draw_text(surf, "The game keeps going while this is open.", 13, GRAY, (640, 200 + self.pause_h),
                         bold=False, alpha=255 * k)

    def draw_gameover(self, surf):
        k = ui.ease_out(self.over_a)
        ui.dim_screen(surf, 200 * k)
        self.draw_particles(surf)
        standings = sorted(self.v["players"], key=lambda p: -p["score"])
        n = len(standings)
        row_h = 36 if n <= 8 else 32
        panel_h = 236 + n * row_h + 80
        y0 = (ui.DH - panel_h) / 2 + 30 * (1 - k)
        ui.draw_panel(surf, (370, y0, 540, panel_h), alpha=255, fade=k)
        top = standings[0]
        tied = [p for p in standings if p["score"] == top["score"]]
        ui.draw_crown(surf, (640, y0 + 52), 46)
        if len(tied) > 1:
            title = "It's a tie!"
        elif self.session.net and top["id"] == self.session.me:
            title = "You win!"
        else:
            title = f"{top['name']} wins!"
        ui.draw_text(surf, title, 40, WHITE, (640, y0 + 108), alpha=255 * k)
        ui.draw_text(surf, f"after {self.v['round']} rounds", 15, GRAY, (640, y0 + 144), bold=False, alpha=255 * k)
        rank, prev = 0, None
        for i, p in enumerate(standings):
            if p["score"] != prev:
                rank, prev = i + 1, p["score"]
            y = y0 + 190 + i * row_h
            col = ACCENT if p["score"] == top["score"] else WHITE
            ui.draw_text(surf, f"{rank}.", 17, GRAY, (430, y), "midleft", alpha=255 * k)
            ui.draw_text(surf, ui.ellipsize(p["name"], 18, 300), 18, col, (468, y), "midleft", alpha=255 * k)
            ui.draw_text(surf, f"{p['score']} pt{'s' if p['score'] != 1 else ''}", 17, col, (850, y), "midright",
                         alpha=255 * k)
        by = y0 + panel_h - 84
        if self.o_again.visible:
            self.o_again.rect.topleft = (440, by)
            self.o_menu.rect.topleft = (650, by)
        else:
            self.o_menu.rect.topleft = (545, by)
            ui.draw_text(surf, "The host can start another round from the lobby.", 13, GRAY, (640, by - 18),
                         bold=False, alpha=255 * k)
        self.o_again.draw(surf)
        self.o_menu.draw(surf)

    def draw_error(self, surf):
        if self.err_a < 0.01:
            return
        k = ui.ease_out(self.err_a)
        ui.dim_screen(surf, 210 * k)
        ui.draw_panel(surf, (390, 250, 500, 230), fade=k)
        ui.draw_text(surf, "Disconnected", 30, WHITE, (640, 300), alpha=255 * k)
        ui.draw_text(surf, self.session.error or "", 16, GRAY, (640, 348), bold=False, alpha=255 * k)
        self.err_btn.draw(surf)
