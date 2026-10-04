"""Draw the 100 CloudPunks and the seed data that describes them (DESIGN.md 16.3, ADR-20).

    python3 -m cloudpunks.generate render           # the SVGs and local/seed/cloudpunks.json
    python3 -m cloudpunks.generate check            # exit 1 if those files are stale
    python3 -m cloudpunks.generate roster --seed N  # draw a new roster.json, then render and review

(with ``PYTHONPATH=scripts``; ``make cloudpunks`` renders and ``make lint`` runs the check.)

Each CloudPunk is a 24x24 grid: a base head (male, female, zombie, ape or alien, in one of four skin
tones for the human heads) with trait layers painted over it in a fixed order. The trait pixels are
in ``traits.json``; which traits each CloudPunk has, and its mint price, are in ``roster.json``.
Both are committed, so rendering is deterministic: the same inputs give byte-identical SVGs, and
#0001 is exactly the design the owner approved.

The SVGs have no background: the UI colours each tile by its market state (DESIGN.md 16.1).
Standard library only.
"""

import argparse
import json
import random
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRAITS = HERE / "traits.json"
ROSTER = HERE / "roster.json"
COLLECTION = ROOT / "nft-collection"
SEED_DATA = ROOT / "local" / "seed" / "cloudpunks.json"

SIZE = 24
COUNT = 100
CURRENCY = "ETH"
CENT = Decimal("0.01")

_ = "........................"
MALE = [_] * 5 + [
    "........KKKKKKK.........",
    ".......KSSSSSSSK........",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSBBSSSBBK.......",
    ".....KSSSKESSSKEK.......",
    ".....KSSSSSSSSSSK.......",
    ".....KKSSSSSSSSSK.......",
    "......KSSSSSKKSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSKKKSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSK........",
    "......KSSSKKKKK.........",
    "......KSSSK.............",
    "......KSSSK.............",
]
FEMALE = [_] * 8 + [
    "..........KKKKK.........",
    ".........KSSSSSK........",
    "........KSSSSSSSK.......",
    ".......KSSSSSSSSK.......",
    "......KSSBBSSSBBK.......",
    "......KSSKESSSKEK.......",
    ".....KSKSSSSSSSSK.......",
    "......KKSSSSSSSSK.......",
    ".......KSSSSKSSSK.......",
    ".......KSSSSSSSSK.......",
    ".......KSSSKKKSSK.......",
    "........KSSSSSSK........",
    "........KSKSSSK.........",
    "........KSSKKK..........",
    "........KSSSK...........",
    "........KSSSK...........",
]
ZOMBIE = [_] * 5 + [
    "........KKKKKKK.........",
    ".......KSSSSSSSK........",
    "......KSSHSSSSSSK.......",
    "......KSHSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSBBSSSBBK.......",
    ".....KSSSRKSSSRKK.......",
    ".....KSSSBSSSSBSK.......",
    ".....KKSSSSSSSSSK.......",
    "......KSSSSSKKSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSKKKSSK.......",
    "......KSSSSBSSSSK.......",
    "......KSSSSSSSSK........",
    "......KSSSKKKKK.........",
    "......KSSSK.............",
    "......KSSSK.............",
]
APE = [_] * 5 + [
    "........KKKKKKK.........",
    ".......KFFFFFFFK........",
    "......KFFFFFFFFFK.......",
    "......KFFFFFFFFFK.......",
    "......KFFFFFFFFFK.......",
    "......KFDDDDDDDDK.......",
    "......KKKKKKKKKKK.......",
    ".....KKFDKKDDDKKK.......",
    ".....KFFDKKDDDKKK.......",
    ".....KKFDDDDDDDDK.......",
    "......KFFDDKDKDDK.......",
    "......KFFFDDDDDFK.......",
    "......KFFDDDDDDDK.......",
    "......KFKDKKKKKDK.......",
    "......KFKDDDDDDDK.......",
    "......KFFKDDDDDK........",
    "......KFFFKKKKK.........",
    "......KFFFK.............",
    "......KFFFK.............",
]
ALIEN = [_] * 5 + [
    "........KKKKKKK.........",
    ".......KSSSSSSSK........",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSSK.......",
    ".....KKSSBKSSSBKK.......",
    "....KSESSKESSSKEK.......",
    ".....KSSSSSSSSSSK.......",
    ".....KKSSSSSESSSK.......",
    "......KSSSSSESSSK.......",
    "......KSSSSSESSSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSKKKKKSK.......",
    "......KSSSSSSSSSK.......",
    "......KSSSSSSSSK........",
    "......KSSSKKKKK.........",
    "......KSSSK.............",
    "......KSSSK.............",
]

# Skin (S), brow (B) and eye (E) for the human heads; the approved #0001 is "medium".
SKINS = {
    "albino": {"S": "#ead9d9", "B": "#a28d89", "E": "#c6b2b0"},
    "light": {"S": "#dbb180", "B": "#9f6f32", "E": "#cb9e64"},
    "medium": {"S": "#ae8b61", "B": "#815923", "E": "#a17d49"},
    "dark": {"S": "#713f1d", "B": "#532701", "E": "#6c380e"},
}
TYPES = {
    "male": (MALE, None),
    "female": (FEMALE, None),
    "zombie": (ZOMBIE, {"S": "#7da269", "B": "#657050", "H": "#a3bb89", "R": "#ea311b"}),
    "ape": (APE, {"F": "#35230b", "D": "#836f53"}),
    "alien": (ALIEN, {"S": "#c8fbfb", "B": "#88bbba", "E": "#abdede"}),
}
BLACK = "#000000"
# A trait pixel can be the wearer's own skin, brow or eye colour showing through (between curls,
# under a brim, the shade of a beard). Apes have fur and face colours instead, zombies no eye shade.
TOKENS = ("S", "B", "E")
TOKEN_FALLBACK = {"S": ("D",), "B": ("F",), "E": ("B", "D")}

# Paint order: later layers cover earlier ones (eyewear over hair, a cigarette over a beard).
SLOT_ORDER = ("beard", "lips", "mole", "head", "nose", "eyes", "mouth", "neck", "earring")

Pixel = tuple[str, float] | None
Grid = list[list[Pixel]]


def load_traits(path: Path = TRAITS) -> dict[str, dict]:
    return json.loads(path.read_text())


def load_roster(path: Path = ROSTER) -> list[dict]:
    return json.loads(path.read_text())


def variant_for(kind: str) -> str:
    """Zombies, apes and aliens share the male head shape, so they wear the male layers."""
    return "female" if kind == "female" else "male"


def compose(punk: dict, traits: dict[str, dict]) -> Grid:
    base, palette = TYPES[punk["type"]]
    colours = dict(palette or SKINS[punk["skin"]])
    colours["K"] = BLACK
    grid: Grid = [[(colours[ch], 1.0) if ch != "." else None for ch in row] for row in base]
    chosen = {traits[name]["slot"]: name for name in punk["traits"]}
    variant = variant_for(punk["type"])
    for slot in SLOT_ORDER:
        name = chosen.get(slot)
        if name is None:
            continue
        for cell in traits[name]["variants"][variant]:
            r, c, colour = cell[0], cell[1], cell[2]
            opacity = float(cell[3]) if len(cell) > 3 else 1.0
            if colour in TOKENS:
                colour = next(colours[k] for k in (colour, *TOKEN_FALLBACK[colour]) if k in colours)
            grid[r][c] = None if colour is None else (colour, opacity)
    return grid


def to_svg(number: int, grid: Grid) -> str:
    rects = []
    for y, row in enumerate(grid):
        x = 0
        while x < SIZE:
            pixel = row[x]
            if pixel is None:
                x += 1
                continue
            run = 1
            while x + run < SIZE and row[x + run] == pixel:
                run += 1
            fill, opacity = pixel
            extra = f' fill-opacity="{opacity}"' if opacity != 1.0 else ""
            rects.append(f'<rect x="{x}" y="{y}" width="{run}" height="1" fill="{fill}"{extra}/>')
            x += run
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="480" height="480" '
        'shape-rendering="crispEdges">\n'
        f"<title>#{number:04d}</title>\n" + "\n".join(rects) + "\n</svg>\n"
    )


# How attributes read in a description: hair or hat first, then the face, then accessories.
DISPLAY_ORDER = ("head", "eyes", "beard", "lips", "mouth", "nose", "mole", "neck", "earring")


def describe(punk: dict, traits: dict[str, dict]) -> str:
    """The product description: the type, then the attributes (DESIGN.md 16.3)."""
    kind = punk["type"].capitalize()
    names = sorted(punk["traits"], key=lambda n: DISPLAY_ORDER.index(traits[n]["slot"]))
    return f"{kind} · {', '.join(names)}" if names else kind


def seed_record(punk: dict, traits: dict[str, dict]) -> dict:
    number = punk["id"]
    return {
        "sku": f"CP-{number:04d}",
        "name": f"CloudPunk #{number:04d}",
        "category": punk["type"],
        "description": describe(punk, traits),
        "price": punk["price"],
        "currency": CURRENCY,
    }


def render(
    roster: list[dict], traits: dict[str, dict], out: Path = COLLECTION, seed: Path = SEED_DATA
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for punk in roster:
        (out / f"{punk['id']:04d}.svg").write_text(to_svg(punk["id"], compose(punk, traits)))
    seed.write_text(
        json.dumps([seed_record(p, traits) for p in roster], indent=2, ensure_ascii=False) + "\n"
    )


# -- drawing a roster ------------------------------------------------------------------------------

# How many of each type (rarity), and the approved design, which is always #0001.
TYPE_COUNTS = {"male": 60, "female": 30, "zombie": 6, "ape": 3, "alien": 1}
FIRST = {
    "id": 1,
    "type": "male",
    "skin": "medium",
    "traits": ["Mohawk Thin", "Classic Shades", "Cigarette", "Earring"],
}
# Chance that a CloudPunk has a trait in each slot (some slots only exist for some heads).
SLOT_CHANCE = {
    "head": 0.92,
    "eyes": 0.40,
    "mouth": 0.22,
    "beard": 0.35,
    "lips": 0.55,
    "earring": 0.30,
    "neck": 0.08,
    "nose": 0.05,
    "mole": 0.08,
}
NO_BEARD = {"female", "ape", "alien"}
# At least three traits each: simple one- or two-trait combinations are the ones most likely to
# repeat an existing punk by accident, so the roster never draws them.
MIN_TRAITS = 3
PRICE_RANGE = {
    "male": (15, 40),
    "female": (15, 40),
    "zombie": (60, 90),
    "ape": (120, 160),
    "alien": (180, 200),
}


def _options(traits: dict[str, dict], slot: str, kind: str) -> list[str]:
    variant = variant_for(kind)
    return sorted(n for n, t in traits.items() if t["slot"] == slot and variant in t["variants"])


def draw_roster(traits: dict[str, dict], seed: int) -> list[dict]:
    rng = random.Random(seed)  # noqa: S311 - reproducible art from a seed, not a secret
    kinds = [k for k, n in TYPE_COUNTS.items() for _ in range(n)]
    kinds.remove("male")  # #0001 is the approved male
    rng.shuffle(kinds)
    roster = [dict(FIRST)]
    seen = {("male", "medium", tuple(sorted(FIRST["traits"])))}
    for number, kind in enumerate(kinds, start=2):
        while True:
            skin = rng.choice(sorted(SKINS)) if kind in ("male", "female") else None
            picked = []
            for slot in SLOT_ORDER:
                if slot == "beard" and kind in NO_BEARD:
                    continue
                options = _options(traits, slot, kind)
                chance = 1.0 if (slot == "head" and kind == "female") else SLOT_CHANCE[slot]
                if options and rng.random() < chance:
                    picked.append(rng.choice(options))
            key = (kind, skin, tuple(sorted(picked)))
            if len(picked) >= MIN_TRAITS and key not in seen:
                seen.add(key)
                break
        punk = {"id": number, "type": kind, "traits": picked}
        if skin:
            punk["skin"] = skin
        roster.append(punk)
    for punk in roster:
        low, high = PRICE_RANGE[punk["type"]]
        cents = rng.randint(low * 100, high * 100) + 250 * max(0, len(punk["traits"]) - 2)
        punk["price"] = str((Decimal(cents) / 100).quantize(CENT))  # always two decimals
    return roster


def stale_files(roster: list[dict], traits: dict[str, dict]) -> list[str]:
    """Render into a scratch directory and list the committed files that differ from it."""
    with tempfile.TemporaryDirectory() as tmp:
        out, seed = Path(tmp) / "svg", Path(tmp) / "cloudpunks.json"
        render(roster, traits, out, seed)
        expected = {f"nft-collection/{p.name}": p.read_text() for p in out.glob("*.svg")}
        expected["local/seed/cloudpunks.json"] = seed.read_text()
    actual = {f"nft-collection/{p.name}": p.read_text() for p in COLLECTION.glob("*.svg")}
    if SEED_DATA.is_file():
        actual["local/seed/cloudpunks.json"] = SEED_DATA.read_text()
    return sorted(
        name for name in expected.keys() | actual.keys() if expected.get(name) != actual.get(name)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("render", help="write nft-collection/*.svg and local/seed/cloudpunks.json")
    sub.add_parser("check", help="exit 1 if those files are stale")
    draw = sub.add_parser("roster", help="draw a new roster.json")
    draw.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)
    traits = load_traits()
    if args.command == "roster":
        ROSTER.write_text(json.dumps(draw_roster(traits, args.seed), indent=1) + "\n")
        print(f"wrote {ROSTER.relative_to(ROOT)}")
        return 0
    if args.command == "check":
        stale = stale_files(load_roster(), traits)
        if stale:
            print(
                f"stale CloudPunks files (run make cloudpunks): {', '.join(stale[:10])}",
                file=sys.stderr,
            )
            return 1
        return 0
    render(load_roster(), traits)
    print(f"wrote {COUNT} SVGs to {COLLECTION.relative_to(ROOT)} and {SEED_DATA.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
