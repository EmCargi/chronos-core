"""Tests for the SxM1 Bestiary pullover extractor (engine/sxm1_pullover.py).

All deterministic, no DB, no LLM. Covers the four design-pass rulings: data-sparse
skip, explicit-over-derived stat parity, memo preservation, and tier->rank ladder.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from engine import guild_roster as gr
from engine.sxm1_pullover import (
    extract_character,
    parse_stat_block,
    synthesize_card,
    _resolve_rank,
)
from engine.sxm1_ingest import ingest, normalize_name

FULL_PAGE = """# Goblin Fighter

**Enemy ID:** 113 (SxM1) · **Stratum:** First · **Tier:** Common Mob

> A scrappy melee goblin.
> — *Tamer's Memo (SxM1)*

## 📊 BESM Stat Block

| Attribute | Value | Notes |
|---|---|---|
| **Body** | 4 | Quick |
| **Mind** | 2 | Cunning |
| **Soul** | 2 | Bold |
| **CV** | 3 | Base Combat Value |
| **HP** | 30 | Derived |
| **EP** | 15 | Derived |
| **CP Budget** | 25 | Common Mob |

## 📖 Monster Memo

> The most basic of Goblins! Very common.
> Fighters are very mischievous.
> — *Tamer's Memo (weebly, SxM1)*
"""


def test_full_page_parses():
    p = extract_character(FULL_PAGE)
    assert "skip" not in p
    assert p["name"] == "Goblin Fighter"
    assert p["stat_body"] == 4 and p["stat_mind"] == 2 and p["stat_soul"] == 2
    assert p["acv"] == 3 and p["dcv"] == 1
    assert p["max_hp"] == 30 and p["max_ep"] == 15
    assert p["points_budget"] == 25
    assert p["rank_label"] == "Mob"


def test_data_sparse_skipped():
    md = FULL_PAGE.replace("**Tier:** Common Mob", "**Tier:** Common Mob ⚠️ data-sparse")
    p = extract_character(md)
    assert p["skip"].startswith("data-sparse")


def test_missing_stat_block_skipped():
    md = "# Phantom\n\n**Tier:** Area Boss\n\nNo stats here.\n"
    p = extract_character(md)
    assert p["skip"].startswith("missing/incomplete")


def test_explicit_overrides_formula():
    # Explicit HP/EP differ from the (Body+Soul)*5 / (Mind+Soul)*5 formula,
    # proving the explicit values win (ruling #2).
    md = """# Test Beast

**Tier:** Area Leader

| Attribute | Value |
|---|---|
| **Body** | 6 |
| **Mind** | 4 |
| **Soul** | 5 |
| **CV** | 9 |
| **HP** | 999 |
| **EP** | 888 |
| **CP Budget** | 60 |
"""
    p = extract_character(md)
    assert p["max_hp"] == 999
    assert p["max_ep"] == 888
    assert p["acv"] == 9 and p["dcv"] == 7


def test_formula_fallback_when_stats_absent():
    # No HP/EP/CV rows -> fall back to standard BESM math.
    md = """# Fallback Slime

**Tier:** Common Mob

| Attribute | Value |
|---|---|
| **Body** | 3 |
| **Mind** | 2 |
| **Soul** | 3 |
| **CP Budget** | 25 |
"""
    stats = parse_stat_block(md)
    assert stats["acv"] == (3 + 2 + 3) // 3
    assert stats["dcv"] == max(1, stats["acv"] - 2)
    assert stats["max_hp"] == (3 + 3) * 5
    assert stats["max_ep"] == (2 + 3) * 5


def test_memo_preserved_verbatim():
    p = extract_character(FULL_PAGE)
    assert "The most basic of Goblins!" in p["monster_memo"]
    assert "mischievous" in p["monster_memo"]
    # The attribution line is kept verbatim, not stripped.
    assert "Tamer's Memo (weebly, SxM1)" in p["monster_memo"]


def test_compact_single_row_format():
    # Pages like Blue Oni use a compact single-row stat line + CP in the heading.
    md = """# Blue Oni

**Enemy ID:** 037 (SxM1) · **Stratum:** Fourth · **Tier:** Common Mob

## 📊 BESM Stat Block (25 CP)

| Body 5 | Mind 2 | Soul 4 | CV 4 | HP 45 | EP 25 |

## 📖 Monster Memo

> A fearsome oni!
> — *Tamer's Memo (weebly, SxM1)*
"""
    p = extract_character(md)
    assert "skip" not in p, p.get("skip")
    assert p["stat_body"] == 5 and p["stat_mind"] == 2 and p["stat_soul"] == 4
    assert p["acv"] == 4 and p["dcv"] == 2
    assert p["max_hp"] == 45 and p["max_ep"] == 25
    assert p["points_budget"] == 25
    assert p["rank_label"] == "Mob"


def test_tier_rank_ladder():
    assert _resolve_rank("Common Mob", 25) == ("Mob", 25)
    assert _resolve_rank("Area Leader", 60) == ("Leader", 60)
    assert _resolve_rank("Area Boss", 120) == ("Boss", 120)
    # Explicit CP overrides the mapped default.
    assert _resolve_rank("Common Mob", 40) == ("Mob", 40)


def test_synthesized_card_envelope():
    p = extract_character(FULL_PAGE)
    card = json.loads(p["card_json"])
    assert card["spec"] == "chara_card_v2"
    assert card["data"]["name"] == "Goblin Fighter"
    assert "SYSTEM DATA: BESM 4E MECHANICS" in card["data"]["description"]
    assert card["data"]["creator_notes"] == p["monster_memo"]
    assert "shota_x_monsters" in card["data"]["description"]


def test_duplicate_name_skipped(tmp_path):
    from engine.sxm1_pullover import extract_file
    f = tmp_path / "Dup.md"
    f.write_text(FULL_PAGE, encoding="utf-8")
    f2 = tmp_path / "Dup2.md"
    f2.write_text(FULL_PAGE.replace("Goblin Fighter", "Goblin Fighter"), encoding="utf-8")
    seen = set()
    a = extract_file(str(f), seen=seen)
    b = extract_file(str(f2), seen=seen)
    assert "skip" not in a[0]
    assert b[0]["skip"] == "duplicate source name"


@pytest.fixture
def tmp_roster(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(gr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(gr, "ROSTER_PATH", str(data_dir / "test_roster.db"))
    gr.init_roster_db()
    return gr


def _upsert(grid, name, body=1, hp=10):
    grid.upsert_character(
        "shota_x_monsters",
        {"name": name, "rank_label": "Mob", "race": "Monster", "points_budget": 25,
         "stat_body": body, "stat_mind": 1, "stat_soul": 1, "acv": 1, "dcv": 1,
         "max_hp": hp, "max_ep": hp},
        "{}", "card.json",
    )


def test_normalize_strips_punctuation():
    assert normalize_name("Jack-O'Lantern") == normalize_name("Jack‐O'Lantern")
    assert normalize_name("Blue Oni") == "blueoni"
    assert normalize_name("Nine-tailed Fox") == "ninetailedfox"


def test_add_only_inserts_novel_leaves_existing(tmp_path, tmp_roster):
    bestiary = tmp_path / "bestiary"
    bestiary.mkdir()
    # Existing card-derived row with a punctuation variant -> must match via norm.
    _upsert(tmp_roster, "Jack-O'Lantern")
    (bestiary / "jack.md").write_text(
        "# Jack‐O'Lantern\n\n**Tier:** Common Mob\n\n"
        "| Body 4 | Mind 3 | Soul 3 | CV 3 | HP 35 | EP 30 |\n\n"
        "## 📖 Monster Memo\n\n> jack memo\n", encoding="utf-8")
    (bestiary / "gob.md").write_text(FULL_PAGE, encoding="utf-8")
    (bestiary / "ds.md").write_text(
        "# SXM2 Boss\n\n**Tier:** Area Boss ⚠️ data-sparse\n", encoding="utf-8")

    res = ingest(base=str(bestiary), update_existing=False)
    assert res["skipped"] == 1          # data-sparse page
    assert res["existing"] == 1        # Jack matched via normalization, untouched
    assert res["inserted"] == 1        # Goblin Fighter added
    assert res["updated"] == 0

    names = [r[0] for r in tmp_roster.get_roster_connection().execute(
        "SELECT name FROM characters WHERE setting_id='shota_x_monsters'").fetchall()]
    assert "Goblin Fighter" in names
    assert "Jack-O'Lantern" in names
    # The existing row was NOT upgraded (still the card-derived stats).
    ch = tmp_roster.get_character("shota_x_monsters", "Jack-O'Lantern")
    assert ch["stat_body"] == 1


def test_update_existing_upgrades_overlap(tmp_path, tmp_roster):
    bestiary = tmp_path / "bestiary"
    bestiary.mkdir()
    _upsert(tmp_roster, "Goblin Fighter", body=1, hp=10)  # card-derived placeholder
    (bestiary / "gob.md").write_text(FULL_PAGE, encoding="utf-8")

    res = ingest(base=str(bestiary), update_existing=True)
    assert res["updated"] == 1
    assert res["inserted"] == 0

    ch = tmp_roster.get_character("shota_x_monsters", "Goblin Fighter")
    assert ch["stat_body"] == 4       # upgraded from curated Bestiary
    assert ch["max_hp"] == 30
