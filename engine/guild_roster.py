import os
import re
import shutil
import sqlite3
import json
import logging
from datetime import datetime

logger = logging.getLogger("ChronosCore.GuildRoster")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ROSTER_PATH = os.path.join(DATA_DIR, "guild_rpg_roster.db")

from .config import DEFAULT_SETTINGS

def get_roster_connection() -> sqlite3.Connection:
    """Safely connects to data/guild_rpg_roster.db with standard context manager."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(ROSTER_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_roster_db() -> None:
    """
    Sets up the universal setting catalog tables:
    - settings (setting_id, name, description, default_module, character_label)
    - characters (setting_id, name, rank_label, race, points_budget, body, mind, soul,
      acv, dcv, max_hp, max_ep, card_json, source_path, ingested_at)
    - power_packs (setting_id, character_name, pack_name, source_path)
    This database is the single source of truth for official character stats across
    every registered setting; chronos_session.db holds only runtime session state.
    """
    with get_roster_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                setting_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                default_module TEXT NOT NULL DEFAULT '',
                character_label TEXT NOT NULL DEFAULT 'Rank'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                setting_id TEXT NOT NULL,
                name TEXT NOT NULL,
                rank_label TEXT NOT NULL DEFAULT 'Unranked',
                race TEXT NOT NULL DEFAULT 'Unknown',
                points_budget INTEGER NOT NULL DEFAULT 75,
                stat_body INTEGER NOT NULL,
                stat_mind INTEGER NOT NULL,
                stat_soul INTEGER NOT NULL,
                acv INTEGER NOT NULL DEFAULT 5,
                dcv INTEGER NOT NULL DEFAULT 5,
                max_hp INTEGER NOT NULL,
                max_ep INTEGER NOT NULL,
                sixth_guard TEXT NOT NULL DEFAULT '',
                structural_fault TEXT NOT NULL DEFAULT '',
                levers TEXT NOT NULL DEFAULT '',
                card_json TEXT NOT NULL,
                source_path TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                PRIMARY KEY (setting_id, name),
                FOREIGN KEY (setting_id) REFERENCES settings(setting_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS power_packs (
                setting_id TEXT NOT NULL,
                character_name TEXT NOT NULL,
                pack_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                PRIMARY KEY (setting_id, character_name, pack_name),
                FOREIGN KEY (setting_id, character_name) REFERENCES characters(setting_id, name)
            )
        """)
    migrate_roster_multi_setting()
    migrate_roster_narrative_syntax()
    migrate_roster_besm_columns()
    seed_default_settings()
    init_locations_table()
    init_organizations_table()
    logger.info(f"Guild RPG roster database initialized at {ROSTER_PATH}.")

def migrate_roster_multi_setting() -> None:
    """
    One-time migration: the original roster stored characters with `name` as the sole
    PRIMARY KEY and a hardcoded `guild_rank` column. To support any number of settings,
    characters are rebuilt with a composite PRIMARY KEY (setting_id, name), `guild_rank`
    is renamed to `rank_label`, and power_packs gain setting_id. Existing rows are
    backfilled to the guild_rpg setting. A checkpoint backup is taken first.
    """
    if not os.path.exists(ROSTER_PATH):
        return
    with sqlite3.connect(ROSTER_PATH) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall()]
        pks = [r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall() if r[5]]
        if "guild_rank" not in cols and pks == ["setting_id", "name"]:
            return

        # Backup before destructive migration.
        checkpoint_dir = os.path.join(DATA_DIR, "checkpoints")
        os.makedirs(checkpoint_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(checkpoint_dir, f"roster_pre_multi_setting_{timestamp}.db")
        shutil.copy2(ROSTER_PATH, backup_path)
        logger.info(f"Roster migration checkpoint saved to {backup_path}")

        logger.info("Migrating roster to multi-setting schema (composite PK + rank_label).")
        conn.execute("ALTER TABLE characters RENAME TO characters_old")
        conn.execute("""
            CREATE TABLE characters (
                setting_id TEXT NOT NULL,
                name TEXT NOT NULL,
                rank_label TEXT NOT NULL DEFAULT 'Unranked',
                race TEXT NOT NULL DEFAULT 'Unknown',
                points_budget INTEGER NOT NULL DEFAULT 75,
                stat_body INTEGER NOT NULL,
                stat_mind INTEGER NOT NULL,
                stat_soul INTEGER NOT NULL,
                acv INTEGER NOT NULL DEFAULT 5,
                dcv INTEGER NOT NULL DEFAULT 5,
                max_hp INTEGER NOT NULL,
                max_ep INTEGER NOT NULL,
                card_json TEXT NOT NULL,
                source_path TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                PRIMARY KEY (setting_id, name),
                FOREIGN KEY (setting_id) REFERENCES settings(setting_id)
            )
        """)
        conn.execute("""
            INSERT INTO characters (
                setting_id, name, rank_label, race, points_budget, stat_body, stat_mind,
                stat_soul, acv, dcv, max_hp, max_ep, card_json, source_path, ingested_at
            )
            SELECT 'guild_rpg', name, guild_rank, race, points_budget, stat_body, stat_mind,
                stat_soul, acv, dcv, max_hp, max_ep, card_json, source_path, ingested_at
            FROM characters_old
        """)
        conn.execute("DROP TABLE characters_old")

        # Rebuild power_packs with setting_id.
        pp_cols = [r[1] for r in conn.execute("PRAGMA table_info(power_packs)").fetchall()]
        if "setting_id" not in pp_cols:
            conn.execute("ALTER TABLE power_packs RENAME TO power_packs_old")
            conn.execute("""
                CREATE TABLE power_packs (
                    setting_id TEXT NOT NULL,
                    character_name TEXT NOT NULL,
                    pack_name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    PRIMARY KEY (setting_id, character_name, pack_name),
                    FOREIGN KEY (setting_id, character_name) REFERENCES characters(setting_id, name)
                )
            """)
            conn.execute("""
                INSERT INTO power_packs (setting_id, character_name, pack_name, source_path)
                SELECT 'guild_rpg', character_name, pack_name, source_path FROM power_packs_old
            """)
            conn.execute("DROP TABLE power_packs_old")

def migrate_roster_narrative_syntax() -> None:
    """
    One-time migration: adds the narrative-syntax framework columns (sixth_guard,
    structural_fault, levers) to the characters table. These fields encode the
    Aelthar Keldor narrative syntax (Subject/Predicate, Three Levers, Sixth Guard)
    so the runtime shell can inject them into the AI Director's context.
    Non-destructive: existing rows get empty defaults.
    """
    if not os.path.exists(ROSTER_PATH):
        return
    with sqlite3.connect(ROSTER_PATH) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall()]
        for column, ddl in [
            ("sixth_guard", "sixth_guard TEXT NOT NULL DEFAULT ''"),
            ("structural_fault", "structural_fault TEXT NOT NULL DEFAULT ''"),
            ("levers", "levers TEXT NOT NULL DEFAULT ''"),
        ]:
            if column not in cols:
                conn.execute(f"ALTER TABLE characters ADD COLUMN {ddl}")
                logger.info(f"Added narrative-syntax column: characters.{column}")
    logger.info("Narrative-syntax migration complete.")

def migrate_roster_besm_columns() -> None:
    """
    One-time migration: adds BESM rules columns (combat_techniques, skills,
    defects, shock_value) to the characters table. These fields encode the new
    BESM 4e rules extraction (Combat Techniques, Skills, Defects, Shock Value)
    so the runtime shell can inject mechanical constraints into the AI Director's
    context. Non-destructive: existing rows get safe defaults.
    """
    if not os.path.exists(ROSTER_PATH):
        return
    with sqlite3.connect(ROSTER_PATH) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall()]
        for column, ddl in [
            ("combat_techniques", "combat_techniques TEXT NOT NULL DEFAULT '[]'"),
            ("skills", "skills TEXT NOT NULL DEFAULT '[]'"),
            ("defects", "defects TEXT NOT NULL DEFAULT '[]'"),
            ("shock_value", "shock_value INTEGER NOT NULL DEFAULT 0"),
            ("md_source_path", "md_source_path TEXT NOT NULL DEFAULT ''"),
        ]:
            if column not in cols:
                conn.execute(f"ALTER TABLE characters ADD COLUMN {ddl}")
                logger.info(f"Added BESM rules column: characters.{column}")
    logger.info("BESM rules migration complete.")


def compute_shock_value(max_hp: int, combat_techniques: list) -> int:
    """
    Compute modified Shock Value from base HP + Hardboiled technique.
    Base SV = Max HP // 5. Each Hardboiled level adds +10. Capped at 1/2 Max HP.
    """
    base_sv = max_hp // 5
    hardboiled_bonus = sum(
        10 * t.get("level", 1) for t in combat_techniques
        if isinstance(t, dict) and t.get("name", "").lower() == "hardboiled"
    )
    return min(base_sv + hardboiled_bonus, max_hp // 2)


def get_character_loadout(setting_id: str, name: str) -> dict:
    """
    Return the full BESM loadout for display in the TUI.
    Returns empty dict if character not found.
    """
    char = get_character(setting_id, name)
    if not char:
        return {}
    return {
        "name": char["name"],
        "rank": char["rank_label"],
        "points_budget": char["points_budget"],
        "stats": f"B{char['stat_body']} M{char['stat_mind']} S{char['stat_soul']}",
        "combat": f"ACV{char['acv']} DCV{char['dcv']} HP{char['max_hp']} EP{char['max_ep']}",
        "shock_value": char.get("shock_value", char["max_hp"] // 5),
        "combat_techniques": json.loads(char.get("combat_techniques", "[]")),
        "skills": json.loads(char.get("skills", "[]")),
        "defects": json.loads(char.get("defects", "[]")),
        "narrative_syntax": {
            "structural_fault": char.get("structural_fault", ""),
            "sixth_guard": char.get("sixth_guard", ""),
            "levers": char.get("levers", ""),
        }
    }


def format_loadout_summary(loadout: dict) -> str:
    """Format a character loadout for the narrative history panel."""
    lines = []
    lines.append(f"[bold]{loadout['name']}[/bold] — {loadout['rank']} ({loadout['points_budget']} CP)")
    lines.append(f"  Stats: {loadout['stats']} | {loadout['combat']}")
    lines.append(f"  Shock Value: [bold red]{loadout['shock_value']}[/bold red]")
    lines.append("")

    if loadout["combat_techniques"]:
        lines.append("  [bold yellow]Combat Techniques:[/bold yellow]")
        for t in loadout["combat_techniques"]:
            lines.append(f"    • [cyan]{t['name']}[/cyan] ×{t['level']} — {t['effect']}")

    if loadout["skills"]:
        lines.append("  [bold yellow]Skills:[/bold yellow]")
        for s in loadout["skills"]:
            spec = f" ({s['specialisation']})" if s.get("specialisation") else ""
            lines.append(f"    • [green]{s['name']}[/green] Rank {s['rank']}{spec} [{s['stat']}]")

    if loadout["defects"]:
        lines.append("  [bold yellow]Defects:[/bold yellow]")
        for d in loadout["defects"]:
            lines.append(f"    • [red]{d['name']}[/red] (Rank {d['rank']}, {d['cp']} CP) — {d['trigger']}")

    ns = loadout.get("narrative_syntax", {})
    if ns.get("structural_fault"):
        lines.append("")
        lines.append("  [bold magenta]Structural Fault:[/bold magenta]")
        lines.append(f"    {ns['structural_fault'][:120]}...")
    if ns.get("sixth_guard"):
        lines.append("  [bold magenta]Sixth Guard:[/bold magenta]")
        lines.append(f"    {ns['sixth_guard'][:120]}...")

    return "\n".join(lines)


def update_character_loadout(setting_id: str, name: str,
                              techniques: list, skills: list,
                              defects: list) -> None:
    """
    Update BESM rules fields for a character. Idempotent: safe to re-run.
    shock_value is recomputed from techniques.
    """
    char = get_character(setting_id, name)
    if not char:
        logger.error(f"Cannot update loadout: character '{name}' not found in [{setting_id}].")
        return
    shock = compute_shock_value(char["max_hp"], techniques)
    with get_roster_connection() as conn:
        conn.execute("""
            UPDATE characters
            SET combat_techniques = ?, skills = ?, defects = ?, shock_value = ?
            WHERE setting_id = ? AND name = ?
        """, (
            json.dumps(techniques),
            json.dumps(skills),
            json.dumps(defects),
            shock,
            setting_id,
            name
        ))
    logger.info(f"Updated BESM loadout for {name} [{setting_id}] (SV={shock}).")


def seed_default_settings() -> None:
    """Registers the built-in settings (idempotent)."""
    with get_roster_connection() as conn:
        for s in DEFAULT_SETTINGS:
            conn.execute("""
                INSERT OR IGNORE INTO settings (setting_id, name, description, default_module, character_label)
                VALUES (?, ?, ?, ?, ?)
            """, (s["setting_id"], s["name"], s["description"], s["default_module"], s["character_label"]))
    logger.info("Registered default settings.")

def register_setting(setting_id: str, name: str, description: str = "",
                     default_module: str = "", character_label: str = "Rank") -> None:
    """Upserts a custom setting into the catalog."""
    with get_roster_connection() as conn:
        conn.execute("""
            INSERT INTO settings (setting_id, name, description, default_module, character_label)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(setting_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                default_module = excluded.default_module,
                character_label = excluded.character_label
        """, (setting_id, name, description, default_module, character_label))
    logger.info(f"Registered setting: {setting_id}")

def list_settings() -> list:
    """Returns all registered settings as a list of dicts."""
    with get_roster_connection() as conn:
        rows = conn.execute("SELECT * FROM settings ORDER BY setting_id").fetchall()
        return [dict(r) for r in rows]

def get_setting(setting_id: str) -> dict | None:
    """Returns a single setting as a dict, or None."""
    with get_roster_connection() as conn:
        row = conn.execute("SELECT * FROM settings WHERE setting_id = ?", (setting_id,)).fetchone()
        return dict(row) if row else None

def upsert_character(setting_id: str, character: dict, card_json: str, source_path: str) -> None:
    """
    Inserts or replaces a canonical character row within a setting. character must include:
    name, rank_label, race, points_budget, stat_body, stat_mind, stat_soul, acv, dcv, max_hp, max_ep.
    Optional narrative-syntax fields: sixth_guard, structural_fault, levers.
    Optional BESM rules fields: combat_techniques, skills, defects, shock_value.
    """
    techniques = character.get("combat_techniques", [])
    skills = character.get("skills", [])
    defects = character.get("defects", [])
    shock = character.get("shock_value", compute_shock_value(
        character.get("max_hp", (character["stat_body"] + character["stat_soul"]) * 5),
        techniques if isinstance(techniques, list) else []
    ))
    with get_roster_connection() as conn:
        conn.execute("""
            INSERT INTO characters (
                setting_id, name, rank_label, race, points_budget, stat_body, stat_mind,
                stat_soul, acv, dcv, max_hp, max_ep, sixth_guard, structural_fault, levers,
                combat_techniques, skills, defects, shock_value,
                card_json, source_path, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(setting_id, name) DO UPDATE SET
                rank_label = excluded.rank_label,
                race = excluded.race,
                points_budget = excluded.points_budget,
                stat_body = excluded.stat_body,
                stat_mind = excluded.stat_mind,
                stat_soul = excluded.stat_soul,
                acv = excluded.acv,
                dcv = excluded.dcv,
                max_hp = excluded.max_hp,
                max_ep = excluded.max_ep,
                sixth_guard = excluded.sixth_guard,
                structural_fault = excluded.structural_fault,
                levers = excluded.levers,
                combat_techniques = excluded.combat_techniques,
                skills = excluded.skills,
                defects = excluded.defects,
                shock_value = excluded.shock_value,
                card_json = excluded.card_json,
                source_path = excluded.source_path,
                ingested_at = excluded.ingested_at
        """, (
            setting_id,
            character["name"],
            character.get("rank_label", "Unranked"),
            character.get("race", "Unknown"),
            character.get("points_budget", 75),
            character["stat_body"],
            character["stat_mind"],
            character["stat_soul"],
            character.get("acv", 5),
            character.get("dcv", 5),
            character.get("max_hp", (character["stat_body"] + character["stat_soul"]) * 5),
            character.get("max_ep", (character["stat_mind"] + character["stat_soul"]) * 5),
            character.get("sixth_guard", ""),
            character.get("structural_fault", ""),
            character.get("levers", ""),
            json.dumps(techniques),
            json.dumps(skills),
            json.dumps(defects),
            shock,
            card_json,
            source_path,
            datetime.now().isoformat()
        ))
    logger.info(f"Upserted roster character: [{setting_id}] {character['name']} (SV={shock})")

def add_power_pack(setting_id: str, character_name: str, pack_name: str, source_path: str) -> None:
    """Registers a power pack against a roster character within a setting (idempotent)."""
    with get_roster_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO power_packs (setting_id, character_name, pack_name, source_path)
            VALUES (?, ?, ?, ?)
        """, (setting_id, character_name, pack_name, source_path))
    logger.info(f"Registered power pack '{pack_name}' for [{setting_id}] {character_name}.")

def get_character(setting_id: str, name: str) -> dict | None:
    """Returns a single roster character as a dict, or None."""
    with get_roster_connection() as conn:
        row = conn.execute(
            "SELECT * FROM characters WHERE setting_id = ? AND name = ?", (setting_id, name)
        ).fetchone()
        return dict(row) if row else None

def get_character_power_packs(setting_id: str, name: str) -> list:
    """Returns the list of registered power packs for a character."""
    with get_roster_connection() as conn:
        rows = conn.execute(
            "SELECT pack_name, source_path FROM power_packs WHERE setting_id = ? AND character_name = ? ORDER BY pack_name",
            (setting_id, name)
        ).fetchall()
        return [dict(r) for r in rows]

def list_characters(setting_id: str | None = None, rank_filter: str | None = None) -> list:
    """Lists all roster characters, optionally filtered by setting and/or rank label."""
    with get_roster_connection() as conn:
        if setting_id and rank_filter:
            rows = conn.execute(
                "SELECT * FROM characters WHERE setting_id = ? AND rank_label LIKE ? ORDER BY rank_label, name",
                (setting_id, f"%{rank_filter}%")
            ).fetchall()
        elif setting_id:
            rows = conn.execute(
                "SELECT * FROM characters WHERE setting_id = ? ORDER BY rank_label, name", (setting_id,)
            ).fetchall()
        elif rank_filter:
            rows = conn.execute(
                "SELECT * FROM characters WHERE rank_label LIKE ? ORDER BY setting_id, rank_label, name",
                (f"%{rank_filter}%",)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM characters ORDER BY setting_id, rank_label, name").fetchall()
        return [dict(r) for r in rows]

def roster_summary(setting_id: str | None = None) -> str:
    """
    Human-readable summary of roster characters for the TUI.
    Header uses the setting's character_label when a setting is specified.
    """
    chars = list_characters(setting_id=setting_id)
    if not chars:
        if setting_id:
            return f"No characters registered for setting '{setting_id}'."
        return "Roster is empty. Run 'auto-ingest' to load character cards."
    lines = []
    for c in chars:
        packs = get_character_power_packs(c["setting_id"], c["name"])
        pack_str = ", ".join(p["pack_name"] for p in packs) if packs else "None"
        lines.append(
            f"  • {c['name']} [{c['rank_label']}] — {c['race']} — "
            f"Body {c['stat_body']}/Mind {c['stat_mind']}/Soul {c['stat_soul']} "
            f"({c['points_budget']} CP, ACV {c['acv']}/DCV {c['dcv']}, HP {c['max_hp']}/EP {c['max_ep']}) "
            f"Packs: {pack_str}"
        )
    return "\n".join(lines)

def purge_junk_power_packs() -> int:
    """
    Removes junk power-pack rows left by earlier parsers (e.g. the literal
    "None — ..." prose that a naive [Power Packs] parse registered as a pack).
    Returns the number of rows removed.
    """
    with get_roster_connection() as conn:
        cur = conn.execute(
            "DELETE FROM power_packs WHERE pack_name LIKE 'None%' OR pack_name LIKE 'no %'"
        )
        removed = cur.rowcount
    if removed:
        logger.info(f"Purged {removed} junk power-pack row(s).")
    return removed

def seed_shota_presets() -> None:
    """
    Seeds the Shota x Monsters 2 setting with the campaign module's character
    presets so the setting has a live roster to expand later. Idempotent.
    """
    import json as _json
    module_path = os.path.join(BASE_DIR, "modules", "forest_labyrinth_v1.json")
    if not os.path.exists(module_path):
        logger.warning("forest_labyrinth_v1.json not found; skipping SxM preset seeding.")
        return
    with open(module_path, "r", encoding="utf-8") as f:
        module_data = _json.load(f)

    rank_map = {
        "Jin": "Monster Tamer (A-Rank Heroic Tier)",
        "Mayor Ast": "Rival Tamer (C-Rank Mayor)",
        "Sage Ios": "Sage of Seals (S-Rank Apex)"
    }
    for preset in module_data.get("presets", []):
        name = preset["name"].split(" (")[0]
        body = preset.get("stat_body", 5)
        mind = preset.get("stat_mind", 5)
        soul = preset.get("stat_soul", 5)
        row = {
            "name": name,
            "rank_label": rank_map.get(name, preset["name"]),
            "race": "Human",
            "points_budget": module_data.get("points_budget", 50),
            "stat_body": body,
            "stat_mind": mind,
            "stat_soul": soul,
            "acv": (body + mind + soul) // 3,
            "dcv": max(1, (body + mind + soul) // 3 - 2),
            "max_hp": (body + soul) * 5,
            "max_ep": (mind + soul) * 5
        }
        upsert_character("shota_x_monsters", row, _json.dumps(preset), module_path)
    logger.info("Seeded Shota x Monsters 2 roster presets.")


def parse_greetings_from_markdown(md_text: str) -> list:
    """
    Extract individual greetings from a character markdown profile.
    Handles three formats:
    1. SillyTavern card table: greetings in table cells (| First Message, | Alternate Greeting N)
    2. Explicit GREETINGS: section — a header line followed by prose blocks
       separated by --- delimiters (the newer authoring format; blocks need
       not start with a *scene* italic marker).
    3. Clean markdown: greetings separated by --- delimiters, starting with *scene*
    Returns list of dicts with 'scene', 'opening', 'text' keys.
    """
    # Detect SillyTavern card table format
    if '| First Message' in md_text and '| Alternate Greeting' in md_text:
        return _parse_greetings_sillytavern_table(md_text)
    # Explicit GREETINGS: section (newer authoring format)
    section = _parse_greetings_section(md_text)
    if section is not None:
        return section
    # SillyTavern alternate-greeting export: 'First Message' / 'Alternate Greeting N'
    # headers delimit blocks (no | table, no --- separators). Headers may carry an
    # optional markdown #..###### prefix (e.g. '##### Alternate Greeting 1').
    if re.search(r"(?im)^\s*#{0,6}\s*(first message|alternating greeting|alternate greeting)\b", md_text):
        return _parse_greetings_alternate(md_text)
    return _parse_greetings_clean_markdown(md_text)


def _parse_greetings_alternate(md_text: str) -> list:
    """Parse SillyTavern alternate-greeting exports.

    Greetings are delimited by header lines like `First Message (347 token(s))`
    and `Alternate Greeting 1`, not by `---` or a `|` table. Each block's first
    long italic is treated as the scene, the first quoted line as the opening.
    """
    header_re = re.compile(
        r"(?im)^[ \t]*#{0,6}\s*(?:first message.*|alternate greeting(?=\s+\d|\s*$).*)$"
    )
    matches = list(header_re.finditer(md_text))
    if not matches:
        return []
    greetings = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        block = md_text[start:end].strip()
        if len(block) < 50:
            continue
        scene_match = re.search(r"\*([^*]{10,})\*|_([^_]{10,})_", block)
        scene = (scene_match.group(1) or scene_match.group(2) or "").strip() if scene_match else ""
        quotes = re.findall(r'"([^"]+)"', block)
        opening = quotes[0] if quotes else ""
        clean = re.sub(r"!\[.*?\]\(.*?\)", "", block)  # strip image embeds
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        if clean:
            greetings.append({"scene": scene, "opening": opening, "text": clean})
    return greetings


def _parse_greetings_section(md_text: str):
    """Parse a markdown's explicit `GREETINGS:` section.

    Returns a list of greeting dicts, or None if no GREETINGS: header exists.
    The section is everything after the header line; blocks separated by
    `---` are treated as individual greetings (regardless of leading marker).
    """
    m = re.search(r"(?im)^\s*greetings\s*:\s*$", md_text)
    if not m:
        return None
    body = md_text[m.end():]
    greetings = []
    for part in re.split(r"\n---\n", body):
        part = part.strip()
        if len(part) < 50:
            continue
        scene_match = re.search(r"\*([^*]{10,})\*|_([^_]{10,})_", part)
        scene = (scene_match.group(1) or scene_match.group(2) or "").strip() if scene_match else ""
        quotes = re.findall(r'"([^"]+)"', part)
        opening = quotes[0] if quotes else ""
        clean = re.sub(r"!\[.*?\]\(.*?\)", "", part)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        greetings.append({"scene": scene, "opening": opening, "text": clean})
    return greetings


def _parse_greetings_clean_markdown(md_text: str) -> list:
    """Parse greetings from clean markdown format (--- separated, *scene* start)."""
    parts = re.split(r'\n---\n', md_text)
    greetings = []
    for part in parts[1:]:  # Skip the profile/description section
        part = part.strip()
        if len(part) < 50:
            continue
        first_line = part.split('\n')[0].strip()
        if first_line.startswith('#') or first_line.startswith('$$') or '$$\\text{' in part[:300]:
            continue
        if not part.startswith('*'):
            continue
        scene_match = re.search(r'\*([^*]{10,})\*|_([^_]{10,})_', part)
        scene = (scene_match.group(1) or scene_match.group(2) or "").strip() if scene_match else ''
        quotes = re.findall(r'"([^"]+)"', part)
        opening = quotes[0] if quotes else ''
        clean = re.sub(r'!\[.*?\]\(.*?\)', '', part)
        clean = re.sub(r'\n{3,}', '\n\n', clean).strip()
        greetings.append({'scene': scene, 'opening': opening, 'text': clean})
    return greetings


def _parse_greetings_sillytavern_table(md_text: str) -> list:
    """Parse greetings from SillyTavern card table format."""
    lines = md_text.split('\n')
    greetings = []
    current = None

    for line in lines:
        stripped = line.lstrip('|').strip()

        # Detect greeting header rows
        is_first = 'First Message' in stripped and 'token' in stripped
        is_alternate_header = stripped == 'Alternate Greetings'
        is_alternate = stripped.startswith('Alternate Greeting') and '<br>' in stripped

        if is_first:
            current = {'label': 'First Message', 'scene': '', 'opening': '', 'text': ''}
            greetings.append(current)
        elif is_alternate_header:
            continue  # Skip the header row
        elif is_alternate:
            # Content is on the same line after <br><br>
            label = re.split(r'<br\s*/?>', stripped, maxsplit=1)[0].strip()
            current = {'label': label, 'scene': '', 'opening': '', 'text': ''}
            greetings.append(current)
            # Extract content after the label
            parts = re.split(r'<br\s*/?>', stripped, maxsplit=2)
            if len(parts) > 2:
                text = parts[2]
                text = re.sub(r'<br\s*/?>', '\n', text)
                text = re.sub(r'<[^>]+>', '', text)
                text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
                text = re.sub(r'\n{3,}', '\n\n', text).strip()
                if text:
                    current['text'] = text
        elif current is not None and stripped and not stripped.startswith('---'):
            # Multi-line greeting content
            text = re.sub(r'<br\s*/?>', '\n', stripped)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
            text = re.sub(r'\n{3,}', '\n\n', text).strip()
            if text:
                if current['text']:
                    current['text'] += '\n' + text
                else:
                    current['text'] = text

    # Post-process: extract scene and opening from accumulated text
    for g in greetings:
        text = g['text']
        if not text:
            continue
        scene_match = re.search(r'\*([^*]{10,})\*|_([^_]{10,})_', text)
        g['scene'] = scene_match.group(1).strip() if scene_match else ''
        quotes = re.findall(r'"([^"]+)"', text)
        g['opening'] = quotes[0] if quotes else ''

    return [g for g in greetings if g['text']]


def get_character_greetings(setting_id: str, name: str) -> list:
    """
    Load and parse greetings from the character's canonical markdown file.
    Uses md_source_path (set during backfill). Falls back to empty list if missing.
    """
    char = get_character(setting_id, name)
    if not char:
        return []
    md_path = char.get('md_source_path', '')
    if not md_path or not os.path.exists(md_path):
        return []
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
        greetings = parse_greetings_from_markdown(md_text)
        # Normalize SillyTavern template tokens for clean display
        for g in greetings:
            for key in ("scene", "opening", "text"):
                g[key] = (
                    g[key]
                    .replace("{{char}}", name)
                    .replace("{{user}}", "you")
                )
        return greetings
    except Exception as e:
        logger.error(f"Failed to parse greetings for {name}: {e}")
        return []


def set_character_md_path(setting_id: str, name: str, md_path: str) -> None:
    """Store the canonical markdown file path for a character (idempotent)."""
    with get_roster_connection() as conn:
        conn.execute(
            "UPDATE characters SET md_source_path = ? WHERE setting_id = ? AND name = ?",
            (md_path, setting_id, name)
        )
    logger.info(f"Set md_source_path for {name}: {md_path}")


DOMESTIC_GREETING_KEYWORDS = (
    "guild hall", "guildhall", "guild tavern", "tavern", "library",
    "reception", "common hall", "mess hall", "headquarters", "guild's library",
)
FIELD_GREETING_KEYWORDS = (
    "forest", "quest", "mountain", "road", "dungeon", "wilderness",
    "battlefield", "camp", "trail", "ruins",
)


def classify_greeting(greeting: dict) -> str:
    """Sort a greeting as 'domestic' (guild-hub appropriate) or 'field' (adventure)."""
    blob = f"{greeting.get('scene', '')} {greeting.get('text', '')}".lower()
    if any(k in blob for k in DOMESTIC_GREETING_KEYWORDS):
        return "domestic"
    if any(k in blob for k in FIELD_GREETING_KEYWORDS):
        return "field"
    return "neutral"


def format_greeting_list(greetings: list) -> str:
    """Format greeting list for the narrative history panel, tagging hub vs quest starts."""
    lines = []
    for i, g in enumerate(greetings):
        kind = classify_greeting(g)
        tag = "[dim][Hub][/dim]" if kind == "domestic" else ("[dim][Quest][/dim]" if kind == "field" else "")
        scene = g['scene'][:60] if g['scene'] else '(no scene description)'
        lines.append(f"  [bold cyan]{i+1}.[/bold cyan] {scene} {tag}".rstrip())
        if g['opening']:
            lines.append(f"      [dim]\"{g['opening'][:50]}\"[/dim]")
    return "\n".join(lines)


# ── THREAT INDEX (Bestiary) ──────────────────────────────────────────────

def init_threats_table() -> None:
    """Create the threats table if it doesn't exist."""
    with get_roster_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS threats (
                setting_id     TEXT NOT NULL,
                name           TEXT NOT NULL,
                threat_type    TEXT NOT NULL DEFAULT 'boss',
                size_rank      INTEGER NOT NULL DEFAULT 0,
                stat_body      INTEGER NOT NULL DEFAULT 1,
                stat_mind      INTEGER NOT NULL DEFAULT 1,
                stat_soul      INTEGER NOT NULL DEFAULT 1,
                max_hp         INTEGER NOT NULL DEFAULT 10,
                armour_rating  INTEGER NOT NULL DEFAULT 0,
                base_damage    INTEGER NOT NULL DEFAULT 5,
                description    TEXT NOT NULL DEFAULT '',
                lore           TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (setting_id, name)
            )
        """)

def seed_threat_catalog(setting_id: str = "guild_rpg") -> None:
    """Seed the threat index with canonical bosses (idempotent)."""
    init_threats_table()
    with get_roster_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO threats (
                setting_id, name, threat_type, size_rank,
                stat_body, stat_mind, stat_soul,
                max_hp, armour_rating, base_damage, description, lore
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            setting_id, "Zarkhoth", "boss", 3,
            10, 8, 12,
            110, 70, 75,
            "Ancient demon. Black Diamond Armour forged from the bones of the Shirakane clan. Size Mammoth (3). Killed Tomoe's entire clan in minutes.",
            "Armour resists Penetrating (only -5 AR/rank). Unarmoured at joints—Called Shot at Major Obstacle bypasses. Slain commanders sharpen Kurotsuki."
        ))
        conn.execute("""
            INSERT OR IGNORE INTO threats (
                setting_id, name, threat_type, size_rank,
                stat_body, stat_mind, stat_soul,
                max_hp, armour_rating, base_damage, description, lore
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            setting_id, "Thunderheart Titan", "boss", 6,
            14, 4, 6,
            500, 60, 80,
            "Colossal golem infused with lightning element. Over 100m tall. Creates storms. Destroys all artificial settlements.",
            "Cannot be killed by weapons. Mission: survive until Sylvara recharges teleport. Ancient runes are weak points."
        ))
        conn.execute("""
            INSERT OR IGNORE INTO threats (
                setting_id, name, threat_type, size_rank,
                stat_body, stat_mind, stat_soul,
                max_hp, armour_rating, base_damage, description, lore
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            setting_id, "Korvath", "commander", 2,
            8, 5, 6,
            80, 30, 40,
            "Zarkhoth's brute commander. 7ft tall. Black Diamond greatsword. Absolute killing intent.",
            "Must be killed before Zarkhoth — Kurotsuki sharpens +3 dmg on kill."
        ))
        conn.execute("""
            INSERT OR IGNORE INTO threats (
                setting_id, name, threat_type, size_rank,
                stat_body, stat_mind, stat_soul,
                max_hp, armour_rating, base_damage, description, lore
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            setting_id, "Nythera", "commander", 1,
            6, 9, 8,
            65, 20, 30,
            "Zarkhoth's sorceress commander. Demonic horns. White hair. Black Diamond war scythe. Unhinged laughter.",
            "Must be killed before Zarkhoth — Kurotsuki sharpens +3 dmg on kill."
        ))
    logger.info(f"Seeded threat catalog for setting '{setting_id}'.")

def get_threat(setting_id: str, name: str) -> dict | None:
    """Look up a single threat by substring match on name."""
    with get_roster_connection() as conn:
        row = conn.execute(
            "SELECT * FROM threats WHERE setting_id = ? AND LOWER(name) LIKE ?",
            (setting_id, f"%{name.lower()}%")
        ).fetchone()
        return dict(row) if row else None

def list_threats(setting_id: str, threat_type: str | None = None) -> list:
    """List threats, optionally filtered by type."""
    with get_roster_connection() as conn:
        if threat_type:
            rows = conn.execute(
                "SELECT * FROM threats WHERE setting_id = ? AND threat_type = ? ORDER BY size_rank DESC",
                (setting_id, threat_type)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM threats WHERE setting_id = ? ORDER BY size_rank DESC",
                (setting_id,)
            ).fetchall()
        return [dict(r) for r in rows]

def threat_summary(setting_id: str) -> str:
    """Human-readable threat listing for TUI display."""
    threats = list_threats(setting_id)
    if not threats:
        return "No threats registered."
    lines = [f"  [bold red]{'='*60}[/bold red]"]
    for t in threats:
        lines.append(f"  [bold white]{t['name']}[/bold white] [{t['threat_type']}] "
                     f"Size {t['size_rank']} | HP {t['max_hp']} | AR {t['armour_rating']} | DMG {t['base_damage']}")
        lines.append(f"      [dim]{t['description'][:100]}[/dim]")
    lines.append(f"  [bold red]{'='*60}[/bold red]")
    return "\n".join(lines)


# ── LOCATION ATLAS ────────────────────────────────────────────────────────

def init_locations_table() -> None:
    """Create the locations table if it doesn't exist."""
    with get_roster_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                setting_id    TEXT NOT NULL,
                name          TEXT NOT NULL,
                location_type TEXT NOT NULL DEFAULT 'settlement',
                region        TEXT NOT NULL DEFAULT '',
                description   TEXT NOT NULL DEFAULT '',
                travel_from_capital TEXT NOT NULL DEFAULT '',
                notes         TEXT NOT NULL DEFAULT '',
                structural_fault TEXT NOT NULL DEFAULT '',
                sixth_guard  TEXT NOT NULL DEFAULT '',
                levers       TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (setting_id, name)
            )
        """)
        # Non-destructive migration for existing roster DBs (adds the
        # narrative-syntax columns and provenance columns without touching
        # seeded data).
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(locations)")}
        for col in ("structural_fault", "sixth_guard", "levers",
                    "card_json", "source_path", "ingested_at"):
            if col not in cols:
                ddl = "TEXT NOT NULL DEFAULT ''" if col != "ingested_at" else "TEXT"
                conn.execute(f"ALTER TABLE locations ADD COLUMN {col} {ddl}")

def seed_locations(setting_id: str = "guild_rpg") -> None:
    """Seed the canonical atlas locations (idempotent)."""
    init_locations_table()
    atlas = [
        ("The Capital City", "capital", "Central Realm",
         "Hub of the realm. Aelthar Keldor guild founded here 62 years ago.",
         "Here", ""),
        ("Capital Arena", "venue", "The Capital",
         "Massive tournament structure where grand adventurer matches are held before kings and nobles.",
         "In city", ""),
        ("Inewell", "city", "Western Realm",
         "Large western city renowned for numerous magical academies. Magic is a craft and profession.",
         "5 days via main road", "Eira, Sefne, Sera educated here."),
        ("Srurpolis", "city", "Central Realm",
         "Stratified city — wealthy elite at center, poor struggling on outskirts.",
         "5 days via main road, 2 via Stoneshade Pass", "Feala was born in the poorest district."),
        ("Auciel", "kingdom", "Northern Realm",
         "Towering northern kingdom. Nobility isolated high in clouds, peasantry at mountain base.",
         "Via brittle mountain roads", "Lord Auciel's private parlor — social combat arena."),
        ("Khaz-Durak", "stronghold", "Western Mountains",
         "Massive dwarven stronghold-city. Echoing stone halls, roaring forges, gem-cutting workshops. Plagued by goblin raids.",
         "Deep under western mountains", "Dillia's birthplace."),
        ("Eldrakor Volcano", "danger_zone", "South",
         "Volcanic region. Labyrinthine cave system beneath slopes used as hidden demonic base.",
         "2 weeks south", "Zarkhoth's commanders Korvath and Nythera lair here."),
        ("Hemlock", "ruin", "Northern Forest",
         "Abandoned wraith-haunted village on the old forest path to Auciel. Destroyed 18 years ago.",
         "Via old forest path", "Fred disappeared here. Wraiths chant Puissance, Releguer, Repentir."),
        ("Stoneshade Mountain Pass", "route", "Central Mountains",
         "Treacherous mountain road cutting travel to Srurpolis to 2 days. Far more dangerous than main path.",
         "Via mountain pass", ""),
        ("Redfang Plains", "region", "Central Realm",
         "Flatlands frequently traversed by merchant caravans. Heavily plagued by bandit camps and ambushes.",
         "1-2 days", ""),
        ("Guiltos Grove", "danger_zone", "Deep Forest",
         "Highly dangerous forest. Home to rare arcane tree species Veyl'ethar.",
         "Deep forest", ""),
        ("Elf Realm", "continent", "Overseas",
         "Distant continent across the ocean. Completely inhabited by elves. Powerful High Elf kingdoms.",
         "Overseas — months by ship", "Sylvara is from here."),
        ("The Distant East", "region", "Eastern Realm",
         "Former home of the secretive Shirakane clan. Eastern capital devastated by Zarkhoth.",
         "Months of travel", "Tomoe's homeland. Shirakane clan massacre site."),
        ("Loneon", "town", "Central Realm",
         "City a short one-day walk from the guild along the main road.",
         "1 day", ""),
        ("Oakhaven", "town", "Central Realm",
         "Town half a day from the capital. Home to blacksmith Brom.",
         "Half day", ""),
    ]
    with get_roster_connection() as conn:
        for name, ltype, region, desc, travel, notes in atlas:
            conn.execute("""
                INSERT OR IGNORE INTO locations (
                    setting_id, name, location_type, region, description, travel_from_capital, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (setting_id, name, ltype, region, desc, travel, notes))
    logger.info(f"Seeded {len(atlas)} locations for '{setting_id}'.")


def upsert_location(setting_id: str, location: dict, card_json: str = "{}",
                    source_path: str = "") -> None:
    """Inserts or replaces a location row, carrying the Active Narrative Syntax
    (structural_fault / sixth_guard / levers) alongside the atlas columns.

    Mirrors ``upsert_character``: keyed by (setting_id, name) so a re-run with
    updated region sheets upgrades the row without duplicating it.
    """
    with get_roster_connection() as conn:
        conn.execute("""
            INSERT INTO locations (
                setting_id, name, location_type, region, description,
                travel_from_capital, notes, structural_fault, sixth_guard, levers,
                card_json, source_path, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(setting_id, name) DO UPDATE SET
                location_type   = excluded.location_type,
                region          = excluded.region,
                description     = excluded.description,
                travel_from_capital = excluded.travel_from_capital,
                notes           = excluded.notes,
                structural_fault = excluded.structural_fault,
                sixth_guard     = excluded.sixth_guard,
                levers          = excluded.levers,
                card_json       = excluded.card_json,
                source_path     = excluded.source_path,
                ingested_at     = CURRENT_TIMESTAMP
        """, (
            setting_id,
            location["name"],
            location.get("location_type", "settlement"),
            location.get("region", ""),
            location.get("description", ""),
            location.get("travel_from_capital", ""),
            location.get("notes", ""),
            location.get("structural_fault", ""),
            location.get("sixth_guard", ""),
            location.get("levers", ""),
            card_json,
            source_path,
        ))

def list_locations(setting_id: str, location_type: str | None = None) -> list:
    """List atlas locations, optionally filtered by type."""
    with get_roster_connection() as conn:
        if location_type:
            rows = conn.execute(
                "SELECT * FROM locations WHERE setting_id = ? AND location_type = ? ORDER BY name",
                (setting_id, location_type)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM locations WHERE setting_id = ? ORDER BY name", (setting_id,)
            ).fetchall()
        return [dict(r) for r in rows]

def get_location(setting_id: str, name: str) -> dict | None:
    """Look up a location by substring match."""
    with get_roster_connection() as conn:
        row = conn.execute(
            "SELECT * FROM locations WHERE setting_id = ? AND LOWER(name) LIKE ?",
            (setting_id, f"%{name.lower()}%")
        ).fetchone()
        return dict(row) if row else None

def location_summary(setting_id: str) -> str:
    """Human-readable atlas for TUI display."""
    locs = list_locations(setting_id)
    if not locs:
        return "No locations registered."
    lines = [f"  [bold cyan]{'='*60}[/bold cyan]"]
    by_type = {}
    for l in locs:
        by_type.setdefault(l['location_type'], []).append(l)
    for ltype, items in sorted(by_type.items()):
        lines.append(f"  [bold cyan]── {ltype.title()}s ──[/bold cyan]")
        for l in items:
            travel = f" [{l['travel_from_capital']}]" if l['travel_from_capital'] else ""
            lines.append(f"  [bold white]{l['name']}[/bold white] ({l['region']}){travel}")
            if l['notes']:
                lines.append(f"      [dim italic]{l['notes']}[/dim italic]")
    lines.append(f"  [bold cyan]{'='*60}[/bold cyan]")
    return "\n".join(lines)


# ── ORGANIZATION ATLAS ──────────────────────────────────────────────────

def init_organizations_table() -> None:
    """Create the organizations table if it doesn't exist."""
    with get_roster_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                setting_id          TEXT NOT NULL,
                name                TEXT NOT NULL,
                organization_type   TEXT NOT NULL DEFAULT 'guild',
                scale_tier          TEXT NOT NULL DEFAULT '',
                leader              TEXT NOT NULL DEFAULT '',
                base_of_operations  TEXT NOT NULL DEFAULT '',
                description         TEXT NOT NULL DEFAULT '',
                structural_fault    TEXT NOT NULL DEFAULT '',
                sixth_guard         TEXT NOT NULL DEFAULT '',
                levers              TEXT NOT NULL DEFAULT '',
                card_json           TEXT NOT NULL DEFAULT '{}',
                source_path         TEXT NOT NULL DEFAULT '',
                ingested_at         TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (setting_id, name)
            )
        """)
        # Non-destructive migration for existing roster DBs (adds the
        # narrative-syntax + provenance columns without touching seeded data).
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(organizations)")}
        for col in ("structural_fault", "sixth_guard", "levers",
                    "card_json", "source_path", "ingested_at"):
            if col not in cols:
                conn.execute(f"ALTER TABLE organizations ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")

def upsert_organization(setting_id: str, org: dict, card_json: str = "{}",
                        source_path: str = "") -> None:
    """Inserts or replaces an organization row, carrying the Active Narrative
    Syntax (structural_fault / sixth_guard / levers) alongside the org columns.

    Mirrors ``upsert_location``: keyed by (setting_id, name) so a re-run with
    updated org sheets upgrades the row without duplicating it.
    """
    with get_roster_connection() as conn:
        conn.execute("""
            INSERT INTO organizations (
                setting_id, name, organization_type, scale_tier, leader,
                base_of_operations, description, structural_fault, sixth_guard,
                levers, card_json, source_path, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(setting_id, name) DO UPDATE SET
                organization_type   = excluded.organization_type,
                scale_tier          = excluded.scale_tier,
                leader              = excluded.leader,
                base_of_operations  = excluded.base_of_operations,
                description         = excluded.description,
                structural_fault    = excluded.structural_fault,
                sixth_guard         = excluded.sixth_guard,
                levers              = excluded.levers,
                card_json           = excluded.card_json,
                source_path         = excluded.source_path,
                ingested_at         = CURRENT_TIMESTAMP
        """, (
            setting_id,
            org["name"],
            org.get("organization_type", "guild"),
            org.get("scale_tier", ""),
            org.get("leader", ""),
            org.get("base_of_operations", ""),
            org.get("description", ""),
            org.get("structural_fault", ""),
            org.get("sixth_guard", ""),
            org.get("levers", ""),
            card_json,
            source_path,
        ))

def list_organizations(setting_id: str, organization_type: str | None = None) -> list:
    """List organizations, optionally filtered by type."""
    with get_roster_connection() as conn:
        if organization_type:
            rows = conn.execute(
                "SELECT * FROM organizations WHERE setting_id = ? AND organization_type = ? ORDER BY name",
                (setting_id, organization_type)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM organizations WHERE setting_id = ? ORDER BY name", (setting_id,)
            ).fetchall()
        return [dict(r) for r in rows]

def get_organization(setting_id: str, name: str) -> dict | None:
    """Look up an organization by substring match."""
    with get_roster_connection() as conn:
        row = conn.execute(
            "SELECT * FROM organizations WHERE setting_id = ? AND LOWER(name) LIKE ?",
            (setting_id, f"%{name.lower()}%")
        ).fetchone()
        return dict(row) if row else None

def organization_summary(setting_id: str) -> str:
    """Human-readable organization listing for TUI display."""
    orgs = list_organizations(setting_id)
    if not orgs:
        return "No organizations registered."
    lines = [f"  [bold cyan]{'='*60}[/bold cyan]"]
    for o in orgs:
        lines.append(f"  [bold white]{o['name']}[/bold white] [{o['organization_type']}] — led by {o['leader'] or 'Unknown'}")
        if o['base_of_operations'] or o['scale_tier']:
            meta = " | ".join(p for p in (o['base_of_operations'], o['scale_tier']) if p)
            lines.append(f"      [dim]{meta}[/dim]")
        if o['structural_fault']:
            lines.append(f"      [magenta]Structural Fault:[/magenta] {o['structural_fault'][:80]}...")
    lines.append(f"  [bold cyan]{'='*60}[/bold cyan]")
    return "\n".join(lines)


# ── TOURNAMENT ENGINE ─────────────────────────────────────────────────────

def init_tournaments_table() -> None:
    """Create the tournaments table if it doesn't exist."""
    with get_roster_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tournaments (
                setting_id     TEXT NOT NULL,
                tournament_id  TEXT NOT NULL,
                name           TEXT NOT NULL,
                rank_bracket   TEXT NOT NULL,
                prize_silver   INTEGER NOT NULL DEFAULT 0,
                prize_rank_promo TEXT NOT NULL DEFAULT '',
                guild_count    INTEGER NOT NULL DEFAULT 8,
                status         TEXT NOT NULL DEFAULT 'upcoming',
                champion       TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (setting_id, tournament_id)
            )
        """)

def seed_tournaments(setting_id: str = "guild_rpg") -> None:
    """Seed the canonical tournament schedule (idempotent)."""
    init_tournaments_table()
    tourneys = [
        ("capital_arena_spring", "Spring Grand Tournament", "B", 500, "A-Rank promotion consideration",
         16, "upcoming", ""),
        ("underground_slums", "South-East Slum Rings", "D", 50, "C-Rank promotion",
         4, "recurring", ""),
        ("cross_guild_autumn", "Autumn Cross-Guild Championship", "A", 5000, "S-Rank consideration + territory rights",
         8, "upcoming", ""),
    ]
    with get_roster_connection() as conn:
        for tid, name, bracket, prize, promo, guilds, status, champ in tourneys:
            conn.execute("""
                INSERT OR IGNORE INTO tournaments (
                    setting_id, tournament_id, name, rank_bracket, prize_silver,
                    prize_rank_promo, guild_count, status, champion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (setting_id, tid, name, bracket, prize, promo, guilds, status, champ))
    logger.info(f"Seeded tournaments for '{setting_id}'.")

def list_tournaments(setting_id: str) -> list:
    """List all tournaments for a setting."""
    with get_roster_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tournaments WHERE setting_id = ? ORDER BY rank_bracket",
            (setting_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def load_campaign_module(setting_id: str, module_name: str | None = None) -> tuple:
    """Load a campaign module (STORY_MAP dict + resolved module name).

    Falls back to the setting's default_module, then to a built-in fallback map.
    Returns (story_map, resolved_module_name). Canonical copy — the TUI
    (chronos.py) and web port (browser_chronos.py) both import from here.
    """
    setting = get_setting(setting_id) or {}
    resolved = module_name or setting.get("default_module", "")
    module_path = os.path.join(BASE_DIR, "modules", resolved)
    try:
        if resolved and os.path.exists(module_path):
            with open(module_path, "r", encoding="utf-8") as f:
                module_data = json.load(f)
            story_map = module_data.get("nodes", {})
            resolved = module_data.get("module_name", resolved)
            logger.info(f"[{setting_id}] Loaded campaign module '{resolved}' with {len(story_map)} nodes.")
            return story_map, resolved
    except Exception as e:
        logger.error(f"Failed to load campaign map '{resolved}' for {setting_id}: {e}")

    # Fallback default map
    logger.warning(f"No valid module for setting '{setting_id}'. Using built-in fallback map.")
    return {
        "node_start": {
            "node_id": "node_start",
            "title": "The Chronos Diagnostic Chamber",
            "description": "A pristine obsidian enclosure humming with low-frequency mesh telemetry seals.",
            "exits": {"north": "node_corridor"},
            "required_check": None
        }
    }, "builtin_fallback"


def roster_dict_to_char(rc: dict) -> "CharacterSchema":
    """Convert a roster DB dict to a CharacterSchema with all BESM fields populated.

    Centralizes the JSON parsing for combat_techniques, skills, defects.
    Canonical copy — the TUI (chronos.py) and web port (browser_chronos.py)
    both import from here (was chronos._roster_dict_to_char).
    """
    from .models import CharacterSchema
    char = CharacterSchema(
        name=rc["name"],
        gender=rc.get("gender", ""),
        race=rc.get("race", ""),
        stat_body=rc["stat_body"],
        stat_mind=rc["stat_mind"],
        stat_soul=rc["stat_soul"],
        current_hp=rc.get("max_hp"),
        current_ep=rc.get("max_ep"),
        # Explicit stored maxima win over the Tri-Stat derivation, so Tough /
        # Energised bonuses survive runtime (bypasses the formula when provided).
        max_hp=rc.get("max_hp"),
        max_ep=rc.get("max_ep")
    )
    char.points_budget = rc.get("points_budget", 75)
    char.shock_value = rc.get("shock_value", char.max_hp // 5)
    char.combat_techniques = json.loads(rc.get("combat_techniques", "[]"))
    char.skills = json.loads(rc.get("skills", "[]"))
    char.defects = json.loads(rc.get("defects", "[]"))
    char.spellbook = json.loads(rc.get("spellbook", "[]"))
    return char


def build_vitals_with_full_loadout(setting_id: str, char: "CharacterSchema", org_name: str | None = None) -> dict:
    """
    Compiles the FULL character loadout for the LLM shell. Injects narrative-syntax
    fields (Sixth Guard, Structural Fault, Three Levers) AND BESM rules fields
    (Combat Techniques, Skills, Defects, Shock Value) from the roster DB.
    Falls back to empty defaults if the character has no data.

    Canonical copy (moved from chronos.py 2026-09-08 — CP-7). Roster-DB-only:
    session writes must stay in the caller.
    """
    vitals = {
        # core vitals
        "name": char.name,
        "current_hp": char.current_hp if char.current_hp is not None else char.max_hp,
        "current_ep": char.current_ep if char.current_ep is not None else char.max_ep,
        "stat_body": char.stat_body,
        "stat_mind": char.stat_mind,
        "stat_soul": char.stat_soul,
        "max_hp": char.max_hp,
        "max_ep": char.max_ep,
        "base_acv": char.base_acv,
        "base_dcv": char.base_dcv,
        # narrative syntax
        "structural_fault": "",
        "sixth_guard": "",
        "levers": "",
        # BESM rules
        "combat_techniques": [],
        "skills": [],
        "defects": [],
        "shock_value": char.shock_value if char.shock_value else char.max_hp // 5,
    }
    roster_char = get_character(setting_id, char.name)
    if roster_char:
        vitals["structural_fault"] = roster_char.get("structural_fault", "")
        vitals["sixth_guard"] = roster_char.get("sixth_guard", "")
        vitals["levers"] = roster_char.get("levers", "")
        vitals["combat_techniques"] = json.loads(roster_char.get("combat_techniques", "[]"))
        vitals["skills"] = json.loads(roster_char.get("skills", "[]"))
        vitals["defects"] = json.loads(roster_char.get("defects", "[]"))
        vitals["shock_value"] = roster_char.get("shock_value", char.max_hp // 5)
    # Home guild / hub (organization Narrative Syntax)
    org = get_organization(setting_id, org_name) if org_name else None
    vitals["org_name"] = org["name"] if org else ""
    vitals["org_type"] = org["organization_type"] if org else ""
    vitals["org_leader"] = org["leader"] if org else ""
    vitals["org_base"] = org["base_of_operations"] if org else ""
    vitals["org_scale"] = org["scale_tier"] if org else ""
    vitals["org_structural_fault"] = org["structural_fault"] if org else ""
    vitals["org_sixth_guard"] = org["sixth_guard"] if org else ""
    vitals["org_levers"] = org["levers"] if org else ""
    return vitals


def build_greeting_start(char, greeting: dict, active_org: str, idx: int):
    """Build the opening node for a /startgreeting launch.

    Domestic (guild-hub) greetings anchor to the active org's guildhall so the
    hub becomes the literal starting location; field greetings open on a generic
    quest node. Returns (kind, NodeSchema, assembled_text).

    Canonical copy (moved from chronos.py 2026-09-08 — CP-7). Pure — no DB access.
    """
    from .models import NodeSchema
    kind = classify_greeting(greeting)
    greeting_text = greeting.get("text", "")
    if greeting.get("opening"):
        greeting_text += f"\n\n{getattr(char, 'name', 'You')}: \"{greeting['opening']}\""
    if kind == "domestic":
        hub_title = f"{active_org} Guildhall" if active_org else "Guildhall"
        node = NodeSchema(node_id="hub_guildhall", title=hub_title, description=greeting_text, exits={})
    else:
        node = NodeSchema(node_id=f"greeting_{idx+1}", title=f"{getattr(char, 'name', 'You')} — Greeting {idx+1}", description=greeting_text, exits={})
    return kind, node, greeting_text
