"""Tests for the Guild RPG cast pullover extractor (engine/guild_pullover.py).

Covers the two markdown layouts (single ``### Basic`` files + ``<Name>`` tagged
pairs/trio), metadata variant tolerance (``- Name:`` vs ``### Name:`` vs bare
``Basic:``), narrative-syntax extraction (Structural Fault / Sixth Guard /
Levers), the rank-tier stat derivation, and canonical-name normalisation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

from engine.guild_pullover import (
    split_character_blocks,
    parse_metadata,
    extract_narrative_syntax,
    derive_stats,
    classify_archetype,
    extract_character,
    extract_file,
    CANONICAL_NAMES,
    RANK_LABELS,
)

# --- Sample markdowns modeled on the real cast files -------------------------

SINGLE_MD = """### Description

- Name: Nimmi

- Basic: Female, Human, Age 18, Height 155cm

- Rank: D-Rank

{{char}} is a shy sheepkin.

---

## 📐 Nimmi's Individual Narrative Sentence

## 📦 I. The Subject: The Bounding Box (The Frail Pastoral Payload)

YAML

```
The_Subject:
  Arena_Geometry: "meadows"
  Structural_Fault: "The Absolute Frailty Deficit. No self-confidence or combat training."
  Terminal_Scarcity: "Composure"
  The_Sixth_Guard: "The Cornered Melee Threshold."
```

### 🛑 The Anchor: The Sixth Guard (The Cornered Melee Threshold)

For Nimmi, the **Sixth Guard** is unavoidable physical engagement. If trapped she collapses.

## 🎛️ II. The Predicate: The Verb Phrase

#### 🛡️ Lever 1: The Containment Vector (The Liorean Emulation)

- **The Strategy:** Stick to safe low-risk tasks.
- **The Action:** Complete gathering quests near the counter.

#### 🚀 Lever 2: The Velocity Vector (The Panic Headbutt)

- **The Strategy:** Desperate blind surge.
- **The Action:** Headbutt with her horns when cornered.

#### 🧭 Lever 3: The Defection Vector (The Herbivorous Retreat)

- **The Strategy:** Flee to pastoral safety.
- **The Action:** Hide behind trees and puffed wool.
"""

PAIR_MD = """{char}} represents the couple Beril and Vandil.

<Beril>

- Name: Beril
- Gender: Female
- Race: Human
- Age: 40
- Rank: C-Rank

Beril is gentle.

</Beril>

<Vandil>

- Name: Vandil
- Gender: Male
- Race: Human
- Age: 42
- Rank: B-Rank

Vandil is fierce.

</Vandil>

## 📐 The Couple's Narrative Sentence

### 🛑 The Anchor: The Sixth Guard (The Shield Split)

For this couple, the Sixth Guard is separation.

#### 🛡️ Lever 1: The Containment Vector (The Shared Grind)

- **The Strategy:** Work the safe quests together.
- **The Action:** Take paired assignments.
"""


def test_split_single_block():
    blocks = split_character_blocks(SINGLE_MD)
    assert len(blocks) == 1
    assert "Nimmi" in blocks[0]


def test_split_pair_blocks():
    blocks = split_character_blocks(PAIR_MD)
    assert len(blocks) == 2
    assert "Name: Beril" in blocks[0]
    assert "Name: Vandil" in blocks[1]


def test_parse_metadata_single():
    meta = parse_metadata(SINGLE_MD, full_text=SINGLE_MD)
    assert meta["name"] == "Nimmi"
    assert meta["rank"] == "D-Rank"
    assert meta["race"] == "Human"


def test_parse_metadata_heading_name():
    md = "### Name: Thora\n\n- Basic: Female, Human, age 23, 174cm height\n"
    meta = parse_metadata(md, full_text=md)
    assert meta["name"] == "Thora"


def test_parse_metadata_bare_basic_no_rank_path_fallback(tmp_path):
    md = "Name: Nyssa\nBasic: Female, Human, age 12, 134cm height\n"
    p = tmp_path / "D-Rank" / "Nyssa.md"
    p.parent.mkdir()
    p.write_text(md)
    # parse_metadata alone leaves rank empty; extract_character uses path fallback
    payload = extract_character(md, source_path=str(p))
    assert payload["name"] == "Nyssa"
    assert payload["rank_label"] == RANK_LABELS["D"]


def test_extract_narrative_syntax():
    ns = extract_narrative_syntax(SINGLE_MD)
    assert "Frailty Deficit" in ns["structural_fault"]
    assert "unavoidable physical engagement" in ns["sixth_guard"]
    assert "Containment:" in ns["levers"]
    assert "Velocity:" in ns["levers"]
    assert "Defection:" in ns["levers"]
    assert "**The Strategy:**" not in ns["levers"]  # scaffolding stripped


def test_derive_stats_rank_ordering():
    s = derive_stats("S", "a mighty legendary warrior")
    d = derive_stats("D", "a timid harmless girl")
    assert s["points_budget"] > d["points_budget"]
    assert s["stat_body"] + s["stat_mind"] + s["stat_soul"] > d["stat_body"] + d["stat_mind"] + d["stat_soul"]
    assert s["acv"] >= d["acv"]


def test_derive_stats_archetype_difference():
    tank = derive_stats("B", "frontline defender tank shield armor protect")
    caster = derive_stats("B", "arcane magic caster spell elemental sorcerer")
    assert tank["stat_body"] >= caster["stat_body"]
    assert caster["stat_mind"] >= tank["stat_mind"]


def test_classify_archetype_balanced():
    assert classify_archetype("no role keywords here at all") == "Balanced"


def test_extract_character_payload():
    p = extract_character(SINGLE_MD)
    assert p["name"] == "Nimmi"
    assert p["rank_label"] == RANK_LABELS["D"]
    assert p["stat_body"] >= 1 and p["stat_mind"] >= 1 and p["stat_soul"] >= 1
    assert p["max_hp"] == (p["stat_body"] + p["stat_soul"]) * 5
    assert p["max_ep"] == (p["stat_mind"] + p["stat_soul"]) * 5
    assert p["acv"] == (p["stat_body"] + p["stat_mind"] + p["stat_soul"]) // 3
    assert p["dcv"] == max(1, p["acv"] - 2)
    assert p["structural_fault"] and p["sixth_guard"] and p["levers"]


def test_extract_file_pair_returns_two():
    payloads = extract_file.__wrapped__ if hasattr(extract_file, "__wrapped__") else extract_file
    # Use extract_character-level path via a temp file
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "Beril and Vandil B Rank.md"
        f.write_text(PAIR_MD)
        res = extract_file(str(f))
    assert len(res) == 2
    assert res[0]["name"] == "Beril"
    assert res[1]["name"] == "Vandil"
    assert res[0]["rank_label"] == RANK_LABELS["C"]
    assert res[1]["rank_label"] == RANK_LABELS["B"]
    # file-level NS backfilled into both members
    assert "Sixth Guard" in res[0]["sixth_guard"] or "separation" in res[0]["sixth_guard"]
    assert "Containment" in res[0]["levers"]


def test_canonical_name_normalisation():
    md = """- Name: Sylvara Duskveil
- Rank: S-Rank

### 📐 Sylvara's Individual Narrative Sentence
"""
    p = extract_character(md, source_path="S-Rank/Sylvara.md")
    assert p["name"] == "Sylvara"


def test_missing_name_raises():
    import pytest
    with pytest.raises(ValueError):
        extract_character("no name or rank anywhere here")


def test_rank_ladder_constant_shape():
    from engine.guild_pullover import RANK_BRACKETS
    for letter in ("S", "A", "B", "C", "D"):
        budget, pool, cap = RANK_BRACKETS[letter]
        assert budget > 0 and pool >= 3 and 1 <= cap <= 12
        assert RANK_LABELS[letter]


# --- Registry-sheet format (the design-pass "Individual Action Syntax Card") --

REGISTRY_MD = """# AELTHAR KELDOR GUILD: ADVENTURER REGISTRY

##### Basic
*  **Name:** Soren
*  **Gender:** Male
*  **Race:** Human
*  **Adventurer Rank:** D-Rank (Novice Tier | 40 CP)

---

##### Combat Stats & Derived Values

| Stat / Derived Value | Level / Rating | Mechanical Execution & Physics || :--- | :---: | :--- || **Body (B) Stat** | **2** | fragile frame. || **Mind (M) Stat** | **5** | memory. || **Soul (S) Stat** | **5** | resilience. || **Base Combat Value (CV)** | **4** | base. || **Attack Combat Value (ACV)** | **4** | cv. || **Defence Combat Value (DCV)** | **4** | cv. || **Health Points (HP)** | **35** | hp. || **Energy Points (EP)** | **50** | ep. |

##### 📐 Individual Action Syntax Card
```yaml
Character: "Soren" (The Mobile Quartermaster)
Rank Bracket: D-Rank Logistical Support (40 CP)

SUBJECT (The Noun Phrase / Bounding Box):
  - Structural Fault: "Invisible Trauma" — He is conditioned to accept mistreatment and will never call for help.
  - Terminal Scarcity: "The Fragile Frame" — tiny HP pool.

THE ANCHOR (The Sixth Guard):
  - Failure Trigger: "The Frontline Shield Collapse" — a threat bypasses Urkakh.
  - Systemic Collapse: Soren freezes, DCV drops to 1.

PREDICATE (The Verb Phrase / Strategic Levers):
  - Lever 1: Containment (The Logistical Ledger):
      - Strategy: Maximizing party uptime.
      - Action: Soren cleans equipment and writes reports.
  - Lever 2: Velocity (The Triage & Evasion Protocol):
      - Strategy: Overriding fear with survival protocols.
      - Action: Ducks behind Urkakh then applies first aid.
  - Lever 3: Defection (The Domestic Stasis):
      - Strategy: Defecting to quiet comforts.
      - Action: Enjoys tea, submits to Urkakh.
```
"""


def test_registry_metadata():
    meta = parse_metadata(REGISTRY_MD, full_text=REGISTRY_MD)
    assert meta["name"] == "Soren"
    assert meta["race"] == "Human"
    assert "D-Rank" in meta["rank"]


def test_registry_explicit_stats_override_ladder():
    p = extract_character(REGISTRY_MD, source_path="D-Rank/soren.md")
    # Explicit table values win over the D-rank ladder defaults.
    assert p["stat_body"] == 2
    assert p["stat_mind"] == 5
    assert p["stat_soul"] == 5
    assert p["acv"] == 4
    assert p["dcv"] == 4
    assert p["max_hp"] == 35
    assert p["max_ep"] == 50
    assert p["points_budget"] == 40  # from the Adventurer Rank line, not attribute CP


def test_registry_narrative_syntax():
    p = extract_character(REGISTRY_MD, source_path="D-Rank/soren.md")
    assert "Invisible Trauma" in p["structural_fault"]
    assert "Frontline Shield Collapse" in p["sixth_guard"]
    assert "Containment:" in p["levers"]
    assert "Velocity:" in p["levers"]
    assert "Defection:" in p["levers"]
    # Scaffolding / quote artifacts stripped
    assert '"' not in p["structural_fault"]
    assert "**The Strategy:**" not in p["levers"]
