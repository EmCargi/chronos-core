#!/usr/bin/env python3
import os
import sys
import logging
import json
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.console import Console

# Ensure the root folder is on Python path to allow running directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import (
    CharacterSchema,
    NodeSchema,
    execute_action_check,
    check_shock,
    check_incapacitation,
    check_poison_resistance,
    check_sanity,
    check_catastrophic_damage,
    resolve_combat_roll,
    resolve_attack_damage,
    character_scv,
    social_damage,
    falling_damage,
    range_obstacle,
    size_lookup,
    size_knockback,
    wound_obstacle,
    sanity_obstacle,
    hp_recovery,
    ep_recovery,
    technique_obstacle_reduction,
    technique_edge_bonus,
    defect_hp_modifier,
    defect_damage_modifier,
    defect_achilles_multiplier,
    defect_bane_damage,
    defect_blocks_recovery,
    defect_shortcoming_obstacle,
    defect_sensory_obstacle,
    init_db,
    run_db_checkpoint,
    save_runtime_snapshot,
    load_runtime_navigation,
    log_narrative_turn,
    add_loot_to_inventory,
    get_character_inventory,
    run_auto_ingest,
    init_economy_db,
    catalog_summary,
    get_wallet,
    grant_silver,
    buy_item,
    inventory_summary,
    use_item,
    seed_besm_catalog,
    besm_catalog_summary,
    besm_catalog_matches,
    get_scene_effects,
    tick_scene_effects,
    mark_chest_opened,
    unmark_chest_opened,
    is_chest_opened,
    parse_chest_loot,
    deposit_chest_loot,
    loot_cap_for,
    compute_tcr,
    resolve_diceless_combat,
    hedged_check,
    resolve_tactical_stance,
    two_weapon_attack,
    strike_to_wound,
    touch_attack,
    resolve_called_shot,
    grapple_attack_edges,
    grabbed_condition,
    escape_grapple,
    pin_condition,
    multi_target_dispersion,
    CALLED_SHOTS,
    LLMBridge,
    ACTIVE_MODEL,
    THIN_MODEL,
    DEFAULT_RULES,
    DEFAULT_SETTING
)

# Configure logging to file rather than console to avoid disturbing the UI layout
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, "chronos_runtime.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ChronosCore.Main")

def make_progress_bar(current: int, maximum: int, color: str) -> str:
    """Renders a beautiful colored progress block bar."""
    percent = max(0, min(100, int((current / maximum) * 100)))
    bar_length = 15
    filled_length = int(bar_length * percent // 100)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)
    return f"[{color}]{bar}[/{color}] ({current}/{maximum})"

def _roster_dict_to_char(rc: dict) -> CharacterSchema:
    """
    Convert a roster DB dict to a CharacterSchema with all BESM fields populated.
    Delegates to the canonical engine copy (engine.guild_roster.roster_dict_to_char).
    """
    from engine.guild_roster import roster_dict_to_char
    return roster_dict_to_char(rc)


def make_left_panel(char: CharacterSchema) -> Panel:
    """Compiles the vital statistics panel for the active Character."""
    current_hp = char.current_hp if char.current_hp is not None else char.max_hp
    current_ep = char.current_ep if char.current_ep is not None else char.max_ep
    
    hp_bar = make_progress_bar(current_hp, char.max_hp, "red")
    ep_bar = make_progress_bar(current_ep, char.max_ep, "cyan")
    sv = char.shock_value if char.shock_value else char.max_hp // 5
    sv_bar = make_progress_bar(sv, char.max_hp // 2, "magenta")

    text = f"""
[bold yellow]Character Info[/bold yellow]
  • Name:          [bold white]{char.name}[/bold white]
  • Points Budget: [bold white]{char.points_budget} CP[/bold white]

[bold yellow]Tri-Stat Attributes[/bold yellow]
  • Body (Physical):   [bold green]{char.stat_body:<2}[/bold green] {"★" * char.stat_body}
  • Mind (Mental):     [bold green]{char.stat_mind:<2}[/bold green] {"★" * char.stat_mind}
  • Soul (Spiritual):  [bold green]{char.stat_soul:<2}[/bold green] {"★" * char.stat_soul}

[bold yellow]Derived Vitals[/bold yellow]
  • HP Threshold:  {hp_bar}
  • EP Threshold:  {ep_bar}
  • Shock Value:   {sv_bar} (capped at ½ Max HP)

[bold yellow]Combat Capacities[/bold yellow]
  • Attack Combat Value (ACV):  [bold orange3]{char.base_acv}[/bold orange3]
  • Defense Combat Value (DCV): [bold orange3]{char.base_dcv}[/bold orange3]
"""
    return Panel(text, title="[bold cyan]⚡ CHRONOS OPERATIVE VITALS ⚡[/bold cyan]", border_style="cyan")

def make_right_panel(node: NodeSchema, inventory_items: list) -> Panel:
    """Compiles the navigation state and obstacle constraints panel."""
    exits_str = " | ".join([f"[cyan]{k.upper()}[/cyan] ➔ [green]{v}[/green]" for k, v in node.exits.items()]) if node.exits else "None"
    
    required_check_str = "None"
    if node.required_check:
        stat_name = node.required_check.get("stat", "stat_body").replace("stat_", "").upper()
        difficulty = node.required_check.get("dv", 12)
        required_check_str = f"[bold yellow]{stat_name}[/bold yellow] check (Difficulty: [bold red]{difficulty}[/bold red])"
        
    # Render inventory list inside padded section
    inventory_cards = []
    if inventory_items:
        for item in inventory_items:
            mod = item.get("raw_modifiers", "None")
            attr = item.get("attribute_granted", "None").replace("stat_", "").upper()
            inventory_cards.append(
                f"   • [bold white]{item.get('item_name')}[/bold white] ({item.get('item_type')}) [green]{mod} {attr}[/green] [[dim]{item.get('item_id')}[/dim]]"
            )
    else:
        inventory_cards.append("   [italic dim]No items inside inventory ledger.[/italic dim]")
    
    inventory_str = "\n".join(inventory_cards)

    text = f"""
[bold yellow]Current Coordinates[/bold yellow]
  • Area Designation:  [bold green]{node.title}[/bold green]
  • Internal Node ID:  [bold green]{node.node_id}[/bold green]

[bold yellow]Environmental Exits[/bold yellow]
  • {exits_str}

[bold yellow]Area Obstacles[/bold yellow]
  • {required_check_str}

[bold yellow]🎒 INVENTORY LEDGER[/bold yellow]
{inventory_str}

[bold yellow]Coprocessor Context[/bold yellow]
  • Tri-Stat System:   [bold white]BESM 4th Edition[/bold white]
  • Local Inference:   [bold white]Ollama ({ACTIVE_MODEL})[/bold white]
  • Session Database:  [bold white]chronos_session.db[/bold white]
"""
    return Panel(text, title="[bold green]🗺️ CAMPAIGN NAVIGATION HUD 🗺️[/bold green]", border_style="green")

def make_bottom_panel(narrative_history: list[str]) -> Panel:
    """Compiles the rolling historical dialogue panel."""
    text = "\n".join(narrative_history)
    return Panel(text, title="[bold yellow]📜 NARRATIVE & RESOLUTION CHRONOLOGY 📜[/bold yellow]", border_style="yellow")

def build_vitals_with_full_loadout(setting_id: str, char: CharacterSchema, org_name: str | None = None) -> dict:
    """
    Compiles the FULL character loadout for the LLM shell. Injects narrative-syntax
    fields (Sixth Guard, Structural Fault, Three Levers) AND BESM rules fields
    (Combat Techniques, Skills, Defects, Shock Value) from the roster DB.
    Falls back to empty defaults if the character has no data.
    """
    from engine.guild_roster import build_vitals_with_full_loadout as _build
    return _build(setting_id, char, org_name)

def render_interface_grid(character_data: dict, current_node: dict, narrative_history: list[str], inventory_items: list) -> Layout:
    """
    HUD layout function that outputs a clean, horizontally split pane.
    - Left Upper Panel: Displays Tri-Stat metrics, HP/EP, and combat properties.
    - Right Upper Panel: Displays active node details, exits, obstacles, and active inventory.
    - Bottom Panel: Wraps rolling narrative log entries.
    """
    layout = Layout()
    layout.split_column(
        Layout(name="top", ratio=2),
        Layout(name="bottom", ratio=3)
    )
    layout["top"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )
    
    char = CharacterSchema(**character_data)
    node = NodeSchema(**current_node)
    
    layout["left"].update(make_left_panel(char))
    layout["right"].update(make_right_panel(node, inventory_items))
    layout["bottom"].update(make_bottom_panel(narrative_history))
    
    return layout

def load_campaign_module(setting_id: str, module_name: str | None = None) -> tuple:
    """
    Loads a campaign module (STORY_MAP dict + module name) for the active setting.
    Delegates to the canonical engine copy (engine.guild_roster.load_campaign_module).
    """
    from engine.guild_roster import load_campaign_module as _load
    return _load(setting_id, module_name)

def _obstacle_label(weight: int) -> str:
    """Turn an obstacle weight into its BESM-facing label for the TUI echo."""
    if weight <= 0:
        return "no obstacle"
    return "Minor Obstacle" if weight == 1 else "Major Obstacle"

def _edge_label(weight: int) -> str:
    """Turn an edge weight into its BESM-facing label for the TUI echo."""
    if weight <= 0:
        return "no edge"
    return "Minor Edge" if weight == 1 else "Major Edge"


def build_greeting_start(char, greeting: dict, active_org: str, idx: int):
    """Build the opening node for a /startgreeting launch.

    Domestic (guild-hub) greetings anchor to the active org's guildhall so the
    hub becomes the literal starting location; field greetings open on a generic
    quest node. Returns (kind, NodeSchema, assembled_text).
    """
    from engine.guild_roster import build_greeting_start as _build
    return _build(char, greeting, active_org, idx)

def main():
    # 1. Initialize SQLite session database and canonical setting roster
    init_db()
    from engine.guild_roster import init_roster_db, list_characters
    init_roster_db()
    init_economy_db()
    session_id = "chronos_interactive_session"
    
    # 2. Resolve active setting + module from persisted session state (fallback: config default)
    nav = load_runtime_navigation(session_id) or {}
    active_setting_id = nav.get("setting_id") or DEFAULT_SETTING
    # Re-point the roster/economy connections at the resolved DB (demo discs own
    # their roster DB; IP discs fall back to the shared one).
    from engine.disc_registry import set_active_setting
    set_active_setting(active_setting_id)
    active_module_name = nav.get("module_name") or ""
    active_org = nav.get("org_name") or "Aelthar Keldor"

    # 3. Load active character from the canonical roster for the active setting
    roster_chars = list_characters(setting_id=active_setting_id)
    if roster_chars:
        char = _roster_dict_to_char(roster_chars[0])
        logger.info(f"Loaded active character from roster: {char.name} [{active_setting_id}] (SV={char.shock_value})")
    else:
        logger.info(f"No roster characters for setting '{active_setting_id}'. Creating baseline character.")
        char = CharacterSchema(name="Alex Mercer", stat_body=6, stat_mind=8, stat_soul=6)
        char.current_hp = char.max_hp
        char.current_ep = char.max_ep

    # 4. Load dynamic Story Navigation Nodes for the active setting/module
    STORY_MAP, active_module_name = load_campaign_module(active_setting_id, active_module_name)

    active_node_id = (nav.get("active_node_id") or "node_start")
    if active_node_id not in STORY_MAP:
        active_node_id = list(STORY_MAP.keys())[0]
    save_runtime_snapshot(session_id, char, active_node_id, active_setting_id, active_module_name, active_org)

    # Retrieve current active node schema
    active_node = NodeSchema(**STORY_MAP.get(active_node_id, list(STORY_MAP.values())[0]))
    
    # Narrative history ledger list
    narrative_history = [
        "[bold cyan]System:[/bold cyan] Welcome to [bold gold1]Chronos Core[/bold gold1]. Connection to local DB active.",
        f"[bold cyan]System:[/bold cyan] Session Loaded. Active location: [bold green]{active_node.title}[/bold green]"
    ]
    
    bridge = LLMBridge()
    console = Console()

    # Initial compile check data
    char_dict = char.model_dump()
    node_dict = active_node.model_dump()
    inventory_items = get_character_inventory(session_id)
    layout = render_interface_grid(char_dict, node_dict, narrative_history, inventory_items)

    # 4. Arching interactive game loop
    with Live(layout, auto_refresh=True, screen=False) as live:
        while True:
            # Query active items from relational database
            inventory_items = get_character_inventory(session_id)
            
            # Update HUD layout grid
            char_dict = char.model_dump()
            node_dict = active_node.model_dump()
            layout = render_interface_grid(char_dict, node_dict, narrative_history, inventory_items)
            
            # Ensure the updates are pushed to terminal
            live.update(layout)
            
            # Temporarily pause live display to allow clean console stdin prompts
            live.stop()
            console.print("[bold cyan]COMMANDS:[/bold cyan] [white]exit | examine | north | south | east | west | /attack | /loot | /open | /roster | /settings | /setting <id> | /module <name> | /char <name> | /org <name> | /orgs | /shop | /buy <item_id> | /wallet | /grant <silver> | /inventory | /loadout | /greetings | /startgreeting <n> | /use <item_id> | /effects | /provision [info] [filters] | /diceless | /maneuver | auto-ingest[/white]")
            try:
                player_input = console.input("[bold magenta]Select action > [/bold magenta]").strip()
            except (KeyboardInterrupt, EOFError):
                player_input = "exit"
            
            if player_input.lower() == "exit":
                console.print("\n[bold red]Terminating Chronos Core session. Goodbye.[/bold red]\n")
                break
                
            if not player_input:
                live.start()
                continue
                
            # Log action into database history
            log_narrative_turn(session_id, "Player", player_input)
            
            # Action: auto-ingest
            if player_input.lower() == "auto-ingest":
                narrative_history.append("[bold cyan]System:[/bold cyan] Triggering Auto-Ingest staging sweep...")
                try:
                    res = run_auto_ingest()
                    proc_cnt = len(res["processed"])
                    fail_cnt = len(res["failed"])
                    
                    narrative_history.append(f"[bold green]Auto-Ingest Complete:[/bold green] Successfully processed {proc_cnt} files. Failed {fail_cnt} files.")
                    
                    if proc_cnt > 0:
                        # Reload the active character from the canonical roster to instantly update HUD!
                        from engine.guild_roster import list_characters
                        roster_chars = list_characters(setting_id=active_setting_id)
                        if roster_chars:
                            char = _roster_dict_to_char(roster_chars[0])
                            narrative_history.append(f"[bold green]System:[/bold green] Reloaded active player entity from roster: {char.name} (SV={char.shock_value}).")
                except Exception as e:
                    logger.error(f"Auto-Ingest execution error: {e}")
                    narrative_history.append(f"[bold red]System Error:[/bold red] Staging sweep failed: {e}")

            # Action: /roster
            elif player_input.lower() == "/roster":
                from engine.guild_roster import roster_summary, get_setting
                setting_meta = get_setting(active_setting_id) or {}
                roster_text = roster_summary(setting_id=active_setting_id)
                label = setting_meta.get("character_label", "Rank")
                narrative_history.append(f"[bold yellow]System:[/bold yellow] [{setting_meta.get('name', active_setting_id)}] roster ({label} column):")
                for line in roster_text.splitlines():
                    narrative_history.append(f"[dim]{line}[/dim]")

            # Action: /lore (show active setting narrative architecture)
            elif player_input.lower() == "/lore":
                from engine.guild_roster import get_roster_connection
                with get_roster_connection() as conn:
                    row = conn.execute(
                        "SELECT name, description, setting_lore FROM settings WHERE setting_id = ?",
                        (active_setting_id,)
                    ).fetchone()
                if row:
                    narrative_history.append(f"[bold gold1]═══ SETTING: {row[0]} ═══[/bold gold1]")
                    if row[1]:
                        narrative_history.append(f"  [dim]{row[1]}[/dim]")
                    if row[2]:
                        for line in row[2].split('. '):
                            if line.strip():
                                narrative_history.append(f"  {line.strip()}.")
                else:
                    narrative_history.append("[bold yellow]System:[/bold yellow] No lore available for current setting.")

            # Action: /settings (list all registered settings)
            elif player_input.lower() == "/settings":
                from engine.guild_roster import list_settings
                setting_list = list_settings()
                narrative_history.append("[bold yellow]System:[/bold yellow] Registered settings:")
                for s in setting_list:
                    marker = " >" if s["setting_id"] == active_setting_id else "  "
                    narrative_history.append(f"[dim]{marker} [{s['setting_id']}] {s['name']} (module: {s['default_module']})[/dim]")

            # Action: /setting <id> (switch active setting)
            elif player_input.lower().startswith("/setting"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /setting <setting_id> (try /settings to list).")
                else:
                    target = parts[1].lower()
                    # Re-point roster + economy at the target's DB FIRST so
                    # get_setting() reads the authoritative source (a demo disc's
                    # own DB after --prune-shared has removed the dormant rows).
                    from engine.disc_registry import set_active_setting
                    set_active_setting(target)
                    from engine.guild_roster import get_setting
                    if not get_setting(target):
                        narrative_history.append(f"[bold red]System:[/bold red] Unknown setting '{target}'. Run /settings to see registered settings.")
                    else:
                        active_setting_id = target
                        active_module_name = ""
                        STORY_MAP, active_module_name = load_campaign_module(active_setting_id, None)
                        active_node_id = list(STORY_MAP.keys())[0]
                        active_node = NodeSchema(**STORY_MAP[active_node_id])
                        # Reload the active character for the new setting
                        from engine.guild_roster import list_characters
                        roster_chars = list_characters(setting_id=active_setting_id)
                        if roster_chars:
                            char = _roster_dict_to_char(roster_chars[0])
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)
                        narrative_history.append(f"[bold green]System:[/bold green] Switched to setting '{active_setting_id}' (module: {active_module_name}). Active character: {char.name}.")

            # Action: /module <name> (switch campaign module within the active setting)
            elif player_input.lower().startswith("/module"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /module <module_filename.json> (e.g. forest_labyrinth_stratum1.json).")
                else:
                    target = parts[1]
                    STORY_MAP, active_module_name = load_campaign_module(active_setting_id, target)
                    active_node_id = list(STORY_MAP.keys())[0]
                    active_node = NodeSchema(**STORY_MAP[active_node_id])
                    save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)
                    narrative_history.append(f"[bold green]System:[/bold green] Loaded module '{active_module_name}'.")

            # Action: /char <name> (switch active character within the setting)
            elif player_input.lower().startswith("/char"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /char <name> (run /roster to list).")
                else:
                    target = " ".join(parts[1:])
                    from engine.guild_roster import get_character
                    roster_char = get_character(active_setting_id, target)
                    if not roster_char:
                        narrative_history.append(f"[bold red]System:[/bold red] No character '{target}' in setting '{active_setting_id}'. Run /roster to list.")
                    else:
                        char = _roster_dict_to_char(roster_char)
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)
                        narrative_history.append(f"[bold green]System:[/bold green] Active character set to {char.name} (SV={char.shock_value}).")

            # Action: /org <name> (switch active home guild / hub)
            elif player_input.lower().startswith("/org"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /org <name> (run /orgs to list).")
                else:
                    target = " ".join(parts[1:])
                    from engine.guild_roster import get_organization
                    roster_org = get_organization(active_setting_id, target)
                    if not roster_org:
                        narrative_history.append(f"[bold red]System:[/bold red] No organization '{target}' in setting '{active_setting_id}'. Run /orgs to list.")
                    else:
                        active_org = roster_org["name"]
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)
                        narrative_history.append(f"[bold green]System:[/bold green] Active home guild set to {active_org} ({roster_org['organization_type']}).")

            # Action: /orgs (list organizations in the active setting)
            elif player_input.lower().startswith("/orgs"):
                from engine.guild_roster import organization_summary
                narrative_history.append("[bold yellow]System:[/bold yellow] Organizations in '{active_setting_id}':")
                for line in organization_summary(active_setting_id).splitlines():
                    narrative_history.append(f"[dim]{line}[/dim]")

            # Action: /shop [rank] (list setting item catalog)
            elif player_input.lower().startswith("/shop"):
                parts = player_input.split()
                rank_filter = parts[1].upper() if len(parts) > 1 else None
                shop_text = catalog_summary(active_setting_id, rank_filter)
                narrative_history.append(f"[bold yellow]System:[/bold yellow] [{active_setting_id}] shop listing:")
                for line in shop_text.splitlines():
                    narrative_history.append(f"[dim]{line}[/dim]")

            # Action: /provision [filters] — GM provisioning from the BESM canon
            elif player_input.lower().startswith("/provision"):
                parts = player_input.split()
                cmd = parts[1].lower() if len(parts) > 1 else ""
                if cmd in ("usage", "help"):
                    narrative_history.append("[bold yellow]System:[/bold yellow] /provision usage:")
                    narrative_history.append("[dim]  /provision [info] [filters] — seed the BESM canon into this setting's shop[/dim]")
                    narrative_history.append("[dim]  filters: eras=archaic,modern | categories=melee | types=weapon | cap=800[/dim]")
                    narrative_history.append("[dim]  bare token = era filter (e.g. /provision archaic); info = preview only[/dim]")
                else:
                    eras = categories = types = None
                    cap = None
                    dry_run = False
                    if cmd == "info":
                        dry_run = True
                        parts = [parts[0]] + parts[2:]
                    for tok in parts[1:]:
                        tok = tok.lower()
                        if "=" in tok:
                            key, val = tok.split("=", 1)
                            vals = [v.strip() for v in val.split(",") if v.strip()]
                            if key in ("era", "eras"):
                                eras = vals
                            elif key in ("cat", "category", "categories"):
                                categories = vals
                            elif key in ("type", "types", "item_type", "item_types"):
                                types = vals
                            elif key in ("cap", "price_cap", "max", "maxsp"):
                                try:
                                    cap = int(val)
                                except ValueError:
                                    narrative_history.append("[bold yellow]System:[/bold yellow] cap= needs an integer (e.g. cap=800).")
                                    cap = None
                            else:
                                narrative_history.append(f"[bold yellow]System:[/bold yellow] Unknown filter '{key}' — try eras=, categories=, types=, cap=.")
                        else:
                            if tok not in ("info", "usage", "help"):
                                eras = [tok]
                    count, spread = besm_catalog_matches(eras, categories, types, cap)
                    spread_text = ", ".join(f"{k} {v}" for k, v in sorted(spread.items())) if spread else "no match"
                    if dry_run:
                        narrative_history.append(f"[bold yellow]System:[/bold yellow] Preview: would seed [bold white]{count}[/bold white] BESM items into [{active_setting_id}] ({spread_text}).")
                        narrative_history.append("[dim]Re-run without 'info' to commit.[/dim]")
                    else:
                        if count == 0:
                            narrative_history.append("[bold red]System:[/bold red] No BESM items match those filters.")
                        else:
                            seeded = seed_besm_catalog(active_setting_id, eras, categories, types, cap)
                            narrative_history.append(f"[bold green]Provisioned:[/bold green] seeded [bold white]{seeded}[/bold white] BESM items into [{active_setting_id}] ({spread_text}).")
                            narrative_history.append("[dim]Run /shop to see the new stock.[/dim]")

            # Action: /buy <item_id> [qty] (purchase from catalog)
            elif player_input.lower().startswith("/buy"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /buy <item_id> [qty] (run /shop to list).")
                else:
                    item_id = parts[1].lower()
                    qty = 1
                    if len(parts) > 2:
                        try:
                            qty = max(1, int(parts[2]))
                        except ValueError:
                            narrative_history.append("[bold yellow]System:[/bold yellow] Quantity must be a positive integer.")
                            qty = 0
                    if qty > 0:
                        ok, msg = buy_item(active_setting_id, char.name, item_id, qty)
                        if ok:
                            narrative_history.append(f"[bold green]Purchase:[/bold green] {msg}")
                        else:
                            narrative_history.append(f"[bold red]Purchase Failed:[/bold red] {msg}")

            # Action: /wallet [name] (show silver balance)
            elif player_input.lower().startswith("/wallet"):
                parts = player_input.split()
                name = " ".join(parts[1:]) if len(parts) > 1 else char.name
                balance = get_wallet(active_setting_id, name)
                narrative_history.append(f"[bold yellow]System:[/bold yellow] [{active_setting_id}] {name} wallet: [bold white]{balance} sp[/bold white].")

            # Action: /grant <silver> (GM quick-balance for the active character)
            elif player_input.lower().startswith("/grant"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /grant <silver>.")
                else:
                    try:
                        amount = int(parts[1])
                    except ValueError:
                        narrative_history.append("[bold yellow]System:[/bold yellow] Amount must be an integer.")
                    else:
                        balance = grant_silver(active_setting_id, char.name, amount)
                        narrative_history.append(f"[bold green]System:[/bold green] Granted {amount} sp to {char.name}. New balance: [bold white]{balance} sp[/bold white].")

            # Action: /inventory (show owned items)
            elif player_input.lower() == "/inventory":
                inv_text = inventory_summary(active_setting_id, char.name)
                narrative_history.append(f"[bold yellow]System:[/bold yellow] [{active_setting_id}] {char.name} inventory:")
                for line in inv_text.splitlines():
                    narrative_history.append(f"[dim]{line}[/dim]")

            # Action: /loadout (show full BESM build)
            elif player_input.lower() == "/loadout":
                from engine.guild_roster import get_character_loadout, format_loadout_summary
                loadout = get_character_loadout(active_setting_id, char.name)
                if loadout:
                    narrative_history.append(f"[bold yellow]System:[/bold yellow] [{active_setting_id}] {char.name} full loadout:")
                    for line in format_loadout_summary(loadout).splitlines():
                        narrative_history.append(f"  {line}")
                else:
                    narrative_history.append("[bold red]System:[/bold red] No loadout data available.")

            # Action: /greetings (list session-start greetings)
            elif player_input.lower() == "/greetings":
                from engine.guild_roster import get_character_greetings, format_greeting_list
                greetings = get_character_greetings(active_setting_id, char.name)
                if greetings:
                    narrative_history.append(f"[bold yellow]System:[/bold yellow] [{active_setting_id}] {char.name} session starters ({len(greetings)}):")
                    for line in format_greeting_list(greetings).splitlines():
                        narrative_history.append(f"  {line}")
                    narrative_history.append("[dim]Use /startgreeting <number> to begin a session. [Hub] greetings open at the guild hall.[/dim]")
                else:
                    narrative_history.append("[bold yellow]System:[/bold yellow] No greetings available for this character (source file missing).")

            # Action: /startgreeting <n> (launch session from greeting)
            elif player_input.lower().startswith("/startgreeting"):
                from engine.guild_roster import get_character_greetings
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /startgreeting <number> (run /greetings to list).")
                else:
                    try:
                        idx = int(parts[1]) - 1
                    except ValueError:
                        narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /startgreeting <number>.")
                    else:
                        greetings = get_character_greetings(active_setting_id, char.name)
                        if not greetings:
                            narrative_history.append("[bold red]System:[/bold red] No greetings available.")
                        elif idx < 0 or idx >= len(greetings):
                            narrative_history.append(f"[bold red]System:[/bold red] Greeting {idx+1} not found. Use /greetings to list.")
                        else:
                            g = greetings[idx]
                            # Build greeting as the opening node; domestic greetings anchor to the guild hub
                            kind, start_node, greeting_text = build_greeting_start(char, g, active_org, idx)
                            active_node = start_node
                            if kind == "domestic":
                                narrative_history.append(f"[bold green]Session Started at the Hub:[/bold green] {char.name} — {start_node.title} (Greeting {idx+1})")
                            else:
                                narrative_history.append(f"[bold green]Session Started:[/bold green] {char.name} — Greeting {idx+1}")
                            narrative_history.append(f"[dim]{g['scene'][:100]}[/dim]")
                            narrative_history.append("")
                            # Inject greeting as the first narrative turn via LLM
                            vitals = build_vitals_with_full_loadout(active_setting_id, char, active_org)
                            try:
                                compiled = bridge.compile_system_frame("besm_shell", vitals, {
                                    'node_id': start_node.node_id,
                                    'title': start_node.title,
                                    'description': start_node.description,
                                    'exits': start_node.exits,
                                    'required_check': start_node.required_check,
                                })
                                result = bridge.dispatch_ollama_turn(ACTIVE_MODEL, compiled, "Player observes the scene.")
                                if result.get('success'):
                                    prose, _ = bridge.inspect_llm_output(result['response'])
                                    narrative_history.append(f"[bold yellow]AI Director:[/bold yellow] {prose}")
                                else:
                                    narrative_history.append(f"[bold red]System Error:[/bold red] LLM dispatch failed: {result.get('error', 'Unknown')}")
                            except Exception as e:
                                logger.error(f"Greeting session error: {e}")
                                narrative_history.append(f"[bold red]System Error:[/bold red] {e}")
                            finally:
                                # Persist the anchored location (hub or quest) so navigation follows
                                save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)

            # Action: /use <item_id> (consume a consumable)
            elif player_input.lower().startswith("/use"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /use <item_id> (run /inventory to list).")
                else:
                    item_id = parts[1].lower()
                    ok, msg = use_item(active_setting_id, char.name, item_id, node_id=active_node.node_id)
                    if ok:
                        narrative_history.append(f"[bold green]Item Used:[/bold green] {msg}")
                        # Refresh vitals display after healing/EP effects
                        char.current_hp = char.current_hp if char.current_hp is not None else char.max_hp
                        char.current_ep = char.current_ep if char.current_ep is not None else char.max_ep
                        from engine.state_manager import get_db_connection
                        with get_db_connection() as conn:
                            row = conn.execute(
                                "SELECT current_hp, current_ep FROM character_vitals WHERE session_id = ? AND name = ?",
                                (session_id, char.name)
                            ).fetchone()
                        if row:
                            char.current_hp = row[0]
                            char.current_ep = row[1]
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)
                    else:
                        narrative_history.append(f"[bold red]Use Failed:[/bold red] {msg}")

            # ── BESM ENGINE COMMANDS ───────────────────────────────────────

            # Action: /engine (show available engine commands)
            elif player_input.lower() == "/engine":
                narrative_history.append("[bold yellow]System:[/bold yellow] BESM Engine Commands:")
                cmds = [
                    "/shock <dmg>", "/resist <poison|sleep|paralysis> [blight]",
                    "/fall <meters>", "/range <max> <distance>",
                    "/size <rank>", "/defence <dmg> [AR] [FF_AR] [pen]",
                    "/scv", "/sanity <mild|mod|major|severe|cat>",
                    "/recover", "/techniques", "/defects",
                    "/diceless <defender_cv> [AR] [extra_def] [edge]", "/diceless hedge <target> [stat]",
                    "/maneuver <subcommand>", "/effects",
                    "/open",
                ]
                for c in cmds:
                    narrative_history.append(f"  [dim]{c}[/dim]")

            # Action: /shock <damage> (check shock/knockout)
            elif player_input.lower().startswith("/shock"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /shock <damage_taken>")
                else:
                    try:
                        dmg = int(parts[1])
                    except ValueError:
                        narrative_history.append("[bold yellow]System:[/bold yellow] Damage must be an integer.")
                    else:
                        r = check_shock(char, dmg)
                        if not r["triggered"]:
                            narrative_history.append(f"[bold green]Engine:[/bold green] {dmg} damage — below SV ({char.shock_value_computed}). No shock check triggered.")
                        elif r["status_key"] is None:
                            narrative_history.append(f"[bold green]Engine:[/bold green] {r['severity']} shock check PASSED (roll {r['roll']}+Soul{char.stat_soul}={r['total']} vs TN {r['target']}).")
                        elif r["status_key"] == "shocked":
                            narrative_history.append(f"[bold red]Engine:[/bold red] SHOCKED! Roll {r['roll']}+Soul{char.stat_soul}={r['total']} vs TN {r['target']} — margin {r['margin']}. Stunned — lose next action.")
                        else:
                            narrative_history.append(f"[bold red]Engine:[/bold red] UNCONSCIOUS! {r['unconscious_rounds']} rounds. Roll {r['roll']}+Soul{char.stat_soul}={r['total']} vs TN {r['target']} — margin {r['margin']} > Soul.")

            # Action: /resist <type> (poison/incapacitation check)
            elif player_input.lower().startswith("/resist"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /resist <poison|sleep|paralysis> [blight_level|obstacle]")
                else:
                    rtype = parts[1].lower()
                    if rtype == "poison":
                        blight = int(parts[2]) if len(parts) > 2 else 1
                        r = check_poison_resistance(char, blight)
                        outcome = "PASSED (20% damage)" if r["success"] else "FAILED (full damage)"
                        narrative_history.append(
                            f"[bold {'green' if r['success'] else 'red'}]Engine:[/bold {'green' if r['success'] else 'red'}] "
                            f"Blight {blight}: roll {r['roll']}+Body{char.stat_body}={r['total']} vs TN {r['target']} — {outcome}"
                        )
                    elif rtype in ("sleep", "paralysis", "incapacitation"):
                        obs = parts[2] if len(parts) > 2 else "none"
                        r = check_incapacitation(char, obs)
                        outcome = "RESISTED" if r["success"] else "AFFECTED"
                        narrative_history.append(
                            f"[bold {'green' if r['success'] else 'red'}]Engine:[/bold {'green' if r['success'] else 'red'}] "
                            f"{rtype}: roll {r['roll']}+Stat{max(char.stat_body, char.stat_soul)}={r['total']} vs TN {r['target']} "
                            f"[{r.get('obstacle', 'none')}] — {outcome}"
                        )
                    else:
                        narrative_history.append(f"[bold yellow]System:[/bold yellow] Unknown resist type: {rtype}. Use: poison, sleep, paralysis.")

            # Action: /fall <meters>
            elif player_input.lower().startswith("/fall"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /fall <meters>")
                else:
                    try:
                        dist = float(parts[1])
                    except ValueError:
                        narrative_history.append("[bold yellow]System:[/bold yellow] Distance must be a number.")
                    else:
                        dmg = falling_damage(dist)
                        narrative_history.append(f"[bold red]Engine:[/bold red] Fall from {dist}m → [bold white]{dmg} HP[/bold white] damage.")

            # Action: /range <max> <distance>
            elif player_input.lower().startswith("/range"):
                parts = player_input.split()
                if len(parts) < 3:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /range <max_range> <distance>")
                else:
                    try:
                        max_r, dist = float(parts[1]), float(parts[2])
                    except ValueError:
                        narrative_history.append("[bold yellow]System:[/bold yellow] Values must be numbers.")
                    else:
                        obs = range_obstacle(max_r, dist)
                        if obs is None and dist <= max_r:
                            narrative_history.append(f"[bold green]Engine:[/bold green] {dist}m from {max_r}m max — Effective range, no obstacle.")
                        elif obs:
                            narrative_history.append(f"[bold yellow]Engine:[/bold yellow] {dist}m from {max_r}m max — {obs.title()} Obstacle.")
                        else:
                            narrative_history.append(f"[bold red]Engine:[/bold red] {dist}m — out of range (max {max_r}m).")

            # Action: /size <rank>
            elif player_input.lower().startswith("/size"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /size <rank> (-3 to 6)")
                else:
                    try:
                        rank = int(parts[1])
                    except ValueError:
                        narrative_history.append("[bold yellow]System:[/bold yellow] Rank must be an integer (-3 to 6).")
                    else:
                        info = size_lookup(rank)
                        if info:
                            narrative_history.append(
                                f"[bold white]Size {rank} — {info['category']}[/bold white] | "
                                f"Mass: {info['mass']} | Damage: {info['strength_damage']:+d} | "
                                f"AR: {info['armour']:+d} | Ranged: {info['ranged_mod']:+d} | "
                                f"Range×: {info['range_mult']}"
                            )
                            kb = size_knockback(rank, 0)
                            if kb["auto_knockback"]:
                                narrative_history.append(f"[bold red]  Auto Knockback: {kb['distance_meters']}m vs Medium target[/bold red]")
                        else:
                            narrative_history.append("[bold yellow]System:[/bold yellow] Unknown size rank. Range: -3 (Diminutive) to 6 (Colossal).")

            # Action: /defence <damage> [AR] [FF_AR] [penetration_ranks]
            elif player_input.lower().startswith("/defence"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /defence <damage> [armour_AR] [force_field_AR] [penetration_ranks]")
                else:
                    try:
                        dmg = int(parts[1])
                        ar = int(parts[2]) if len(parts) > 2 else 0
                        ff = int(parts[3]) if len(parts) > 3 else 0
                        pen = int(parts[4]) if len(parts) > 4 else 0
                    except ValueError:
                        narrative_history.append("[bold yellow]System:[/bold yellow] All values must be integers.")
                    else:
                        r = resolve_attack_damage(dmg, armour_rating=ar, force_field_ar=ff,
                                                   penetrating_ranks=pen,
                                                   current_hp=char.current_hp or char.max_hp,
                                                   max_hp=char.max_hp)
                        narrative_history.append(
                            f"[bold white]Defence Pipeline[/bold white] — {dmg} incoming → "
                            f"FF {r['force_field_ar']}AR → {r['after_force_field']} | "
                            f"Armour {r['effective_armour_ar']}AR → {r['after_armour']} | "
                            f"Net: [bold red]{r['net_damage']} HP[/bold red]"
                        )
                        if r['hp_absorbed']:
                            narrative_history.append(f"[bold green]  Absorbed: {r['hp_absorbed']} HP, {r['ep_absorbed']} EP[/bold green]")

            # Action: /scv (show social combat value)
            elif player_input.lower() == "/scv":
                scv = character_scv(char)
                sp = scv
                demure = -2 * (next((d.get("rank",0) for d in (char.defects or []) if isinstance(d, dict) and d.get("name","").lower() == "demure"), 0))
                narrative_history.append(
                    f"[bold white]Social Profile:[/bold white] SCV={scv} (Mind{char.stat_mind}+Soul{char.stat_soul})/2"
                    + (f" Demure{demure}" if demure else "")
                    + f" | Society Points={sp} | Recovery: 1/hour"
                )

            # Action: /sanity <trauma> (sanity check)
            elif player_input.lower().startswith("/sanity"):
                parts = player_input.split()
                trauma = parts[1].lower() if len(parts) > 1 else "mild"
                sp_max = char.stat_mind + char.stat_soul
                sp_current = sp_max  # default: full SP unless tracked elsewhere
                r = check_sanity(char.stat_mind, char.stat_soul, sp_current, trauma)
                obs = sanity_obstacle(r["new_sp"])
                outcome = "PASSED" if r["passed"] else f"FAILED (-{r['sp_loss']} SP)"
                narrative_history.append(
                    f"[bold {'green' if r['passed'] else 'red'}]Engine:[/bold {'green' if r['passed'] else 'red'}] "
                    f"{trauma.title()} trauma: roll {r['roll']}+{(char.stat_mind+char.stat_soul)//2}={r['total']} vs TN {r['target']} — {outcome}"
                )
                if obs:
                    narrative_history.append(f"[bold red]  Sanity Spiral: {obs.title()} Obstacle on all rolls[/bold red]")

            # Action: /recover (show recovery rates)
            elif player_input.lower() == "/recover":
                hp_day = hp_recovery(char.stat_body, 1)
                ep_hour = ep_recovery(char.stat_mind, char.stat_soul, 1)
                blocks = defect_blocks_recovery(char.defects or [])
                narrative_history.append(
                    f"[bold white]Recovery Rates:[/bold white] HP={hp_day}/day"
                    + (" (×2 medical)" if not blocks["hp"] else " [red](BLOCKED: No Healing)[/red]")
                    + f" | EP={ep_hour}/hour"
                    + (" [red](BLOCKED: Nightmares)[/red]" if blocks["rest"] else "")
                )

            # Action: /techniques (show active technique effects)
            elif player_input.lower() == "/techniques":
                techs = char.combat_techniques or []
                if not techs:
                    narrative_history.append("[dim]No combat techniques equipped.[/dim]")
                else:
                    narrative_history.append("[bold white]Active Technique Effects:[/bold white]")
                    for t in techs:
                        if isinstance(t, dict):
                            name = t.get("name", "?")
                            lvl = t.get("level", 1)
                            effects = []
                            if technique_obstacle_reduction(techs, "range"):
                                effects.append("range penalty removal")
                            if technique_obstacle_reduction(techs, "called_shot"):
                                effects.append("called shot reduction")
                            if technique_edge_bonus(techs, "initiative"):
                                effects.append(f"initiative {'Minor' if technique_edge_bonus(techs, 'initiative')==1 else 'Major'} Edge")
                            if technique_edge_bonus(techs, "amplify_aim"):
                                effects.append("Aim/Wait → Major Edge")
                            narrative_history.append(f"  [bold]{name}[/bold] Lv{lvl}" + (f" — {', '.join(effects)}" if effects else ""))

            # Action: /defects (show active defect effects)
            elif player_input.lower() == "/defects":
                defs = char.defects or []
                if not defs:
                    narrative_history.append("[dim]No defects.[/dim]")
                else:
                    narrative_history.append("[bold red]Active Defect Effects:[/bold red]")
                    hp_mod = defect_hp_modifier(defs)
                    dmg_mod = defect_damage_modifier(defs)
                    blocks = defect_blocks_recovery(defs)
                    achilles = defect_achilles_multiplier(defs, "")
                    bane = defect_bane_damage(defs)
                    if hp_mod:
                        narrative_history.append(f"  Fragile: [red]{hp_mod} max HP[/red]")
                    if dmg_mod:
                        narrative_history.append(f"  Reduced Damage: [red]{dmg_mod} Damage Multiplier[/red]")
                    if achilles > 1:
                        narrative_history.append(f"  Achilles Heel: [red]×{achilles:.0f} damage from source[/red]")
                    if bane:
                        narrative_history.append(f"  Bane: [red]{bane} dmg/round[/red]")
                    if blocks["hp"]:
                        narrative_history.append(f"  No Healing: [red]blocked[/red]")
                    if blocks["rest"]:
                        narrative_history.append(f"  Nightmares: [red]rest recovery blocked[/red]")
                    if defect_sensory_obstacle(defs):
                        narrative_history.append(f"  Sensory Impairment: [red]Major Obstacle on perception[/red]")
                    for d in defs:
                        if isinstance(d, dict):
                            short = defect_shortcoming_obstacle(defs, d.get("aspect", ""))
                            if short:
                                narrative_history.append(f"  Shortcoming ({d.get('aspect','?')}): [red]{short.title()} Obstacle[/red]")

            # Action: /diceless (diceless BESM — Extras Ch.9 TCR + Table-15)
            elif player_input.lower().startswith("/diceless"):
                parts = player_input.split()
                sub = parts[1].lower() if len(parts) > 1 else "help"
                if sub in ("usage", "help"):
                    narrative_history.append("[bold yellow]System:[/bold yellow] /diceless usage:")
                    narrative_history.append("[dim]  /diceless <defender_cv> [AR] [extra_defences] [edge] — pure-algebraic clash vs a challenge[/dim]")
                    narrative_history.append("[dim]  /diceless hedge <target> [body|mind|soul] — auto-7 non-combat check (BESM4 p182)[/dim]")
                    narrative_history.append("[dim]  edge for the attacker: minor | major[/dim]")
                elif sub == "hedge":
                    if len(parts) < 3:
                        narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /diceless hedge <target> [body|mind|soul]")
                    else:
                        try:
                            target = int(parts[2])
                        except ValueError:
                            narrative_history.append("[bold yellow]System:[/bold yellow] Target must be an integer.")
                        else:
                            stat_key = parts[3].lower() if len(parts) > 3 else "body"
                            stat_map = {"body": char.stat_body, "mind": char.stat_mind, "soul": char.stat_soul}
                            if stat_key not in stat_map:
                                narrative_history.append("[bold yellow]System:[/bold yellow] Unknown stat. Use body, mind, or soul.")
                            else:
                                r = hedged_check(stat_map[stat_key], target)
                                veredict = "PASSED" if r["success"] else "FAILED"
                                narrative_history.append(
                                    f"[bold {'green' if r['success'] else 'red'}]Engine:[/bold {'green' if r['success'] else 'red'}] "
                                    f"Auto-7 ({r['rolled']}) + {stat_key.upper()}{r['total']-r['rolled']} = {r['total']} vs TN {target} — {veredict}"
                                )
                else:
                    try:
                        dcv = int(parts[1])
                    except (IndexError, ValueError):
                        narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /diceless <defender_cv> [AR] [extra_defences] [edge]")
                    else:
                        ar = int(parts[2]) if len(parts) > 2 else 0
                        edef = int(parts[3]) if len(parts) > 3 else 0
                        edge = parts[4].lower() if len(parts) > 4 else None
                        if edge not in ("minor", "major"):
                            if edge is not None:
                                narrative_history.append("[bold yellow]System:[/bold yellow] Edge must be minor or major — ignoring.")
                            edge = None
                        attacker = {
                            "combat_value": char.base_acv,
                            "current_hp": char.current_hp if char.current_hp is not None else char.max_hp,
                            "target_ar": ar,
                            "target_extra_defences": edef,
                        }
                        if edge:
                            attacker["edge"] = edge
                        a = compute_tcr(**attacker)
                        d = compute_tcr(combat_value=dcv)
                        r = resolve_diceless_combat(a["tcr"], d["tcr"])
                        band_title = r["band"].replace("_", " ").title()
                        victor = "Attacker" if r["attacker_wins"] else "Defender"
                        narrative_history.append(
                            f"[bold white]Total Combat Roll[/bold white] — "
                            f"Attacker {char.name}: TCR {a['tcr']} (CV {a['combat_value']}+HP {a['hp_mod']}"
                            + (f"+Edge {a['edge_mod']}" if edge else "")
                            + f"-AR {a['armour_mod']}-Def {a['defence_mod']}) | "
                            f"Defender: TCR {d['tcr']} (CV {dcv})"
                        )
                        narrative_history.append(
                            f"[bold {'green' if r['attacker_wins'] else 'red'}]Resolve:[/bold {'green' if r['attacker_wins'] else 'red'}] "
                            f"MoS {r['mos']} → {band_title} ({r['duration']}). {victor} wins — "
                            f"victor −{r['victor_hp_loss_pct']}% HP, opponent −{r['opponent_hp_loss_pct']}% HP."
                        )

            # Action: /maneuver (combat maneuver arsenal — stances, called shots, grappling)
            elif player_input.lower().startswith("/maneuver"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /maneuver <sub> (run '/maneuver list' for the menu).")
                else:
                    techs = char.combat_techniques or []
                    sub = parts[1].lower()
                    if sub in ("usage", "help", "list"):
                        narrative_history.append("[bold yellow]System:[/bold yellow] Maneuver menu:")
                        narrative_history.append("[dim]  stance <aim|wait|total_defence> [consecutive_rounds] [ranged] — tactical action[/dim]")
                        narrative_history.append("[dim]  two-weapon <1|2> — 1 target minor obstacle, 2 targets major[/dim]")
                        narrative_history.append("[dim]  strike <dmg> [area] [autofire] [spreading] — flat wound damage[/dim]")
                        narrative_history.append("[dim]  touch [protected] — passive Minor Edge[/dim]")
                        narrative_history.append("[dim]  called <shot> — disarm_melee|disarm_ranged|reduce_armour|bypass_armour|vital_spot|weak_point_*[/dim]")
                        narrative_history.append("[dim]  grapple <defender_free_hands> [attacker_free_hands] [size_delta] — grab initiation[/dim]")
                        narrative_history.append("[dim]  grabbed <grappler_body> [much_stronger] [much_weaker] — the Grabbed condition[/dim]")
                        narrative_history.append("[dim]  escape <grappler_body> [damage_dealt] — break a grapple[/dim]")
                        narrative_history.append("[dim]  pin — the Pinned condition[/dim]")
                        narrative_history.append("[dim]  multi <num_targets> — dispersion across N defenders[/dim]")
                    elif sub in ("stance", "aim", "wait", "total_defence"):
                        stance = (parts[2] if sub == "stance" and len(parts) > 2 else sub).lower()
                        cr = int(parts[3]) if sub == "stance" and len(parts) > 3 else 1
                        ranged = len(parts) > 4 and parts[4].lower() in ("ranged", "true", "1") if sub == "stance" else False
                        if stance not in ("aim", "wait", "total_defence"):
                            narrative_history.append("[bold yellow]System:[/bold yellow] stance must be aim, wait, or total_defence.")
                        else:
                            r = resolve_tactical_stance(stance, has_ranged=ranged, consecutive_rounds=cr)
                            if not r["valid"]:
                                narrative_history.append(f"[bold red]Maneuver Denied:[/bold red] {r['reason']}")
                            elif stance == "total_defence":
                                narrative_history.append(
                                    f"[bold cyan]Maneuver:[/bold cyan] Total Defence — {_edge_label(r['defence_edge'])} to defence; attacks off this round."
                                )
                            else:
                                narrative_history.append(
                                    f"[bold cyan]Maneuver:[/bold cyan] {stance.title()} (round {cr}) — {_edge_label(r['attack_edge'])} to next attack."
                                )
                    elif sub == "two-weapon":
                        same = not (len(parts) > 2 and parts[2] in ("2", "two"))
                        r = two_weapon_attack(same_target=same, techniques=techs)
                        target_txt = "one target" if same else "two targets"
                        if r["negated"]:
                            narrative_history.append(f"[bold cyan]Maneuver:[/bold cyan] Two-Weapon attack ({target_txt}) — penalty negated by 'Two Weapons' technique.")
                        else:
                            narrative_history.append(f"[bold cyan]Maneuver:[/bold cyan] Two-Weapon attack ({target_txt}) — {_obstacle_label(r['obstacle'])}.")
                    elif sub == "strike":
                        try:
                            base_dmg = int(parts[2])
                        except (IndexError, ValueError):
                            narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /maneuver strike <damage> [area] [autofire] [spreading]")
                        else:
                            flags = [p.lower() for p in parts[3:]]
                            r = strike_to_wound(base_dmg, has_area="area" in flags,
                                                has_autofire="autofire" in flags,
                                                has_spreading="spreading" in flags)
                            if r["valid"]:
                                narrative_history.append(f"[bold cyan]Maneuver:[/bold cyan] Strike to Wound — flat [bold white]{r['damage']} HP[/bold white] damage (un-multiplied).")
                            else:
                                narrative_history.append(f"[bold red]Maneuver Denied:[/bold red] {r['reason']}")
                    elif sub == "touch":
                        protected = len(parts) > 2 and parts[2].lower() in ("protected", "called", "spot")
                        r = touch_attack(called_spot=protected)
                        if r["requires_called_shot"]:
                            narrative_history.append(f"[bold cyan]Maneuver:[/bold cyan] Touching a protected spot — {_edge_label(r['edge'])} but the called-shot obstacle still applies.")
                        else:
                            narrative_history.append(f"[bold cyan]Maneuver:[/bold cyan] Touch attack — passive {_edge_label(r['edge'])}.")
                    elif sub == "called":
                        shot = " ".join(parts[2:]).lower()
                        if not shot:
                            narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /maneuver called <shot>")
                        else:
                            r = resolve_called_shot(shot, techs)
                            if not r["valid"]:
                                narrative_history.append(f"[bold red]Maneuver Denied:[/bold red] {r['reason']}")
                            else:
                                ar_txt = {"ignore": "ignores armour", "half": "halves armour", "": "normal armour"}.get(r["ar_effect"], "normal armour")
                                narrative_history.append(
                                    f"[bold cyan]Called Shot:[/bold cyan] {shot.title()} — {_obstacle_label(r['obstacle'])}, "
                                    f"{ar_txt}, damage ×{r['multiplier']}"
                                    + (f", Body TN {r['body_tn']}" if r.get("body_tn") else "")
                                    + (f", defender {_edge_label(r['defender_edge'])}" if r.get("defender_edge") else "")
                                )
                    elif sub in ("grapple", "grab"):
                        try:
                            dfh = int(parts[2])
                        except (IndexError, ValueError):
                            narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /maneuver grapple <defender_free_hands> [attacker_free_hands] [size_delta]")
                        else:
                            afh = int(parts[3]) if len(parts) > 3 else 2
                            sdelta = int(parts[4]) if len(parts) > 4 else 0
                            r = grapple_attack_edges(afh, dfh, sdelta)
                            target_txt = "much weaker (penalties escalate)" if r["much_weaker"] else "even footing"
                            narrative_history.append(
                                f"[bold cyan]Maneuver:[/bold cyan] Grapple initiation — {_edge_label(r['edge'])} (hands {r['free_hand_delta']:+d}), {target_txt}."
                            )
                    elif sub == "grabbed":
                        try:
                            gbody = int(parts[2])
                        except (IndexError, ValueError):
                            narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /maneuver grabbed <grappler_body> [much_stronger] [much_weaker]")
                        else:
                            strong = len(parts) > 3 and parts[3].lower() in ("much_stronger", "strong", "true")
                            weak = len(parts) > 4 and parts[4].lower() in ("much_weaker", "weak", "true")
                            r = grabbed_condition(gbody, char.stat_body, target_much_stronger=strong, target_much_weaker=weak)
                            if r["paralyzed"]:
                                narrative_history.append(f"[bold red]Grabbed:[/bold red] {char.name} is much weaker — completely paralyzed, no rolls permitted.")
                            else:
                                narrative_history.append(
                                    f"[bold cyan]Grabbed:[/bold cyan] {char.name} grappled by Body {gbody} vs Body {char.stat_body} — "
                                    f"{_obstacle_label(r['melee_obstacle'])} on melee, {_obstacle_label(r['task_obstacle'])} on movement."
                                )
                    elif sub in ("escape", "grapple-escape"):
                        try:
                            gbody = int(parts[2])
                        except (IndexError, ValueError):
                            narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /maneuver escape <grappler_body> [damage_dealt]")
                        else:
                            dmg = int(parts[3]) if len(parts) > 3 else 0
                            r = escape_grapple(char.stat_body, gbody, dmg)
                            if r["auto_escape"]:
                                narrative_history.append(f"[bold cyan]Escape:[/bold cyan] Pain Dissociation — {dmg} ≥ {r['threshold']} (5×Body {gbody}) — automatic escape.")
                            else:
                                narrative_history.append(f"[bold cyan]Escape:[/bold cyan] Opposed Body roll vs {gbody}; or deal {r['threshold']} HP in one shot to auto-escape.")
                    elif sub == "pin":
                        r = pin_condition()
                        narrative_history.append(
                            f"[bold cyan]Pinned:[/bold cyan] no attack, no defence — {_obstacle_label(r['escape_obstacle'])} on escape rolls."
                        )
                    elif sub in ("multi", "dispersion", "multi-target"):
                        try:
                            n = int(parts[2])
                        except (IndexError, ValueError):
                            narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /maneuver multi <num_targets>")
                        else:
                            r = multi_target_dispersion(n, techs)
                            narrative_history.append(
                                f"[bold cyan]Maneuver:[/bold cyan] {n} targets, one attack roll — {_obstacle_label(r['obstacle'])}"
                                + (f", defenders get {_edge_label(r['defender_edge'])}" if r["defender_edge"] else "")
                                + (" (unified roll)" if r.get("unified_roll") else "")
                            )
                    else:
                        narrative_history.append(f"[bold yellow]System:[/bold yellow] Unknown maneuver '{sub}'. Run '/maneuver list' for the menu.")

            # Action: /effects (list active scene effects at the current node)
            elif player_input.lower() == "/effects":
                effects = get_scene_effects(session_id, active_node.node_id)
                if not effects:
                    narrative_history.append("[bold yellow]System:[/bold yellow] No active scene effects at this node.")
                else:
                    narrative_history.append(f"[bold yellow]System:[/bold yellow] Active scene effects at '{active_node.title}':")
                    for e in effects:
                        narrative_history.append(
                            f"  [bold cyan]{e['kind']}[/bold cyan] ({e['rounds_remaining']} round{'s' if e['rounds_remaining'] != 1 else ''} left) [dim]{e['description']}[/dim]"
                        )

            # Action: /location <name> (look up a location from the atlas)
            elif player_input.lower().startswith("/location"):
                parts = player_input.split()
                if len(parts) < 2:
                    from engine.guild_roster import location_summary
                    narrative_history.append(f"[bold yellow]System:[/bold yellow] Location Atlas:")
                    for line in location_summary(active_setting_id).splitlines():
                        narrative_history.append(line)
                else:
                    from engine.guild_roster import get_location
                    name = " ".join(parts[1:])
                    loc = get_location(active_setting_id, name)
                    if loc:
                        narrative_history.append(f"[bold cyan]═══ LOCATION: {loc['name']} [{loc['location_type']}] ═══[/bold cyan]")
                        narrative_history.append(f"  Region: {loc['region']} | Travel: {loc['travel_from_capital'] or 'N/A'}")
                        narrative_history.append(f"  [dim]{loc['description']}[/dim]")
                        if loc['notes']:
                            narrative_history.append(f"  [italic]{loc['notes']}[/italic]")
                    else:
                        narrative_history.append(f"[bold yellow]System:[/bold yellow] No location matching '{name}'. Try /location alone to list all.")

            # Action: /threat <name> (look up a threat from the bestiary)
            elif player_input.lower().startswith("/threat"):
                parts = player_input.split()
                if len(parts) < 2:
                    from engine.guild_roster import threat_summary
                    narrative_history.append(f"[bold yellow]System:[/bold yellow] Threat Index:")
                    for line in threat_summary(active_setting_id).splitlines():
                        narrative_history.append(line)
                else:
                    from engine.guild_roster import get_threat
                    name = " ".join(parts[1:])
                    t = get_threat(active_setting_id, name)
                    if t:
                        from engine.models import size_lookup, size_strength_damage, size_armour_rating
                        narrative_history.append(f"[bold red]═══ THREAT: {t['name']} [{t['threat_type']}] ═══[/bold red]")
                        narrative_history.append(f"  Size {t['size_rank']} | HP {t['max_hp']} | AR {t['armour_rating']} | DMG {t['base_damage']}")
                        narrative_history.append(f"  Body {t['stat_body']} Mind {t['stat_mind']} Soul {t['stat_soul']}")
                        narrative_history.append(f"  [dim]{t['description']}[/dim]")
                        if t['lore']:
                            narrative_history.append(f"  [italic]{t['lore']}[/italic]")
                    else:
                        narrative_history.append(f"[bold yellow]System:[/bold yellow] No threat matching '{name}'. Try /threat alone to list all.")

            # Action: /attack
            elif player_input == "/attack":
                if active_node.required_check:
                    check_info = active_node.required_check
                    stat_name = check_info.get("stat", "stat_body")
                    skill_rank = check_info.get("skill", 0)
                    difficulty = check_info.get("dv", 12)
                    fail_damage = check_info.get("fail_damage", 0)
                    
                    stat_rank = getattr(char, stat_name, 6)
                    
                    narrative_history.append(f"[bold red]Combat Action:[/bold red] Attacking the obstacle using {stat_name.replace('stat_', '').upper()}...")
                    
                    res = execute_action_check(stat_rank, skill_rank=skill_rank, difficulty_value=difficulty)
                    roll = res["roll"]
                    total = res["total"]
                    success = res["success"]
                    
                    if success:
                        success_msg = f"[bold green]TELEMETRY SUCCESS:[/bold green] Breached {active_node.title} obstacle! (Roll: {roll} + Rank: {stat_rank} = {total} vs DV: {difficulty})"
                        narrative_history.append(success_msg)
                        log_narrative_turn(session_id, "System", success_msg)
                        
                        # Clear check from active_node and STORY_MAP
                        active_node.required_check = None
                        STORY_MAP[active_node.node_id]["required_check"] = None
                        
                        # Save cleared status to SQLite snapshot
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)
                    else:
                        fail_msg = f"[bold red]TELEMETRY FAILURE:[/bold red] Attack failed. (Roll: {roll} + Rank: {stat_rank} = {total} vs DV: {difficulty})"
                        narrative_history.append(fail_msg)
                        log_narrative_turn(session_id, "System", fail_msg)
                        
                        # Calculate and apply damage directly to player current_hp row in SQLite
                        current_hp = char.current_hp if char.current_hp is not None else char.max_hp
                        new_hp = max(0, current_hp - fail_damage)
                        char.current_hp = new_hp
                        
                        try:
                            from engine.state_manager import get_db_connection
                            with get_db_connection() as conn:
                                conn.execute("UPDATE character_vitals SET current_hp = ? WHERE session_id = ? AND name = ?", (new_hp, session_id, char.name))
                        except Exception as e:
                            logger.error(f"Error applying HP damage to DB: {e}")
                            
                        narrative_history.append(f"[bold red]Damage Applied:[/bold red] Took {fail_damage} damage. Current HP: {new_hp}/{char.max_hp}")
                        log_narrative_turn(session_id, "System", f"Applied {fail_damage} damage. HP now {new_hp}.")
                else:
                    narrative_history.append("[bold yellow]System:[/bold yellow] There is no active obstacle to attack in this area.")
            
            # Action: /loot (Item Inventory Subsystem Synthesis)
            elif player_input == "/loot":
                narrative_history.append("[bold blue]Player:[/bold blue] Searching coordinates for equipment artifacts...")

                vitals = build_vitals_with_full_loadout(active_setting_id, char, active_org)
                
                try:
                    compiled_prompt = bridge.compile_system_frame("besm_loot", vitals, node_dict)
                    response_dict = bridge.dispatch_ollama_turn(
                        model_name=ACTIVE_MODEL,
                        complete_context=compiled_prompt,
                        user_input="Player performs search action inside local stasis grid."
                    )
                    
                    if response_dict.get("success"):
                        prose, item_data = bridge.inspect_llm_output(response_dict["response"])
                        if item_data and "item_name" in item_data:
                            item_id = add_loot_to_inventory(session_id, item_data)
                            narrative_history.append(f"[bold yellow]AI Director:[/bold yellow] {prose}")
                            narrative_history.append(f"[bold green]Item Acquired:[/bold green] [bold white]{item_data['item_name']}[/bold white] (ID: {item_id}) Added to Inventory Ledger.")
                        else:
                            # Parse recovery fallback
                            fallback_item = {
                                "item_name": "Chronos Nanite Capacitor",
                                "item_type": "Accessory",
                                "attribute_granted": "stat_soul",
                                "raw_modifiers": "+1"
                            }
                            item_id = add_loot_to_inventory(session_id, fallback_item)
                            narrative_history.append("[bold yellow]AI Director (Parser Fallback):[/bold yellow] You found a Chronos Nanite Capacitor (+1 SOUL)!")
                    else:
                        # Offline fallback
                        fallback_item = {
                            "item_name": "Rust Vibroblade",
                            "item_type": "Weapon",
                            "attribute_granted": "stat_body",
                            "raw_modifiers": "+1"
                        }
                        item_id = add_loot_to_inventory(session_id, fallback_item)
                        narrative_history.append("[bold yellow]AI Director (Offline Fallback):[/bold yellow] You discover a discarded Rust Vibroblade (+1 BODY)!")
                except Exception as e:
                    logger.error(f"Loot synthesis failure: {e}")
                    narrative_history.append("[bold red]System Error:[/bold red] Loot extraction failed.")

            # Action: /open (Generative chest loot — The Pydantic Weaver)
            elif player_input == "/open":
                chest = getattr(active_node, "chest", None) or {}
                chest_tier = chest.get("tier") if isinstance(chest, dict) else None
                if not chest_tier:
                    narrative_history.append("[bold yellow]System:[/bold yellow] There is nothing to open here.")
                elif is_chest_opened(session_id, active_node.node_id):
                    narrative_history.append("[bold yellow]System:[/bold yellow] This chest has already been opened.")
                else:
                    narrative_history.append("[bold blue]Player:[/bold blue] Opening the chest...")
                    # CP-1: lock BEFORE the ~10s dispatch so a double-trigger can't
                    # double-generate; roll back on any failure.
                    mark_chest_opened(session_id, active_node.node_id)
                    stratum = active_node.stratum or 1
                    cap = loot_cap_for(chest_tier, stratum)
                    try:
                        vitals = build_vitals_with_full_loadout(active_setting_id, char, active_org)
                        node_ctx = node_dict.copy()
                        node_ctx["node_title"] = active_node.title
                        node_ctx["chest_tier"] = chest_tier
                        node_ctx["stratum"] = stratum
                        node_ctx["loot_cap"] = cap
                        compiled_prompt = bridge.compile_system_frame("loot_weaver", vitals, node_ctx)
                        response_dict = bridge.dispatch_ollama_turn(
                            model_name=ACTIVE_MODEL,
                            complete_context=compiled_prompt,
                            user_input="Player opens the chest."
                        )
                        if response_dict.get("success"):
                            raw = response_dict["response"]
                            item = parse_chest_loot(raw, chest_tier, stratum)
                            item_id = deposit_chest_loot(active_setting_id, char.name, item, stratum)
                            prose = raw.split("[LOOT PAYLOAD]")[0].strip()
                            narrative_history.append(f"[bold yellow]AI Director:[/bold yellow] {prose}")
                            narrative_history.append(f"[bold green]Chest Opened:[/bold green] [bold white]{item.name}[/bold white] ({item.item_type}, {item.item_cp} CP) added to inventory. [[dim]{item_id}[/dim]]")
                        else:
                            unmark_chest_opened(session_id, active_node.node_id)
                            narrative_history.append("[bold red]System Error:[/bold red] The chest creaks shut — the weave failed.")
                    except ValueError as e:
                        unmark_chest_opened(session_id, active_node.node_id)
                        logger.error(f"Chest loot parse rejected: {e}")
                        narrative_history.append("[bold red]System Error:[/bold red] The chest's contents refuse to materialize.")
                    except Exception as e:
                        unmark_chest_opened(session_id, active_node.node_id)
                        logger.error(f"Chest open failure: {e}")
                        narrative_history.append("[bold red]System Error:[/bold red] Chest open failed.")

            # Action: EXAMINE (invokes Ollama LLM Bridge with fallback)
            elif player_input.lower() == "examine":
                narrative_history.append(f"[bold blue]Player:[/bold blue] Examining surroundings...")

                vitals = build_vitals_with_full_loadout(active_setting_id, char, active_org)
                
                try:
                    compiled_prompt = bridge.compile_system_frame("besm_shell", vitals, node_dict)
                    response_dict = bridge.dispatch_ollama_turn(
                        model_name=ACTIVE_MODEL,
                        complete_context=compiled_prompt,
                        user_input="Player examines the details of the environment."
                    )
                    
                    if response_dict.get("success"):
                        prose, _ = bridge.inspect_llm_output(response_dict["response"])
                    else:
                        prose = f"The environment matches active descriptors: {active_node.description}"
                except Exception as e:
                    logger.error(f"Inference bridge error: {e}")
                    prose = f"The environment matches active descriptors: {active_node.description}"
                    
                narrative_history.append(f"[bold yellow]AI Director:[/bold yellow] {prose}")
                log_narrative_turn(session_id, "AI Director", prose)
                
            # Action: MOVEMENT
            elif player_input.lower() in ["north", "south", "east", "west"]:
                direction = player_input.lower()
                if direction in active_node.exits:
                    target_id = active_node.exits[direction]
                    target_node_data = STORY_MAP[target_id]
                    
                    # Resolve obstacles using rule check coprocessor
                    if target_node_data.get("required_check"):
                        check_info = target_node_data["required_check"]
                        stat_name = check_info.get("stat", "stat_body")
                        skill_rank = check_info.get("skill", 0)
                        difficulty = check_info.get("dv", 12)
                        
                        stat_rank = getattr(char, stat_name, 6)
                        
                        narrative_history.append(f"[bold red]System Check:[/bold red] Traversing requires a {stat_name.replace('stat_', '').upper()} check (Difficulty: {difficulty})...")
                        
                        try:
                            res = execute_action_check(stat_rank, skill_rank=skill_rank, difficulty_value=difficulty)
                            roll = res["roll"]
                            total = res["total"]
                            success = res["success"]
                            
                            narrative_history.append(
                                f"[bold red]Roll Outcome:[/bold red] 2d6 ({roll}) + Stat Rank ({stat_rank}) + Skill Rank ({skill_rank}) = {total} vs Target ({difficulty}) -> "
                                f"{'[green]SUCCESS[/green]' if success else '[red]FAILURE[/red]'}"
                            )
                            
                            if success:
                                active_node = NodeSchema(**target_node_data)
                                save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)
                                _expired = tick_scene_effects(session_id, active_node.node_id)
                                if _expired:
                                    narrative_history.append(f"[dim]System: {_expired} scene effect(s) expired as a round passed at '{active_node.title}'.[/dim]")
                                narrative_history.append(f"[bold cyan]System:[/bold cyan] Moved to [bold green]{active_node.title}[/bold green].")
                            else:
                                narrative_history.append("[bold yellow]AI Director:[/bold yellow] You failed to bypass the obstacle and remain at your position.")
                        except Exception as e:
                            logger.error(f"Action check error: {e}")
                            narrative_history.append("[bold red]System Error:[/bold red] Failed to resolve check, navigation halted.")
                    else:
                        # Move freely
                        active_node = NodeSchema(**target_node_data)
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name, active_org)
                        _expired = tick_scene_effects(session_id, active_node.node_id)
                        if _expired:
                            narrative_history.append(f"[dim]System: {_expired} scene effect(s) expired as a round passed at '{active_node.title}'.[/dim]")
                        narrative_history.append(f"[bold cyan]System:[/bold cyan] Moved to [bold green]{active_node.title}[/bold green].")
                else:
                    narrative_history.append(f"[bold red]System:[/bold red] You cannot go {direction.upper()} from here.")
            else:
                narrative_history.append(f"[bold red]System:[/bold red] Unknown action '{player_input}'.")
                
            # Cap the narrative list size to prevent overflowing the pane boundaries
            if len(narrative_history) > 10:
                narrative_history = narrative_history[-10:]
                
            # Restart live updates
            live.start()

if __name__ == "__main__":
    main()
