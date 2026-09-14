"""Tests for the deterministic SxM card → BESM compiler (engine/card_to_besm.py).

Covers HP table parsing (both layouts), tier detection, archetype
classification, stat allocation, and the SYSTEM DATA block contract that
batch_ingest METHOD 1 consumes.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

from engine.card_to_besm import (
    extract_game_hp,
    detect_tier,
    classify_archetype,
    allocate_stats,
    derive_acv,
    build_system_data_block,
    get_combat_profile_table,
)


ROW_TABLE = (
    "**Physical Description:** A squishy boy.\n\n"
    "**Combat Profile:**\n\n"
    "| Stat | Value |\n|------|-------|\n"
    "| HP | 23 |\n| MP | 0 |\n| Experience | 16 |\n| Dropped Gold | 8 |\n\n"
    "**Elemental Resistances:** Blunt +50%, Ice -100%.\n"
    "**Combat Role:** Support/tank hybrid using draining attacks to sustain."
)

COL_TABLE = (
    "**Combat Profile:**\n\n"
    "| HP | MP | Experience | Gold Drop |\n"
    "|----|----|------------|-----------|\n"
    "| 201 | 172 | 195 | 58 |\n\n"
    "**Combat Role:** Hit-and-run tactics with Blind and Sleep dark magic."
)

NO_STATS = (
    "**Combat Profile**: No stats available - mechanics pending decode.\n"
    "**Combat Role:** Support."
)


def test_get_combat_profile_table():
    assert "HP | 23" in get_combat_profile_table(ROW_TABLE)
    assert "201" in get_combat_profile_table(COL_TABLE)
    assert get_combat_profile_table("no profile here") == ""


def test_extract_game_hp_row_layout():
    assert extract_game_hp(ROW_TABLE) == 23


def test_extract_game_hp_col_layout():
    assert extract_game_hp(COL_TABLE) == 201


def test_extract_game_hp_no_stats():
    assert extract_game_hp(NO_STATS) == 0


def test_extract_game_hp_absent():
    assert extract_game_hp("Just flavor text, no combat block.") == 0


def test_detect_tier_brackets():
    assert detect_tier(ROW_TABLE)[0] == 1                     # HP 23 → Tier 1
    assert detect_tier(_hp_desc(300))[0] == 2                 # HP 300 → Tier 2
    assert detect_tier(_hp_desc(1000))[0] == 3                # HP 1000 → Tier 3
    assert detect_tier(_hp_desc(4000))[0] == 4                # HP 4000 → Tier 4
    assert detect_tier(_hp_desc(12000))[0] == 5               # HP 12000 → Tier 5
    assert detect_tier(_hp_desc(999999))[2] == 30             # boss rank pool
    assert detect_tier(ROW_TABLE)[2] == 10                    # slime stat pool


def test_detect_tier_budget():
    assert detect_tier(ROW_TABLE)[1] == 35                    # Tier 1 budget
    assert detect_tier(_hp_desc(4000))[1] == 120              # Tier 4 budget
    assert detect_tier(_hp_desc(12000))[1] == 200             # Tier 5 budget


def test_classify_archetype_hybrid_prefers_support():
    assert classify_archetype(ROW_TABLE) == "Divine Support"  # 'tank'+'support' → Support (order tie-break)


def test_classify_archetype_tank():
    desc = "**Combat Role:** A defensive tank-type monster absorbing damage through regenerative barriers."
    assert classify_archetype(desc) == "Frontline Defender"


def test_classify_archetype_caster():
    desc = "**Combat Role:** Pure magic attacker specializing in ice elemental damage."
    assert classify_archetype(desc) == "Arcane Artillery"


def test_classify_archetype_marksman():
    desc = "**Combat Role:** Mobile ranged attacker applying paralyzing effects from a distance."
    assert classify_archetype(desc) == "Ranged Marksman"


def test_classify_archetype_balanced_when_absent():
    assert classify_archetype("No combat role text here at all.") == "Balanced"


def test_allocate_stats_min_ranks():
    assert allocate_stats("Balanced", 3, 12) == (1, 1, 1)


def test_allocate_stats_weights():
    b, m, s = allocate_stats("Arcane Artillery", 12, 12)
    assert m >= b and m >= s           # Mind is the artillery emphasis


def test_allocate_stats_cap():
    b, m, s = allocate_stats("Frontline Defender", 30, 7)
    assert max(b, m, s) <= 7


def test_allocate_stats_total():
    total = sum(allocate_stats("Balanced", 17, 12))
    assert total == 17


def test_derive_acv():
    assert derive_acv(3, 2, 3) == 2
    assert derive_acv(12, 12, 12) == 12


def test_build_system_data_block_contract():
    out = build_system_data_block("Slime", ROW_TABLE, race="Slime")
    assert out["tier"] == 1
    assert out["rank_label"] == "Tier 1"
    block = out["system_block"]
    assert "[SYSTEM DATA: BESM 4E MECHANICS]" in block
    assert "[Setting: besm_disc]" in block
    assert "Body" in block and "[Combat Values:" in block
    assert block.lstrip().startswith("[SYSTEM DATA:")


def test_system_block_values_consistent():
    out = build_system_data_block("Ghost", COL_TABLE)
    block = out["system_block"]
    assert f"Body {out['stat_body']}, Mind {out['stat_mind']}, Soul {out['stat_soul']}" in block
    assert f"HP {out['max_hp']}. EP {out['max_ep']}." in block
    assert (out["stat_body"] + out["stat_soul"]) * 5 == out["max_hp"]
    assert (out["stat_mind"] + out["stat_soul"]) * 5 == out["max_ep"]


def _hp_desc(hp):
    return (
        "**Combat Profile:**\n\n"
        f"| Stat | Value |\n|------|-------|\n| HP | {hp} |\n| MP | 10 |\n\n"
    )