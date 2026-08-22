"""Regression tests for the Guild RPG region live ingest (engine/guild_region_ingest.py)."""

import pytest

from engine import guild_roster as gr
from engine import guild_region_ingest as gri
from engine.guild_region_pullover import extract_file, extract_region

# Boss-style region layout (Inewell/Srurpolis/Vardun): a Geopolitical Profile,
# a yaml SUBJECT block, and a PREDICATE lever section using "- Strategy:" /
# "- Action:" bullets. Exercises [cite: N] stripping, the Rank-Bracket -> city
# type derivation, the THE ANCHOR bullet block, and the boss-style levers.
REGION_SHEET = """# Inewell (The Western City of Academies)

### Geopolitical Profile
*  **Name:** Inewell (The Western City of Academies) [cite: 145]
*  **Geopolitical Scale:** SS-Rank (Sovereign Geopolitical / Macro-Character Tier) [cite: 4, 158]
*  **Rank Bracket:** SS-Rank Sovereign City-State (Colossal Scale) [cite: 4, 158]

```yaml
Institution: "Inewell" (The Academic Arcane Grid) [cite: 158]
SUBJECT (The Noun Phrase / Bounding Box):
  - Arena Geometry: The Rigid Urban Grid [cite: 158]. Spatially locked.
  - Structural Fault: "Staff-Focus Dependency" — The entire citizenry rely on staves [cite: 158].
  - Terminal Scarcity: "The Quantified Mana Clock" — finite.
THE ANCHOR (The Grand Guard):
  - Failure Trigger: "The Null-Focus Resource Collapse" — The exact millisecond [cite: 158].
  - Systemic Collapse: Inewell's civilization suffers catastrophic stall [cite: 158].
PREDICATE (The Verb Phrase / Strategic Levers):
  - Lever 1: Containment (The Curricular Foundation) [cite: 159]:
      - Strategy: Beating the volatile nature
      - Action: Enforcing strict zoning
  - Lever 2: Velocity (The Staff-Bound Overclock) [cite: 160]:
      - Strategy: Channeling massive magical output
      - Action: Overclocking the grid
  - Lever 3: Defection (The Tool-less Contingency) [cite: 161]:
      - Strategy: Training tool-less reserves
      - Action: Arming mercenaries
```
"""

# Capital-style region layout: lever section uses "Lever N: The <Name> Vector"
# with **The Strategy:** / **The Action:** bullets and an inline "The Anchor:"
# label rather than a THE ANCHOR bullet block.
CAPITAL_SHEET = """# The Capital City (The Crown of the Mortal Realm)

### Geopolitical Profile
*  **Name:** The Capital City (The Crown of the Mortal Realm) [cite: 273]
*  **Scale & Tier:** SS-Tier Geopolitical Metropolis (Macro-Sovereign Entity)
*  **Rank Bracket:** SS-Tier Sovereign Metropolis (Macro-Sovereign Entity)

```yaml
The_Subject:
  Regional_Geometry: A massive, sprawling stone metropolis [cite: 273].
  Structural_Fault: "Cohesive Deficit" — While the Capital possesses wealth [cite: 273].
  The_Grand_Guard: The Civil Rupture / Systemic Desynced Anarchy [cite: 273].
The Anchor: The Grand Guard (The Civil Rupture / Systemic Desynced Anarchy) [cite: 273]
PREDICATE (The Verb Phrase / Strategic Levers):
  ###### 🛡️ Lever 1: The Containment Vector (The Civic Balancing Ledger) [cite: 16]:
  *   **The Strategy:** Siphoning off the volatile, desperate classes.
  *   **The Action:** Running the grand tournament as a pressure valve.
  ###### 🚀 Lever 2: The Velocity Vector (The Tournament of Deterrence) [cite: 291]:
  *   **The Strategy:** Funneling restless strength into sanctioned combat.
  *   **The Action:** Broadcasting the spectacle across the realm.
  ###### 🔥 Lever 3: The Defection Vector (The Shadow Conduit) [cite: 13, 17]:
  *   **The Strategy:** Appeasing the criminal underbelly with autonomy.
  *   **The Action:** Licensing the smuggling rings as a release valve.
```
"""


@pytest.fixture
def tmp_roster(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(gr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(gr, "ROSTER_PATH", str(data_dir / "test_roster.db"))
    gr.init_roster_db()
    return gr


def _upsert_location(grid, name, location_type="settlement"):
    grid.upsert_location(
        "guild_rpg",
        {"name": name, "location_type": location_type, "region": "",
         "description": "", "travel_from_capital": "", "notes": ""},
        "{}", "seed.json",
    )


def test_region_boss_style_extracts_ns():
    import tempfile, os
    d = tempfile.mkdtemp()
    p = os.path.join(d, "inewell-region-sheet.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(REGION_SHEET)
    r = extract_file(p)[0]
    assert r["name"] == "Inewell"
    assert r["location_type"] == "city"          # derived from Rank Bracket
    assert "[cite" not in r["structural_fault"]
    assert r["structural_fault"].startswith("Staff-Focus Dependency")
    assert "[cite" not in r["sixth_guard"]
    assert "Failure Trigger" in r["sixth_guard"]
    assert "Systemic Collapse" in r["sixth_guard"]
    assert r["levers"].startswith("Containment:")
    assert "Velocity:" in r["levers"] and "Defection:" in r["levers"]


def test_region_capital_style_extracts_ns():
    import tempfile, os
    d = tempfile.mkdtemp()
    p = os.path.join(d, "capital-region-sheet.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(CAPITAL_SHEET)
    r = extract_file(p)[0]
    assert r["name"] == "The Capital City"
    assert r["location_type"] == "capital"
    assert "Cohesive Deficit" in r["structural_fault"]
    assert "The Grand Guard (The Civil Rupture" in r["sixth_guard"]
    assert r["levers"].startswith("Containment:")
    assert "Velocity:" in r["levers"] and "Defection:" in r["levers"]


def test_region_add_only_leaves_seeded(tmp_path, tmp_roster):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    _upsert_location(tmp_roster, "Inewell")  # pre-seeded atlas row
    (sheets / "inewell-region-sheet.md").write_text(REGION_SHEET, encoding="utf-8")

    res = gri.ingest(base=str(sheets), update_existing=False)
    assert res["inserted"] == 0
    assert res["updated"] == 0
    assert res["existing"] == 1      # matched, untouched (add-only)

    loc = tmp_roster.get_roster_connection().execute(
        "SELECT structural_fault FROM locations WHERE setting_id='guild_rpg' AND name='Inewell'"
    ).fetchone()
    assert loc["structural_fault"] == ""   # NOT enriched under add-only


def test_region_update_existing_enriches(tmp_path, tmp_roster):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    _upsert_location(tmp_roster, "Inewell")
    (sheets / "inewell-region-sheet.md").write_text(REGION_SHEET, encoding="utf-8")

    res = gri.ingest(base=str(sheets), update_existing=True)
    assert res["updated"] == 1
    assert res["inserted"] == 0

    loc = tmp_roster.get_roster_connection().execute(
        "SELECT structural_fault, sixth_guard, levers, location_type FROM locations "
        "WHERE setting_id='guild_rpg' AND name='Inewell'"
    ).fetchone()
    assert loc["structural_fault"].startswith("Staff-Focus Dependency")
    assert "Failure Trigger" in loc["sixth_guard"]
    assert loc["levers"].startswith("Containment:")
    assert loc["location_type"] == "city"
