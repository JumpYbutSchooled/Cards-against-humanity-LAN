"""Card browser: flip through every card in any packs and build combos by hand."""
import random

import pygame

from . import ui
from .app import Scene
from .cards import BlackCard, WhiteCard, fill, _norm
from .render import card_face, CARD_RATIO
from .ui import Button, Segmented, TextInput, V, WHITE, GRAY, DIM, INK, ACCENT

GRID = pygame.Rect(40, 150, 820, 490)
COLS = 5
CW = 148
CH = CW * CARD_RATIO
GAP_X = (GRID.w - COLS * CW) / (COLS - 1)
STEP_Y = CH + 18
COMBO = pygame.Rect(880, 96, 360, 544)


class CardBrowserScene(Scene):
    def __init__(self, app, back, pack_ids=None, title=None):
        super().__init__(app)
        self.back = back
        lib = app.library
        self.scope_ids = list(pack_ids or app.settings["packs"])
        self.title = title or f"{len(self.scope_ids)} selected pack{'s' if len(self.scope_ids) != 1 else ''}"
        self._cache = {}
        self.kind = Segmented((40, 96, 300, 42), ["Black cards", "White cards"], 0, lambda i: self.refilter(),
                              15, app.sounds)
        self.scope = Segmented((352, 96, 250, 42), ["These packs", "All packs"], 0, lambda i: self.refilter(), 15,
                               app.sounds)
        self.search = TextInput((614, 96, 246, 42), "", "Search cards...", 40, 16,
                                on_change=lambda t: self.refilter())
        self.back_btn = Button((1040, 654, 200, 50), "Back", self.go_back, "primary", 20)
        self.rand_btn = Button((COMBO.x + 20, COMBO.bottom - 58, 160, 42), "Random combo", self.random_combo,
                               "accent", 15)
        self.clear_btn = Button((COMBO.x + 190, COMBO.bottom - 58, 150, 42), "Clear", self.clear_combo,
                                "secondary", 15)
        self.btns = self.buttons(self.back_btn, self.rand_btn, self.clear_btn)
        self.black = None
        self.whites = []
        self.cards = []
        self.scroll = self.scroll_t = 0.0
        self.hover_i = None
        self.dragging = None
        self.lib = lib
        self.refilter()

    # ---------------------------------------------------------- data
    def pool(self):
        ids = self.scope_ids if self.scope.index == 0 else [p["id"] for p in self.lib.packs]
        key = tuple(ids)
        if key not in self._cache:
            black, white, sb, sw = [], [], set(), set()
            for pid in ids:
                d = self.lib.load(pid)
                for c in d["black"]:
                    k = _norm(c["text"])
                    if k not in sb:
                        sb.add(k)
                        black.append(BlackCard(c["text"], c.get("pick", 1), d["name"]))
                for t in d["white"]:
                    k = _norm(t)
                    if k not in sw:
                        sw.add(k)
                        white.append(WhiteCard(t, d["name"]))
            self._cache[key] = (black, white)
        return self._cache[key]

    def refilter(self):
        black, white = self.pool()
        cards = black if self.kind.index == 0 else white
        q = self.search.text.strip().lower()
        if q:
            cards = [c for c in cards if q in c.text.lower() or q in c.pack.lower()]
        self.cards = cards
        self.scroll = self.scroll_t = 0.0

    # ---------------------------------------------------------- combo
    def click_card(self, c):
        if isinstance(c, BlackCard):
            self.black = c
            self.whites = self.whites[:c.pick]
            self.app.sounds.play("flip")
            if self.kind.index == 0:  # next: pick answers
                self.kind.index = 1
                self.refilter()
        else:
            if c in self.whites:
                self.whites.remove(c)
                self.app.sounds.play("deselect")
                return
            pick = self.black.pick if self.black else 1
            if len(self.whites) >= pick:
                self.whites[-1] = c
            else:
                self.whites.append(c)
            self.app.sounds.play("select")

    def random_combo(self):
        black, white = self.pool()
        if not black or not white:
            black, white = self.lib.build([p["id"] for p in self.lib.packs])
        self.black = random.choice(black)
        self.whites = random.sample(white, min(self.black.pick, len(white)))
        self.app.sounds.play("card")

    def clear_combo(self):
        self.black = None
        self.whites = []

    def go_back(self):
        self.app.switch(self.back())

    # ---------------------------------------------------------- grid geometry
    def rows(self):
        return (len(self.cards) + COLS - 1) // COLS

    def max_scroll(self):
        return max(0.0, self.rows() * STEP_Y - GRID.h + 8)

    def card_pos(self, i):
        r, c = divmod(i, COLS)
        return GRID.x + c * (CW + GAP_X), GRID.y + 4 + r * STEP_Y - self.scroll

    def index_at(self, p):
        if not GRID.collidepoint(p):
            return None
        y = p[1] - GRID.y - 4 + self.scroll
        r = int(y // STEP_Y)
        if y - r * STEP_Y > CH:
            return None
        c = int((p[0] - GRID.x) // (CW + GAP_X))
        if c >= COLS or (p[0] - GRID.x) - c * (CW + GAP_X) > CW:
            return None
        i = r * COLS + c
        return i if 0 <= i < len(self.cards) else None

    def scrollbar(self):
        if self.max_scroll() <= 0:
            return None
        track = pygame.Rect(GRID.right + 6, GRID.y, 6, GRID.h)
        th = max(36, track.h * GRID.h / (self.rows() * STEP_Y))
        ty = track.y + (track.h - th) * (self.scroll / self.max_scroll())
        return track, pygame.Rect(track.x, ty, track.w, th)

    # ---------------------------------------------------------- events
    def handle(self, ev):
        if self.search.handle(ev) and ev.type != pygame.MOUSEBUTTONDOWN:
            return
        if self.kind.handle(ev) or self.scope.handle(ev):
            return
        for b in self.btns:
            if b.handle(ev):
                return
        if ev.type == pygame.MOUSEWHEEL:
            self.scroll_t = max(0.0, min(self.max_scroll(), self.scroll_t - ev.y * 120))
        elif ev.type == pygame.KEYDOWN and not self.search.focused:
            if ev.key == pygame.K_ESCAPE:
                self.go_back()
            elif ev.key in (pygame.K_PAGEDOWN, pygame.K_PAGEUP):
                d = GRID.h * 0.9 * (1 if ev.key == pygame.K_PAGEDOWN else -1)
                self.scroll_t = max(0.0, min(self.max_scroll(), self.scroll_t + d))
            elif ev.key == pygame.K_r:
                self.random_combo()
            elif ev.key == pygame.K_f and ev.mod & pygame.KMOD_CTRL:
                self.search.focused = True
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = V.to_design(ev.pos)
            bar = self.scrollbar()
            if bar and bar[0].inflate(14, 0).collidepoint(p):
                track, thumb = bar
                if not thumb.collidepoint(p):
                    frac = (p[1] - track.y - thumb.h / 2) / max(1, track.h - thumb.h)
                    self.scroll_t = self.scroll = max(0.0, min(1.0, frac)) * self.max_scroll()
                self.dragging = (p[1], self.scroll_t)
                return
            i = self.index_at(p)
            if i is not None:
                self.click_card(self.cards[i])
                return
            # Clicking a chosen answer in the combo panel removes it.
            for j, rect in enumerate(self.white_rows()):
                if rect.collidepoint(p) and j < len(self.whites):
                    self.whites.pop(j)
                    self.app.sounds.play("deselect")
                    return
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self.dragging = None
        elif ev.type == pygame.MOUSEMOTION and self.dragging:
            y0, s0 = self.dragging
            track, thumb = self.scrollbar()
            d = (V.to_design(ev.pos)[1] - y0) / max(1, track.h - thumb.h) * self.max_scroll()
            self.scroll_t = self.scroll = max(0.0, min(self.max_scroll(), s0 + d))

    def update(self, dt):
        self.search.update(dt)
        self.kind.update(dt)
        self.scope.update(dt)
        for b in self.btns:
            b.update(dt)
        self.scroll_t = max(0.0, min(self.max_scroll(), self.scroll_t))
        self.scroll = ui.approach(self.scroll, self.scroll_t, 16, dt)
        self.hover_i = None if self.dragging else self.index_at(ui.mouse_pos())

    # ---------------------------------------------------------- draw
    def white_rows(self):
        n = max(len(self.whites), self.black.pick if self.black else 1)
        return [pygame.Rect(COMBO.x + 20, COMBO.y + 336 + j * 40, COMBO.w - 40, 34) for j in range(min(n, 4))]

    def draw(self, surf):
        ui.draw_text(surf, "Card Browser", 40, WHITE, (40, 22), "topleft")
        scope = self.title if self.scope.index == 0 else "every pack"
        ui.draw_text(surf, f"Showing {scope}", 15, GRAY, (42, 70), "topleft", bold=False)
        self.kind.draw(surf)
        self.scope.draw(surf)
        self.search.draw(surf)

        clip = surf.get_clip()
        surf.set_clip(V.rect((GRID.x - 10, GRID.y, GRID.w + 20, GRID.h)))
        first = max(0, int((self.scroll - 4) // STEP_Y) * COLS)
        last = min(len(self.cards), first + (int(GRID.h // STEP_Y) + 2) * COLS)
        pw, ph = V.s(CW), V.s(CH)
        for i in range(first, last):
            c = self.cards[i]
            x, y = self.card_pos(i)
            hov = i == self.hover_i
            if hov:
                y -= 4
            is_black = isinstance(c, BlackCard)
            face = card_face("black" if is_black else "white", c.display if is_black else c.text, CW, CH,
                             c.pick if is_black else 1, c.pack)
            r = V.rect((x, y, CW, CH))
            sh, pad = ui.shadow_px(pw, ph, V.s(10), V.s(8 if hov else 5), 140 if hov else 100)
            surf.blit(sh, (r.x - pad, r.y - pad + V.s(4 if hov else 2)))
            surf.blit(face, r)
            chosen = c is self.black or c in self.whites
            if chosen or hov:
                col = ACCENT if chosen else (150, 150, 160)
                surf.blit(ui.outline_px(r.w, r.h, max(3, int(r.w * 0.075)), col, V.s(3 if chosen else 2)), r)
            if c in self.whites:
                bx, by = x + CW - 14, y + 14
                pygame.draw.circle(surf, ACCENT, V.pt(bx, by), V.s(12))
                ui.draw_text(surf, str(self.whites.index(c) + 1), 14, INK, (bx, by + 0.5))
        surf.set_clip(clip)
        if not self.cards:
            ui.draw_text(surf, "No cards match.", 20, GRAY, (GRID.centerx, GRID.y + 90))
        bar = self.scrollbar()
        if bar:
            track, thumb = bar
            tr = V.rect(track)
            surf.blit(ui.rounded_px(tr.w, tr.h, tr.w // 2, (40, 40, 46)), tr)
            th = V.rect(thumb)
            surf.blit(ui.rounded_px(th.w, th.h, th.w // 2, (120, 120, 130)), th)
        kind = "black" if self.kind.index == 0 else "white"
        ui.draw_text(surf, f"{len(self.cards):,} {kind} cards", 18, WHITE, (42, 668), "midleft")
        ui.draw_text(surf, "Scroll to browse · R for a random combo", 13, DIM, (240, 669), "midleft", bold=False)

        self.draw_combo(surf)
        self.back_btn.draw(surf)

    def draw_combo(self, surf):
        ui.draw_panel(surf, COMBO)
        x, y, w = COMBO.x, COMBO.y, COMBO.w
        ui.draw_text(surf, "Combo maker", 20, WHITE, (x + 20, y + 26), "midleft")
        if self.black is None:
            tip = ["1. Click a black card", "2. Then click white cards", "    to fill in the blanks", "",
                   "Or hit Random combo."]
            for i, t in enumerate(tip):
                ui.draw_text(surf, t, 15, GRAY, (x + 20, y + 80 + i * 26), "midleft", bold=False)
        else:
            segs = fill(self.black.text, [c.text for c in self.whites], WHITE, ACCENT)
            ui.draw_rich(surf, segs, (x + 20, y + 52, w - 40, 230), 26, 12, align="left", valign="top")
            ui.draw_text(surf, ui.ellipsize(self.black.pack, 12, w - 40, False), 12, DIM, (x + 20, y + 296),
                         "midleft", bold=False)
            ui.draw_text(surf, f"Pick {self.black.pick} · {len(self.whites)} chosen", 13, ACCENT,
                         (x + 20, y + 318), "midleft")
            m = ui.mouse_pos()
            for j, r in enumerate(self.white_rows()):
                rr = V.rect(r)
                if j < len(self.whites):
                    hov = r.collidepoint(m)
                    surf.blit(ui.rounded_px(rr.w, rr.h, V.s(8), (238, 238, 234) if not hov else (255, 220, 220)), rr)
                    ui.draw_text(surf, ui.ellipsize(self.whites[j].text, 13, r.w - 46, False), 13, INK,
                                 (r.x + 12, r.centery), "midleft", bold=False)
                    ui.draw_text(surf, "x", 14, (200, 60, 60) if hov else GRAY, (r.right - 16, r.centery))
                else:
                    surf.blit(ui.outline_px(rr.w, rr.h, V.s(8), (80, 80, 90), V.s(1.5)), rr)
                    ui.draw_text(surf, "click a white card", 13, DIM, (r.x + 12, r.centery), "midleft", bold=False)
        self.rand_btn.draw(surf)
        self.clear_btn.draw(surf)
