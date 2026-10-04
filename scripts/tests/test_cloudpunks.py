"""scripts/cloudpunks: the collection is the approved art, complete, reproducible and in step."""

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
from cloudpunks import generate

# sha256 of nft-collection/0001.svg as the owner approved it (3 Oct 2026). It never changes.
APPROVED_0001 = "026bc5edff783339cd3fdcd761310b8cec2cf12e3ed7638ed84d4d00c961e61e"
ROSTER_SEED = 7  # the committed roster is exactly what this seed draws


@pytest.fixture(scope="module")
def traits() -> dict[str, dict]:
    return generate.load_traits()


@pytest.fixture(scope="module")
def roster() -> list[dict]:
    return generate.load_roster()


def test_0001_renders_byte_for_byte_as_approved(
    traits: dict[str, dict], roster: list[dict]
) -> None:
    svg = generate.to_svg(1, generate.compose(roster[0], traits))

    assert hashlib.sha256(svg.encode()).hexdigest() == APPROVED_0001
    assert roster[0]["traits"] == generate.FIRST["traits"]


def test_the_committed_svgs_and_seed_data_are_not_stale(
    traits: dict[str, dict], roster: list[dict]
) -> None:
    assert generate.stale_files(roster, traits) == []


def test_the_roster_is_what_its_seed_draws(traits: dict[str, dict], roster: list[dict]) -> None:
    assert generate.draw_roster(traits, ROSTER_SEED) == roster


def test_one_hundred_numbered_one_to_one_hundred_with_the_planned_rarity(
    roster: list[dict],
) -> None:
    assert [p["id"] for p in roster] == list(range(1, generate.COUNT + 1))
    assert Counter(p["type"] for p in roster) == generate.TYPE_COUNTS


def test_every_cloudpunk_is_a_different_combination(roster: list[dict]) -> None:
    keys = [(p["type"], p.get("skin"), tuple(sorted(p["traits"]))) for p in roster]

    assert len(set(keys)) == len(keys)


def test_every_trait_exists_for_its_head_and_slots_are_not_doubled(
    traits: dict[str, dict], roster: list[dict]
) -> None:
    for punk in roster:
        variant = generate.variant_for(punk["type"])
        assert all(variant in traits[name]["variants"] for name in punk["traits"]), punk
        slots = [traits[name]["slot"] for name in punk["traits"]]
        assert len(slots) == len(set(slots)), punk
        assert len(punk["traits"]) >= generate.MIN_TRAITS, punk
        if punk["type"] in generate.NO_BEARD:
            assert "beard" not in slots, punk


def test_human_heads_have_a_skin_and_the_others_do_not(roster: list[dict]) -> None:
    for punk in roster:
        assert (punk.get("skin") in generate.SKINS) == (punk["type"] in ("male", "female")), punk


def test_prices_are_two_decimal_eth_strings_in_their_rarity_band(roster: list[dict]) -> None:
    for punk in roster:
        price = Decimal(punk["price"])
        assert re.fullmatch(r"\d+\.\d{2}", punk["price"]), punk
        low, high = generate.PRICE_RANGE[punk["type"]]
        assert low <= price <= high + Decimal("2.50") * len(punk["traits"]), punk


def test_seed_records_describe_each_cloudpunk(traits: dict[str, dict], roster: list[dict]) -> None:
    records = json.loads(generate.SEED_DATA.read_text())

    assert [r["sku"] for r in records] == [f"CP-{n:04d}" for n in range(1, 101)]
    assert records[0] == {
        "sku": "CP-0001",
        "name": "CloudPunk #0001",
        "category": "male",
        "description": "Male · Mohawk Thin, Classic Shades, Cigarette, Earring",
        "price": roster[0]["price"],
        "currency": "ETH",
    }
    assert {r["category"] for r in records} == set(generate.TYPE_COUNTS)


def test_svgs_are_24_by_24_crisp_and_have_no_background() -> None:
    files = sorted(generate.COLLECTION.glob("*.svg"))
    assert [f.name for f in files] == [f"{n:04d}.svg" for n in range(1, 101)]
    for f in files:
        text = f.read_text()
        assert 'viewBox="0 0 24 24"' in text, f.name
        assert 'shape-rendering="crispEdges"' in text, f.name
        # the page colours the tile by market state, so no rect may cover the whole square
        assert 'width="24" height="24"' not in text, f.name


def test_a_trait_cell_can_take_the_wearers_skin(traits: dict[str, dict]) -> None:
    """Skin showing through hair follows the wearer: the same curls on two skins differ there."""
    pale = generate.compose({"type": "female", "skin": "albino", "traits": ["Tight Curls"]}, traits)
    dark = generate.compose({"type": "female", "skin": "dark", "traits": ["Tight Curls"]}, traits)
    tokens = [
        (r, c) for r, c, colour, *_ in traits["Tight Curls"]["variants"]["female"] if colour == "S"
    ]

    assert tokens
    for r, c in tokens:
        assert pale[r][c] == (generate.SKINS["albino"]["S"], 1.0)
        assert dark[r][c] == (generate.SKINS["dark"]["S"], 1.0)


def test_the_ui_bundles_an_identical_copy_of_the_art() -> None:
    copy = Path(generate.ROOT, "ui", "src", "assets", "cloudpunks")
    for f in sorted(generate.COLLECTION.glob("*.svg")):
        assert (copy / f.name).read_bytes() == f.read_bytes(), f.name
