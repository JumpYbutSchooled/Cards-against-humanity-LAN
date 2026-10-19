"""Window, main loop, scene switching, animated background and saved settings."""
import json
import math
import os
import random
import sys

import pygame

from . import ui
from .cards import Library
from .sound import Sounds
from .ui import V

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(ROOT, "settings.json")

DEFAULT_SETTINGS = {
    "packs": None,
    "players": [{"name": "Player 1", "bot": False}, {"name": "Rando Cardrissian", "bot": True},
                {"name": "Bot Barbara", "bot": True}, {"name": "Bot Gary", "bot": True}],
    "points": 7,
    "hand": 10,
    "volume": 0.6,
}


class Scene:
    def __init__(self, app):
        self.app = app

    def handle(self, ev):
        pass

    def update(self, dt):
        pass

    def draw(self, surf):
        pass

    def buttons(self, *buttons):
        for b in buttons:
            b.sounds = self.app.sounds
        return list(buttons)


class Background:
    def __init__(self):
        self.size = None
        self.base = None
        rnd = random.Random(3)
        self.floaters = [{"x": rnd.uniform(0, ui.DW), "y": rnd.uniform(0, ui.DH), "a": rnd.uniform(-25, 25),
                          "v": rnd.uniform(6, 16), "s": rnd.uniform(0.6, 1.3), "white": rnd.random() < 0.6}
                         for _ in range(14)]
        self.cache = {}

    def _build(self, w, h):
        self.size = (w, h)
        grad = pygame.Surface((1, 64))
        for i in range(64):
            t = i / 63
            grad.set_at((0, i), ui.lerp_color((26, 26, 31), (9, 9, 11), t))
        self.base = pygame.transform.smoothscale(grad, (w, h))
        # Vignette: a soft radial darkening at the edges.
        vs = pygame.Surface((64, 36), pygame.SRCALPHA)
        for y in range(36):
            for x in range(64):
                dx, dy = (x - 31.5) / 32, (y - 17.5) / 18
                d = min(1.0, math.sqrt(dx * dx + dy * dy))
                vs.set_at((x, y), (0, 0, 0, int(150 * d ** 2.2)))
        self.base.blit(pygame.transform.smoothscale(vs, (w, h)), (0, 0))
        self.cache = {}

    def _floater(self, f):
        key = (round(f["s"], 2), round(f["a"]), f["white"], V.scale)
        img = self.cache.get(key)
        if img is None:
            w, h = V.s(110 * f["s"]), V.s(154 * f["s"])
            col = (255, 255, 255) if f["white"] else (0, 0, 0)
            card = ui.rounded_px(w, h, max(2, int(w * 0.08)), col, 9 if f["white"] else 60).copy()
            img = pygame.transform.rotozoom(card, f["a"], 1)
            self.cache[key] = img
        return img

    def update(self, dt):
        for f in self.floaters:
            f["y"] -= f["v"] * dt
            if f["y"] < -120:
                f["y"] = ui.DH + 120
                f["x"] = random.uniform(0, ui.DW)

    def draw(self, surf):
        w, h = surf.get_size()
        if self.size != (w, h):
            self._build(w, h)
        surf.blit(self.base, (0, 0))
        for f in self.floaters:
            img = self._floater(f)
            surf.blit(img, img.get_rect(center=V.pt(f["x"], f["y"])))


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def enable_dpi_awareness():
    """Without this, Windows display scaling (125%-200%) renders the game at low res and stretches it (blurry)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class App:
    def __init__(self):
        enable_dpi_awareness()
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption("Cards Against Humanity")
        info = pygame.display.Info()
        if info.current_w > 0 and info.current_h > 0:
            w = int(min(info.current_w * 0.8, info.current_h * 0.8 * 16 / 9))
        else:
            w = 1280
        h = int(w * 9 / 16)
        self.windowed_size = (w, h)
        self.screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self.fullscreen = False
        V.resize(*self.screen.get_size())
        pygame.key.set_repeat(400, 35)

        self.settings = load_settings()
        self.library = Library(os.path.join(ROOT, "assets", "cards"))
        if not self.settings.get("packs"):
            self.settings["packs"] = self.library.default_selection()
        self.settings["packs"] = self.library.migrate_ids(self.settings["packs"]) or \
            self.library.default_selection()
        self.sounds = Sounds(self.settings.get("volume", 0.6))
        self.restart_requested = False
        try:
            import updater
            self.updater = updater.Updater() if os.environ.get("CAH_NO_UPDATE") != "1" else None
            self.version = updater.read_version()
        except ImportError:
            self.updater, self.version = None, 0
        self.bg = Background()
        self.clock = pygame.time.Clock()
        self.running = True
        self.fade_img = None
        self.fade = 0.0
        self.scene = None

        from .scene_menu import MenuScene
        self.scene = MenuScene(self)

    def save(self):
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=1)
        except OSError:
            pass

    def switch(self, scene):
        self.fade_img = self.screen.copy()
        self.fade = 1.0
        self.scene = scene
        self.sounds.play("whoosh")

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.windowed_size = self.screen.get_size()
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        V.resize(*self.screen.get_size())

    def quit(self):
        self.running = False

    def restart(self):
        """Closes the game and starts it again (used to install updates)."""
        self.restart_requested = True
        self.running = False

    def run(self, max_frames=None, on_frame=None):
        frames = 0
        while self.running:
            dt = min(self.clock.tick(120) / 1000.0, 1 / 20)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type == pygame.VIDEORESIZE and not self.fullscreen:
                    self.screen = pygame.display.get_surface()
                    V.resize(*self.screen.get_size())
                elif ev.type == pygame.KEYDOWN and (ev.key == pygame.K_F11 or
                                                    (ev.key == pygame.K_RETURN and ev.mod & pygame.KMOD_ALT)):
                    self.toggle_fullscreen()
                else:
                    self.scene.handle(ev)
            if self.screen.get_size() != (V.w, V.h):
                V.resize(*self.screen.get_size())
            self.bg.update(dt)
            self.scene.update(dt)
            self.bg.draw(self.screen)
            self.scene.draw(self.screen)
            if self.fade > 0 and self.fade_img is not None:
                self.fade = max(0.0, self.fade - dt * 4)
                if self.fade_img.get_size() == self.screen.get_size():
                    self.fade_img.set_alpha(int(255 * self.fade * self.fade))
                    self.screen.blit(self.fade_img, (0, 0))
            pygame.display.flip()
            frames += 1
            if on_frame:
                on_frame(self, frames)
            if max_frames and frames >= max_frames:
                break
        self.save()
        if getattr(self, "session", None):
            self.session.leave()
        pygame.quit()
        if self.restart_requested:
            import subprocess
            subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py")], cwd=ROOT)
