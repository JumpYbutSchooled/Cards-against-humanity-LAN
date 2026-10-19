import random

import pygame

from . import ui
from .app import Scene
from .ui import Button, Segmented, Stepper, TextInput, V, WHITE, GRAY, DIM, ACCENT, RED

MAX_PLAYERS = 10
MIN_PLAYERS = 3
BOT_NAMES = ["Rando Cardrissian", "Bot Barbara", "Bot Gary", "Sir Beeps-a-Lot", "Unit 69", "Clippy's Cousin",
             "HAL 9001", "Dr. Roboto", "Botty McBotface", "The Algorithm", "Toaster", "Siri's Ex"]
ROW_Y, ROW_H = 166, 46


class SetupScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        st = app.settings
        self.players = [dict(p) for p in st.get("players", [])][:MAX_PLAYERS]
        self.points = Stepper((800, 158, 410, 50), "Points to win", st.get("points", 7), 1, 25,
                              on_change=lambda v: st.__setitem__("points", v), sounds=app.sounds)
        self.hand = Stepper((800, 214, 410, 50), "Cards in hand", st.get("hand", 10), 5, 15,
                            on_change=lambda v: st.__setitem__("hand", v), sounds=app.sounds)
        self.add_human = Button((440, 112, 130, 38), "+ Player", lambda: self.add(False), "secondary", 15)
        self.add_bot = Button((580, 112, 130, 38), "+ Bot", lambda: self.add(True), "secondary", 15)
        self.packs_btn = Button((800, 432, 410, 46), "Customize packs...", self.on_packs, "secondary", 16)
        from .scene_packs import PresetChips
        self.chips = PresetChips(app, 800, 318, 410, self.on_preset)
        self.voice = Segmented((1046, 114, 174, 34), ["Off", "On"], 1 if st.get("tts_local") else 0,
                               self.on_voice, 13, app.sounds)
        self.back = Button((40, 654, 160, 50), "Back", self.on_back, "ghost", 18)
        self.start = Button((1010, 654, 230, 50), "Start Game", self.on_start, "accent", 20)
        self.fixed = self.buttons(self.add_human, self.add_bot, self.packs_btn, self.back, self.start)
        self.rows = []
        self.anim = {}
        self.rebuild()

    def rebuild(self):
        self.rows = []
        for i, p in enumerate(self.players):
            y = ROW_Y + i * ROW_H
            inp = TextInput((92, y, 330, 38), p["name"], "Name", 18, 16,
                            on_change=lambda t, p=p: p.__setitem__("name", t))
            seg = Segmented((436, y, 170, 38), ["Human", "Bot"], 1 if p["bot"] else 0,
                            on_change=lambda i, p=p: self.set_bot(p, i == 1), sounds=self.app.sounds)
            rm = Button((620, y, 90, 38), "Remove", lambda p=p: self.remove(p), "danger", 14)
            rm.sounds = self.app.sounds
            rm.enabled = len(self.players) > MIN_PLAYERS
            self.rows.append((p, inp, seg, rm))

    def set_bot(self, p, bot):
        p["bot"] = bot
        taken = {q["name"] for q in self.players}
        if bot and (not p["name"].strip() or p["name"].startswith("Player ")):
            p["name"] = next((n for n in BOT_NAMES if n not in taken), "Bot")
        elif not bot and p["name"] in BOT_NAMES:
            p["name"] = self._next_human_name()
        self.rebuild()

    def _next_human_name(self):
        taken = {q["name"] for q in self.players}
        i = 1
        while f"Player {i}" in taken:
            i += 1
        return f"Player {i}"

    def add(self, bot):
        if len(self.players) >= MAX_PLAYERS:
            return
        taken = {q["name"] for q in self.players}
        if bot:
            pool = [n for n in BOT_NAMES if n not in taken] or ["Bot %d" % random.randint(10, 99)]
            name = pool[0]
        else:
            name = self._next_human_name()
        p = {"name": name, "bot": bot}
        self.players.append(p)
        self.anim[id(p)] = 0.0
        self.rebuild()

    def remove(self, p):
        if len(self.players) > MIN_PLAYERS:
            self.players.remove(p)
            self.rebuild()

    def save(self):
        for i, p in enumerate(self.players):
            if not p["name"].strip():
                p["name"] = f"Bot {i + 1}" if p["bot"] else f"Player {i + 1}"
        self.app.settings["players"] = self.players
        self.app.save()

    def problems(self):
        b, w = self.app.library.counts(self.app.settings["packs"])
        n = len(self.players)
        if n < MIN_PLAYERS:
            return f"You need at least {MIN_PLAYERS} players."
        if b == 0:
            return "Your packs have no black cards. Add a pack with black cards."
        need = n * (self.hand.value + 3)
        if w < need:
            return f"Not enough white cards ({w}) for {n} players - add more packs."
        names = [p["name"].strip().lower() for p in self.players if p["name"].strip()]
        if len(set(names)) != len(names):
            return "Each player needs a different name."
        return None

    def on_voice(self, i):
        self.app.settings["tts_local"] = i == 1
        self.app.save()
        if i == 1:
            from .tts import speaker
            speaker().say("Robot voice on.")

    def on_preset(self, packs, name):
        self.app.settings["packs"] = packs
        self.app.save()

    def on_packs(self):
        self.save()
        from .scene_packs import PacksScene
        self.app.switch(PacksScene(self.app, back=lambda: SetupScene(self.app)))

    def on_back(self):
        self.save()
        from .scene_menu import MenuScene
        self.app.switch(MenuScene(self.app))

    def on_start(self):
        if self.problems():
            return
        self.save()
        from .scene_game import start_local_game
        self.app.switch(start_local_game(self.app))

    def handle(self, ev):
        for p, inp, seg, rm in self.rows:
            if inp.handle(ev) and ev.type != pygame.MOUSEBUTTONDOWN:
                return
        for p, inp, seg, rm in list(self.rows):
            if seg.handle(ev) or rm.handle(ev):
                return
        for w in self.fixed + [self.points, self.hand, self.chips, self.voice]:
            if w.handle(ev):
                return
        if ev.type == pygame.KEYDOWN and not any(r[1].focused for r in self.rows):
            if ev.key == pygame.K_ESCAPE:
                self.on_back()
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.on_start()

    def update(self, dt):
        full = len(self.players) >= MAX_PLAYERS
        self.add_human.enabled = self.add_bot.enabled = not full
        self.start.enabled = self.problems() is None
        for w in self.fixed + [self.points, self.hand, self.voice]:
            w.update(dt)
        from .presets import match_name
        self.preset = match_name(self.app.library, self.app.settings["packs"], self.app.settings)
        self.chips.update(dt, self.preset)
        for p, inp, seg, rm in self.rows:
            inp.update(dt)
            seg.update(dt)
            rm.update(dt)
            self.anim[id(p)] = ui.approach(self.anim.get(id(p), 1.0), 1.0, 12, dt)

    def draw(self, surf):
        ui.draw_text(surf, "Local Game", 40, WHITE, (40, 22), "topleft")
        ui.draw_text(surf, "Add people sitting at this computer and as many bots as you like.", 15, GRAY,
                     (42, 70), "topleft", bold=False)

        ui.draw_panel(surf, (24, 100, 712, 540))
        humans = sum(1 for p in self.players if not p["bot"])
        ui.draw_text(surf, "Players", 22, WHITE, (48, 131), "midleft")
        ui.draw_text(surf, f"{len(self.players)} / {MAX_PLAYERS}  ·  {humans} human", 14, GRAY, (150, 132),
                     "midleft", bold=False)
        self.add_human.draw(surf)
        self.add_bot.draw(surf)
        for i, (p, inp, seg, rm) in enumerate(self.rows):
            a = ui.ease_out(self.anim.get(id(p), 1.0))
            y = ROW_Y + i * ROW_H
            pygame.draw.circle(surf, (50, 50, 58), V.pt(64, y + 19), V.s(15))
            ui.draw_text(surf, str(i + 1), 15, WHITE, (64, y + 19.5))
            inp.rect.x = 92 - 20 * (1 - a)
            inp.draw(surf)
            seg.draw(surf)
            rm.draw(surf)

        ui.draw_panel(surf, (770, 100, 470, 540))
        ui.draw_text(surf, "Rules", 22, WHITE, (800, 131), "midleft")
        ui.draw_text(surf, "Robot voice", 14, GRAY, (1036, 131), "midright", bold=False)
        self.voice.draw(surf)
        self.points.draw(surf)
        self.hand.draw(surf)
        ui.draw_text(surf, "Card packs", 22, WHITE, (800, 296), "midleft")
        lib = self.app.library
        b, w = lib.counts(self.app.settings["packs"])
        n = len(self.app.settings["packs"])
        self.chips.draw(surf)
        label = getattr(self, "preset", None) or "Custom mix"
        ui.draw_text(surf, f"{label}:  {n} pack{'s' if n != 1 else ''}  ·  {b:,} black  ·  {w:,} white", 14, GRAY,
                     (800, 412), "midleft", bold=False)
        self.packs_btn.draw(surf)
        tips = ["Pass-and-play: humans take turns at this screen, and a",
                "cover screen hides each hand until you're ready.",
                "Bots play and judge on their own."]
        for i, t in enumerate(tips):
            ui.draw_text(surf, t, 13, DIM, (800, 516 + i * 21), "midleft", bold=False)

        self.back.draw(surf)
        self.start.draw(surf)
        prob = self.problems()
        if prob:
            ui.draw_text(surf, prob, 15, RED, (990, 679), "midright", bold=False)
