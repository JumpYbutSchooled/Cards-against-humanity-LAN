"""Small synthesized sound effects, so the game needs no audio files."""
import array
import math
import random

import pygame


class Sounds:
    def __init__(self, volume=0.6):
        self.sounds = {}
        self.volume = volume
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(44100, -16, 2, 512)
            self.rate, _, self.channels = pygame.mixer.get_init()
        except pygame.error:
            return
        rnd = random.Random(7)
        self._add("click", self._tone([(1250, 0.035)], decay=60, vol=0.25))
        self._add("select", self._tone([(880, 0.05)], decay=45, vol=0.22))
        self._add("deselect", self._tone([(620, 0.05)], decay=45, vol=0.2))
        self._add("card", self._noise(0.13, rnd, lo=0.15, vol=0.32))
        self._add("flip", self._noise(0.07, rnd, lo=0.35, vol=0.3))
        self._add("deal", self._noise(0.09, rnd, lo=0.25, vol=0.22))
        self._add("point", self._tone([(660, 0.08), (990, 0.16)], decay=14, vol=0.3))
        self._add("win", self._tone([(523, 0.11), (659, 0.11), (784, 0.11), (1047, 0.4)], decay=6, vol=0.3))
        self._add("whoosh", self._noise(0.3, rnd, lo=0.08, vol=0.2, swell=True))

    def _add(self, name, samples):
        if self.channels == 2:
            st = array.array("h", [0]) * (len(samples) * 2)
            st[0::2] = samples
            st[1::2] = samples
            samples = st
        try:
            self.sounds[name] = pygame.mixer.Sound(buffer=samples.tobytes())
        except pygame.error:
            pass

    def _tone(self, notes, decay=30, vol=0.3):
        out = array.array("h")
        for freq, dur in notes:
            n = int(self.rate * dur)
            for i in range(n):
                t = i / self.rate
                env = math.exp(-decay * t) * min(1.0, i / (self.rate * 0.003))
                v = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
                out.append(int(max(-1, min(1, v * env * vol)) * 32767))
        return out

    def _noise(self, dur, rnd, lo=0.2, vol=0.3, swell=False):
        n = int(self.rate * dur)
        out = array.array("h")
        prev = 0.0
        for i in range(n):
            t = i / n
            env = math.sin(math.pi * t) ** (1.5 if swell else 0.6) * (1 - t) ** (0.3 if swell else 1.2)
            prev += lo * (rnd.uniform(-1, 1) - prev)  # one-pole low-pass
            out.append(int(max(-1, min(1, prev * 3 * env * vol)) * 32767))
        return out

    def play(self, name):
        s = self.sounds.get(name)
        if s and self.volume > 0:
            s.set_volume(self.volume)
            s.play()
