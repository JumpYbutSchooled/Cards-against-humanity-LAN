import math

import pygame

from . import ui
from .app import Scene
from .presets import all_presets, builtin, match_name
from .ui import Button, TextInput, V, WHITE, GRAY, DIM, INK, ACCENT, PANEL, PANEL_HI, RED

LIST = pygame.Rect(316, 166, 924, 474)
SIDE = pygame.Rect(40, 166, 256, 474)
SECTION_H, GROUP_H, PACK_H = 54, 50, 40
PRESET_H = 43
SECTION_LABEL = {"Mixes": "Mixes - matching cards from every pack", "Official": "Official Cards Against Humanity",
                 "Third-Party": "Third-Party & Community Games"}


def card_icon(surf, x, y, black):
    r = V.rect((x, y - 8, 12, 16))
    rad = V.s(2.5)
    if black:
        surf.blit(ui.rounded_px(r.w, r.h, rad, (8, 8, 10)), r)
        surf.blit(ui.outline_px(r.w, r.h, rad, (120, 120, 128), V.s(1.2)), r)
    else:
        surf.blit(ui.rounded_px(r.w, r.h, rad, WHITE), r)


class PresetChips:
    """Quick preset buttons for the setup screen and the host lobby."""
    NAMES = ["Classic", "Party", "18+ Filthy", "Sex & Vulgarity", "Family", "Everything"]

    def __init__(self, app, x, y, w, on_pick, cols=3, h=34, gap=8):
        self.app = app
        self.on_pick = on_pick
        cw = (w - gap * (cols - 1)) / cols
        self.chips = []
        for i, n in enumerate(self.NAMES):
            r = (x + (i % cols) * (cw + gap), y + (i // cols) * (h + gap), cw, h)
            b = Button(r, n, lambda n=n: self.pick(n), "secondary", 14)
            b.sounds = app.sounds
            self.chips.append(b)
        self.active = None

    def pick(self, name):
        p = next(p for p in builtin(self.app.library) if p["name"] == name)
        self.on_pick(list(p["packs"]), name)

    def handle(self, ev):
        return any(b.handle(ev) for b in self.chips)

    def update(self, dt, active):
        self.active = active
        for b in self.chips:
            b.style = "primary" if b.label == active else "secondary"
            b.update(dt)

    def draw(self, surf):
        for b in self.chips:
            b.draw(surf)


class PacksScene(Scene):
    def __init__(self, app, back):
        super().__init__(app)
        self.back = back
        lib = app.library
        self.sel = set(app.settings["packs"])
        self.groups = lib.groups
        self.open = {g["name"]: (1.0 if g["category"] == "Official" else 0.0) for g in self.groups}
        self.open_target = dict(self.open)
        self.check = {p["id"]: (1.0 if p["id"] in self.sel else 0.0) for p in lib.packs}
        self.gcheck = {}
        self.hover = {}
        self.scroll = self.scroll_t = 0.0
        self.content_h = 0
        self.rows = []
        self.filter = ""
        self.dragging_bar = None
        self.t = 0.0
        self.presets = []
        self.preset_hover = {}
        self.side_scroll = 0.0
        self.naming = False

        self.search = TextInput((872, 40, 368, 46), "", "Search packs...", 40, 17, on_change=self.on_search)
        self.preset_name = TextInput((SIDE.x + 12, SIDE.bottom - 52, SIDE.w - 24, 40), "", "Preset name, then Enter",
                                     22, 15)
        bx, y = LIST.x, 108
        specs = [("Browse cards", self.browse, "accent"), ("Clear", self.clear, "secondary"),
                 ("Expand all", lambda: self.expand(True), "secondary"),
                 ("Collapse all", lambda: self.expand(False), "secondary")]
        btns = []
        for label, cb, style in specs:
            w = int(ui.text_width(label, 15)) + 36
            btns.append(Button((bx, y, w, 40), label, cb, style, 15))
            bx += w + 10
        self.top_btns = btns
        self.save_btn = Button((SIDE.x + 12, SIDE.bottom - 52, SIDE.w - 24, 40), "+ Save current as preset",
                               self.start_naming, "ghost", 14)
        self.done = Button((1040, 654, 200, 50), "Done", self.on_done, "primary", 20)
        self.all = self.buttons(*btns, self.save_btn, self.done)
        self.refresh_presets()

    # ---------------------------------------------------------- presets
    def refresh_presets(self):
        lib = self.app.library
        self.presets = all_presets(lib, self.app.settings)
        for p in self.presets:
            p["counts"] = lib.counts(p["packs"])

    def apply_preset(self, p):
        self.sel = set(p["packs"])
        self.app.sounds.play("select")

    def start_naming(self):
        self.naming = True
        self.preset_name.text = ""
        self.preset_name.focused = True

    def save_preset(self):
        name = self.preset_name.text.strip()
        self.naming = False
        self.preset_name.focused = False
        if not name or not self.sel:
            return
        lst = [c for c in self.app.settings.get("presets", []) if c["name"].lower() != name.lower()]
        lst.append({"name": name, "packs": [p["id"] for p in self.app.library.packs if p["id"] in self.sel]})
        self.app.settings["presets"] = lst
        self.app.save()
        self.refresh_presets()
        self.app.sounds.play("point")

    def delete_preset(self, name):
        self.app.settings["presets"] = [c for c in self.app.settings.get("presets", []) if c["name"] != name]
        self.app.save()
        self.refresh_presets()
        self.app.sounds.play("deselect")

    def preset_rows(self):
        """(preset, y) pairs for the sidebar list, scrolled."""
        top = SIDE.y + 44 - self.side_scroll
        return [(p, top + i * PRESET_H) for i, p in enumerate(self.presets)]

    def side_max_scroll(self):
        list_h = SIDE.h - 44 - 80
        return max(0.0, len(self.presets) * PRESET_H - list_h)

    # ---------------------------------------------------------- selection helpers
    def _set(self, ids, on):
        changed = False
        for i in ids:
            if on and i not in self.sel:
                self.sel.add(i)
                changed = True
            elif not on and i in self.sel:
                self.sel.discard(i)
                changed = True
        if changed:
            self.app.sounds.play("select" if on else "deselect")

    def visible_packs(self, group):
        f = self.filter
        return [p for p in group["packs"] if not f or f in p["name"].lower() or f in group["name"].lower()]

    def clear(self):
        self._set(list(self.sel), False)

    def expand(self, on):
        for g in self.groups:
            self.open_target[g["name"]] = 1.0 if on else 0.0

    def on_search(self, text):
        self.filter = text.strip().lower()
        self.scroll_t = 0

    def commit(self):
        lib = self.app.library
        self.app.settings["packs"] = [p["id"] for p in lib.packs if p["id"] in self.sel]
        self.app.save()

    def on_done(self):
        self.commit()
        self.app.switch(self.back())

    def browse(self, pack_ids=None, title=None):
        from .scene_browser import CardBrowserScene
        ids = pack_ids or [p["id"] for p in self.app.library.packs if p["id"] in self.sel]
        self.app.switch(CardBrowserScene(self.app, back=lambda: self, pack_ids=ids, title=title))

    # ---------------------------------------------------------- layout
    def layout(self):
        rows = []
        y = 0.0
        cat = None
        for g in self.groups:
            packs = self.visible_packs(g)
            if not packs:
                continue
            if g["category"] != cat:
                cat = g["category"]
                cat_ids = [p["id"] for gg in self.groups if gg["category"] == cat for p in self.visible_packs(gg)]
                rows.append(("section", cat, y, SECTION_H, cat_ids))
                y += SECTION_H
            openness = 1.0 if self.filter else self.open[g["name"]]
            rows.append(("group", g, y, GROUP_H, [p["id"] for p in packs]))
            y += GROUP_H + 6
            if openness > 0.01:
                for p in packs:
                    h = PACK_H * openness
                    rows.append(("pack", p, y, h, openness))
                    y += h
                y += 8 * openness
        self.rows = rows
        self.content_h = y + 20

    def max_scroll(self):
        return max(0.0, self.content_h - LIST.h)

    def row_at(self, p):
        if not LIST.collidepoint(p):
            return None
        y = p[1] - LIST.y + self.scroll
        for row in self.rows:
            if row[2] <= y < row[2] + row[3]:
                return row
        return None

    def view_btn_rect(self, ry):
        return pygame.Rect(LIST.right - 330, ry + 7, 76, PACK_H - 14)

    # ---------------------------------------------------------- events
    def handle(self, ev):
        if self.naming:
            if self.preset_name.handle(ev) and ev.type != pygame.MOUSEBUTTONDOWN:
                if ev.type == pygame.KEYDOWN:
                    if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self.save_preset()
                    elif ev.key == pygame.K_ESCAPE:
                        self.naming = False
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and not self.preset_name.focused:
                self.naming = False
        if self.search.handle(ev):
            return
        for b in self.all:
            if b.visible and b.handle(ev):
                return
        if ev.type == pygame.MOUSEWHEEL:
            if SIDE.collidepoint(ui.mouse_pos()):
                self.side_scroll = max(0.0, min(self.side_max_scroll(), self.side_scroll - ev.y * 40))
            else:
                self.scroll_t = max(0.0, min(self.max_scroll(), self.scroll_t - ev.y * 90))
        elif ev.type == pygame.KEYDOWN and not self.search.focused:
            if ev.key == pygame.K_ESCAPE:
                self.on_done()
            elif ev.key in (pygame.K_PAGEDOWN, pygame.K_DOWN):
                self.scroll_t = min(self.max_scroll(),
                                    self.scroll_t + (LIST.h * 0.8 if ev.key == pygame.K_PAGEDOWN else 60))
            elif ev.key in (pygame.K_PAGEUP, pygame.K_UP):
                self.scroll_t = max(0.0, self.scroll_t - (LIST.h * 0.8 if ev.key == pygame.K_PAGEUP else 60))
            elif ev.key == pygame.K_f and ev.mod & pygame.KMOD_CTRL:
                self.search.focused = True
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            p = V.to_design(ev.pos)
            if SIDE.collidepoint(p):
                self.click_sidebar(p)
                return
            bar = self.scrollbar()
            if bar and bar[0].inflate(16, 0).collidepoint(p):
                track, thumb = bar
                if not thumb.collidepoint(p):
                    frac = (p[1] - track.y - thumb.h / 2) / max(1, track.h - thumb.h)
                    self.scroll_t = self.scroll = max(0.0, min(1.0, frac)) * self.max_scroll()
                self.dragging_bar = (p[1], self.scroll_t)
                return
            row = self.row_at(p)
            if row is None:
                return
            kind = row[0]
            if kind == "pack":
                pk = row[1]
                ry = LIST.y - self.scroll + row[2]
                if self.view_btn_rect(ry).collidepoint(p):
                    self.app.sounds.play("click")
                    self.browse([pk["id"]], pk["name"])
                    return
                self._set([pk["id"]], pk["id"] not in self.sel)
            elif kind in ("group", "section"):
                ids = row[4]
                # Group header: arrow area (left) and name toggle open/closed; only the checkbox selects.
                on_box = (LIST.x + 44 <= p[0] <= LIST.x + 84) if kind == "group" else p[0] <= LIST.x + 40
                if on_box:
                    self._set(ids, not all(i in self.sel for i in ids))
                elif self.filter or kind == "section":
                    pass  # while searching every matching group is forced open
                else:
                    name = row[1]["name"]
                    self.open_target[name] = 0.0 if self.open_target[name] > 0.5 else 1.0
                    self.app.sounds.play("flip")
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self.dragging_bar = None
        elif ev.type == pygame.MOUSEMOTION and self.dragging_bar:
            y0, s0 = self.dragging_bar
            track, thumb = self.scrollbar()
            d = (V.to_design(ev.pos)[1] - y0) / max(1, track.h - thumb.h) * self.max_scroll()
            self.scroll_t = self.scroll = max(0.0, min(self.max_scroll(), s0 + d))

    def click_sidebar(self, p):
        for preset, y in self.preset_rows():
            if y < SIDE.y + 40 or y + PRESET_H > SIDE.bottom - 76:
                continue
            if y <= p[1] < y + PRESET_H:
                if not preset["builtin"] and p[0] > SIDE.right - 40:
                    self.delete_preset(preset["name"])
                else:
                    self.apply_preset(preset)
                return

    def scrollbar(self):
        if self.max_scroll() <= 0:
            return None
        track = pygame.Rect(LIST.right - 8, LIST.y + 4, 6, LIST.h - 8)
        th = max(40, track.h * LIST.h / self.content_h)
        ty = track.y + (track.h - th) * (self.scroll / self.max_scroll())
        return track, pygame.Rect(track.x, ty, track.w, th)

    # ---------------------------------------------------------- update / draw
    def update(self, dt):
        self.t += dt
        self.search.update(dt)
        self.save_btn.visible = not self.naming
        if self.naming:
            self.preset_name.update(dt)
        for b in self.all:
            b.update(dt)
        for k in self.open:
            self.open[k] = ui.approach(self.open[k], self.open_target[k], 14, dt)
        for pid in self.check:
            self.check[pid] = ui.approach(self.check[pid], 1.0 if pid in self.sel else 0.0, 18, dt)
        self.layout()
        self.scroll_t = max(0.0, min(self.max_scroll(), self.scroll_t))
        self.scroll = ui.approach(self.scroll, self.scroll_t, 16, dt)
        m = ui.mouse_pos()
        hovered = self.row_at(m) if not self.dragging_bar else None
        hk = id(hovered[1]) if hovered else None
        for row in self.rows:
            k = id(row[1])
            self.hover[k] = ui.approach(self.hover.get(k, 0.0), 1.0 if k == hk else 0.0, 16, dt)
            if row[0] in ("group", "section"):
                n = sum(1 for i in row[4] if i in self.sel)
                self.gcheck[k] = ui.approach(self.gcheck.get(k, 0.0), 1.0 if n else 0.0, 18, dt)
        self.active_preset = None
        for p in self.presets:
            if set(p["packs"]) == self.sel:
                self.active_preset = p["name"]
                break
        for preset, y in self.preset_rows():
            k = preset["name"]
            on = SIDE.collidepoint(m) and y <= m[1] < y + PRESET_H
            self.preset_hover[k] = ui.approach(self.preset_hover.get(k, 0.0), 1.0 if on else 0.0, 16, dt)

    def draw(self, surf):
        lib = self.app.library
        ui.draw_text(surf, "Card Packs", 40, WHITE, (40, 34), "topleft")
        b, w = lib.counts(self.sel)
        n = len(self.sel)
        ui.draw_text(surf, "Pick a preset, or tick any packs you like - they all get shuffled together.", 15, GRAY,
                     (42, 82), "topleft", bold=False)
        self.search.draw(surf)
        ui.draw_text(surf, "Ctrl+F", 12, DIM, (1228, 63), "midright", bold=False)
        for btn in self.top_btns:
            btn.draw(surf)

        self.draw_sidebar(surf)

        clip = surf.get_clip()
        surf.set_clip(V.rect(LIST))
        top = LIST.y - self.scroll
        for row in self.rows:
            kind, obj, y, h = row[0], row[1], row[2], row[3]
            ry = top + y
            if ry + h < LIST.y - 4 or ry > LIST.bottom + 4:
                continue
            hv = self.hover.get(id(obj), 0.0)
            if kind == "section":
                self._draw_section(surf, row, ry, hv)
            elif kind == "group":
                self._draw_group(surf, row, ry, hv)
            else:
                self._draw_pack(surf, row, ry, hv)
        surf.set_clip(clip)
        if not self.rows:
            ui.draw_text(surf, "No packs match your search.", 20, GRAY, (LIST.centerx, LIST.y + 80))

        bar = self.scrollbar()
        if bar:
            track, thumb = bar
            tr = V.rect(track)
            surf.blit(ui.rounded_px(tr.w, tr.h, tr.w // 2, (40, 40, 46)), tr)
            th = V.rect(thumb)
            surf.blit(ui.rounded_px(th.w, th.h, th.w // 2, (150, 150, 158) if self.dragging_bar else (100, 100, 108)),
                      th)

        label = f"{n} pack{'s' if n != 1 else ''} selected"
        ui.draw_text(surf, label, 22, WHITE, (42, 666), "midleft")
        x = 42 + ui.text_width(label, 22) + 26
        card_icon(surf, x, 667, True)
        tr = ui.draw_text(surf, f"{b:,} black", 16, GRAY, (x + 18, 667), "midleft", bold=False)
        x = (tr.right - V.ox) / V.scale + 18
        card_icon(surf, x, 667, False)
        tr = ui.draw_text(surf, f"{w:,} white", 16, GRAY, (x + 18, 667), "midleft", bold=False)
        if self.active_preset:
            x = (tr.right - V.ox) / V.scale + 22
            ui.draw_text(surf, f"Preset: {self.active_preset}", 16, ACCENT, (x, 667), "midleft")
        if b == 0 or w == 0:
            ui.draw_text(surf, "Pick at least one pack with black and white cards to play.", 14, ACCENT,
                         (42, 694), "midleft", bold=False)
        self.done.draw(surf)

    def draw_sidebar(self, surf):
        ui.draw_panel(surf, SIDE)
        ui.draw_text(surf, "Presets", 18, WHITE, (SIDE.x + 16, SIDE.y + 22), "midleft")
        clip = surf.get_clip()
        surf.set_clip(V.rect((SIDE.x, SIDE.y + 40, SIDE.w, SIDE.h - 40 - 80)))
        for p, y in self.preset_rows():
            if y + PRESET_H < SIDE.y + 30 or y > SIDE.bottom:
                continue
            active = p["name"] == self.active_preset
            hv = self.preset_hover.get(p["name"], 0.0)
            r = V.rect((SIDE.x + 8, y + 2, SIDE.w - 16, PRESET_H - 4))
            if active:
                surf.blit(ui.rounded_px(r.w, r.h, V.s(10), (78, 64, 18)), r)
            elif hv > 0.01:
                surf.blit(ui.rounded_px(r.w, r.h, V.s(10), PANEL_HI, int(255 * round(hv * 4) / 4)), r)
            ui.draw_text(surf, p["name"], 15, ACCENT if active else WHITE, (SIDE.x + 20, y + 15), "midleft")
            b, w = p["counts"]
            ui.draw_text(surf, f"{len(p['packs'])} packs · {b + w:,} cards", 11, GRAY, (SIDE.x + 20, y + 32),
                         "midleft", bold=False)
            if not p["builtin"] and hv > 0.3:
                ui.draw_text(surf, "x", 16, RED, (SIDE.right - 26, y + PRESET_H / 2))
        surf.set_clip(clip)
        hov = next((p for p, y in self.preset_rows() if self.preset_hover.get(p["name"], 0) > 0.5), None)
        if hov and not self.naming:
            ui.draw_text(surf, ui.ellipsize(hov["desc"], 12, SIDE.w - 24, False), 12, DIM,
                         (SIDE.x + 14, SIDE.bottom - 66), "midleft", bold=False)
        if self.naming:
            self.preset_name.draw(surf)
        else:
            self.save_btn.draw(surf)

    def _group_state(self, ids):
        n = sum(1 for i in ids if i in self.sel)
        return 0 if n == 0 else (1 if n == len(ids) else 2), n

    def _draw_section(self, surf, row, ry, hv):
        cat, ids = row[1], row[4]
        state, n = self._group_state(ids)
        ui.draw_checkbox(surf, (LIST.x + 8, ry + 20, 24, 24), state, self.gcheck.get(id(cat), 0.0), hv)
        ui.draw_text(surf, SECTION_LABEL.get(cat, cat).upper(), 17, WHITE, (LIST.x + 46, ry + 32), "midleft")
        ui.draw_text(surf, f"{n} / {len(ids)} packs", 14, GRAY, (LIST.right - 24, ry + 32), "midright",
                     bold=False)
        pygame.draw.line(surf, (60, 60, 68), V.pt(LIST.x + 4, ry + SECTION_H - 4),
                         V.pt(LIST.right - 20, ry + SECTION_H - 4), max(1, V.s(1)))

    def _draw_group(self, surf, row, ry, hv):
        g, ids = row[1], row[4]
        state, n = self._group_state(ids)
        rect = (LIST.x + 4, ry + 2, LIST.w - 28, GROUP_H - 4)
        r = V.rect(rect)
        surf.blit(ui.rounded_px(r.w, r.h, V.s(12), ui.lerp_color(PANEL, PANEL_HI, round(hv * 6) / 6), 240), r)
        openness = 1.0 if self.filter else self.open[g["name"]]
        # Arrow: points right when closed, rotates to point down when open.
        ui.draw_triangle(surf, (LIST.x + 24, ry + GROUP_H / 2), 7, openness * math.pi / 2,
                         WHITE if hv > 0.5 else GRAY)
        ui.draw_checkbox(surf, (LIST.x + 52, ry + 13, 24, 24), state, self.gcheck.get(id(g), 0.0), hv)
        ui.draw_text(surf, ui.ellipsize(g["name"], 18, 420), 18, WHITE, (LIST.x + 92, ry + GROUP_H / 2), "midleft")
        b = sum(self.app.library.by_id[i]["black"] for i in ids)
        w = sum(self.app.library.by_id[i]["white"] for i in ids)
        ui.draw_text(surf, f"{n} / {len(ids)} selected", 14, ACCENT if n else GRAY,
                     (LIST.right - 260, ry + GROUP_H / 2), "midright", bold=False)
        self._counts(surf, LIST.right - 236, ry + GROUP_H / 2, b, w)

    def _draw_pack(self, surf, row, ry, hv):
        p, openness = row[1], row[4]
        if openness < 0.6:
            return
        a = 255 * min(1.0, (openness - 0.6) / 0.4)
        if hv > 0.01:
            r = V.rect((LIST.x + 36, ry + 2, LIST.w - 60, PACK_H - 4))
            surf.blit(ui.rounded_px(r.w, r.h, V.s(10), (255, 255, 255), int(14 * round(hv * 4) / 4)), r)
        on = p["id"] in self.sel
        ui.draw_checkbox(surf, (LIST.x + 74, ry + 9, 22, 22), 1 if on else 0, self.check[p["id"]], hv)
        name = ui.ellipsize(p["name"], 16, LIST.w - 470, bold=False)
        ui.draw_text(surf, name, 16, WHITE if on else (200, 200, 205), (LIST.x + 110, ry + PACK_H / 2), "midleft",
                     bold=False, alpha=a)
        if hv > 0.3:  # "View" pill: peek at this pack's cards
            vr = self.view_btn_rect(ry)
            r = V.rect(vr)
            over = vr.collidepoint(ui.mouse_pos())
            surf.blit(ui.rounded_px(r.w, r.h, r.h // 2, ACCENT if over else (70, 70, 80)), r)
            ui.draw_text(surf, "View", 13, INK if over else WHITE, vr.center)
        self._counts(surf, LIST.right - 236, ry + PACK_H / 2, p["black"], p["white"], a)

    def _counts(self, surf, x, y, b, w, alpha=255):
        card_icon(surf, x, y, True)
        ui.draw_text(surf, f"{b:,}", 14, GRAY, (x + 18, y), "midleft", bold=False, alpha=alpha)
        card_icon(surf, x + 96, y, False)
        ui.draw_text(surf, f"{w:,}", 14, GRAY, (x + 114, y), "midleft", bold=False, alpha=alpha)
