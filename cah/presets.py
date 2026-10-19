"""Card pack presets. Built-ins are defined by pack names so they survive card database rebuilds.

Family / 18+ lists were picked by name and checked against a profanity scan of every pack.
"""

CONVERSIONS = ("Conversion Kit",)
FAMILY = ("CAH: Family Edition", "Kids Against Maturity", "Kids Create Absurdity", "Not Parent Approved",
          "Cards Against Profanity", "The Catholic Card Game")
CLASSIC = ("CAH Base Set", "CAH: First Expansion", "CAH: Second Expansion", "CAH: Third Expansion",
           "CAH: Fourth Expansion", "CAH: Fifth Expansion", "CAH: Sixth Expansion", "CAH: Red Box Expansion",
           "CAH: Blue Box Expansion", "CAH: Green Box Expansion", "Absurd Box Expansion", "CAH: Box Expansion")
FILTHY = ("CAH: Ass Pack", "Weed Pack", "Period Pack", "CAH: College Pack", "Dirty Nasty Filthy", "Depravity",
          "Dick", "Cocks Abreast Hostility", "Carbs of the Huge Manatee - Kink", "Carbs of the Huge Manatee - Online",
          "Carps & Angsty Manatee", "Evil Apples", "Personally Incorrect", "Skewered And Roasted",
          "WTF Did You Say", "Hilarious!", "Cads About Matrimony", "Cads Against Adulting", "Cads About Maternity",
          "Charlie Foxtrot", "Potheads Against Sanity", "Rotten Apples", "The Game Without Decency",
          "That's What She Said", "KinderPerfect: Naughty", "Cakes Athirst Hilarity", "Pigs Against Profanity",
          "Guards Against Insanity", "Words Against Morality", "Crows Adopt Vulgarity", "Cows Against Hamburgers")

BUILTIN = [
    ("Classic", "The base game and the main expansions"),
    ("Party", "Everything except family packs and conversion kits"),
    ("18+ Filthy", "Classic plus the dirtiest packs"),
    ("Family", "Clean packs - fine for kids and grandparents"),
    ("All Official", "Every official CAH pack"),
    ("Everything", "All 205 packs, no exceptions"),
    ("Base Game", "Just the CAH base set"),
]


def _match(name, prefixes):
    return any(name == p or name.startswith(p) for p in prefixes)


def builtin(lib):
    packs = lib.packs
    family = {p["id"] for p in packs if _match(p["name"], FAMILY)}
    conv = {p["id"] for p in packs if _match(p["name"], CONVERSIONS)}
    classic = [p["id"] for p in packs if p["name"] in CLASSIC]
    filthy = {p["id"] for p in packs if _match(p["name"], FILTHY)}
    ids = {
        "Classic": classic,
        "Party": [p["id"] for p in packs if p["id"] not in family | conv],
        "18+ Filthy": [p["id"] for p in packs if p["id"] in filthy or p["id"] in classic],
        "Family": [p["id"] for p in packs if p["id"] in family],
        "All Official": [p["id"] for p in packs if p["official"] and p["id"] not in family | conv],
        "Everything": [p["id"] for p in packs],
        "Base Game": lib.default_selection(),
    }
    return [{"name": n, "desc": d, "packs": ids[n], "builtin": True} for n, d in BUILTIN]


def all_presets(lib, settings):
    custom = [{"name": c["name"], "desc": f"Your preset - {len(c['packs'])} packs", "packs": lib.migrate_ids(c["packs"]),
               "builtin": False} for c in settings.get("presets", [])]
    return builtin(lib) + custom


def match_name(lib, packs, settings=None):
    """Name of the preset exactly matching this selection, or None."""
    sel = set(packs)
    for p in (all_presets(lib, settings) if settings else builtin(lib)):
        if set(p["packs"]) == sel:
            return p["name"]
    return None
