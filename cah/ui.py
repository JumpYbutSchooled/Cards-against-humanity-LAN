"""Resolution-independent drawing helpers and widgets.

Everything is laid out in a 1280x720 "design" space and converted to real
pixels at draw time, so text is rendered at native size and stays crisp.
"""
import math
import os
import re
from collections import OrderedDict

import pygame

DW, DH = 1280, 720

WHITE = (246, 246, 244)
BLACK = (14, 14, 16)
INK = (24, 24, 27)
GRAY = (150, 150, 158)
DIM = (92, 92, 100)
PANEL = (30, 30, 35)
PANEL_HI = (44, 44, 51)
ACCENT = (255, 199, 44)
ACCENT_DARK = (120, 92, 10)
GREEN = (96, 214, 140)
RED = (240, 92, 92)


class View:
    def __init__(self):
        self.resize(DW, DH)

    def resize(self, w, h):
        self.w, self.h = w, h
        self.scale = min(w / DW, h / DH)
        self.ox = (w - DW * self.scale) / 2
        self.oy = (h - DH * self.scale) / 2

    def s(self, v):
        return max(1, int(round(v * self.scale)))

    def pt(self, x, y):
        return int(round(self.ox + x * self.scale)), int(round(self.oy + y * self.scale))

    def rect(self, r):
        x, y, w, h = r
        X, Y = self.pt(x, y)
        return pygame.Rect(X, Y, max(1, int(round(w * self.scale))), max(1, int(round(h * self.scale))))

    def to_design(self, pos):
        return (pos[0] - self.ox) / self.scale, (pos[1] - self.oy) / self.scale


V = View()


def mouse_pos():
    return V.to_design(pygame.mouse.get_pos())


def approach(cur, target, speed, dt):
    return target + (cur - target) * math.exp(-speed * dt)


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- fonts / text

_font_paths = {}
_fonts = {}
# Explicit files: pygame's name matching picks Arial *Narrow* on many Windows installs.
_FONT_FILES = {True: ["HelveticaNeue-Bold.ttf", "HelveticaNeueBold.ttf", "arialbd.ttf", "Arial Bold.ttf",
                      "segoeuib.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
               False: ["HelveticaNeue.ttf", "arial.ttf", "Arial.ttf", "segoeui.ttf", "LiberationSans-Regular.ttf",
                       "DejaVuSans.ttf"]}
_FONT_DIRS = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts"),
              os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
              "/Library/Fonts", "/System/Library/Fonts/Supplemental", "/usr/share/fonts/truetype/msttcorefonts",
              "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/dejavu"]


def _find_font(bold):
    for name in _FONT_FILES[bold]:
        for d in _FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return pygame.font.match_font("arial,helvetica,segoeui", bold=bold)


def font_px(px, bold=True):
    key = (px, bold)
    f = _fonts.get(key)
    if f is None:
        if bold not in _font_paths:
            _font_paths[bold] = _find_font(bold)
        path = _font_paths[bold]
        f = pygame.font.Font(path, px) if path else pygame.font.SysFont(None, px, bold=bold)
        _fonts[key] = f
    return f


def font(size, bold=True):
    return font_px(V.s(size), bold)


_glyph_ok = {}
_GLYPH_SUBS = {"★": "*", "✰": "*", "☆": "*", "♥": "<3", "❤": "<3"}


def sanitize(text):
    """Swap characters the font cannot draw for plain look-alikes."""
    ref = font_px(20)
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
            continue
        ok = _glyph_ok.get(ch)
        if ok is None:
            m = ref.metrics(ch)
            ok = bool(m) and m[0] is not None
            _glyph_ok[ch] = ok
        out.append(ch if ok else _GLYPH_SUBS.get(ch, "?"))
    return "".join(out)


class LRU(OrderedDict):
    def __init__(self, cap):
        super().__init__()
        self.cap = cap

    def get_or(self, key, make):
        if key in self:
            self.move_to_end(key)
            return self[key]
        v = make()
        self[key] = v
        if len(self) > self.cap:
            self.popitem(last=False)
        return v


_text_cache = LRU(1500)


def text_surf_px(s, px, color, bold=True):
    return _text_cache.get_or((s, px, color, bold), lambda: font_px(px, bold).render(s, True, color))


def text_surf(s, size, color, bold=True):
    return text_surf_px(s, V.s(size), color, bold)


def draw_text(surf, s, size, color, pos, anchor="center", bold=True, alpha=255):
    img = text_surf(s, size, color, bold)
    if alpha < 255:
        img = img.copy()
        img.set_alpha(max(0, int(alpha)))
    r = img.get_rect()
    setattr(r, anchor, V.pt(*pos))
    surf.blit(img, r)
    return r


def text_width(s, size, bold=True):
    return font(size, bold).size(s)[0] / V.scale


def ellipsize(s, size, max_w, bold=True):
    if text_width(s, size, bold) <= max_w:
        return s
    while s and text_width(s + "...", size, bold) > max_w:
        s = s[:-1]
    return s.rstrip() + "..."


def wrap(text, f, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            if not word:
                continue
            t = word if not cur else cur + " " + word
            if f.size(t)[0] <= max_w:
                cur = t
                continue
            if cur:
                lines.append(cur)
            while f.size(word)[0] > max_w and len(word) > 1:
                i = len(word) - 1
                while i > 1 and f.size(word[:i] + "-")[0] > max_w:
                    i -= 1
                lines.append(word[:i] + "-")
                word = word[i:]
            cur = word
        lines.append(cur)
    return lines


# Rich text: list of (text, color) segments, wrapped word by word.

def _rich_tokens(segments):
    toks, space = [], False
    for text, color in segments:
        for m in re.finditer(r"\n|[ \t]+|\S+", text):
            t = m.group()
            if t == "\n":
                toks.append(("\n", None, False))
                space = False
            elif t.isspace():
                space = True
            else:
                toks.append((t, color, space))
                space = False
    return toks


def _layout_rich(toks, f, max_w):
    lines, x = [[]], 0
    sp = f.size(" ")[0]
    for t, c, spb in toks:
        if t == "\n":
            lines.append([])
            x = 0
            continue
        w = f.size(t)[0]
        gap = sp if (spb and lines[-1]) else 0
        if lines[-1] and x + gap + w > max_w:
            lines.append([])
            x, gap = 0, 0
        lines[-1].append((x + gap, t, c))
        x += gap + w
    return lines


def draw_rich(surf, segments, rect, max_size, min_size=12, align="center", valign="center", line_gap=1.18):
    """Draws wrapped multi-colour text inside a design-space rect, shrinking to fit."""
    r = V.rect(rect)
    toks = _rich_tokens([(sanitize(t), c) for t, c in segments])
    size = max_size
    while True:
        px = V.s(size)
        f = font_px(px)
        lines = _layout_rich(toks, f, r.w)
        lh = int(f.get_linesize() * line_gap)
        if len(lines) * lh <= r.h or size <= min_size:
            break
        size -= 1
    total = len(lines) * lh
    y = r.y + {"top": 0, "center": (r.h - total) // 2, "bottom": r.h - total}[valign]
    for line in lines:
        if line:
            width = line[-1][0] + f.size(line[-1][1])[0]
            x0 = r.x + {"left": 0, "center": (r.w - width) // 2, "right": r.w - width}[align]
            for x, t, c in line:
                surf.blit(text_surf_px(t, px, c), (x0 + x, y))
        y += lh
    return size


# ---------------------------------------------------------------- shapes

_shape_cache = LRU(260)


_mask_cache = LRU(300)


def _aa_mask(w, h, radius, width=0):
    """White anti-aliased rounded rect (filled, or an outline if width > 0). Supersampled once per size."""
    def make():
        ss = 2 if w * h > 250_000 else 3
        big = pygame.Surface((w * ss, h * ss), pygame.SRCALPHA)
        pygame.draw.rect(big, (255, 255, 255, 255), big.get_rect(), width=int(round(width * ss)),
                         border_radius=int(radius * ss))
        return pygame.transform.smoothscale(big, (w, h))
    return _mask_cache.get_or((w, h, radius, round(width, 1)), make)


def _tinted(mask, color, alpha):
    s = mask.copy()
    s.fill((*color, alpha), special_flags=pygame.BLEND_RGBA_MULT)
    return s


def rounded_px(w, h, radius, color, alpha=255):
    """Anti-aliased rounded rectangle surface."""
    return _shape_cache.get_or(("r", w, h, radius, color, alpha),
                               lambda: _tinted(_aa_mask(w, h, radius), color, alpha))


def outline_px(w, h, radius, color, width, alpha=255):
    return _shape_cache.get_or(("o", w, h, radius, color, width, alpha),
                               lambda: _tinted(_aa_mask(w, h, radius, max(1, width)), color, alpha))


_dim_cache = {}


def dim_screen(surf, alpha, color=(0, 0, 0)):
    """Darkens the whole screen. Reuses one surface instead of allocating a full-screen one per frame."""
    if alpha <= 0:
        return
    key = (surf.get_size(), color)
    d = _dim_cache.get(key)
    if d is None:
        _dim_cache.clear()
        d = pygame.Surface(surf.get_size()).convert()
        d.fill(color)
        _dim_cache[key] = d
    d.set_alpha(int(max(0, min(255, alpha))))
    surf.blit(d, (0, 0))


def shadow_px(w, h, radius, blur, alpha=110):
    def make():
        pad = blur * 2
        small_scale = 0.25
        sw, sh = max(2, int((w + pad * 2) * small_scale)), max(2, int((h + pad * 2) * small_scale))
        small = pygame.Surface((sw, sh), pygame.SRCALPHA)
        inner = pygame.Rect(int(pad * small_scale), int(pad * small_scale), max(1, int(w * small_scale)),
                            max(1, int(h * small_scale)))
        pygame.draw.rect(small, (0, 0, 0, alpha), inner, border_radius=max(1, int(radius * small_scale)))
        for _ in range(2):
            small = pygame.transform.smoothscale(small, (max(2, sw // 2), max(2, sh // 2)))
            small = pygame.transform.smoothscale(small, (sw, sh))
        return pygame.transform.smoothscale(small, (w + pad * 2, h + pad * 2)), pad
    return _shape_cache.get_or(("s", w, h, radius, blur, alpha), make)


def draw_panel(surf, rect, color=PANEL, radius=14, alpha=235, border=None, shadow=True, fade=1.0):
    r = V.rect(rect)
    rad = V.s(radius)
    if fade <= 0.01:
        return r
    if shadow:
        sh, pad = shadow_px(r.w, r.h, rad, V.s(10), 90)
        if fade < 1:
            sh = sh.copy()
            sh.set_alpha(int(255 * fade))
        surf.blit(sh, (r.x - pad, r.y - pad + V.s(4)))
    img = rounded_px(r.w, r.h, rad, color, alpha)
    if fade < 1:
        img = img.copy()
        img.set_alpha(int(255 * fade))
    surf.blit(img, r)
    if border:
        surf.blit(outline_px(r.w, r.h, rad, border[0], V.s(border[1])), r)
    return r


def draw_check(surf, center, size, t, color=INK):
    """Check mark drawn progressively (t from 0..1)."""
    if t <= 0.02:
        return
    cx, cy = center
    pts = [(cx - size * 0.32, cy + size * 0.02), (cx - size * 0.08, cy + size * 0.26), (cx + size * 0.34, cy - size * 0.24)]
    pts = [V.pt(*p) for p in pts]
    a, b, c = pts
    w = max(2, V.s(size * 0.14))
    if t < 0.4:
        k = t / 0.4
        pygame.draw.line(surf, color, a, (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k), w)
    else:
        k = (t - 0.4) / 0.6
        pygame.draw.line(surf, color, a, b, w)
        pygame.draw.line(surf, color, b, (b[0] + (c[0] - b[0]) * k, b[1] + (c[1] - b[1]) * k), w)
        pygame.draw.circle(surf, color, b, w // 2)


def draw_checkbox(surf, rect, state, anim, hover=0.0):
    """state: 0 off, 1 on, 2 partial. anim: 0..1 fill amount."""
    x, y, w, h = rect
    r = V.rect(rect)
    rad = V.s(6)
    base = lerp_color((70, 70, 78), (200, 200, 205), hover * 0.5)
    surf.blit(outline_px(r.w, r.h, rad, base, V.s(2)), r)
    if anim > 0.01:
        k = ease_out(anim)
        fw, fh = max(1, int(r.w * k)), max(1, int(r.h * k))
        surf.blit(rounded_px(fw, fh, max(1, int(rad * k)), WHITE), (r.centerx - fw // 2, r.centery - fh // 2))
        if state == 2:
            pygame.draw.line(surf, INK, V.pt(x + w * 0.27, y + h / 2), V.pt(x + w * 0.73, y + h / 2), max(2, V.s(3)))
        elif state == 1:
            draw_check(surf, (x + w / 2, y + h / 2), w, anim)


def draw_triangle(surf, center, size, angle, color):
    cx, cy = center
    pts = []
    for a in (0, 2.094, 4.189):
        pts.append(V.pt(cx + math.cos(a + angle) * size, cy + math.sin(a + angle) * size))
    pygame.draw.polygon(surf, color, pts)
    pygame.draw.aalines(surf, color, True, pts)


def draw_crown(surf, center, size, color=ACCENT):
    cx, cy = center
    s = size
    pts = [(-0.5, 0.35), (-0.5, -0.25), (-0.25, 0.05), (0, -0.4), (0.25, 0.05), (0.5, -0.25), (0.5, 0.35)]
    pts = [V.pt(cx + px * s, cy + py * s) for px, py in pts]
    pygame.draw.polygon(surf, color, pts)
    pygame.draw.aalines(surf, color, True, pts)


# ---------------------------------------------------------------- widgets

class Button:
    STYLES = {
        "primary": (WHITE, INK, (255, 255, 255)),
        "secondary": (PANEL_HI, WHITE, (66, 66, 76)),
        "accent": (ACCENT, INK, (255, 214, 92)),
        "ghost": (None, WHITE, (40, 40, 46)),
        "danger": ((70, 32, 34), (255, 170, 170), (96, 40, 42)),
    }

    def __init__(self, rect, label, callback=None, style="primary", size=20, enabled=True, sub=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.callback = callback
        self.style = style
        self.size = size
        self.enabled = enabled
        self.sub = sub
        self.hover = 0.0
        self.press = 0.0
        self._down = False
        self.visible = True
        self.sounds = None

    def contains(self, p):
        return self.visible and self.rect.collidepoint(p)

    def handle(self, ev):
        if not self.visible or not self.enabled:
            self._down = False
            return False
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.rect.collidepoint(V.to_design(ev.pos)):
            self._down = True
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            was = self._down
            self._down = False
            if was and self.rect.collidepoint(V.to_design(ev.pos)):
                self.click()
                return True
        return False

    def click(self):
        if self.sounds:
            self.sounds.play("click")
        if self.callback:
            self.callback()

    def update(self, dt):
        hov = self.visible and self.enabled and self.rect.collidepoint(mouse_pos())
        self.hover = approach(self.hover, 1.0 if hov else 0.0, 14, dt)
        self.press = approach(self.press, 1.0 if self._down else 0.0, 24, dt)

    def draw(self, surf):
        if not self.visible:
            return
        bg, fg, hi = self.STYLES[self.style]
        x, y, w, h = self.rect
        lift = -2 * self.hover + 2 * self.press
        rect = (x, y + lift, w, h)
        r = V.rect(rect)
        rad = V.s(min(h / 2, 14))
        alpha = 255 if self.enabled else 90
        hq = round(self.hover * 8) / 8  # quantised so hover fades reuse cached shapes
        if bg is not None or hq > 0:
            if self.enabled and self.style in ("primary", "accent"):
                sh, pad = shadow_px(r.w, r.h, rad, V.s(8), int(60 + 70 * hq))
                surf.blit(sh, (r.x - pad, r.y - pad + V.s(5)))
            col = lerp_color(bg or (24, 24, 28), hi, hq) if bg else hi
            surf.blit(rounded_px(r.w, r.h, rad, col, alpha if bg else int(255 * hq)), r)
        if self.style == "ghost":
            surf.blit(outline_px(r.w, r.h, rad, (90, 90, 100), V.s(1.5)), r)
        cy = y + lift + h / 2
        if self.sub:
            draw_text(surf, self.label, self.size, fg, (x + w / 2, cy - self.size * 0.35), alpha=alpha)
            draw_text(surf, self.sub, self.size * 0.55, lerp_color(fg, GRAY, 0.5), (x + w / 2, cy + self.size * 0.6),
                      bold=False, alpha=alpha)
        else:
            draw_text(surf, self.label, self.size, fg, (x + w / 2, cy), alpha=alpha)


class TextInput:
    def __init__(self, rect, text="", placeholder="", max_len=20, size=18, on_change=None):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.placeholder = placeholder
        self.max_len = max_len
        self.size = size
        self.focused = False
        self.blink = 0.0
        self.hover = 0.0
        self.focus_anim = 0.0
        self.on_change = on_change

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            was = self.focused
            self.focused = self.rect.collidepoint(V.to_design(ev.pos))
            if self.focused:
                self.blink = 0
            return self.focused and not was
        if not self.focused:
            return False
        if ev.type == pygame.TEXTINPUT:
            if len(self.text) < self.max_len:
                self.text += ev.text
                self._changed()
            return True
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                if ev.mod & pygame.KMOD_CTRL:
                    self.text = self.text.rstrip().rsplit(" ", 1)[0] if " " in self.text.strip() else ""
                else:
                    self.text = self.text[:-1]
                self._changed()
                return True
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_TAB):
                self.focused = False
                return True
            if ev.key == pygame.K_v and ev.mod & pygame.KMOD_CTRL:
                try:
                    clip = pygame.scrap.get_text() if hasattr(pygame.scrap, "get_text") else ""
                except Exception:
                    clip = ""
                if clip:
                    self.text = (self.text + clip.replace("\n", " "))[: self.max_len]
                    self._changed()
                return True
            return True
        return False

    def _changed(self):
        self.blink = 0
        if self.on_change:
            self.on_change(self.text)

    def update(self, dt):
        self.blink += dt
        self.hover = approach(self.hover, 1.0 if self.rect.collidepoint(mouse_pos()) else 0.0, 14, dt)
        self.focus_anim = approach(self.focus_anim, 1.0 if self.focused else 0.0, 16, dt)

    def draw(self, surf):
        x, y, w, h = self.rect
        r = V.rect(self.rect)
        rad = V.s(10)
        surf.blit(rounded_px(r.w, r.h, rad, lerp_color((22, 22, 26), (30, 30, 36), round(self.hover * 4) / 4)), r)
        border = lerp_color((60, 60, 68), WHITE, round(self.focus_anim * 8) / 8)
        surf.blit(outline_px(r.w, r.h, rad, border, V.s(1.5 + round(self.focus_anim))), r)
        pad = 14
        clip = surf.get_clip()
        surf.set_clip(V.rect((x + 6, y, w - 12, h)).clip(clip) if clip else V.rect((x + 6, y, w - 12, h)))
        if self.text:
            tw = text_width(self.text, self.size, False)
            off = min(0, (w - pad * 2) - tw - 4)
            tr = draw_text(surf, self.text, self.size, WHITE, (x + pad + off, y + h / 2), "midleft", bold=False)
            end_x = (tr.right - V.ox) / V.scale
        else:
            draw_text(surf, self.placeholder, self.size, DIM, (x + pad, y + h / 2), "midleft", bold=False)
            end_x = x + pad
        if self.focused and (self.blink % 1.0) < 0.55:
            pygame.draw.line(surf, WHITE, V.pt(end_x + 2, y + h * 0.25), V.pt(end_x + 2, y + h * 0.75), max(1, V.s(2)))
        surf.set_clip(clip)


class Stepper:
    def __init__(self, rect, label, value, lo, hi, step=1, fmt="{}", on_change=None, sounds=None):
        self.rect = pygame.Rect(rect)
        self.label, self.value, self.lo, self.hi, self.step, self.fmt = label, value, lo, hi, step, fmt
        self.on_change = on_change
        x, y, w, h = self.rect
        bw = h - 10
        self.minus = Button((x + w - bw * 2 - 70, y + 5, bw, bw), "-", lambda: self.change(-1), "secondary", 22)
        self.plus = Button((x + w - bw, y + 5, bw, bw), "+", lambda: self.change(1), "secondary", 22)
        self.minus.sounds = self.plus.sounds = sounds
        self.bump = 0.0

    def change(self, d):
        v = max(self.lo, min(self.hi, self.value + d * self.step))
        if v != self.value:
            self.value = v
            self.bump = 1.0
            if self.on_change:
                self.on_change(v)

    def handle(self, ev):
        if ev.type == pygame.MOUSEWHEEL and self.rect.collidepoint(mouse_pos()):
            self.change(1 if ev.y > 0 else -1)
            return True
        return self.minus.handle(ev) or self.plus.handle(ev)

    def update(self, dt):
        self.minus.enabled = self.value > self.lo
        self.plus.enabled = self.value < self.hi
        self.minus.update(dt)
        self.plus.update(dt)
        self.bump = approach(self.bump, 0, 10, dt)

    def draw(self, surf):
        x, y, w, h = self.rect
        draw_text(surf, self.label, 18, WHITE, (x, y + h / 2), "midleft")
        self.minus.draw(surf)
        self.plus.draw(surf)
        cx = (self.minus.rect.right + self.plus.rect.left) / 2
        draw_text(surf, self.fmt.format(self.value), 22 + 4 * self.bump, lerp_color(WHITE, ACCENT, self.bump),
                  (cx, y + h / 2))


class Segmented:
    """Two-or-more option pill switch."""

    def __init__(self, rect, options, index=0, on_change=None, size=15, sounds=None):
        self.rect = pygame.Rect(rect)
        self.options = options
        self.index = index
        self.on_change = on_change
        self.size = size
        self.knob = float(index)
        self.sounds = sounds

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = V.to_design(ev.pos)
            if self.rect.collidepoint(p):
                i = int((p[0] - self.rect.x) / (self.rect.w / len(self.options)))
                i = max(0, min(len(self.options) - 1, i))
                if i != self.index:
                    self.index = i
                    if self.sounds:
                        self.sounds.play("select")
                    if self.on_change:
                        self.on_change(i)
                return True
        return False

    def update(self, dt):
        self.knob = approach(self.knob, self.index, 16, dt)

    def draw(self, surf):
        x, y, w, h = self.rect
        r = V.rect(self.rect)
        surf.blit(rounded_px(r.w, r.h, r.h // 2, (22, 22, 26)), r)
        surf.blit(outline_px(r.w, r.h, r.h // 2, (60, 60, 68), V.s(1.5)), r)
        sw = w / len(self.options)
        kr = V.rect((x + 3 + self.knob * sw, y + 3, sw - 6, h - 6))
        surf.blit(rounded_px(kr.w, kr.h, kr.h // 2, WHITE), kr)
        for i, opt in enumerate(self.options):
            t = max(0.0, 1 - abs(self.knob - i))
            draw_text(surf, opt, self.size, lerp_color(GRAY, INK, t), (x + sw * i + sw / 2, y + h / 2))
