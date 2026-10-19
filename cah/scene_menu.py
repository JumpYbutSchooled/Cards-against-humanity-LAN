import math
import random

import pygame

from . import ui
from .app import Scene
from .render import CardSprite
from .ui import Button, V, WHITE, GRAY, DIM, ACCENT


def deck_for(app):
    key = tuple(app.settings["packs"])
    if getattr(app, "_deck_key", None) != key:
        app._deck = app.library.build(app.settings["packs"])
        app._deck_key = key
    return app._deck


class MenuScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.t = 0.0
        x = 112
        self.play = Button((x, 356, 320, 60), "Play Local", self.on_play, "primary", 24,
                           sub="one computer, pass it around")
        self.lan = Button((x, 426, 320, 60), "Multiplayer", self.on_lan, "primary", 24,
                          sub="online with a room code, or LAN")
        self.packs = Button((x, 496, 320, 60), "Card Packs", self.on_packs, "secondary", 22, sub="")
        self.quit = Button((x, 566, 320, 48), "Quit", app.quit, "ghost", 19)
        self.sound = Button((40, 664, 150, 36), "", self.toggle_sound, "ghost", 14)
        self.update_btn = Button((470, 660, 330, 42), "", app.restart, "accent", 15)
        self.update_btn.visible = False
        self.retry_btn = Button((0, 667, 80, 30), "Retry", lambda: app.updater and app.updater.start(), "ghost", 13)
        self.retry_btn.visible = False
        self.all = self.buttons(self.play, self.lan, self.packs, self.quit, self.sound, self.update_btn,
                                self.retry_btn)
        black, white = deck_for(app)
        self.black_pool = [c for c in black if c.pick == 1] or black
        self.white_pool = white
        self.bc = CardSprite("black", self._rand(self.black_pool), 900, 900, 236)
        self.wc = CardSprite("white", self._rand(self.white_pool), 1040, 1000, 210)
        if self.bc.card:
            self.bc.text = self.bc.card.display
        self.bc.tangle, self.wc.tangle = 7, -6
        self.bc.move(880, 330, delay=0.15)
        self.wc.move(1035, 420, delay=0.3)
        self.bc.speed = self.wc.speed = 7
        self.cycle = 0.0
        self.swapping = False

    @staticmethod
    def _rand(pool):
        return random.choice(pool) if pool else None

    def on_play(self):
        from .scene_setup import SetupScene
        self.app.switch(SetupScene(self.app))

    def on_lan(self):
        from .scene_lan import LanScene
        self.app.switch(LanScene(self.app))

    def on_packs(self):
        from .scene_packs import PacksScene
        self.app.switch(PacksScene(self.app, back=lambda: MenuScene(self.app)))

    def draw_update_status(self, surf):
        up = self.app.updater
        v = self.app.version
        if up is None:
            text, col = f"v{v}", DIM
        elif up.state == "checking":
            text, col = f"v{v} · checking for updates...", DIM
        elif up.state == "latest":
            text, col = f"v{v} · up to date", DIM
        elif up.state == "downloading":
            text, col = f"Downloading update v{up.remote}...", ACCENT
        elif up.state == "dev":
            text, col = f"v{up.remote} is on GitHub (you have v{v}) - git pull to update", ACCENT
        elif up.state == "error":
            text, col = f"v{v} · update failed (details in update.log)", ui.RED
        elif up.state == "ready":
            return  # the restart button shows instead
        else:
            text, col = f"v{v} · couldn't check for updates", DIM
        ui.draw_text(surf, text, 13, col, (330, 682), "midleft", bold=False)
        self.retry_btn.visible = up is not None and up.state in ("offline", "error")
        if self.retry_btn.visible:
            self.retry_btn.rect.x = 330 + ui.text_width(text, 13, False) + 12

    def toggle_sound(self):
        s = self.app.sounds
        s.volume = 0.0 if s.volume > 0 else 0.6
        self.app.settings["volume"] = s.volume
        if s.volume:
            s.play("click")

    def handle(self, ev):
        for b in self.all:
            if b.handle(ev):
                return
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.play.click()
            elif ev.key == pygame.K_ESCAPE:
                self.app.quit()
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = V.to_design(ev.pos)
            if self.bc.contains(p) or self.wc.contains(p):
                self.cycle = 99

    def update(self, dt):
        self.t += dt
        n = len(self.app.settings["packs"])
        b, w = self.app.library.counts(self.app.settings["packs"])
        self.packs.sub = f"{n} pack{'s' if n != 1 else ''} · {b + w:,} cards"
        self.sound.label = "Sound: On" if self.app.sounds.volume > 0 else "Sound: Off"
        up = self.app.updater
        self.update_btn.visible = bool(up and up.state == "ready")
        if self.update_btn.visible:
            self.update_btn.label = f"Update v{up.remote} ready - restart now"
        for btn in self.all:
            btn.update(dt)
        self.cycle += dt
        if not self.swapping and self.cycle > 5.5:
            self.swapping = True
            self.bc.tflip = self.wc.tflip = 1.0
            self.app.sounds.play("flip")
        if self.swapping and self.bc.flip > 0.97 and self.wc.flip > 0.97:
            self.bc.card = self._rand(self.black_pool)
            self.wc.card = self._rand(self.white_pool)
            for s in (self.bc, self.wc):
                s.text, s.pack = (s.card.text, s.card.pack) if s.card else ("", "")
                s.tflip = 0.0
            if self.bc.card:
                self.bc.text = self.bc.card.display
            self.bc.pick = self.bc.card.pick if self.bc.card else 1
            self.swapping = False
            self.cycle = 0.0
        bob = 4 * math.sin(self.t * 1.3)
        self.bc.ty = 330 + bob
        self.wc.ty = 420 - bob
        self.bc.update(dt)
        self.wc.update(dt)

    def draw(self, surf):
        k = ui.ease_out(self.t / 0.8)
        x = 112 - 30 * (1 - k)
        a = 255 * k
        for i, word in enumerate(("Cards", "Against", "Humanity.")):
            ui.draw_text(surf, word, 66, WHITE, (x, 92 + i * 70), "topleft", alpha=a)
        ui.draw_text(surf, "A party game for horrible people.", 19, GRAY, (x + 2, 312), "topleft", bold=False,
                     alpha=a)
        for b in self.all:
            b.draw(surf)
        self.bc.draw(surf)
        self.wc.draw(surf)
        ui.draw_text(surf, "F11: fullscreen", 13, DIM, (210, 682), "midleft", bold=False)
        self.draw_update_status(surf)
        ui.draw_text(surf, "Cards via JSON Against Humanity · CC BY-NC-SA", 13, DIM, (1240, 682), "midright",
                     bold=False)
        ui.draw_text(surf, "Click the cards for a new combo", 13, ACCENT if self.t < 6 else DIM, (958, 610),
                     alpha=255 * min(1, max(0, self.t - 1)))
