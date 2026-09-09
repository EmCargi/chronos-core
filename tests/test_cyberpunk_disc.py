"""Tests for the Cyberpunk 2077 game disc build (cyberpunk-digital-dm).

Covers the deterministic seams ONLY — vault split / frontmatter parse (CP-21),
type-taxonomy collapse, Street Cred stat derivation, offline fallback matcher,
and the heist module contract. The Cydonia transform itself is a live-rig path
(exercised via the build CLI + compiled/ checkpoints, never in the suite).

These tests are hermetic: synthetic vaults in tmp_path, plus one real-corpus
count lock against the lore-matrix compiled vault if it's present.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

_CHRONOS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DISC_SCRIPTS = os.path.join(os.path.dirname(_CHRONOS), "cyberpunk-digital-dm", "scripts")
sys.path.insert(0, _DISC_SCRIPTS)

import build_cyberpunk_disc as bcd  # noqa: E402


def _note(name: str, type_val: str, body: str = "Flavor text.") -> str:
    return f"---\naliases: [\"{name.lower()}\"]\ntags: [\"cyberpunk 2077\"]\ntype: {type_val}\n---\n{body}\n"


def _write_vault(tmp_path: Path, notes: dict[str, str]) -> Path:
    src = tmp_path / "vault"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in notes.items():
        (src / f"{name}.md").write_text(text, encoding="utf-8")
    return src


# ── frontmatter parse + type taxonomy collapse (CP-21) ─────────────────────

def test_load_entries_parses_frontmatter(tmp_path):
    src = _write_vault(tmp_path, {
        "Adam Smasher": _note("Adam Smasher", "Character", "A borged enforcer."),
        "Voodoo Boys": _note("Voodoo Boys", "Faction"),
        "Japantown": _note("Japantown", "Location"),
        "Kiroshi": _note("Kiroshi", "Item"),
    })
    entries = bcd.load_entries(src)
    assert {e["name"] for e in entries} == {"Adam Smasher", "Voodoo Boys", "Japantown", "Kiroshi"}
    assert {e["folder"] for e in entries} == {"Characters", "Factions", "Districts", "Items"}


def test_type_taxonomy_collapses_case_and_dupes():
    assert bcd.folder_for_type("Character") == "Characters"
    assert bcd.folder_for_type("npc") == "Characters"
    assert bcd.folder_for_type("Faction") == "Factions"
    assert bcd.folder_for_type("gang") == "Factions"
    assert bcd.folder_for_type("Company") == "Factions"
    assert bcd.folder_for_type("Location") == "Districts"
    assert bcd.folder_for_type("Cyberware") == "Items"
    assert bcd.folder_for_type("Role") == "World"  # one-off types → World
    assert bcd.folder_for_type("") == "World"


def test_list_of_entries_route_to_world(tmp_path):
    src = _write_vault(tmp_path, {
        "List of fixers": _note("List of fixers", "Character"),
        "Rebecca": _note("Rebecca", "Character"),
    })
    entries = bcd.load_entries(src)
    by_name = {e["name"]: e["folder"] for e in entries}
    assert by_name["List of fixers"] == "World"  # reference list, not a roster row
    assert by_name["Rebecca"] == "Characters"


def test_malformed_frontmatter_skipped_gracefully(tmp_path):
    src = _write_vault(tmp_path, {
        "Good": _note("Good", "Character"),
        "Bad": "---\nthis: [is: not: yaml\n---\nbody\n",
    })
    entries = bcd.load_entries(src)
    assert [e["name"] for e in entries] == ["Good"]


# ── Street Cred stat derivation (deterministic math) ───────────────────────

def test_street_cred_ladder_budgets():
    assert bcd.STREET_CRED["S"][0] == "Street Cred Legend"
    assert bcd.STREET_CRED["C"][0] == "Street Cred Gangoon"
    budgets = {t: v[1] for t, v in bcd.STREET_CRED.items()}
    assert budgets == {"S": 200, "A": 150, "B": 110, "C": 75}


def test_derive_stats_within_besm_caps():
    for tier in ("S", "A", "B", "C"):
        for arch in bcd.ARCHETYPES:
            s = bcd.derive_stats(tier, arch)
            cap = bcd.STREET_CRED[tier][3]
            assert 1 <= s["stat_body"] <= 12
            assert 1 <= s["stat_mind"] <= 12
            assert 1 <= s["stat_soul"] <= 12
            assert max(s["stat_body"], s["stat_mind"], s["stat_soul"]) <= cap
            assert s["max_hp"] == (s["stat_body"] + s["stat_soul"]) * 5
            assert s["max_ep"] == (s["stat_mind"] + s["stat_soul"]) * 5
            assert s["dcv"] == max(1, s["acv"] - 2)


def test_derive_stats_rank_label():
    s = bcd.derive_stats("A", "Frontline Defender")
    assert s["rank_label"] == "Street Cred Edgerunner"


# ── offline fallback matcher (dry-run review path) ─────────────────────────

def test_fallback_matchers_are_deterministic():
    assert bcd.fallback_tier("A top fixer who runs a crew.") == "A"
    assert bcd.fallback_tier("Street thug working the Watson docks.") == "C"
    arch = bcd.classify_archetype_keywords("sniper, marksman, long-range rifle work")
    assert arch == "Ranged Marksman"


# ── heist module contract (verify_dungeon) ─────────────────────────────────

def test_heist_module_validates():
    module = os.path.join(_CHRONOS, "modules", "night_city_heist_v1.json")
    from engine.verify_dungeon import verify_dungeon_structure
    assert verify_dungeon_structure(module)


# ── real-corpus count lock (lore-matrix compiled vault) ────────────────────

def test_real_corpus_counts():
    if not bcd.DEFAULT_SOURCE.exists():
        pytest.skip("lore-matrix compiled Cyberpunk vault not present")
    entries = bcd.load_entries(bcd.DEFAULT_SOURCE)
    counts = {}
    for e in entries:
        counts[e["folder"]] = counts.get(e["folder"], 0) + 1
    assert counts == {"Characters": 33, "Factions": 26, "Districts": 17, "Items": 11, "World": 36}
    assert len(entries) == 123