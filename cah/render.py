"""Card faces and animated card sprites."""
import math

import pygame

from . import ui
from .ui import V, WHITE, INK, ACCENT

CARD_RATIO = 1.4  # height / width

_face_cache = ui.LRU(220)
_glow_cache = ui.LRU(40)


def _glow(w, h):
    def make():
        g, _ = ui.shadow_px(w, h, V.s(14), V.s(10), 255)
        g = g.copy()
        g.fill((*ACCENT, 0), special_flags=pygame.BLEND_RGBA_MAX)
        return g
    return _glow_cache.get_or((w, h, V.scale), make)


def _logo(surf, x, y, px, fg, bg):
    """The little three-card logo plus wordmark in a card's footer."""
    s = max(4, int(px * 1.05))
    for i, (dx, ang) in enumerate(((0, -14), (s * 0.35, 0), (s * 0.7, 14))):
        card = pygame.Surface((int(s * 0.62), int(s * 0.86)), pygame.SRCALPHA)
        card.fill((*fg, 255))
        pygame.draw.rect(card, (*bg, 255), card.get_rect().inflate(-max(2, s // 6), -max(2, s // 6)))
        if i == 2:
            card.fill((*fg, 255))
        rot = pygame.transform.rotozoom(card, -ang, 1)
        surf.blit(rot, rot.get_rect(center=(x + dx + s * 0.3, y)))
    img = ui.text_surf_px("Cards Against Humanity", px, fg)
    surf.blit(img, (x + s * 1.35, y - img.get_height() // 2))


MASTER = 1.25  # faces are drawn this much larger, then scaled down, so hover zoom stays sharp
_master_cache = ui.LRU(90)


def card_master(kind, text, w, h, pick=1, pack="", back=False):
    pw, ph = int(V.s(w) * MASTER), int(V.s(h) * MASTER)
    return _master_cache.get_or((kind, text, pw, ph, pick, pack, back),
                                lambda: _make_face(kind, text, pw, ph, pick, pack, back))


def card_face(kind, text, w, h, pick=1, pack="", back=False):
    """kind is 'black' or 'white'. w/h are design units; returns a pixel surface at 1x size."""
    pw, ph = V.s(w), V.s(h)
    return _face_cache.get_or((kind, text, pw, ph, pick, pack, back),
                              lambda: pygame.transform.smoothscale(
                                  card_master(kind, text, w, h, pick, pack, back), (pw, ph)))


def _make_face(kind, text, pw, ph, pick, pack, back):
    bg, fg = (INK, WHITE) if kind == "black" else (WHITE, INK)
    surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
    rad = max(3, int(pw * 0.075))
    surf.blit(ui.rounded_px(pw, ph, rad, bg), (0, 0))
    if kind == "black":
        surf.blit(ui.outline_px(pw, ph, rad, (58, 58, 64), max(1, pw // 110)), (0, 0))
    else:
        surf.blit(ui.outline_px(pw, ph, rad, (210, 210, 206), max(1, pw // 110)), (0, 0))
    pad = int(pw * 0.1)

    if back:
        px = int(pw * 0.165)
        f = ui.font_px(px)
        y = int(ph * 0.12)
        for word in ("Cards", "Against", "Humanity."):
            img = ui.text_surf_px(word, px, fg)
            surf.blit(img, (pad, y))
            y += int(f.get_linesize() * 0.98)
        return surf

    text = ui.sanitize(text)
    footer_h = int(ph * 0.14)
    avail_w, avail_h = pw - pad * 2, ph - pad - footer_h - int(ph * 0.03)
    px = int(pw * 0.112)
    min_px = max(6, int(pw * 0.058))
    while True:
        f = ui.font_px(px)
        lines = ui.wrap(text, f, avail_w)
        lh = int(f.get_linesize() * 1.06)
        if len(lines) * lh <= avail_h or px <= min_px:
            break
        px -= 1
    y = pad
    for line in lines:
        if y + lh > pad + avail_h + lh * 0.3:
            break
        if line:
            surf.blit(ui.text_surf_px(line, px, fg), (pad, y))
        y += lh

    fpx = max(5, int(pw * 0.046))
    fy = ph - int(footer_h * 0.5)
    if pack and pw >= 90:
        label = pack if len(pack) <= 34 else pack[:32].rstrip() + "..."
        img = ui.text_surf_px(label, fpx, (120, 120, 126) if kind == "black" else (150, 150, 146))
        if img.get_width() > pw - pad * 2 - (pw * 0.3 if kind == "black" and pick > 1 else 0):
            _logo(surf, pad, fy, fpx, fg, bg)
        else:
            surf.blit(img, (pad, fy - img.get_height() // 2))
    else:
        _logo(surf, pad, fy, fpx, fg, bg)

    if kind == "black" and pick > 1:
        bpx = max(6, int(pw * 0.062))
        label = ui.text_surf_px("PICK", bpx, WHITE)
        num = ui.text_surf_px(str(pick), int(bpx * 1.25), INK)
        cr = int(num.get_height() * 0.62)
        cx = pw - pad - cr
        pygame.draw.circle(surf, WHITE, (cx, fy), cr)
        surf.blit(num, num.get_rect(center=(cx, fy + 1)))
        surf.blit(label, label.get_rect(midright=(cx - cr - int(pw * 0.03), fy)))
    return surf


class CardSprite:
    """A card that glides toward its targets. Positions are the card's centre."""

    def __init__(self, kind, card, x, y, w=140, face_up=True, pick=1):
        self.kind = kind
        self.card = card
        self.text = card.text if card is not None else ""
        self.pack = card.pack if card is not None else ""
        self.pick = pick
        self.w = w
        self.h = w * CARD_RATIO
        self.x = self.tx = x
        self.y = self.ty = y
        self.scale = self.tscale = 1.0
        self.flip = self.tflip = 0.0 if face_up else 1.0
        self.alpha = self.talpha = 255.0
        self.angle = self.tangle = 0.0
        self.glow = self.tglow = 0.0
        self.dim = self.tdim = 0.0
        self.badge = None
        self.speed = 11.0
        self.delay = 0.0
        self.on_flip = None
        self._flipped = self.flip > 0.5

    def move(self, x, y, scale=None, delay=None):
        self.tx, self.ty = x, y
        if scale is not None:
            self.tscale = scale
        if delay is not None:
            self.delay = delay

    def snap(self):
        self.x, self.y, self.scale, self.flip = self.tx, self.ty, self.tscale, self.tflip
        self.alpha, self.angle, self.glow, self.dim = self.talpha, self.tangle, self.tglow, self.tdim

    def resize(self, w):
        self.w, self.h = w, w * CARD_RATIO

    @property
    def settled(self):
        return abs(self.x - self.tx) < 1 and abs(self.y - self.ty) < 1 and abs(self.flip - self.tflip) < 0.02

    def update(self, dt):
        if self.delay > 0:
            self.delay -= dt
            return
        k = self.speed
        self.x = ui.approach(self.x, self.tx, k, dt)
        self.y = ui.approach(self.y, self.ty, k, dt)
        self.scale = ui.approach(self.scale, self.tscale, k * 1.3, dt)
        self.flip = ui.approach(self.flip, self.tflip, 8.5, dt)
        self.alpha = ui.approach(self.alpha, self.talpha, 9, dt)
        self.angle = ui.approach(self.angle, self.tangle, k, dt)
        self.glow = ui.approach(self.glow, self.tglow, 8, dt)
        self.dim = ui.approach(self.dim, self.tdim, 8, dt)
        flipped = self.flip > 0.5
        if flipped != self._flipped:
            self._flipped = flipped
            if self.on_flip:
                self.on_flip()

    def rect(self):
        w, h = self.w * self.scale, self.h * self.scale
        return pygame.Rect(int(self.x - w / 2), int(self.y - h / 2), int(w), int(h))

    def contains(self, p):
        return self.alpha > 20 and self.rect().collidepoint(p)

    def draw(self, surf):
        if self.alpha < 2:
            return
        back = self.flip > 0.5
        face = card_face(self.kind, self.text, self.w, self.h, self.pick, self.pack, back)
        fx = abs(math.cos(self.flip * math.pi))
        pw, ph = face.get_size()
        sw, sh = max(1, int(pw * self.scale * fx)), max(1, int(ph * self.scale))
        if (sw, sh) == (pw, ph):
            img = face
        else:
            src = card_master(self.kind, self.text, self.w, self.h, self.pick, self.pack, back) \
                if self.scale > 1.01 else face
            img = pygame.transform.smoothscale(src, (sw, sh))
        if abs(self.angle) > 0.3:
            img = pygame.transform.rotozoom(img, self.angle, 1)
        if self.dim > 0.01:
            img = img.copy()
            v = int(255 * (1 - 0.6 * self.dim))
            img.fill((v, v, v), special_flags=pygame.BLEND_RGB_MULT)
        cx, cy = V.pt(self.x, self.y)
        lift = round(max(0.0, self.scale - 1.0) * 20) / 20

        def q(v):  # blurred shapes don't need exact sizes; quantising keeps the cache small
            return max(8, int(round(v / 8.0)) * 8)

        if self.glow > 0.02:
            g = _glow(q(sw + V.s(10)), q(sh + V.s(10)))
            g.set_alpha(int(220 * self.glow * self.alpha / 255))
            surf.blit(g, g.get_rect(center=(cx, cy)))
        sh_img, pad = ui.shadow_px(q(sw), q(sh), V.s(10), V.s(6 + 10 * lift), int(100 + 120 * lift))
        off = V.s(4 + 20 * lift)
        if self.alpha < 254:
            sh_img = sh_img.copy()
            sh_img.set_alpha(int(self.alpha))
            img = img.copy()
            img.set_alpha(int(self.alpha))
        surf.blit(sh_img, sh_img.get_rect(center=(cx, cy + off)))
        surf.blit(img, img.get_rect(center=(cx, cy)))
        if self.badge is not None and not back:
            r = self.rect()
            bx, by = r.centerx - r.w * 0.18, r.top - 2
            pygame.draw.circle(surf, INK, V.pt(bx, by), V.s(15))
            pygame.draw.circle(surf, ACCENT, V.pt(bx, by), V.s(13))
            ui.draw_text(surf, str(self.badge), 16, INK, (bx, by + 0.5))
