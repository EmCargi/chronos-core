"""Regression: roster rows linked to a Character Markdown surface greetings.

The vault `Character Markdowns/` are the canonical source of truth for
greetings (engine.guild_roster.get_character_greetings parses them). This test
locks that linking a row to a real markdown file yields parseable greetings,
and that a missing/unset source yields an empty list — the exact contract the
greeting linker (link_greetings_dryrun.py) depends on.

Reads the real vault markdown files (read-only); the roster DB itself is a
throwaway temp DB, so live data/ is never touched.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

import engine.guild_roster as gr

VAULT = "/home/megane/dev/digital-dm-project/guild-rpg-digital-dm/Characters/Official AK Characters/Character Markdowns"
SAMPLE = {
    "Eira": f"{VAULT}/A-Rank/Eira A-Rank.md",
    "Belne": f"{VAULT}/D-Rank/Belne D-Rank.md",
    "Kari": f"{VAULT}/B-Rank/Kari B-Rank.md",
}


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(gr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(gr, "ROSTER_PATH", str(data_dir / "test_roster.db"))
    gr.init_roster_db()
    return gr


CHAR = {
    "name": "Test",
    "rank_label": "Test",
    "race": "Human",
    "points_budget": 75,
    "stat_body": 5,
    "stat_mind": 5,
    "stat_soul": 5,
}


def _seed(db, name, md_path):
    c = dict(CHAR, name=name)
    db.upsert_character("guild_rpg", c, "{}", "t.json")
    if md_path:
        db.set_character_md_path("guild_rpg", name, md_path)


def test_markdown_with_greetings_surfaces_them(db):
    # Eira/Belne markdown files contain parseable greeting blocks.
    for name, path in (("Eira", SAMPLE["Eira"]), ("Belne", SAMPLE["Belne"])):
        assert os.path.exists(path), f"source markdown missing: {path}"
        _seed(db, name, path)
        greetings = db.get_character_greetings("guild_rpg", name)
        assert greetings, f"{name} should have >=1 greeting from {path}"
        assert greetings[0]["scene"] or greetings[0]["text"]


def test_card_without_greeting_blocks_links_but_empty(db, tmp_path):
    # A linked card with no parseable greeting block still links as the source
    # of truth, but yields no greetings until authored. Use a hermetic card so
    # the assertion does not depend on any live vault character's greeting state.
    card = tmp_path / "NoGreetings.md"
    card.write_text(
        "Name: Ghost\nDescription\n\nGhost is a shy specter with no greetings yet.\n",
        encoding="utf-8",
    )
    _seed(db, "Ghost", str(card))
    assert db.get_character_greetings("guild_rpg", "Ghost") == []


def test_missing_source_yields_empty(db):
    _seed(db, "Phantom", "/no/such/file.md")
    assert db.get_character_greetings("guild_rpg", "Phantom") == []
