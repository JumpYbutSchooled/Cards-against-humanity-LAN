"""Authoritative game rules. Runs on the host (or locally for hot-seat play).

Clients never touch this directly: they get per-player snapshots from view()
and send actions to act(). Every change bumps `version` so hosts know when to
broadcast.
"""
import random

from .cards import Deck
from .presets import match_name

INTRO_TIME = 2.2
BOT_PLAY_DELAY = (0.8, 2.6)
AWAY_PLAY_DELAY = 6.0
BOT_REVEAL_GAP = 0.85
BOT_THINK = 1.3
RESULT_AUTO_NEXT = 6.0  # only when nobody human is around to press "next"
MIN_PLAYERS = 3
MAX_PLAYERS = 10


def _card(c):
    return {"t": c.text, "p": c.pack}


class Engine:
    def __init__(self, library, packs, points=7, hand_size=10, local=False):
        self.lib = library
        self.packs = list(packs)
        self.preset = match_name(library, self.packs)
        self.goal = points
        self.hand_size = hand_size
        self.local = local  # hot-seat: anyone at the screen may press "next"
        self.players = []
        self._next_id = 1
        self.phase = "lobby"
        self.t = 0.0
        self.round = 0
        self.czar = None
        self.black = None
        self.played = {}  # pid -> [cards] this round
        self.round_pids = set()
        self.subs = []  # [{"pid", "cards", "revealed"}] in judging order
        self.focus = None
        self.reading = None
        self.winner = None
        self.final = False
        self.bot_due = {}
        self.judge_due = 0.0
        self.version = 0
        self.black_deck = None
        self.white_deck = None

    # ------------------------------------------------------------ players
    def touch(self):
        self.version += 1

    def get(self, pid):
        return next((p for p in self.players if p["id"] == pid), None)

    def auto(self, p):
        return p["bot"] or p["away"]

    def unique_name(self, name):
        name = (name or "Player").strip()[:18] or "Player"
        taken = {p["name"].lower() for p in self.players}
        if name.lower() not in taken:
            return name
        i = 2
        while f"{name} {i}".lower() in taken:
            i += 1
        return f"{name} {i}"

    def add_player(self, name, bot=False, host=False):
        if len(self.players) >= MAX_PLAYERS:
            return None
        p = {"id": self._next_id, "name": self.unique_name(name), "bot": bot, "host": host, "away": False,
             "score": 0, "hand": []}
        self._next_id += 1
        self.players.append(p)
        if self.phase != "lobby" and self.white_deck:
            p["hand"] = self.white_deck.draw(self.hand_size)  # late joiner plays from next round
        self.touch()
        return p["id"]

    def remove_player(self, pid):
        p = self.get(pid)
        if not p:
            return
        if self.phase == "lobby":
            self.players.remove(p)
        else:
            p["away"] = True
            self.bot_due.setdefault(pid, self.t + AWAY_PLAY_DELAY)
        self.touch()

    def set_away(self, pid, away):
        p = self.get(pid)
        if p and p["away"] != away:
            p["away"] = away
            if away:
                self.bot_due[pid] = self.t + AWAY_PLAY_DELAY
            self.touch()

    def configure(self, packs=None, points=None, hand=None, preset=None):
        if packs is not None:
            self.packs = list(packs)
            self.preset = preset if preset is not None else match_name(self.lib, self.packs)
            if self.phase != "lobby":
                self.rebuild_decks()
        if points is not None:
            self.goal = points
        if hand is not None:
            self.hand_size = hand
        self.touch()

    def rebuild_decks(self):
        """Mid-game pack change: new draw piles from the new packs, minus cards already in play."""
        if not self.black_deck:
            return False
        black, white = self.lib.build(self.packs)
        in_play = {c.text for p in self.players for c in p["hand"]}
        in_play |= {c.text for cards in self.played.values() for c in cards}
        white = [c for c in white if c.text not in in_play]
        black = [c for c in black if not self.black or c.text != self.black.text]
        if not black or len(white) < len(self.players) * 3:
            return False  # not playable - keep the old piles
        self.black_deck, self.white_deck = Deck(black), Deck(white)
        self.touch()
        return True

    def deck_counts(self):
        return self.lib.counts(self.packs)

    def start_problem(self):
        if len(self.players) < MIN_PLAYERS:
            return f"Need at least {MIN_PLAYERS} players (add bots?)"
        b, w = self.deck_counts()
        if b == 0:
            return "Selected packs have no black cards"
        if w < len(self.players) * (self.hand_size + 3):
            return "Not enough white cards - add packs"
        return None

    # ------------------------------------------------------------ flow
    def start(self):
        if self.start_problem():
            return False
        black, white = self.lib.build(self.packs)
        self.black_deck, self.white_deck = Deck(black), Deck(white)
        for p in self.players:
            p["score"] = 0
            p["hand"] = []
        self.round = 0
        self.czar = None
        self.final = False
        self.new_round()
        return True

    def to_lobby(self):
        for p in list(self.players):
            if p["away"]:
                self.players.remove(p)
        for p in self.players:
            p["score"] = 0
            p["hand"] = []
        self.phase = "lobby"
        self.black = None
        self.subs = []
        self.played = {}
        self.touch()

    def set_phase(self, ph):
        self.phase = ph
        self.t = 0.0
        self.touch()

    def new_round(self):
        self.round += 1
        ids = [p["id"] for p in self.players]
        if self.czar in ids:
            self.czar = ids[(ids.index(self.czar) + 1) % len(ids)]
        else:
            self.czar = random.choice(ids)
        self.black = self.black_deck.draw(1)[0]
        pick = self.black.pick
        for p in self.players:
            need = self.hand_size - len(p["hand"])
            if need > 0:
                p["hand"].extend(self.white_deck.draw(need))
            if pick >= 3 and p["id"] != self.czar:
                p["hand"].extend(self.white_deck.draw(pick - 1))
        self.played = {}
        self.subs = []
        self.focus = None
        self.winner = None
        self.round_pids = set(ids)
        self.set_phase("intro")

    def required(self):
        return [p for p in self.players if p["id"] in self.round_pids and p["id"] != self.czar]

    def tick(self, dt):
        if self.phase == "lobby":
            return
        self.t += dt
        if self.phase == "intro" and self.t >= INTRO_TIME:
            self.set_phase("play")
            for p in self.required():
                lo, hi = BOT_PLAY_DELAY
                self.bot_due[p["id"]] = random.uniform(lo, hi) if p["bot"] else AWAY_PLAY_DELAY
        elif self.phase == "play":
            for p in self.required():
                if self.auto(p) and p["id"] not in self.played and self.t >= self.bot_due.get(p["id"], 0):
                    n = min(self.black.pick, len(p["hand"]))
                    self._submit(p, random.sample(range(len(p["hand"])), n))
            if all(p["id"] in self.played for p in self.required()):
                self._begin_judging()
        elif self.phase == "judge":
            czar = self.get(self.czar)
            if czar is None or self.auto(czar):
                self._auto_judge()
        elif self.phase == "result":
            humans = [p for p in self.players if not self.auto(p)]
            if not humans and self.t > RESULT_AUTO_NEXT:
                self._next()

    def _submit(self, p, idxs):
        cards = [p["hand"][i] for i in idxs]
        for c in cards:
            p["hand"].remove(c)
        self.played[p["id"]] = cards
        self.touch()

    def _begin_judging(self):
        order = list(self.played.items())
        random.shuffle(order)
        self.subs = [{"pid": pid, "cards": cards, "revealed": False} for pid, cards in order]
        self.reading = None
        self.judge_due = 2.0  # a moment to read the black card out loud first
        self.set_phase("judge")

    def _auto_judge(self):
        if self.t < self.judge_due or not self.subs:
            return
        hidden = [s for s in self.subs if not s["revealed"]]
        if hidden:
            hidden[0]["revealed"] = True
            self.reading = self.subs.index(hidden[0])
            self.judge_due = self.t + BOT_REVEAL_GAP + 0.6 + 0.4 * len(hidden[0]["cards"])  # time to read it
            self.touch()
        elif self.focus is None:
            self.focus = random.randrange(len(self.subs))
            self.reading = self.focus
            self.judge_due = self.t + BOT_THINK
            self.touch()
        else:
            self._award(self.focus)

    def _award(self, i):
        s = self.subs[i]
        p = self.get(s["pid"])
        if p:
            p["score"] += 1
        self.winner = i
        self.focus = i
        self.reading = i
        self.final = bool(p and p["score"] >= self.goal)
        for sub in self.subs:
            self.white_deck.discard(sub["cards"])
        self.black_deck.discard([self.black])
        self.set_phase("result")

    def _next(self):
        if self.final:
            self.set_phase("gameover")
        else:
            self.new_round()

    def can_next(self, pid):
        if self.phase != "result":
            return False
        czar = self.get(self.czar)
        p = self.get(pid)
        return self.local or (p is not None and (pid == self.czar or p["host"] or czar is None or self.auto(czar)))

    # ------------------------------------------------------------ actions
    def act(self, pid, a):
        """Applies a player's action. Returns True if it was accepted."""
        kind = a.get("a")
        p = self.get(pid)
        if p is None or (a.get("round") is not None and a.get("round") != self.round):
            return False
        if kind == "submit" and self.phase == "play":
            if pid == self.czar or pid in self.played or pid not in self.round_pids:
                return False
            idxs = a.get("cards", [])
            need = min(self.black.pick, len(p["hand"]))
            if len(idxs) != need or len(set(idxs)) != need or not all(
                    isinstance(i, int) and 0 <= i < len(p["hand"]) for i in idxs):
                return False
            self._submit(p, idxs)
            return True
        if pid != self.czar and kind in ("reveal", "reveal_all", "focus", "award"):
            return False
        if self.phase == "judge":
            i = a.get("i")
            valid = isinstance(i, int) and 0 <= i < len(self.subs)
            # "reading" is the answer the Czar is reading out right now; everyone's screen shows it in sync.
            if kind == "reveal" and valid and not self.subs[i]["revealed"]:
                self.subs[i]["revealed"] = True
                self.reading = i
                self.touch()
                return True
            if kind == "reveal_all":
                for s in self.subs:
                    s["revealed"] = True
                self.touch()
                return True
            if kind == "focus" and valid and self.subs[i]["revealed"]:
                self.focus = i
                self.reading = i
                self.touch()
                return True
            if kind == "award" and valid and all(s["revealed"] for s in self.subs):
                self._award(i)
                return True
        if kind == "next" and self.can_next(pid):
            self._next()
            return True
        return False

    # ------------------------------------------------------------ snapshots
    def view(self, pid=None):
        me = self.get(pid)
        show_owner = self.phase in ("result", "gameover")
        subs = []
        if self.phase in ("judge", "result"):
            for s in self.subs:
                subs.append({"n": len(s["cards"]),
                             "cards": [_card(c) for c in s["cards"]] if s["revealed"] else None,
                             "pid": s["pid"] if show_owner else None})
        b, w = self.deck_counts()
        return {
            "phase": self.phase,
            "round": self.round,
            "goal": self.goal,
            "hand_size": self.hand_size,
            "czar": self.czar,
            "black": {"t": self.black.text, "pick": self.black.pick, "p": self.black.pack} if self.black else None,
            "players": [{"id": p["id"], "name": p["name"], "bot": p["bot"], "host": p["host"], "away": p["away"],
                         "score": p["score"], "played": p["id"] in self.played,
                         "in_round": p["id"] in self.round_pids} for p in self.players],
            "hand": [_card(c) for c in me["hand"]] if me else [],
            "mine": [_card(c) for c in self.played.get(pid, [])],
            "subs": subs,
            "focus": self.focus,
            "reading": self.reading,
            "winner": self.winner,
            "final": self.final,
            "can_next": self.can_next(pid) if pid is not None else self.local,
            "config": {"points": self.goal, "hand": self.hand_size, "packs": len(self.packs), "black": b,
                       "white": w, "preset": self.preset},
            "ver": self.version,
        }
