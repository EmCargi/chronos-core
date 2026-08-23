"""Regression tests for the Guild RPG org live ingest (engine/guild_org_ingest.py)."""

import pytest

from engine import guild_roster as gr
from engine import guild_org_ingest as goi
from engine.guild_org_pullover import extract_file, extract_org

# Aelthar Keldor layout: Basic block with org metadata + a fenced yaml NS card
# using a THE ANCHOR bullet block and boss-style "- Strategy:" / "- Action:"
# levers. Exercises org-type derivation, leader/base grabs, and the shared
# region NS parser (Structural Fault / Grand Guard / three levers).
ORG_SHEET = """# Aelthar Keldor (The Capital Sanctuary Domain)

##### Basic
*  **Name:** Aelthar Keldor
*  **Organization Type:** Adventurer Guild (Sovereign Institution)
*  **Scale & Tier:** Continental Guild Network (Capital-City Anchor)
*  **Rank Bracket:** SS-Rank Sovereign Guild
*  **Leader:** Guild Master Sylvara Duskveil (S-Rank High Elf)
*  **Base of Operations:** The Capital City

```yaml
Entity: "Aelthar Keldor" (The Capital Sanctuary Domain)
SUBJECT (The Noun Phrase / Bounding Box):
  - Structural Fault: "The Institutional Dependency" — the guild's equilibrium depends on a strict boundary between frontier violence and urban peace.
  - Terminal Scarcity: "The Silver Economy" — a stalled board starves the workforce.
THE ANCHOR (The Grand Guard):
  - Failure Trigger: Internal rogue infighting breaches the main social floor.
  - Systemic Collapse: The entire system faces an immediate, catastrophic stall.
PREDICATE (The Verb Phrase / Strategic Levers):
  - Lever 1: Containment (The Civic Balancing Ledger):
      - Strategy: Maximizing the daily processing efficiency of the D-to-B Rank workforce.
      - Action: Run entirely through Liora's desk using silver payouts.
  - Lever 2: Velocity (The Marginal Expedition Vector):
      - Strategy: The guild's overclock state, managed directly through Sylvara's chambers.
      - Action: When a catastrophic threat emerges, mobilize specialized A-and-S Rank vanguards.
  - Lever 3: Defection (The Sanctuary Extradition):
      - Strategy: Declaring external feudal law unviable inside guild boundaries.
      - Action: The guild establishes complete legal neutrality, offering a refuge.
```
"""

# Dark-guild variant: inline "The Anchor:" label + YAML The_Grand_Guard fallback
# and Capital-style "Lever N: The <Name> Vector" with **The Strategy:** bullets.
# Exercises the org-type derivation (dark_guild) and the alternate NS parse paths.
DARK_SHEET = """# The Crimson Covenant (Dark Guild)

##### Basic
*  **Name:** The Crimson Covenant
*  **Organization Type:** Dark Guild
*  **Scale & Tier:** Regional Shadow Network
*  **Leader:** Unknown
*  **Base of Operations:** The Capital City Undermarket

```yaml
The_Subject:
  Structural_Fault: "The Exposure Debt" — the covenant relies on anonymity.
  The_Grand_Guard: The Ledger Burn (Total Unmasking)
The Anchor: The Grand Guard (The Ledger Burn)
PREDICATE (The Verb Phrase / Strategic Levers):
  ###### 🛡️ Lever 1: The Containment Vector (The Quiet Tax):
  *   **The Strategy:** Siphoning protection coin from the undermarket.
  *   **The Action:** Running the silent toll as a pressure valve.
  ###### 🚀 Lever 2: The Velocity Vector (The Blood Ledger):
  *   **The Strategy:** Funneling restless strength into sanctioned combat.
  *   **The Action:** Broadcasting the spectacle across the shadow market.
  ###### 🔥 Lever 3: The Defection Vector (The Ashen Escape):
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


def _upsert_org(grid, name):
    grid.upsert_organization(
        "guild_rpg", {"name": name}, "{}", "seed.json",
    )


def test_org_extracts_metadata_and_ns():
    import tempfile, os
    d = tempfile.mkdtemp()
    p = os.path.join(d, "aelthar-keldor-org-sheet.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(ORG_SHEET)
    r = extract_file(p)[0]
    assert r["name"] == "Aelthar Keldor"
    assert r["organization_type"] == "guild"
    assert r["leader"] == "Guild Master Sylvara Duskveil (S-Rank High Elf)"
    assert r["base_of_operations"] == "The Capital City"
    assert r["scale_tier"].startswith("Continental Guild Network")
    assert r["structural_fault"].startswith("The Institutional Dependency")
    assert "Failure Trigger" in r["sixth_guard"]
    assert "Systemic Collapse" in r["sixth_guard"]
    assert r["levers"].startswith("Containment:")
    assert "Velocity:" in r["levers"] and "Defection:" in r["levers"]


def test_dark_org_extracts_type_and_inline_guard():
    import tempfile, os
    d = tempfile.mkdtemp()
    p = os.path.join(d, "crimson-covenant-org-sheet.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(DARK_SHEET)
    r = extract_file(p)[0]
    assert r["name"] == "The Crimson Covenant"
    assert r["organization_type"] == "dark_guild"
    assert "Exposure Debt" in r["structural_fault"]
    assert "Ledger Burn" in r["sixth_guard"]
    assert r["levers"].startswith("Containment:")
    assert "Velocity:" in r["levers"] and "Defection:" in r["levers"]


def test_org_add_only_leaves_seeded(tmp_path, tmp_roster):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    _upsert_org(tmp_roster, "Aelthar Keldor")  # pre-seeded row
    (sheets / "aelthar-keldor-org-sheet.md").write_text(ORG_SHEET, encoding="utf-8")

    res = goi.ingest(base=str(sheets), update_existing=False)
    assert res["inserted"] == 0
    assert res["updated"] == 0
    assert res["existing"] == 1      # matched, untouched (add-only)

    row = tmp_roster.get_roster_connection().execute(
        "SELECT structural_fault FROM organizations WHERE setting_id='guild_rpg' AND name='Aelthar Keldor'"
    ).fetchone()
    assert row["structural_fault"] == ""   # NOT enriched under add-only


def test_org_update_existing_enriches(tmp_path, tmp_roster):
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    _upsert_org(tmp_roster, "Aelthar Keldor")
    (sheets / "aelthar-keldor-org-sheet.md").write_text(ORG_SHEET, encoding="utf-8")

    res = goi.ingest(base=str(sheets), update_existing=True)
    assert res["updated"] == 1
    assert res["inserted"] == 0

    row = tmp_roster.get_roster_connection().execute(
        "SELECT structural_fault, sixth_guard, levers, organization_type, leader, base_of_operations "
        "FROM organizations WHERE setting_id='guild_rpg' AND name='Aelthar Keldor'"
    ).fetchone()
    assert row["structural_fault"].startswith("The Institutional Dependency")
    assert "Failure Trigger" in row["sixth_guard"]
    assert row["levers"].startswith("Containment:")
    assert row["organization_type"] == "guild"
    assert row["leader"] == "Guild Master Sylvara Duskveil (S-Rank High Elf)"
    assert row["base_of_operations"] == "The Capital City"


def test_shell_injects_org_context():
    """The org Narrative Syntax must surface in the compiled besm_shell prompt."""
    import sys
    sys.path.insert(0, "/home/megane/dev")  # expose core.* used by engine.llm_bridge
    from engine.llm_bridge import LLMBridge

    vitals = {
        "name": "Kari", "current_hp": 80, "current_ep": 80,
        "stat_body": 5, "stat_mind": 5, "stat_soul": 5,
        "max_hp": 80, "max_ep": 80, "base_acv": 5, "base_dcv": 5,
        "structural_fault": "", "sixth_guard": "", "levers": "",
        "combat_techniques": [], "skills": [], "defects": [],
        "shock_value": 16,
        "org_name": "Aelthar Keldor", "org_type": "guild",
        "org_leader": "Sylvara Duskveil", "org_base": "The Capital City",
        "org_scale": "Continental Guild Network",
        "org_structural_fault": "The Institutional Dependency",
        "org_sixth_guard": "Failure Trigger: internal rogue infighting",
        "org_levers": "Containment: the civic balancing ledger",
    }
    node = {"node_id": "node_01", "title": "Yard Gate", "description": "packed dirt yard"}
    out = LLMBridge().compile_system_frame("besm_shell", vitals, node)
    assert "Aelthar Keldor" in out
    assert "The Institutional Dependency" in out
    assert "Failure Trigger: internal rogue infighting" in out
    # Placeholders must be resolved, not left literal.
    assert "{org_name}" not in out
    assert "{org_structural_fault}" not in out
    assert "{org_levers}" not in out
