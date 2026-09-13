"""Tests for per-disc roster DB routing (engine/disc_registry.py).

Covers the approved proposal rulings:
- CP-1: filename-keyed manifest (immune to seeded settings), migrations-only on
  disc switch (never seed_default_settings).
- CP-2: DISC_DB_DIRS resolve relative to BASE_DIR.
- OQ-1: lazy manifest; refresh=True rebuilds.
- OQ-2: --prune-shared gates (timestamped checkpoint + disc presence) — the
  splitter's gate logic is unit-tested via the registry manifest here; the
  splitter script itself is exercised in a smoke test.
- Multi-root (2026-09-13): DISC_DB_DIRS is a list; both the demo-discs layout
  (root/<disc>/data/) and a direct disc-folder root (root/data/) are scanned.

Runs entirely against tmp_path — the live data/ and demo-discs/ are never touched.
"""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

from engine import disc_registry as dr
from engine import guild_roster as gr
from engine import economy as ec


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    """Redirect shared DB + disc roots to tmp, and reset the active-path sentinels."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shared = data_dir / "guild_rpg_roster.db"

    monkeypatch.setattr(gr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(gr, "ROSTER_PATH", str(shared))
    gr.set_active_roster_path(None)          # reset sentinel -> shared
    ec.set_active_roster_path(str(shared))   # economy follows the shared DB

    # Two roots: demo-discs (root/<disc>/data/) and a direct disc folder (root/data/)
    demo_root = tmp_path / "demo-discs"
    demo_root.mkdir()
    guild_root = tmp_path / "guild-rpg-digital-dm"
    guild_root.mkdir()
    monkeypatch.setattr(dr, "load_settings",
                        lambda: {"DISC_DB_DIRS": [str(demo_root), str(guild_root)]})

    gr.init_roster_db()
    gr.seed_default_settings()

    # Demo layout: demo-discs/enid-digital-dm/data/besm_enid.db
    disc_data = demo_root / "enid-digital-dm" / "data"
    disc_data.mkdir(parents=True)
    _make_disc_db(disc_data / "besm_enid.db", "besm_enid", "Enid: Heavy Weather")
    # Direct layout: guild-rpg-digital-dm/data/guild_rpg.db
    guild_data = guild_root / "data"
    guild_data.mkdir(parents=True)
    _make_disc_db(guild_data / "guild_rpg.db", "guild_rpg", "Aelthar Keldor: Guild RPG")
    return {"data": data_dir, "shared": shared, "demo_root": demo_root, "guild_root": guild_root}


def _make_disc_db(path: Path, setting_id: str, name: str) -> None:
    """Create a minimal per-disc DB with its own settings row + one character."""
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE settings (setting_id TEXT PRIMARY KEY, name TEXT, "
                     "description TEXT DEFAULT '', default_module TEXT DEFAULT '', "
                     "character_label TEXT DEFAULT 'Rank', setting_lore TEXT DEFAULT '')")
        conn.execute("CREATE TABLE characters (setting_id TEXT, name TEXT, rank_label TEXT, "
                     "race TEXT, points_budget INTEGER, stat_body INTEGER, stat_mind INTEGER, "
                     "stat_soul INTEGER, acv INTEGER, dcv INTEGER, max_hp INTEGER, max_ep INTEGER, "
                     "PRIMARY KEY (setting_id, name))")
        conn.execute("INSERT INTO settings (setting_id, name) VALUES (?, ?)",
                     (setting_id, name))
        conn.execute(
            "INSERT INTO characters (setting_id, name, rank_label, race, points_budget, "
            "stat_body, stat_mind, stat_soul, acv, dcv, max_hp, max_ep) "
            "VALUES (?, 'Lyra Vance', 'Clearance', 'Human', 50, 5, 6, 5, 6, 4, 50, 55)",
            (setting_id,))


class TestDiscDirResolution:
    def test_absent_config_is_off(self, env, monkeypatch):
        monkeypatch.setattr(dr, "load_settings", lambda: {})
        assert dr._resolve_disc_dirs() == []

    def test_resolves_relative_to_base(self, env):
        # env forces the disc roots to absolute tmp paths; verify the relative
        # resolution logic maps through BASE_DIR when given a relative value.
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(dr, "load_settings",
                            lambda: {"DISC_DB_DIRS": ["../demo-discs", "../guild-rpg-digital-dm"]})
        resolved = dr._resolve_disc_dirs()
        assert resolved == [
            os.path.normpath(os.path.join(gr.BASE_DIR, "../demo-discs")),
            os.path.normpath(os.path.join(gr.BASE_DIR, "../guild-rpg-digital-dm")),
        ]
        monkeypatch.undo()

    def test_legacy_single_dir_still_works(self, env, monkeypatch):
        monkeypatch.setattr(dr, "load_settings",
                            lambda: {"DISC_DB_DIR": "../demo-discs"})
        assert dr._resolve_disc_dirs() == [
            os.path.normpath(os.path.join(gr.BASE_DIR, "../demo-discs"))]


class TestManifest:
    def test_manifest_scans_both_layouts(self, env):
        m = dr.build_disc_manifest([str(env["demo_root"]), str(env["guild_root"])])
        assert m == {
            "besm_enid": str(env["demo_root"] / "enid-digital-dm" / "data" / "besm_enid.db"),
            "guild_rpg": str(env["guild_root"] / "data" / "guild_rpg.db"),
        }

    def test_manifest_ignores_settings_table(self, env):
        # CP-1: even if a disc DB's settings table is polluted with all 13 rows,
        # the manifest keys off the FILENAME and maps only to its own setting.
        with sqlite3.connect(env["demo_root"] / "enid-digital-dm" / "data" / "besm_enid.db") as conn:
            conn.execute("INSERT INTO settings (setting_id, name) VALUES ('shota_x_monsters', 'SxM')")
        m = dr.build_disc_manifest([str(env["demo_root"])])
        assert set(m.keys()) == {"besm_enid"}


class TestResolve:
    def test_disc_setting_resolves_to_disc(self, env):
        assert dr.resolve_roster_db("besm_enid") == \
            str(env["demo_root"] / "enid-digital-dm" / "data" / "besm_enid.db")
        assert dr.resolve_roster_db("guild_rpg") == \
            str(env["guild_root"] / "data" / "guild_rpg.db")

    def test_shared_setting_falls_back(self, env):
        assert dr.resolve_roster_db("my_hero_academia") == str(env["shared"])
        assert dr.resolve_roster_db("shota_x_monsters") == str(env["shared"])

    def test_no_disc_root_falls_back(self, env, monkeypatch):
        monkeypatch.setattr(dr, "load_settings", lambda: {})
        assert dr.resolve_roster_db("besm_enid") == str(env["shared"])
        assert dr.resolve_roster_db("guild_rpg") == str(env["shared"])


class TestListSettingsMerged:
    def test_merge_dedupes_disc_win(self, env):
        shared = [{"setting_id": "guild_rpg", "name": "stale shared row"},
                  {"setting_id": "besm_enid", "name": "stale shared row"},
                  {"setting_id": "my_hero_academia", "name": "MHA"}]
        merged = dr.list_settings_merged(shared)
        ids = [s["setting_id"] for s in merged]
        assert ids == ["besm_enid", "guild_rpg", "my_hero_academia"]
        # disc DB's metadata wins for both
        enid = next(s for s in merged if s["setting_id"] == "besm_enid")
        guild = next(s for s in merged if s["setting_id"] == "guild_rpg")
        assert enid["name"] == "Enid: Heavy Weather"
        assert guild["name"] == "Aelthar Keldor: Guild RPG"

    def test_no_disc_root_returns_shared(self, env, monkeypatch):
        monkeypatch.setattr(dr, "load_settings", lambda: {})
        shared = [{"setting_id": "guild_rpg", "name": "Guild"}]
        assert dr.list_settings_merged(shared) == shared


class TestSetActiveSetting:
    def test_disc_switch_reads_disc_db(self, env):
        dr.set_active_setting("besm_enid")
        chars = gr.list_characters("besm_enid")
        assert [c["name"] for c in chars] == ["Lyra Vance"]
        assert ec.ACTIVE_ROSTER_PATH == str(env["demo_root"] / "enid-digital-dm" / "data" / "besm_enid.db")

    def test_guild_switch_reads_guild_db(self, env):
        dr.set_active_setting("guild_rpg")
        chars = gr.list_characters("guild_rpg")
        assert [c["name"] for c in chars] == ["Lyra Vance"]
        assert ec.ACTIVE_ROSTER_PATH == str(env["guild_root"] / "data" / "guild_rpg.db")

    def test_disc_switch_does_not_seed(self, env):
        # CP-1: migrations run, but the disc DB's settings table keeps ONE row.
        dr.set_active_setting("besm_enid")
        with sqlite3.connect(env["demo_root"] / "enid-digital-dm" / "data" / "besm_enid.db") as conn:
            rows = conn.execute("SELECT setting_id FROM settings").fetchall()
        assert [r[0] for r in rows] == ["besm_enid"]

    def test_back_to_shared(self, env):
        dr.set_active_setting("besm_enid")
        dr.set_active_setting("my_hero_academia")
        assert gr.list_characters("my_hero_academia") is not None
        assert ec.ACTIVE_ROSTER_PATH == str(env["shared"])

    def test_list_settings_stays_complete_after_disc_switch(self, env):
        # list_settings() must still see the shared settings while on a disc DB.
        dr.set_active_setting("besm_enid")
        ids = [s["setting_id"] for s in gr.list_settings()]
        assert "my_hero_academia" in ids
        assert "besm_enid" in ids
        assert "guild_rpg" in ids


class TestRefresh:
    def test_refresh_rebuilds_manifest(self, env):
        before = dr.resolve_roster_db("besm_enid")
        # add a second demo disc, then resolve WITHOUT refresh (stale) and WITH refresh
        extra_data = env["demo_root"] / "ikaris-digital-dm" / "data"
        extra_data.mkdir(parents=True)
        _make_disc_db(extra_data / "besm_ikaris.db", "besm_ikaris", "Ikaris: Swords & Sorcery")
        assert dr.resolve_roster_db("besm_ikaris") == str(env["shared"])  # stale cache
        assert dr.resolve_roster_db("besm_ikaris", refresh=True) == \
            str(extra_data / "besm_ikaris.db")
        assert before == str(env["demo_root"] / "enid-digital-dm" / "data" / "besm_enid.db")