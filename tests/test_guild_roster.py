"""Tests for roster CRUD + BESM loadout (engine/guild_roster.py).

Runs against a throwaway SQLite DB in tmp_path — the real
data/guild_rpg_roster.db is never touched.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

import engine.guild_roster as gr


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    """Redirect roster globals to a temp DB and init fresh schema."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(gr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(gr, "ROSTER_PATH", str(data_dir / "test_roster.db"))
    gr.init_roster_db()
    return gr


CHAR = {
    "name": "Eira",
    "rank_label": "S-Rank",
    "race": "High Elf",
    "points_budget": 120,
    "stat_body": 7,
    "stat_mind": 9,
    "stat_soul": 8,
}


class TestInitAndSettings:
    def test_init_creates_tables(self, db):
        with db.get_roster_connection() as conn:
            for table in ("settings", "characters", "power_packs"):
                assert conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()

    def test_default_settings_seeded(self, db):
        assert db.get_setting("guild_rpg")["character_label"] == "Guild Rank"
        assert db.get_setting("besm_disc")["character_label"] == "Monster Tier"

    def test_register_setting_upserts(self, db):
        db.register_setting("test_realm", "Test Realm", "A sandbox", character_label="Tier")
        row = db.get_setting("test_realm")
        assert row["name"] == "Test Realm"
        db.register_setting("test_realm", "Test Realm Renamed", character_label="Rank")
        assert db.get_setting("test_realm")["name"] == "Test Realm Renamed"


class TestCharacterCRUD:
    def test_upsert_and_get_roundtrip(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "test.json")
        c = db.get_character("guild_rpg", "Eira")
        assert c["stat_mind"] == 9
        assert c["max_hp"] == (7 + 8) * 5
        assert c["max_ep"] == (9 + 8) * 5

    def test_defaults_applied(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "test.json")
        c = db.get_character("guild_rpg", "Eira")
        assert c["rank_label"] == "S-Rank"
        assert c["race"] == "High Elf"
        assert c["sixth_guard"] == ""

    def test_upsert_overwrites_on_conflict(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "a.json")
        variant = dict(CHAR, stat_body=10, rank_label="SS-Rank")
        db.upsert_character("guild_rpg", variant, "{}", "b.json")
        c = db.get_character("guild_rpg", "Eira")
        assert c["stat_body"] == 10
        assert c["rank_label"] == "SS-Rank"

    def test_narrative_syntax_persisted(self, db):
        char = dict(CHAR, sixth_guard="Never break the veil.",
                    structural_fault="Loyal to a fault.", levers="Principle;Memory;Fear")
        db.upsert_character("guild_rpg", char, "{}", "t.json")
        c = db.get_character("guild_rpg", "Eira")
        assert c["sixth_guard"] == "Never break the veil."
        assert c["levers"] == "Principle;Memory;Fear"

    def test_missing_character_returns_none(self, db):
        assert db.get_character("guild_rpg", "Nobody") is None

    def test_list_characters_filtered_by_setting(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        db.upsert_character("besm_disc", dict(CHAR, name="Slime"), "{}", "t.json")
        assert len(db.list_characters(setting_id="guild_rpg")) == 1
        assert len(db.list_characters(setting_id="besm_disc")) == 1
        assert len(db.list_characters()) == 2

    def test_list_characters_rank_filter(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        db.upsert_character("guild_rpg", dict(CHAR, name="Trainee", rank_label="C-Rank"), "{}", "t.json")
        names = [c["name"] for c in db.list_characters(rank_filter="S-Rank")]
        assert names == ["Eira"]


class TestPowerPacks:
    def test_add_and_list(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        db.add_power_pack("guild_rpg", "Eira", "Blade Oath", "t.json")
        db.add_power_pack("guild_rpg", "Eira", "Sanctuary", "t.json")
        packs = db.get_character_power_packs("guild_rpg", "Eira")
        assert [p["pack_name"] for p in packs] == ["Blade Oath", "Sanctuary"]

    def test_add_power_pack_idempotent(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        db.add_power_pack("guild_rpg", "Eira", "Blade Oath", "t.json")
        db.add_power_pack("guild_rpg", "Eira", "Blade Oath", "t.json")
        assert len(db.get_character_power_packs("guild_rpg", "Eira")) == 1

    def test_purge_junk_packages(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        db.add_power_pack("guild_rpg", "Eira", "None — no packs yet", "t.json")
        db.add_power_pack("guild_rpg", "Eira", "no special abilities", "t.json")
        db.add_power_pack("guild_rpg", "Eira", "Blade Oath", "t.json")
        assert db.purge_junk_power_packs() == 2
        assert [p["pack_name"] for p in db.get_character_power_packs("guild_rpg", "Eira")] == ["Blade Oath"]


class TestBESMLoadout:
    def test_compute_shock_value_base(self, db):
        assert db.compute_shock_value(100, []) == 20

    def test_compute_shock_value_hardboiled(self, db):
        techniques = [{"name": "Hardboiled", "level": 2, "effect": "+20 SV"}]
        assert db.compute_shock_value(100, techniques) == 40

    def test_compute_shock_value_capped_at_half_hp(self, db):
        tech = [{"name": "Hardboiled", "level": 9, "effect": ""}]
        assert db.compute_shock_value(50, tech) == 25

    def test_update_and_get_loadout(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        techniques = [{"name": "Hardboiled", "level": 1, "effect": "+10 SV"}]
        skills = [{"name": "Swordsmanship", "rank": 3, "stat": "Body", "specialisation": "Longsword"}]
        defects = [{"name": "Fragile", "rank": 1, "cp": 15, "trigger": "Physical trauma"}]
        db.update_character_loadout("guild_rpg", "Eira", techniques, skills, defects)
        lo = db.get_character_loadout("guild_rpg", "Eira")
        assert lo["shock_value"] == db.compute_shock_value((7 + 8) * 5, techniques)
        assert lo["combat_techniques"][0]["name"] == "Hardboiled"
        assert lo["skills"][0]["specialisation"] == "Longsword"
        assert lo["defects"][0]["name"] == "Fragile"
        assert lo["narrative_syntax"]["structural_fault"] == ""

    def test_update_loadout_missing_character_is_safe(self, db):
        db.update_character_loadout("guild_rpg", "Ghost", [], [], [])

    def test_loadout_formats_summary(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        lo = db.get_character_loadout("guild_rpg", "Eira")
        summary = db.format_loadout_summary(lo)
        assert "Eira" in summary and "120 CP" in summary
        assert "7] S8" in summary or "B7" in summary


class TestSummaries:
    def test_roster_summary_lists_characters(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        out = db.roster_summary("guild_rpg")
        assert "Eira" in out and "High Elf" in out and "ACV" in out

    def test_roster_summary_empty_setting(self, db):
        assert "No characters" in db.roster_summary("besm_disc")

    def test_roster_summary_no_setting_empty_db(self, db):
        assert "empty" in db.roster_summary()


class TestMarkdownGreetings:
    def test_clean_markdown_greetings(self, db):
        md = (
            "**Profile header**\n\n"
            "---\n"
            "*You enter the candlelit hall.*\n"
            "\"Welcome, adventurer,\" she says, smiling.\n"
            "More prose continues here beyond the minimum length."
        )
        greetings = db.parse_greetings_from_markdown(md)
        assert greetings and greetings[0]["scene"]
        assert "Welcome, adventurer" in greetings[0]["opening"]

    def test_get_greetings_uses_md_path(self, db, tmp_path: Path):
        md_file = tmp_path / "eira.md"
        md_file.write_text(
            "**Profile header**\n\n"
            "---\n"
            "*Scene: A quiet garden in morning light, dew still on the rose bushes.*\n"
            "\"Hello there,\" she says softly, tilting her head to one side as she waits.\n"
            "The garden stretches behind her, long and green and calm under the new sun."
        )
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        db.set_character_md_path("guild_rpg", "Eira", str(md_file))
        greetings = db.get_character_greetings("guild_rpg", "Eira")
        assert greetings and greetings[0]["scene"]
        assert "Hello there" in greetings[0]["opening"]

    def test_greetings_missing_md_path_empty(self, db):
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        assert db.get_character_greetings("guild_rpg", "Eira") == []

    def test_greetings_section_format(self, db, tmp_path: Path):
        # Newer authoring format: an explicit GREETINGS: header followed by
        # prose blocks separated by --- (no *scene* italic marker required).
        md = (
            "Profile text.\n\n"
            "---\n\n"
            "### DM COMBAT CHEAT SHEET\n\n"
            "rules and numbers here.\n\n"
            "GREETINGS:\n\n"
            "{{char}} leaned against the guild hall bar, smirking.\n"
            '"Well, well… an A-rank," he said.\n\n'
            "---\n\n"
            "The forest was thick with shadows. {{user}} stepped back.\n"
            '"Brave, or foolish?" he mused.\n'
        )
        md_file = tmp_path / "k.md"
        md_file.write_text(md)
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        db.set_character_md_path("guild_rpg", "Eira", str(md_file))
        greetings = db.get_character_greetings("guild_rpg", "Eira")
        assert len(greetings) == 2
        # SillyTavern tokens normalized to name / "you"
        assert "Eira" in greetings[0]["text"]
        assert "you" in greetings[1]["text"]
        assert "{{char}}" not in greetings[0]["text"]

    def test_greetings_alternate_export_format(self, db, tmp_path: Path):
        # SillyTavern export: 'First Message' / 'Alternate Greeting N' headers
        # delimit blocks (no | table, no --- separators).
        md = (
            "### Basic\n- Name: Morwen\n\n"
            "First Message (347 token(s))\n"
            "*The guild hall was quiet.* \"Hello!\" she waved.\n"
            "![](https://example.com/x.png)\n\n"
            "Alternate Greetings\n"
            "Alternate Greeting 1\n"
            "*You found her at the graveyard.* \"Join my tea party?\"\n"
            "Alternate Greeting 2\n"
            "*A festival of lights filled the guild district with warm lanterns.* "
            "\"Is it not wonderful?\" she asked, holding out a small basket of sweets.\n"
        )
        md_file = tmp_path / "m.md"
        md_file.write_text(md)
        db.upsert_character("guild_rpg", CHAR, "{}", "t.json")
        db.set_character_md_path("guild_rpg", "Eira", str(md_file))
        greetings = db.get_character_greetings("guild_rpg", "Eira")
        assert len(greetings) == 3
        # Image embeds stripped, narrative preserved
        assert "![](https://example.com/x.png)" not in greetings[0]["text"]
        assert "Hello!" in greetings[0]["text"]


class TestThreatsLocationsTournaments:
    def test_threat_catalog_seeded_and_queried(self, db):
        db.seed_threat_catalog("guild_rpg")
        t = db.get_threat("guild_rpg", "zarkhoth")
        assert t and t["name"] == "Zarkhoth" and t["max_hp"] == 110
        assert len(db.list_threats("guild_rpg")) == 4
        bosses = db.list_threats("guild_rpg", threat_type="boss")
        assert len(bosses) == 2

    def test_locations_seeded_and_filtered(self, db):
        db.seed_locations("guild_rpg")
        assert len(db.list_locations("guild_rpg")) == 15
        assert db.get_location("guild_rpg", "hemlock")["name"] == "Hemlock"
        capitals = db.list_locations("guild_rpg", location_type="capital")
        assert len(capitals) == 1

    def test_tournaments_seeded_and_listed(self, db):
        db.seed_tournaments("guild_rpg")
        ts = db.list_tournaments("guild_rpg")
        assert len(ts) == 3
        assert any(t["tournament_id"] == "capital_arena_spring" for t in ts)