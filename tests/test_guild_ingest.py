"""Regression tests for the Guild RPG cast live ingest (engine/guild_ingest.py)."""

import pytest

from engine import guild_roster as gr
from engine.guild_ingest import ingest, normalize_name

# A minimal registry sheet exercising the format quirks the extractor must
# tolerate: [cite: ...] annotations, the "(EP / Mana)" label variant, and the
# Individual Action Syntax Card YAML with lever lines carrying [cite: N].
REGISTRY_SHEET = """# Test Adventurer Registry (S-RANK)

##### Basic
*  **Name:** Test Hero [cite: 1]
*  **Gender:** Male
*  **Race:** Human
*  **Adventurer Rank:** S-Rank (Legendary Sovereign Tier | 220 CP) [cite: 2]

##### Combat Stats & Derived Values
| Stat | Level | Execution |
| :--- | :---: | :--- |
| **Body (B) Stat** | **6** |
| **Mind (M) Stat** | **6** |
| **Soul (S) Stat** | **6** |
| **Attack Combat Value (ACV)** | **6** |
| **Defence Combat Value (DCV)** | **6** |
| **Health Points (HP)** | **60** |
| **Energy Points (EP / Mana)** | **60** |

##### 📐 Individual Action Syntax Card
```yaml
SUBJECT (The Noun Phrase / Bounding Box):
  - Structural Fault: "Test Fault" — something
THE ANCHOR (The Sixth Guard):
  - Failure Trigger: "Test Trigger" — boom
  - Systemic Collapse: test collapse
PREDICATE (The Predicate Phrase / Strategic Levers):
  - Lever 1: Containment (The Test) [cite: 3]:
      - Strategy: hold
      - Action: guard
  - Lever 2: Velocity (The Test) [cite: 3]:
      - Strategy: rush
      - Action: strike
  - Lever 3: Defection (The Test) [cite: 3]:
      - Strategy: flee
      - Action: leave
```
"""

NOVEL_SHEET = """# New Adventurer Registry (D-RANK)

##### Basic
*  **Name:** New Hero [cite: 9]
*  **Race:** Human
*  **Adventurer Rank:** D-Rank (Novice | 35 CP) [cite: 9]

##### Combat Stats & Derived Values
| Stat | Level |
| :--- | :---: |
| **Body (B) Stat** | **3** |
| **Mind (M) Stat** | **3** |
| **Soul (S) Stat** | **3** |
| **Health Points (HP)** | **30** |
| **Energy Points (EP / Mana)** | **30** |

##### 📐 Individual Action Syntax Card
```yaml
SUBJECT (The Noun Phrase / Bounding Box):
  - Structural Fault: "New Fault"
THE ANCHOR (The Sixth Guard):
  - Failure Trigger: "New Trigger"
  - Systemic Collapse: new collapse
PREDICATE (The Predicate Phrase / Strategic Levers):
  - Lever 1: Containment (The Test) [cite: 9]:
      - Strategy: hold
      - Action: guard
  - Lever 2: Velocity (The Test) [cite: 9]:
      - Strategy: rush
      - Action: strike
  - Lever 3: Defection (The Test) [cite: 9]:
      - Strategy: flee
      - Action: leave
```
"""


@pytest.fixture
def tmp_roster(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(gr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(gr, "ROSTER_PATH", str(data_dir / "test_roster.db"))
    gr.init_roster_db()
    return gr


def _upsert(grid, name, body=1, hp=10):
    grid.upsert_character(
        "guild_rpg",
        {"name": name, "rank_label": "S-Rank (Sovereign Tier)", "race": "Human",
         "points_budget": 220, "stat_body": body, "stat_mind": 1, "stat_soul": 1,
         "acv": 1, "dcv": 1, "max_hp": hp, "max_ep": hp},
        "{}", "card.json",
    )


def test_normalize_strips_punctuation():
    assert normalize_name("Jack-O'Lantern") == normalize_name("Jack‐O'Lantern")
    assert normalize_name("Blue Oni") == "blueoni"
    assert normalize_name("Nine-tailed Fox") == "ninetailedfox"


def test_explicit_ep_mana_variant_parses():
    from engine.guild_pullover import extract_file
    import tempfile, os
    d = tempfile.mkdtemp()
    p = os.path.join(d, "hero.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(REGISTRY_SHEET)
    payload = extract_file(p)[0]
    assert payload["max_ep"] == 60
    assert payload["stat_body"] == 6
    assert payload["levers"].startswith("Containment:")


def test_add_only_inserts_novel_leaves_existing(tmp_path, tmp_roster):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    _upsert(tmp_roster, "Test Hero")  # hand-tuned placeholder
    (sheets / "hero.md").write_text(REGISTRY_SHEET, encoding="utf-8")
    (sheets / "new.md").write_text(NOVEL_SHEET, encoding="utf-8")

    res = ingest(base=str(sheets), update_existing=False)
    assert res["inserted"] == 1     # New Hero
    assert res["existing"] == 1     # Test Hero matched, untouched
    assert res["updated"] == 0
    assert res["errors"] == 0

    names = [r[0] for r in tmp_roster.get_roster_connection().execute(
        "SELECT name FROM characters WHERE setting_id='guild_rpg'").fetchall()]
    assert "New Hero" in names
    assert "Test Hero" in names
    # The existing hand-tuned row was NOT overwritten.
    ch = tmp_roster.get_character("guild_rpg", "Test Hero")
    assert ch["stat_body"] == 1


def test_update_existing_upgrades_overlap(tmp_path, tmp_roster):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    _upsert(tmp_roster, "Test Hero", body=1, hp=10)  # hand-tuned placeholder
    (sheets / "hero.md").write_text(REGISTRY_SHEET, encoding="utf-8")

    res = ingest(base=str(sheets), update_existing=True)
    assert res["updated"] == 1
    assert res["inserted"] == 0

    ch = tmp_roster.get_character("guild_rpg", "Test Hero")
    assert ch["stat_body"] == 6  # upgraded from the registry sheet
    assert ch["max_ep"] == 60


def test_dry_run_writes_nothing(tmp_path, tmp_roster):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    (sheets / "hero.md").write_text(REGISTRY_SHEET, encoding="utf-8")
    (sheets / "new.md").write_text(NOVEL_SHEET, encoding="utf-8")

    res = ingest(base=str(sheets), dry_run=True)
    assert res["inserted"] == 2
    names = [r[0] for r in tmp_roster.get_roster_connection().execute(
        "SELECT name FROM characters WHERE setting_id='guild_rpg'").fetchall()]
    assert names == []  # nothing committed
