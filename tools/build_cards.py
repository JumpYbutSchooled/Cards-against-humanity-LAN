"""Builds assets/cards/ from the JSON Against Humanity database.

Usage:
    python tools/build_cards.py                # downloads the latest database
    python tools/build_cards.py path/to.json   # uses a local copy of cah-all-full.json

Source: https://github.com/crhallberg/json-against-humanity (CC BY-NC-SA 4.0)
Writes one JSON file per pack, grouped into folders, plus assets/cards/index.json.
"""
import json
import os
import re
import shutil
import sys
import urllib.request

SOURCE_URL = "https://raw.githubusercontent.com/crhallberg/json-against-humanity/latest/cah-all-full.json"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "cards")

# Official pack groups, checked in order; first match wins.
OFFICIAL_GROUPS = [
    ("Base Game", [r"^CAH Base Set$", r"^CAH: Main Deck$", r"Family Edition", r"Conversion Kit"]),
    ("Numbered Expansions", [r"^CAH: (First|Second|Third|Fourth|Fifth|Sixth) Expansion$"]),
    ("Box Expansions", [r"Box Expansion", r"Bundle", r"Procedurally", r"^CAH: (A\.I\.|Human|Ass) Pack$"]),
    ("Holiday Packs", [r"Holiday", r"Seasons Greetings"]),
    ("Promos & Conventions", [r"PAX", r"Gen Con", r"Desert Bus", r"Jack White", r"Retail", r"House of Cards",
                              r"Mass Effect", r"TableTop", r"Reject", r"ClickHole", r"Saves America"]),
    ("Themed Packs", [r".*"]),
]

# Third-party names: strip these suffixes to find the game "family".
FAMILY_SPLIT = re.compile(
    r"(\s*[:\-]\s+.*$)|(,?\s+(Vol\.?|Volume|Edition|Expansion|Episode|#)\s*.*$)|(\s+\d+$)|(\s+Bonus Cards.*$)",
    re.IGNORECASE)
FAMILY_ALIASES = {
    "Cads About Matrimony Poly Pack": "Cads About Matrimony",
    "Cows Grilling Hamburgers": "Cows Against Hamburgers",
    "Cols Despite Kentucky": "Cols Against Kentucky",
    "Kiwis Versus Morality": "Kiwis Against Morality",
    "Carps & Angsty Manatee": "Carbs of the Huge Manatee",
    "Humanity Hates the Holidays \"Love\"": "Humanity Hates The Holidays",
    "Personally Incorrect - Expansion": "Personally Incorrect",
    "That's What She Said Game": "That's What She Said",
    "Trumped UpCards": "Trumped UpCards",
    "Pax East 2013 Promo Pack A": None,  # an official promo, mislabelled upstream
}


def official_group(name):
    for group, patterns in OFFICIAL_GROUPS:
        if any(re.search(p, name) for p in patterns):
            return group
    return "Themed Packs"


def family_of(name):
    for k, v in FAMILY_ALIASES.items():
        if name.startswith(k) and v:
            return v
    fam = FAMILY_SPLIT.sub("", name).strip(" ,:-")
    fam = re.sub(r"\s+(Pack|Deck)$", "", fam)
    return fam or name


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:90]


def clean(text):
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.replace("\r", "").split("\n")]
    return "\n".join(ln for ln in lines if ln) if any(lines) else ""


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            packs = json.load(f)
    else:
        print("Downloading", SOURCE_URL)
        with urllib.request.urlopen(SOURCE_URL) as r:
            packs = json.loads(r.read().decode("utf-8"))

    # Fix the one official promo that upstream marks unofficial.
    for p in packs:
        if FAMILY_ALIASES.get(p["name"], 1) is None:
            p["official"] = True

    third = [p for p in packs if not p.get("official")]
    fam_counts = {}
    for p in third:
        fam_counts[family_of(p["name"])] = fam_counts.get(family_of(p["name"]), 0) + 1

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    index = []
    used = set()
    for i, p in enumerate(packs):
        official = bool(p.get("official"))
        if official:
            category, group = "Official", official_group(p["name"])
        else:
            fam = family_of(p["name"])
            category = "Third-Party"
            group = fam if fam_counts[fam] > 1 else "Other Third-Party Games"
        white = [clean(c["text"]) for c in p["white"]]
        black = [{"text": clean(c["text"]), "pick": max(1, int(c.get("pick", 1)))} for c in p["black"]]
        white = [t for t in white if t]
        black = [c for c in black if c["text"]]
        if not white and not black:
            continue

        folder = os.path.join(OUT, category, safe_filename(group))
        os.makedirs(folder, exist_ok=True)
        base = safe_filename(p["name"])
        fname = base
        n = 2
        while (category, group, fname.lower()) in used:
            fname = f"{base} ({n})"
            n += 1
        used.add((category, group, fname.lower()))
        rel = "/".join([category, safe_filename(group), fname + ".json"])
        with open(os.path.join(OUT, *rel.split("/")), "w", encoding="utf-8") as f:
            json.dump({"name": p["name"], "official": official, "category": category, "group": group,
                       "black": black, "white": white}, f, ensure_ascii=False, indent=1)
        index.append({"id": f"p{i:03d}", "name": p["name"], "official": official, "category": category,
                      "group": group, "file": rel, "black": len(black), "white": len(white)})

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"source": "JSON Against Humanity (github.com/crhallberg/json-against-humanity)",
                   "license": "CC BY-NC-SA", "packs": index}, f, ensure_ascii=False, indent=1)

    tb = sum(p["black"] for p in index)
    tw = sum(p["white"] for p in index)
    print(f"{len(index)} packs, {tb} black, {tw} white cards -> {OUT}")
    groups = {}
    for p in index:
        groups.setdefault((p["category"], p["group"]), []).append(p["name"])
    for (cat, g), names in sorted(groups.items()):
        print(f"  [{cat}] {g}: {len(names)}")


if __name__ == "__main__":
    main()
