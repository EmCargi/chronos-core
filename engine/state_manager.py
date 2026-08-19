import os
import sqlite3
import shutil
import logging
import json
import uuid
from datetime import datetime
from contextlib import contextmanager
from typing import Generator
from .models import CharacterSchema

logger = logging.getLogger("ChronosCore.StateManager")

# Resolve DB paths dynamically relative to the core codebase directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "chronos_session.db")

@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Safely connects to data/chronos_session.db with standard context manager.
    Performs commits on success and rollback on exceptions.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database transaction error: {e}")
        raise e
    finally:
        conn.close()

def run_db_checkpoint() -> str:
    """
    Executes an automated backup of the database file before runtime updates.
    Returns the path to the backup checkpoint snapshot, or empty string if no DB file exists.
    """
    if not os.path.exists(DB_PATH):
        logger.info("No active database session found to checkpoint.")
        return ""
    
    checkpoint_dir = os.path.join(DATA_DIR, "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"chronos_session_checkpoint_{timestamp}.db"
    backup_path = os.path.join(checkpoint_dir, backup_filename)
    
    try:
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"Automated checkpoint backup completed successfully at: {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"Failed to create checkpoint snapshot: {e}")
        raise e

def initialize_session_db(db_path: str) -> None:
    """
    Sets up the required structural tables:
    - character_vitals (session_id, name, body, mind, soul, current_hp, current_ep)
    - campaign_navigation (session_id, active_node_id, visited_nodes)
    - chronology_history (turn_id AUTOINCREMENT, session_id, timestamp, speaker, payload)
    - character_inventory (item_id TEXT PRIMARY KEY, session_id TEXT, item_name TEXT, item_type TEXT, attribute_granted TEXT, raw_modifiers TEXT)
    """
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        
    with sqlite3.connect(db_path) as conn:
        ensure_scene_effects_table(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS character_vitals (
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                body INTEGER NOT NULL,
                mind INTEGER NOT NULL,
                soul INTEGER NOT NULL,
                current_hp INTEGER NOT NULL,
                current_ep INTEGER NOT NULL,
                PRIMARY KEY (session_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaign_navigation (
                session_id TEXT PRIMARY KEY,
                setting_id TEXT NOT NULL DEFAULT 'guild_rpg',
                module_name TEXT NOT NULL DEFAULT '',
                active_node_id TEXT NOT NULL,
                visited_nodes TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chronology_history (
                turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                speaker TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS character_inventory (
                item_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                item_type TEXT NOT NULL,
                attribute_granted TEXT NOT NULL,
                raw_modifiers TEXT NOT NULL
            )
        """)
    logger.info(f"Session database initialized at {db_path} with structural tables.")

def init_db() -> None:
    """
    Performs initial connection routing, directory safety initialization,
    and tables setup.
    """
    initialize_session_db(DB_PATH)
    migrate_character_vitals_composite_key(DB_PATH)
    migrate_campaign_navigation_setting(DB_PATH)

def ensure_scene_effects_table(conn) -> None:
    """Creates the transient, node-bound effect ledger if absent. Idempotent so
    older session DBs self-upgrade on launch without a destructive migration."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_effects (
            session_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            rounds_remaining INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, node_id, kind)
        )
    """)

def apply_scene_effect(session_id: str, node_id: str, kind: str,
                       description: str = "", rounds: int = 1) -> None:
    """Upsert a transient, location-bound effect on the session DB.

    Scene effects ride the campaign_navigation model: an effect attaches to a
    node_id (the arena its consequence plays out in — the blinded monster group
    at *this* encounter node, the animal ward over *this* campsite). Re-applying
    the same kind at the same node refreshes its duration (idempotent)."""
    rounds = max(1, int(rounds or 1))
    with get_db_connection() as conn:
        ensure_scene_effects_table(conn)
        conn.execute("""
            INSERT INTO scene_effects (session_id, node_id, kind, description, rounds_remaining)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (session_id, node_id, kind)
            DO UPDATE SET description = excluded.description,
                          rounds_remaining = excluded.rounds_remaining
        """, (session_id, node_id, kind, description, rounds))

def get_scene_effects(session_id: str, node_id: str | None = None) -> list:
    """List active scene effects, newest first. Scoped to one node when given."""
    with get_db_connection() as conn:
        ensure_scene_effects_table(conn)
        conn.row_factory = sqlite3.Row
        if node_id:
            rows = conn.execute(
                "SELECT * FROM scene_effects WHERE session_id = ? AND node_id = ? "
                "ORDER BY created_at DESC",
                (session_id, node_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scene_effects WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]

def tick_scene_effects(session_id: str, node_id: str | None = None) -> int:
    """Advance one round: decrement remaining rounds and drop expired effects.

    Returns the number of effects that expired (deleted) so the caller can
    narrate the consequence. Scoped to a node when given (one round passes at
    the node being re-entered)."""
    with get_db_connection() as conn:
        ensure_scene_effects_table(conn)
        if node_id:
            conn.execute(
                "UPDATE scene_effects SET rounds_remaining = rounds_remaining - 1 "
                "WHERE session_id = ? AND node_id = ?",
                (session_id, node_id)
            )
            conn.execute(
                "DELETE FROM scene_effects WHERE session_id = ? AND node_id = ? "
                "AND rounds_remaining <= 0",
                (session_id, node_id)
            )
            expired = conn.execute(
                "SELECT changes() AS c"
            ).fetchone()[0]
        else:
            conn.execute(
                "DELETE FROM scene_effects WHERE session_id = ? AND rounds_remaining <= 0",
                (session_id,)
            )
            conn.execute(
                "UPDATE scene_effects SET rounds_remaining = rounds_remaining - 1 "
                "WHERE session_id = ?",
                (session_id,)
            )
            conn.execute(
                "DELETE FROM scene_effects WHERE session_id = ? AND rounds_remaining <= 0",
                (session_id,)
            )
            expired = conn.execute("SELECT changes() AS c").fetchone()[0]
    return expired

def migrate_campaign_navigation_setting(db_path: str) -> None:
    """
    One-time migration: campaign_navigation previously held only (session_id,
    active_node_id, visited_nodes). Adds setting_id and module_name so a session
    can track which setting/campaign module it is running.
    """
    if not os.path.exists(db_path):
        return
    with sqlite3.connect(db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(campaign_navigation)").fetchall()]
        if "setting_id" in cols:
            return
        logger.info("Migrating campaign_navigation to track setting_id + module_name.")
        conn.execute("ALTER TABLE campaign_navigation RENAME TO campaign_navigation_old")
        conn.execute("""
            CREATE TABLE campaign_navigation (
                session_id TEXT PRIMARY KEY,
                setting_id TEXT NOT NULL DEFAULT 'guild_rpg',
                module_name TEXT NOT NULL DEFAULT '',
                active_node_id TEXT NOT NULL,
                visited_nodes TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO campaign_navigation (session_id, setting_id, module_name, active_node_id, visited_nodes)
            SELECT session_id, 'guild_rpg', '', active_node_id, visited_nodes FROM campaign_navigation_old
        """)
        conn.execute("DROP TABLE campaign_navigation_old")

def migrate_character_vitals_composite_key(db_path: str) -> None:
    """
    One-time migration: character_vitals previously used session_id as the sole
    PRIMARY KEY, which meant INSERT OR REPLACE could only store a single active
    character per session. Rebuilds the table with a composite PRIMARY KEY
    (session_id, name) so the full guild cast can coexist in one session.
    """
    with sqlite3.connect(db_path) as conn:
        pks = [row[1] for row in conn.execute("PRAGMA table_info(character_vitals)") if row[5]]
        if pks != ["session_id"]:
            return
        logger.info("Migrating character_vitals to composite PRIMARY KEY (session_id, name).")
        conn.execute("ALTER TABLE character_vitals RENAME TO character_vitals_old")
        conn.execute("""
            CREATE TABLE character_vitals (
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                body INTEGER NOT NULL,
                mind INTEGER NOT NULL,
                soul INTEGER NOT NULL,
                current_hp INTEGER NOT NULL,
                current_ep INTEGER NOT NULL,
                PRIMARY KEY (session_id, name)
            )
        """)
        conn.execute("""
            INSERT INTO character_vitals (session_id, name, body, mind, soul, current_hp, current_ep)
            SELECT session_id, name, body, mind, soul, current_hp, current_ep
            FROM character_vitals_old
        """)
        conn.execute("DROP TABLE character_vitals_old")

def save_runtime_snapshot(session_id: str, character: CharacterSchema, active_node: str,
                          setting_id: str = "guild_rpg", module_name: str = "") -> None:
    """
    Performs an idempotent upsert (INSERT OR REPLACE INTO) for both
    character stats and active navigation state parameters.
    """
    with get_db_connection() as conn:
        # Idempotent upsert character vitals
        conn.execute("""
            INSERT OR REPLACE INTO character_vitals (
                session_id, name, body, mind, soul, current_hp, current_ep
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            character.name,
            character.stat_body,
            character.stat_mind,
            character.stat_soul,
            character.current_hp if character.current_hp is not None else character.max_hp,
            character.current_ep if character.current_ep is not None else character.max_ep
        ))
        
        # Load existing visited nodes if any
        cursor = conn.cursor()
        cursor.execute("SELECT visited_nodes FROM campaign_navigation WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        visited_list = []
        if row and row[0]:
            try:
                visited_list = json.loads(row[0])
            except Exception:
                visited_list = [x.strip() for x in row[0].split(",") if x.strip()]
        
        if active_node not in visited_list:
            visited_list.append(active_node)
            
        visited_nodes_json = json.dumps(visited_list)
        
        # Idempotent upsert campaign navigation
        conn.execute("""
            INSERT OR REPLACE INTO campaign_navigation (
                session_id, setting_id, module_name, active_node_id, visited_nodes
            ) VALUES (?, ?, ?, ?, ?)
        """, (session_id, setting_id, module_name, active_node, visited_nodes_json))
        
    logger.info(f"Saved runtime snapshot for session_id {session_id} at node {active_node}.")

def load_runtime_navigation(session_id: str) -> dict | None:
    """Returns the persisted navigation state (setting_id, module_name, active_node_id) or None."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT setting_id, module_name, active_node_id FROM campaign_navigation WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        return dict(row) if row else None

def log_narrative_turn(session_id: str, speaker: str, text_payload: str) -> None:
    """
    Commits raw terminal string dialogues cleanly to chronology history ledger.
    """
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO chronology_history (session_id, speaker, payload)
            VALUES (?, ?, ?)
        """, (session_id, speaker, text_payload))
    logger.info(f"Narrative turn logged: {speaker} -> {text_payload[:50]}...")

def add_loot_to_inventory(session_id: str, item_data: dict) -> str:
    """
    Adds a loot item to the character_inventory database table.
    Generates a unique item_id and commits the item data.
    """
    item_id = str(uuid.uuid4())[:8]
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO character_inventory (item_id, session_id, item_name, item_type, attribute_granted, raw_modifiers)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            item_id,
            session_id,
            item_data.get("item_name", "Unknown Item"),
            item_data.get("item_type", "Miscellaneous"),
            item_data.get("attribute_granted", "None"),
            str(item_data.get("raw_modifiers", "None"))
        ))
    logger.info(f"Added item {item_data.get('item_name')} (ID: {item_id}) to inventory for session {session_id}.")
    return item_id

def get_character_inventory(session_id: str) -> list:
    """Retrieves all active items inside the character's inventory ledger."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT item_id, item_name, item_type, attribute_granted, raw_modifiers 
            FROM character_inventory 
            WHERE session_id = ?
        """, (session_id,))
        return [dict(row) for row in cursor.fetchall()]
