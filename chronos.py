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
    LLMBridge,
    ACTIVE_MODEL,
    OLLAMA_URL,
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
    Convert a roster DB dict to a CharacterSchema with all BESA fields populated.
    Centralizes the JSON parsing for combat_techniques, skills, defects.
    """
    import json
    char = CharacterSchema(
        name=rc["name"],
        stat_body=rc["stat_body"],
        stat_mind=rc["stat_mind"],
        stat_soul=rc["stat_soul"],
        current_hp=rc.get("max_hp"),
        current_ep=rc.get("max_ep")
    )
    char.points_budget = rc.get("points_budget", 75)
    char.shock_value = rc.get("shock_value", char.max_hp // 5)
    char.combat_techniques = json.loads(rc.get("combat_techniques", "[]"))
    char.skills = json.loads(rc.get("skills", "[]"))
    char.defects = json.loads(rc.get("defects", "[]"))
    return char


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

def build_vitals_with_full_loadout(setting_id: str, char: CharacterSchema) -> dict:
    """
    Compiles the FULL character loadout for the LLM shell. Injects narrative-syntax
    fields (Sixth Guard, Structural Fault, Three Levers) AND BESA rules fields
    (Combat Techniques, Skills, Defects, Shock Value) from the roster DB.
    Falls back to empty defaults if the character has no data.
    """
    import json
    from engine.guild_roster import get_character
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
        # BESA rules
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
    return vitals

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
    Falls back to the setting's default_module, then to a built-in fallback map.
    Returns (story_map, resolved_module_name).
    """
    from engine.guild_roster import get_setting

    setting = get_setting(setting_id) or {}
    resolved = module_name or setting.get("default_module", "")
    module_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules", resolved)
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
    active_module_name = nav.get("module_name") or ""

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
    save_runtime_snapshot(session_id, char, active_node_id, active_setting_id, active_module_name)

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
            console.print("[bold cyan]COMMANDS:[/bold cyan] [white]exit | examine | north | south | east | west | /attack | /loot | /roster | /settings | /setting <id> | /module <name> | /char <name> | /shop | /buy <item_id> | /wallet | /grant <silver> | /inventory | /loadout | /greetings | /startgreeting <n> | /use <item_id> | auto-ingest[/white]")
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
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name)
                        narrative_history.append(f"[bold green]System:[/bold green] Switched to setting '{active_setting_id}' (module: {active_module_name}). Active character: {char.name}.")

            # Action: /module <name> (switch campaign module within the active setting)
            elif player_input.lower().startswith("/module"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /module <module_filename.json> (e.g. forest_labyrinth_v1.json).")
                else:
                    target = parts[1]
                    STORY_MAP, active_module_name = load_campaign_module(active_setting_id, target)
                    active_node_id = list(STORY_MAP.keys())[0]
                    active_node = NodeSchema(**STORY_MAP[active_node_id])
                    save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name)
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
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name)
                        narrative_history.append(f"[bold green]System:[/bold green] Active character set to {char.name} (SV={char.shock_value}).")

            # Action: /shop [rank] (list setting item catalog)
            elif player_input.lower().startswith("/shop"):
                parts = player_input.split()
                rank_filter = parts[1].upper() if len(parts) > 1 else None
                shop_text = catalog_summary(active_setting_id, rank_filter)
                narrative_history.append(f"[bold yellow]System:[/bold yellow] [{active_setting_id}] shop listing:")
                for line in shop_text.splitlines():
                    narrative_history.append(f"[dim]{line}[/dim]")

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

            # Action: /loadout (show full BESA build)
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
                    narrative_history.append("[dim]Use /startgreeting <number> to begin a session.[/dim]")
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
                            # Build greeting as initial narrative node
                            greeting_text = g['text']
                            if g['opening']:
                                greeting_text += f"\n\n{g['name'] if hasattr(char, 'name') else char.name}: \"{g['opening']}\""
                            narrative_history.append(f"[bold green]Session Started:[/bold green] {char.name} — Greeting {idx+1}")
                            narrative_history.append(f"[dim]{g['scene'][:100]}[/dim]" if g['scene'] else "")
                            narrative_history.append("")
                            # Inject greeting as the first narrative turn via LLM
                            vitals = build_vitals_with_full_loadout(active_setting_id, char)
                            try:
                                compiled = bridge.compile_system_frame("besm_shell", vitals, {
                                    'node_id': f'greeting_{idx+1}',
                                    'title': f'{char.name} — Greeting {idx+1}',
                                    'description': greeting_text,
                                    'exits': {},
                                    'required_check': None,
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

            # Action: /use <item_id> (consume a consumable)
            elif player_input.lower().startswith("/use"):
                parts = player_input.split()
                if len(parts) < 2:
                    narrative_history.append("[bold yellow]System:[/bold yellow] Usage: /use <item_id> (run /inventory to list).")
                else:
                    item_id = parts[1].lower()
                    ok, msg = use_item(active_setting_id, char.name, item_id)
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
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name)
                    else:
                        narrative_history.append(f"[bold red]Use Failed:[/bold red] {msg}")

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
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name)
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

                vitals = build_vitals_with_full_loadout(active_setting_id, char)
                
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

            # Action: EXAMINE (invokes Ollama LLM Bridge with fallback)
            elif player_input.lower() == "examine":
                narrative_history.append(f"[bold blue]Player:[/bold blue] Examining surroundings...")

                vitals = build_vitals_with_full_loadout(active_setting_id, char)
                
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
                                save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name)
                                narrative_history.append(f"[bold cyan]System:[/bold cyan] Moved to [bold green]{active_node.title}[/bold green].")
                            else:
                                narrative_history.append("[bold yellow]AI Director:[/bold yellow] You failed to bypass the obstacle and remain at your position.")
                        except Exception as e:
                            logger.error(f"Action check error: {e}")
                            narrative_history.append("[bold red]System Error:[/bold red] Failed to resolve check, navigation halted.")
                    else:
                        # Move freely
                        active_node = NodeSchema(**target_node_data)
                        save_runtime_snapshot(session_id, char, active_node.node_id, active_setting_id, active_module_name)
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
