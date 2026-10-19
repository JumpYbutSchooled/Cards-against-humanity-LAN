"""Card library: loads assets/cards, builds decks, fills in black cards."""
import json
import os
import random
import re

OFFICIAL_ORDER = ["Base Game", "Numbered Expansions", "Box Expansions", "Themed Packs", "Holiday Packs",
                  "Promos & Conventions"]
OTHER_GROUP = "Other Third-Party Games"
ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"]
BLANK = "_"


class Library:
    def __init__(self, root):
        self.root = root
        with open(os.path.join(root, "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        self.packs = idx["packs"]
        for p in self.packs:
            p["id"] = p["file"]
        self.by_id = {p["id"]: p for p in self.packs}
        self._loaded = {}

        groups = {}
        for p in self.packs:
            groups.setdefault((p["category"], p["group"]), []).append(p)

        def key(k):
            cat, g = k
            if cat == "Mixes":  # themed packs built from every pack go first
                return (0, 0, g.lower())
            if cat == "Official":
                return (1, OFFICIAL_ORDER.index(g) if g in OFFICIAL_ORDER else 99, g)
            return (2, 1 if g == OTHER_GROUP else 0, g.lower())

        self.groups = []
        for k in sorted(groups, key=key):
            packs = groups[k]
            if k == ("Official", "Numbered Expansions"):
                packs.sort(key=lambda p: next((i for i, o in enumerate(ORDINALS) if o in p["name"]), 99))
            elif k != ("Official", "Base Game"):
                packs.sort(key=lambda p: p["name"].lower())
            self.groups.append({"category": k[0], "name": k[1], "packs": packs})

    def find(self, name):
        for p in self.packs:
            if p["name"] == name:
                return p
        return None

    def migrate_ids(self, ids):
        """Maps saved pack ids from older versions (long file names got shortened) onto current ones."""
        out = []
        for pid in ids:
            if pid in self.by_id:
                out.append(pid)
                continue
            folder, _, base = pid.rpartition("/")
            base = base[:-5] if base.endswith(".json") else base
            best = None
            for p in self.packs:
                pf, _, pb = p["id"].rpartition("/")
                pb = pb[:-5]
                if pf == folder and base.startswith(pb) and (best is None or len(pb) > len(best[1])):
                    best = (p["id"], pb)
            if best and best[0] not in out:
                out.append(best[0])
        return out

    def default_selection(self):
        base = self.find("CAH Base Set")
        return [base["id"]] if base else [self.packs[0]["id"]]

    def load(self, pack_id):
        data = self._loaded.get(pack_id)
        if data is None:
            p = self.by_id[pack_id]
            with open(os.path.join(self.root, *p["file"].split("/")), encoding="utf-8") as f:
                data = json.load(f)
            self._loaded[pack_id] = data
        return data

    def counts(self, ids):
        ids = [i for i in ids if i in self.by_id]
        return (sum(self.by_id[i]["black"] for i in ids), sum(self.by_id[i]["white"] for i in ids))

    def build(self, ids):
        """Returns (black_cards, white_cards), duplicates across packs removed."""
        black, white = [], []
        seen_b, seen_w = set(), set()
        for pid in ids:
            if pid not in self.by_id:
                continue
            data = self.load(pid)
            name = data["name"]
            for c in data["black"]:
                k = _norm(c["text"])
                if k not in seen_b:
                    seen_b.add(k)
                    black.append(BlackCard(c["text"], c.get("pick", 1), name))
            for t in data["white"]:
                k = _norm(t)
                if k not in seen_w:
                    seen_w.add(k)
                    white.append(WhiteCard(t, name))
        return black, white


def _norm(t):
    return re.sub(r"[^a-z0-9]+", "", t.lower())


class BlackCard:
    __slots__ = ("text", "pick", "pack")

    def __init__(self, text, pick, pack):
        self.text, self.pick, self.pack = text, max(1, pick), pack

    @property
    def display(self):
        return re.sub(r"_+", "______", self.text)


class WhiteCard:
    __slots__ = ("text", "pack")

    def __init__(self, text, pack):
        self.text, self.pack = text, pack


class Deck:
    def __init__(self, cards):
        self.cards = list(cards)
        random.shuffle(self.cards)
        self.discards = []

    def draw(self, n=1):
        out = []
        for _ in range(n):
            if not self.cards:
                if not self.discards:
                    break
                self.cards = self.discards
                self.discards = []
                random.shuffle(self.cards)
            out.append(self.cards.pop())
        return out

    def discard(self, cards):
        self.discards.extend(cards)

    def __len__(self):
        return len(self.cards) + len(self.discards)


def _answer_for_blank(text):
    t = text.strip()
    if t.endswith(".") and not t.endswith("..."):
        t = t[:-1]
    return t


def fill(black_text, answers, base, accent):
    """Black card text with answers dropped into the blanks, as rich-text segments."""
    parts = re.split(r"_+", black_text)
    blanks = len(parts) - 1
    segs = []
    if blanks == 0:
        segs.append((black_text, base))
        for a in answers:
            segs.append(("\n", base))
            segs.append((a, accent))
        if not answers:
            segs.append(("\n______", base))
        return segs
    ai = 0
    for i, part in enumerate(parts):
        if part:
            segs.append((part, base))
        if i < blanks:
            if ai < len(answers):
                a = answers[ai]
                # Keep the answer's own punctuation if the blank ends the sentence.
                rest = parts[i + 1].strip() if i + 1 < len(parts) else ""
                segs.append((a.strip() if rest == "" and i == blanks - 1 else _answer_for_blank(a), accent))
                ai += 1
            else:
                segs.append(("______", base))
    for a in answers[ai:]:
        segs.append(("\n", base))
        segs.append((a, accent))
    return segs
