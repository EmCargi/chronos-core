"""Disc registry — resolves a setting_id to its roster database.

Per-disc roster DBs (2026-09-13): each disc owns its roster DB at
`<disc-root>/.../data/<setting_id>.db`. This module builds a lazy, in-memory
manifest keyed by the resolved `DISC_DB_DIRS` config, mapping setting_id →
db_path so the engine can re-point the shared roster/economy connections at a
disc's own database. Non-disc settings fall back to the shared
`guild_rpg_roster.db`.

Two disc-root layouts are supported (both scanned per root):
- `demo-discs/<disc>/data/<setting_id>.db` — the Anime Multiverse set (each
  subdir is a disc folder).
- `<disc-folder>/data/<setting_id>.db` — a disc folder configured directly as a
  root (e.g. `guild-rpg-digital-dm/data/guild_rpg.db`).

Design rules (CP-1..CP-5 / OQ-1..OQ-2 of the approved proposal):
- The manifest keys off the FILE NAME (`data/<setting_id>.db`), never the disc
  DB's `settings` table — `init_roster_db()` seeds all 13 DEFAULT_SETTINGS into
  whatever DB it opens, so reading the table would make every disc claim every
  setting.
- The manifest builds LAZILY on first resolver call, not at module import —
  the test suite redirects DB paths per-fixture via monkeypatch, and an eager
  cache would freeze the manifest before those redirects. A change to the
  resolved DISC_DB_DIRS invalidates it naturally; `refresh=True` forces a rebuild.
- DISC_DB_DIRS resolves relative to BASE_DIR (CP-2), never os.getcwd().
"""

import os
import sqlite3

from .config import BASE_DIR, load_settings


def _resolve_disc_dirs() -> list[str]:
    """Resolve the configured disc roots relative to BASE_DIR (CP-2), or [] if unset.

    Accepts `DISC_DB_DIRS` (list) or the legacy `DISC_DB_DIR` (single string)
    from config/settings.json, plus the CHRONOS_DISC_DB_DIR env var. Empty/absent
    => feature off (shared DB only, byte-identical behavior).
    """
    settings = load_settings()
    raw = os.environ.get("CHRONOS_DISC_DB_DIR")
    if raw:
        dirs = [raw]
    else:
        dirs = settings.get("DISC_DB_DIRS") or []
        if not dirs and settings.get("DISC_DB_DIR"):
            dirs = [settings["DISC_DB_DIR"]]
    resolved = []
    for d in dirs:
        if d:
            resolved.append(os.path.normpath(os.path.join(BASE_DIR, d)))
    return resolved


def build_disc_manifest(disc_roots: list[str]) -> dict:
    """Scan each root for `data/<setting_id>.db` and map filename → db path.

    Per root, both layouts are scanned: `root/*/data/*.db` (demo-discs: each
    subdir is a disc folder) and `root/data/*.db` (a disc folder configured
    directly as a root, e.g. guild-rpg-digital-dm). The setting_id is derived
    from the DB FILE NAME (`besm_enid.db` → `besm_enid`), never from the disc
    DB's `settings` table contents (CP-1) — that table can carry the 13 seeded
    DEFAULT_SETTINGS rows, which would map every disc to every setting. Each
    disc DB's own settings row is read only for display metadata.
    """
    manifest = {}
    for disc_root in disc_roots:
        if not os.path.isdir(disc_root):
            continue
        # Layout A: root/<disc>/data/<setting>.db
        for disc_dir in sorted(os.listdir(disc_root)):
            data_dir = os.path.join(disc_root, disc_dir, "data")
            if os.path.isdir(data_dir):
                for fname in sorted(os.listdir(data_dir)):
                    if fname.endswith(".db"):
                        manifest[fname[:-3]] = os.path.join(data_dir, fname)
        # Layout B: root/data/<setting>.db (the root itself is a disc folder)
        data_dir = os.path.join(disc_root, "data")
        if os.path.isdir(data_dir):
            for fname in sorted(os.listdir(data_dir)):
                if fname.endswith(".db"):
                    manifest[fname[:-3]] = os.path.join(data_dir, fname)
    return manifest


_MANIFEST_CACHE: dict[tuple, dict] = {}  # tuple(roots) -> {setting_id: db_path}


def _roots_key() -> tuple[str, ...]:
    return tuple(_resolve_disc_dirs())


def _manifest() -> dict:
    """Cached manifest lookup (lazy, OQ-1). Builds once per disc-root tuple; a
    changed config gets its own entry. refresh=True forces a rebuild."""
    key = _roots_key()
    if not key:
        return {}
    if key not in _MANIFEST_CACHE:
        _MANIFEST_CACHE[key] = build_disc_manifest(list(key))
    return _MANIFEST_CACHE[key]


def _manifest_refresh() -> dict:
    key = _roots_key()
    if not key:
        return {}
    _MANIFEST_CACHE[key] = build_disc_manifest(list(key))
    return _MANIFEST_CACHE[key]


def resolve_roster_db(setting_id: str, refresh: bool = False) -> str:
    """Return the disc DB path for `setting_id`, or the shared roster DB.

    Non-disc settings (shota_x_monsters, my_hero_academia, cyberpunk_2077) and
    any setting with no disc root resolve to the shared `guild_rpg_roster.db`.
    `refresh=True` forces a manifest rebuild (splitter).
    """
    from .guild_roster import ROSTER_PATH

    manifest = _manifest_refresh() if refresh else _manifest()
    return manifest.get(setting_id, ROSTER_PATH)


def disc_settings() -> list:
    """Return each disc's own settings row (metadata only) as a list of dicts.

    Reads the `settings` table of every resolved disc DB and returns ONLY the
    row whose setting_id matches the disc's filename — the disc DB may carry the
    13 seeded DEFAULT_SETTINGS rows, so the filename is the authority (CP-1).
    """
    out = []
    for setting_id, db_path in _manifest().items():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM settings WHERE setting_id = ?", (setting_id,)
                ).fetchone()
        except sqlite3.Error:
            continue
        if row:
            out.append(dict(row))
    return out


def list_settings_merged(shared_settings: list) -> list:
    """Merge shared DB settings with the disc manifest (disc DBs win on overlap).

    `shared_settings` comes from the shared roster DB (guild_roster.list_settings').
    Any setting the manifest owns is dropped from the shared list and replaced
    by the disc DB's own metadata row.
    """
    manifest = _manifest()
    if not manifest:
        return shared_settings
    owned = set(manifest.keys())
    shared = [s for s in shared_settings if s["setting_id"] not in owned]
    merged = shared + disc_settings()
    merged.sort(key=lambda s: s["setting_id"])
    return merged


def set_active_setting(setting_id: str, refresh: bool = False) -> str:
    """Re-point the roster + economy connections to the setting's DB (CP-1).

    Resolves the DB for `setting_id`, redirects guild_roster.ACTIVE_ROSTER_PATH
    and economy.ACTIVE_ROSTER_PATH, then runs schema + additive migrations ONLY
    (never seed_default_settings — seeding would pollute a disc DB's settings
    table and corrupt the manifest). Returns the active DB path.
    """
    from . import guild_roster
    from . import economy

    path = resolve_roster_db(setting_id, refresh=refresh)
    guild_roster.set_active_roster_path(path)
    economy.set_active_roster_path(path)
    guild_roster.apply_schema_migrations()
    return path