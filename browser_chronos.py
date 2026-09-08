#!/usr/bin/env python3
"""browser_chronos.py — Streamlit web port of Chronos Core TUI.

Replaces the Rich TUI command loop with a sidebar-configured web dashboard
while keeping all BESM 4e engine logic headless and unchanged.

Run:
    cd chronos-core
    streamlit run browser_chronos.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ── sys.path bootstrap: shared core + this project ──────────────────────
# Per AGENTS.md PEP-420: dev/ must NOT have __init__.py for auto-merging.
# We insert manually so engine/* modules resolve correctly without copy-paste.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/ — shared core (ollama)
sys.path.insert(0, str(Path(__file__).resolve().parent))                # chronos-core/

import streamlit as st

from engine import (
    CharacterSchema, NodeSchema,
    execute_action_check, check_shock, check_incapacitation,
    check_poison_resistance, check_sanity, check_catastrophic_damage,
    resolve_combat_roll, resolve_attack_damage, character_scv,
    falling_damage, range_obstacle, size_lookup, size_knockback,
    sanity_obstacle, hp_recovery, ep_recovery,
    compute_tcr, resolve_diceless_combat, hedged_check,
    resolve_tactical_stance, two_weapon_attack, strike_to_wound,
    touch_attack, resolve_called_shot, grapple_attack_edges,
    grabbed_condition, escape_grapple, pin_condition, multi_target_dispersion,
    technique_obstacle_reduction, technique_edge_bonus,
    defect_hp_modifier, defect_damage_modifier, defect_blocks_recovery,
    defect_achilles_multiplier, defect_bane_damage,
    defect_sensory_obstacle, defect_shortcoming_obstacle,
    init_db, save_runtime_snapshot, load_runtime_navigation,
    log_narrative_turn, add_loot_to_inventory, get_character_inventory,
    init_economy_db, catalog_summary, get_wallet, grant_silver,
    buy_item, inventory_summary, use_item,
    seed_besm_catalog, besm_catalog_summary, besm_catalog_matches,
    get_scene_effects, tick_scene_effects, run_auto_ingest,
    LLMBridge, ACTIVE_MODEL, THIN_MODEL, DEFAULT_RULES, DEFAULT_SETTING,
)
from engine.guild_roster import (
    init_roster_db, list_characters, get_character, get_setting,
    list_settings, list_locations, roster_summary,
    load_campaign_module, roster_dict_to_char,
    get_roster_connection, get_character_loadout, format_loadout_summary,
    get_character_greetings, format_greeting_list,
    location_summary, get_location, threat_summary, get_threat,
    build_vitals_with_full_loadout, build_greeting_start,
)
from engine.state_manager import (
    get_db_connection, init_db as init_state_db, set_active_db_path,
    WEB_SESSION_DB_PATH,
)
from core.ollama import default_chain, post_json

# ── render helpers ────────────────────────────────────────────────────────

# CP-8: active_char_name — normalized name accessor (Pydantic attr vs raw dict row)
def active_char_name(char) -> str:
    return getattr(char, "name", None) or (char.get("name") if isinstance(char, dict) else "?")


# CP-9: Rich markup stripper for st.markdown. Targets ONLY known Rich style tags
# (colors, bold/dim/italic/…, compound "bold red on black"), leaving semantic
# markers like [Hub], [Quest], [D-Rank] and plain prose brackets intact.
_RICH_STYLE_TOKEN = (
    r"(?:bold|dim|italic|underline|strike|blink|reverse|conceal"
    r"|(?:bright_)?(?:black|red|green|yellow|blue|magenta|cyan|white|grey|gray)"
    r"|gold1|gold3|orange3|sky_blue1|spring_green3|default|on)"
)
_RICH_TAG_RE = re.compile(rf"\[/?{_RICH_STYLE_TOKEN}(?:\s+{_RICH_STYLE_TOKEN})*\]", re.IGNORECASE)


def _rich_to_markdown(text: str) -> str:
    """Strip Rich console markup for st.markdown, preserving semantic [Hub]/[Quest] tags."""
    return _RICH_TAG_RE.sub("", text)


def _obstacle_label(weight: int) -> str:
    """Turn an obstacle weight into its BESM-facing label (mirrors chronos.py)."""
    if weight <= 0:
        return "no obstacle"
    return "Minor Obstacle" if weight == 1 else "Major Obstacle"


def _edge_label(weight: int) -> str:
    """Turn an edge weight into its BESM-facing label (mirrors chronos.py)."""
    if weight <= 0:
        return "no edge"
    return "Minor Edge" if weight == 1 else "Major Edge"

# ── page config ───────────────────────────────────────────────────────────
st.set_page_config(page_title="Chronos Core — Web Edition", layout="wide")
st.title("⚡ Chronos Core — Web Edition")
st.caption("Browser port of the BESM 4e rules engine — LLM narration, Python rules")

# ── session initialization ────────────────────────────────────────────────
# Bootstrap sentinel: prevents Streamlit re-exec from wiping state on every widget change
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    # Redirect ALL session-DB access to the web port's own DB (CP-2) so the
    # CLI's chronos_session.db is never touched. Must be set before init_db().
    set_active_db_path(WEB_SESSION_DB_PATH)
    init_state_db()
    # Load default setting (Guild RPG) and bind home hub
    st.session_state.setting_id = DEFAULT_SETTING or "guild_rpg"
    st.session_state.active_org = "Aelthar Keldor"
    st.session_state.active_node_id = "node_start"
    # Load the first available character for the default setting
    roster_chars = list_characters(setting_id=st.session_state.setting_id)
    if roster_chars:
        st.session_state.char = roster_dict_to_char(roster_chars[0])
    else:
        from engine.models import CharacterSchema
        st.session_state.char = CharacterSchema(name="Alex Mercer", stat_body=6, stat_mind=8, stat_soul=6)
        st.session_state.char.current_hp = st.session_state.char.max_hp
        st.session_state.char.current_ep = st.session_state.char.max_ep
    # Narrative history ledger
    st.session_state.narrative_history = [
        "[bold cyan]System:[/bold cyan] Welcome to [bold gold1]Chronos Core[/bold gold1]. Connection to local DB active.",
        f"[bold cyan]System:[/bold cyan] Session loaded. Active location: [bold green]{st.session_state.active_node_id}[/bold green]"
    ]
    # Vitals cache keyed on (char_id, mtime) for @st.cache_data
    st.session_state.__math_cache__ = {}

# ── sidebar: disc & roster configuration ──────────────────────────────────
st.sidebar.header("Chronos Core Configuration")

# Model selector
ACTIVE_MODEL = st.sidebar.text_input("Model", value=ACTIVE_MODEL or "gemma4-agentic-16k:latest")
THIN_MODEL = st.sidebar.text_input("Thin Model", value=THIN_MODEL or "deepseek-r1:7b")

# Setting selector
setting_id = st.sidebar.radio(
    "Setting",
    options=["guild_rpg", "shota_x_monsters", "my_hero_academia"],
    index=["guild_rpg", "shota_x_monsters", "my_hero_academia"].index(st.session_state.setting_id),
    help="Disc-based campaign setting. Guild RPG = Aelthar Keldor, SxM = labyrinth taming, MHA = U.A. High",
)
st.session_state.setting_id = setting_id

# Module selector
if "story_map" not in st.session_state or st.session_state.get("last_setting_id") != setting_id:
    st.session_state.last_setting_id = setting_id
    story_map, st.session_state.module_name = load_campaign_module(setting_id, None)
    st.session_state.story_map = story_map
STORY_MAP = st.session_state.story_map
active_module_name = st.session_state.module_name
node_options = list(STORY_MAP.keys())
if not node_options:
    st.sidebar.error("No nodes in the loaded campaign module.")
    st.stop()
if st.session_state.active_node_id not in node_options:
    st.session_state.active_node_id = node_options[0]
st.sidebar.caption(f"Module: {active_module_name}")
st.session_state.active_node_id = st.sidebar.selectbox(
    "Active Node",
    options=node_options,
    index=node_options.index(st.session_state.active_node_id),
    help="Current position within the campaign module.",
)
active_node_id = st.session_state.active_node_id

active_org = st.sidebar.text_input("Home Guild / Org", value=st.session_state.active_org)
st.session_state.active_org = active_org

# ── main: vitals HUD + narrative chat ────────────────────────────────────
# Load character and node from session state
char = st.session_state.char
active_node = NodeSchema(**STORY_MAP.get(active_node_id, list(STORY_MAP.values())[0]))

# Vitals HUD column layout
col1, col2 = st.columns(2)

with col1:
    current_hp = min(char.current_hp, char.max_hp) if char.current_hp is not None else char.max_hp
    current_ep = min(char.current_ep, char.max_ep) if char.current_ep is not None else char.max_ep
    hp_bar = max(0, min(100, int((current_hp / char.max_hp) * 100))) if char.max_hp > 0 else 0
    ep_bar = max(0, min(100, int((current_ep / char.max_ep) * 100))) if char.max_ep > 0 else 0
    sv = (char.shock_value if char.shock_value else char.max_hp // 5)
    sv_bar = max(0, min(100, int((sv / (char.max_hp // 2)) * 100))) if char.max_hp > 0 else 0

    st.metric("HP", f"{current_hp}/{char.max_hp}", f"{hp_bar}%")
    st.metric("EP", f"{current_ep}/{char.max_ep}", f"{ep_bar}%")
    st.progress(hp_bar, "HP")
    st.progress(ep_bar, "EP")
    st.metric("Shock Value", f"{sv}/{char.max_hp // 2}", f"{int(sv_bar)}%")

with col2:
    st.metric("ACV", f"{char.base_acv}")
    st.metric("DCV", f"{char.base_dcv}")
    st.metric("Points Budget", f"{char.points_budget} CP")
    st.metric("Stats", f"Body {char.stat_body} | Mind {char.stat_mind} | Soul {char.stat_soul}")

# Narrative chat area
st.divider()
st.subheader("📜 Narrative Log")

# Display narrative history (Rich markup stripped for st.markdown — CP-9)
for entry in st.session_state.narrative_history:
    st.markdown(_rich_to_markdown(entry))

# Command input
st.divider()
st.subheader("⚡ Command")
player_input = st.chat_input("Enter command...", key="chat_input")

WEB_SESSION_ID = "web_port_session"

# "Examine surroundings" button triggers an AI Director turn without chat input
if st.button("👁️ Examine Surroundings", type="primary", use_container_width=True):
    player_input = "examine"

# Command handler — mirrors chronos.py if/elif dispatch (Phase A display first, Director fallback)
if player_input:
    # Log the action
    log_narrative_turn(WEB_SESSION_ID, "Player", player_input)

    cmd = player_input.strip()
    cmd_lower = cmd.lower()
    char_name = active_char_name(char)
    nh = st.session_state.narrative_history
    handled = False

    # ── Phase A: read-only display commands (zero LLM, zero writes) ───────
    if cmd_lower == "/engine":
        nh.append("[bold yellow]System:[/bold yellow] BESM Engine Commands:")
        for c in [
            "/shock <dmg>", "/resist <poison|sleep|paralysis> [blight]",
            "/fall <meters>", "/range <max> <distance>",
            "/size <rank>", "/defence <dmg> [AR] [FF_AR] [pen]",
            "/scv", "/sanity <mild|mod|major|severe|cat>",
            "/recover", "/techniques", "/defects",
            "/diceless <defender_cv> [AR] [extra_def] [edge]", "/diceless hedge <target> [stat]",
            "/maneuver <subcommand>", "/effects",
            "/roster", "/lore", "/settings", "/shop", "/wallet",
            "/inventory", "/loadout", "/greetings", "/location", "/threat",
        ]:
            nh.append(f"  [dim]{c}[/dim]")
        handled = True

    elif cmd_lower == "/roster":
        setting_meta = get_setting(setting_id) or {}
        roster_text = roster_summary(setting_id=setting_id)
        label = setting_meta.get("character_label", "Rank")
        nh.append(f"[bold yellow]System:[/bold yellow] [{setting_meta.get('name', setting_id)}] roster ({label} column):")
        for line in roster_text.splitlines():
            nh.append(f"[dim]{line}[/dim]")
        handled = True

    elif cmd_lower == "/lore":
        with get_roster_connection() as conn:
            row = conn.execute(
                "SELECT name, description, setting_lore FROM settings WHERE setting_id = ?",
                (setting_id,)
            ).fetchone()
        if row:
            nh.append(f"[bold gold1]═══ SETTING: {row[0]} ═══[/bold gold1]")
            if row[1]:
                nh.append(f"  [dim]{row[1]}[/dim]")
            if row[2]:
                for line in row[2].split('. '):
                    if line.strip():
                        nh.append(f"  {line.strip()}.")
        else:
            nh.append("[bold yellow]System:[/bold yellow] No lore available for current setting.")
        handled = True

    elif cmd_lower == "/settings":
        nh.append("[bold yellow]System:[/bold yellow] Registered settings:")
        for s in list_settings():
            marker = " >" if s["setting_id"] == setting_id else "  "
            nh.append(f"[dim]{marker} [{s['setting_id']}] {s['name']} (module: {s['default_module']})[/dim]")
        handled = True

    elif cmd_lower.startswith("/shop"):
        parts = cmd.split()
        rank_filter = parts[1].upper() if len(parts) > 1 else None
        shop_text = catalog_summary(setting_id, rank_filter)
        nh.append(f"[bold yellow]System:[/bold yellow] [{setting_id}] shop listing:")
        for line in shop_text.splitlines():
            nh.append(f"[dim]{line}[/dim]")
        handled = True

    elif cmd_lower.startswith("/wallet"):
        parts = cmd.split()
        name = " ".join(parts[1:]) if len(parts) > 1 else char_name
        balance = get_wallet(setting_id, name)
        nh.append(f"[bold yellow]System:[/bold yellow] [{setting_id}] {name} wallet: [bold white]{balance} sp[/bold white].")
        handled = True

    elif cmd_lower == "/inventory":
        inv_text = inventory_summary(setting_id, char_name)
        nh.append(f"[bold yellow]System:[/bold yellow] [{setting_id}] {char_name} inventory:")
        for line in inv_text.splitlines():
            nh.append(f"[dim]{line}[/dim]")
        handled = True

    elif cmd_lower == "/loadout":
        loadout = get_character_loadout(setting_id, char_name)
        if loadout:
            nh.append(f"[bold yellow]System:[/bold yellow] [{setting_id}] {char_name} full loadout:")
            for line in format_loadout_summary(loadout).splitlines():
                nh.append(f"  {line}")
        else:
            nh.append("[bold red]System:[/bold red] No loadout data available.")
        handled = True

    elif cmd_lower == "/greetings":
        greetings = get_character_greetings(setting_id, char_name)
        if greetings:
            nh.append(f"[bold yellow]System:[/bold yellow] [{setting_id}] {char_name} session starters ({len(greetings)}):")
            for line in format_greeting_list(greetings).splitlines():
                nh.append(f"  {line}")
            nh.append("[dim]Use /startgreeting <number> to begin a session. [Hub] greetings open at the guild hall.[/dim]")
        else:
            nh.append("[bold yellow]System:[/bold yellow] No greetings available for this character (source file missing).")
        handled = True

    elif cmd_lower.startswith("/startgreeting"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append("[bold yellow]System:[/bold yellow] Usage: /startgreeting <number> (run /greetings to list).")
        else:
            try:
                idx = int(parts[1]) - 1
            except ValueError:
                nh.append("[bold yellow]System:[/bold yellow] Usage: /startgreeting <number>.")
            else:
                greetings = get_character_greetings(setting_id, char_name)
                if not greetings:
                    nh.append("[bold red]System:[/bold red] No greetings available.")
                elif idx < 0 or idx >= len(greetings):
                    nh.append(f"[bold red]System:[/bold red] Greeting {idx+1} not found. Use /greetings to list.")
                else:
                    g = greetings[idx]
                    # CP-4: commit the node FIRST (local, synchronous, idempotent)
                    kind, start_node, greeting_text = build_greeting_start(char, g, st.session_state.active_org, idx)
                    # CP-10/CP-10H: inject the synthetic node into the active disc's map so the
                    # sidebar node_options re-syncs; evicted automatically on setting swap (map re-derives).
                    st.session_state.story_map[start_node.node_id] = start_node.model_dump()
                    st.session_state.active_node_id = start_node.node_id
                    if kind == "domestic":
                        nh.append(f"[bold green]Session Started at the Hub:[/bold green] {char_name} — {start_node.title} (Greeting {idx+1})")
                    else:
                        nh.append(f"[bold green]Session Started:[/bold green] {char_name} — Greeting {idx+1}")
                    nh.append(f"[dim]{g['scene'][:100]}[/dim]")
                    # Then fire the Director opening turn (LLM failure logs an error, node stays — CP-4)
                    try:
                        from engine.llm_bridge import LLMBridge
                        bridge = LLMBridge()
                        vitals = build_vitals_with_full_loadout(setting_id, char, st.session_state.active_org)
                        compiled = bridge.compile_system_frame("besm_shell", vitals, {
                            'node_id': start_node.node_id,
                            'title': start_node.title,
                            'description': start_node.description,
                            'exits': start_node.exits,
                            'required_check': getattr(start_node, 'required_check', None),
                        })
                        with st.spinner("AI Director is composing..."):
                            result = bridge.dispatch_ollama_turn(ACTIVE_MODEL, compiled, "Player observes the scene.")
                        if result.get('success'):
                            prose, _ = bridge.inspect_llm_output(result['response'])
                            nh.append(f"[bold yellow]AI Director:[/bold yellow] {prose}")
                        else:
                            nh.append(f"[bold red]System Error:[/bold red] LLM dispatch failed: {result.get('error', 'Unknown')}")
                    except Exception as e:
                        nh.append(f"[bold red]System Error:[/bold red] {e}")
                    finally:
                        save_runtime_snapshot(WEB_SESSION_ID, char, start_node.node_id, setting_id, active_module_name, st.session_state.active_org)
        handled = True

    elif cmd_lower == "/scv":
        scv = character_scv(char)
        demure = -2 * (next((d.get("rank", 0) for d in (char.defects or []) if isinstance(d, dict) and d.get("name", "").lower() == "demure"), 0))
        nh.append(
            f"[bold white]Social Profile:[/bold white] SCV={scv} (Mind{char.stat_mind}+Soul{char.stat_soul})/2"
            + (f" Demure{demure}" if demure else "")
            + f" | Society Points={scv} | Recovery: 1/hour"
        )
        handled = True

    elif cmd_lower == "/techniques":
        techs = char.combat_techniques or []
        if not techs:
            nh.append("[dim]No combat techniques equipped.[/dim]")
        else:
            nh.append("[bold white]Active Technique Effects:[/bold white]")
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
                    nh.append(f"  [bold]{name}[/bold] Lv{lvl}" + (f" — {', '.join(effects)}" if effects else ""))
        handled = True

    elif cmd_lower == "/defects":
        defs = char.defects or []
        if not defs:
            nh.append("[dim]No defects.[/dim]")
        else:
            nh.append("[bold red]Active Defect Effects:[/bold red]")
            hp_mod = defect_hp_modifier(defs)
            dmg_mod = defect_damage_modifier(defs)
            blocks = defect_blocks_recovery(defs)
            achilles = defect_achilles_multiplier(defs, "")
            bane = defect_bane_damage(defs)
            if hp_mod:
                nh.append(f"  Fragile: [red]{hp_mod} max HP[/red]")
            if dmg_mod:
                nh.append(f"  Reduced Damage: [red]{dmg_mod} Damage Multiplier[/red]")
            if achilles > 1:
                nh.append(f"  Achilles Heel: [red]×{achilles:.0f} damage from source[/red]")
            if bane:
                nh.append(f"  Bane: [red]{bane} dmg/round[/red]")
            if blocks["hp"]:
                nh.append("  No Healing: [red]blocked[/red]")
            if blocks["rest"]:
                nh.append("  Nightmares: [red]rest recovery blocked[/red]")
            if defect_sensory_obstacle(defs):
                nh.append("  Sensory Impairment: [red]Major Obstacle on perception[/red]")
            for d in defs:
                if isinstance(d, dict):
                    short = defect_shortcoming_obstacle(defs, d.get("aspect", ""))
                    if short:
                        nh.append(f"  Shortcoming ({d.get('aspect', '?')}): [red]{short.title()} Obstacle[/red]")
        handled = True

    elif cmd_lower == "/effects":
        effects = get_scene_effects(WEB_SESSION_ID, active_node.node_id)
        if not effects:
            nh.append("[bold yellow]System:[/bold yellow] No active scene effects at this node.")
        else:
            nh.append(f"[bold yellow]System:[/bold yellow] Active scene effects at '{active_node.title}':")
            for e in effects:
                nh.append(
                    f"  [bold cyan]{e['kind']}[/bold cyan] ({e['rounds_remaining']} round{'s' if e['rounds_remaining'] != 1 else ''} left) [dim]{e['description']}[/dim]"
                )
        handled = True

    elif cmd_lower.startswith("/location"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append(f"[bold yellow]System:[/bold yellow] Location Atlas:")
            for line in location_summary(setting_id).splitlines():
                nh.append(line)
        else:
            name = " ".join(parts[1:])
            loc = get_location(setting_id, name)
            if loc:
                nh.append(f"[bold cyan]═══ LOCATION: {loc['name']} [{loc['location_type']}] ═══[/bold cyan]")
                nh.append(f"  Region: {loc['region']} | Travel: {loc['travel_from_capital'] or 'N/A'}")
                nh.append(f"  [dim]{loc['description']}[/dim]")
                if loc['notes']:
                    nh.append(f"  [italic]{loc['notes']}[/italic]")
            else:
                nh.append(f"[bold yellow]System:[/bold yellow] No location matching '{name}'. Try /location alone to list all.")
        handled = True

    elif cmd_lower.startswith("/threat"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append(f"[bold yellow]System:[/bold yellow] Threat Index:")
            for line in threat_summary(setting_id).splitlines():
                nh.append(line)
        else:
            name = " ".join(parts[1:])
            t = get_threat(setting_id, name)
            if t:
                nh.append(f"[bold red]═══ THREAT: {t['name']} [{t['threat_type']}] ═══[/bold red]")
                nh.append(f"  Size {t['size_rank']} | HP {t['max_hp']} | AR {t['armour_rating']} | DMG {t['base_damage']}")
                nh.append(f"  Body {t['stat_body']} Mind {t['stat_mind']} Soul {t['stat_soul']}")
                nh.append(f"  [dim]{t['description']}[/dim]")
                if t['lore']:
                    nh.append(f"  [italic]{t['lore']}[/italic]")
            else:
                nh.append(f"[bold yellow]System:[/bold yellow] No threat matching '{name}'. Try /threat alone to list all.")
        handled = True

    # ── Phase B: deterministic BESM math (zero LLM, zero writes) ──────────
    elif cmd_lower.startswith("/shock"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append("[bold yellow]System:[/bold yellow] Usage: /shock <damage_taken>")
        else:
            try:
                dmg = int(parts[1])
            except ValueError:
                nh.append("[bold yellow]System:[/bold yellow] Damage must be an integer.")
            else:
                r = check_shock(char, dmg)
                if not r["triggered"]:
                    nh.append(f"[bold green]Engine:[/bold green] {dmg} damage — below SV ({char.shock_value_computed}). No shock check triggered.")
                elif r["status_key"] is None:
                    nh.append(f"[bold green]Engine:[/bold green] {r['severity']} shock check PASSED (roll {r['roll']}+Soul{char.stat_soul}={r['total']} vs TN {r['target']}).")
                elif r["status_key"] == "shocked":
                    nh.append(f"[bold red]Engine:[/bold red] SHOCKED! Roll {r['roll']}+Soul{char.stat_soul}={r['total']} vs TN {r['target']} — margin {r['margin']}. Stunned — lose next action.")
                else:
                    nh.append(f"[bold red]Engine:[/bold red] UNCONSCIOUS! {r['unconscious_rounds']} rounds. Roll {r['roll']}+Soul{char.stat_soul}={r['total']} vs TN {r['target']} — margin {r['margin']} > Soul.")
        handled = True

    elif cmd_lower.startswith("/resist"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append("[bold yellow]System:[/bold yellow] Usage: /resist <poison|sleep|paralysis> [blight_level|obstacle]")
        else:
            rtype = parts[1].lower()
            if rtype == "poison":
                try:
                    blight = int(parts[2]) if len(parts) > 2 else 1
                except ValueError:
                    nh.append("[bold yellow]System:[/bold yellow] Blight level must be an integer.")
                else:
                    r = check_poison_resistance(char, blight)
                    outcome = "PASSED (20% damage)" if r["success"] else "FAILED (full damage)"
                    nh.append(
                        f"[bold {'green' if r['success'] else 'red'}]Engine:[/bold {'green' if r['success'] else 'red'}] "
                        f"Blight {blight}: roll {r['roll']}+Body{char.stat_body}={r['total']} vs TN {r['target']} — {outcome}"
                    )
            elif rtype in ("sleep", "paralysis", "incapacitation"):
                obs = parts[2] if len(parts) > 2 else "none"
                r = check_incapacitation(char, obs)
                outcome = "RESISTED" if r["success"] else "AFFECTED"
                nh.append(
                    f"[bold {'green' if r['success'] else 'red'}]Engine:[/bold {'green' if r['success'] else 'red'}] "
                    f"{rtype}: roll {r['roll']}+Stat{max(char.stat_body, char.stat_soul)}={r['total']} vs TN {r['target']} "
                    f"[{r.get('obstacle', 'none')}] — {outcome}"
                )
            else:
                nh.append(f"[bold yellow]System:[/bold yellow] Unknown resist type: {rtype}. Use: poison, sleep, paralysis.")
        handled = True

    elif cmd_lower.startswith("/fall"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append("[bold yellow]System:[/bold yellow] Usage: /fall <meters>")
        else:
            try:
                dist = float(parts[1])
            except ValueError:
                nh.append("[bold yellow]System:[/bold yellow] Distance must be a number.")
            else:
                dmg = falling_damage(dist)
                nh.append(f"[bold red]Engine:[/bold red] Fall from {dist}m → [bold white]{dmg} HP[/bold white] damage.")
        handled = True

    elif cmd_lower.startswith("/range"):
        parts = cmd.split()
        if len(parts) < 3:
            nh.append("[bold yellow]System:[/bold yellow] Usage: /range <max_range> <distance>")
        else:
            try:
                max_r, dist = float(parts[1]), float(parts[2])
            except ValueError:
                nh.append("[bold yellow]System:[/bold yellow] Values must be numbers.")
            else:
                obs = range_obstacle(max_r, dist)
                if obs is None and dist <= max_r:
                    nh.append(f"[bold green]Engine:[/bold green] {dist}m from {max_r}m max — Effective range, no obstacle.")
                elif obs:
                    nh.append(f"[bold yellow]Engine:[/bold yellow] {dist}m from {max_r}m max — {obs.title()} Obstacle.")
                else:
                    nh.append(f"[bold red]Engine:[/bold red] {dist}m — out of range (max {max_r}m).")
        handled = True

    elif cmd_lower.startswith("/size"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append("[bold yellow]System:[/bold yellow] Usage: /size <rank> (-3 to 6)")
        else:
            try:
                rank = int(parts[1])
            except ValueError:
                nh.append("[bold yellow]System:[/bold yellow] Rank must be an integer (-3 to 6).")
            else:
                info = size_lookup(rank)
                if info:
                    nh.append(
                        f"[bold white]Size {rank} — {info['category']}[/bold white] | "
                        f"Mass: {info['mass']} | Damage: {info['strength_damage']:+d} | "
                        f"AR: {info['armour']:+d} | Ranged: {info['ranged_mod']:+d} | "
                        f"Range×: {info['range_mult']}"
                    )
                    kb = size_knockback(rank, 0)
                    if kb["auto_knockback"]:
                        nh.append(f"[bold red]  Auto Knockback: {kb['distance_meters']}m vs Medium target[/bold red]")
                else:
                    nh.append("[bold yellow]System:[/bold yellow] Unknown size rank. Range: -3 (Diminutive) to 6 (Colossal).")
        handled = True

    elif cmd_lower.startswith("/defence"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append("[bold yellow]System:[/bold yellow] Usage: /defence <damage> [armour_AR] [force_field_AR] [penetration_ranks]")
        else:
            try:
                dmg = int(parts[1])
                ar = int(parts[2]) if len(parts) > 2 else 0
                ff = int(parts[3]) if len(parts) > 3 else 0
                pen = int(parts[4]) if len(parts) > 4 else 0
            except ValueError:
                nh.append("[bold yellow]System:[/bold yellow] All values must be integers.")
            else:
                r = resolve_attack_damage(dmg, armour_rating=ar, force_field_ar=ff,
                                           penetrating_ranks=pen,
                                           current_hp=char.current_hp or char.max_hp,
                                           max_hp=char.max_hp)
                nh.append(
                    f"[bold white]Defence Pipeline[/bold white] — {dmg} incoming → "
                    f"FF {r['force_field_ar']}AR → {r['after_force_field']} | "
                    f"Armour {r['effective_armour_ar']}AR → {r['after_armour']} | "
                    f"Net: [bold red]{r['net_damage']} HP[/bold red]"
                )
                if r['hp_absorbed']:
                    nh.append(f"[bold green]  Absorbed: {r['hp_absorbed']} HP, {r['ep_absorbed']} EP[/bold green]")
        handled = True

    elif cmd_lower.startswith("/sanity"):
        parts = cmd.split()
        trauma = parts[1].lower() if len(parts) > 1 else "mild"
        sp_max = char.stat_mind + char.stat_soul
        sp_current = sp_max  # default: full SP unless tracked elsewhere
        r = check_sanity(char.stat_mind, char.stat_soul, sp_current, trauma)
        obs = sanity_obstacle(r["new_sp"])
        outcome = "PASSED" if r["passed"] else f"FAILED (-{r['sp_loss']} SP)"
        nh.append(
            f"[bold {'green' if r['passed'] else 'red'}]Engine:[/bold {'green' if r['passed'] else 'red'}] "
            f"{trauma.title()} trauma: roll {r['roll']}+{(char.stat_mind+char.stat_soul)//2}={r['total']} vs TN {r['target']} — {outcome}"
        )
        if obs:
            nh.append(f"[bold red]  Sanity Spiral: {obs.title()} Obstacle on all rolls[/bold red]")
        handled = True

    elif cmd_lower == "/recover":
        hp_day = hp_recovery(char.stat_body, 1)
        ep_hour = ep_recovery(char.stat_mind, char.stat_soul, 1)
        blocks = defect_blocks_recovery(char.defects or [])
        nh.append(
            f"[bold white]Recovery Rates:[/bold white] HP={hp_day}/day"
            + (" (×2 medical)" if not blocks["hp"] else " [red](BLOCKED: No Healing)[/red]")
            + f" | EP={ep_hour}/hour"
            + (" [red](BLOCKED: Nightmares)[/red]" if blocks["rest"] else "")
        )
        handled = True

    elif cmd_lower.startswith("/diceless"):
        parts = cmd.split()
        sub = parts[1].lower() if len(parts) > 1 else "help"
        if sub in ("usage", "help"):
            nh.append("[bold yellow]System:[/bold yellow] /diceless usage:")
            nh.append("[dim]  /diceless <defender_cv> [AR] [extra_defences] [edge] — pure-algebraic clash vs a challenge[/dim]")
            nh.append("[dim]  /diceless hedge <target> [body|mind|soul] — auto-7 non-combat check (BESM4 p182)[/dim]")
            nh.append("[dim]  edge for the attacker: minor | major[/dim]")
        elif sub == "hedge":
            if len(parts) < 3:
                nh.append("[bold yellow]System:[/bold yellow] Usage: /diceless hedge <target> [body|mind|soul]")
            else:
                try:
                    target = int(parts[2])
                except ValueError:
                    nh.append("[bold yellow]System:[/bold yellow] Target must be an integer.")
                else:
                    stat_key = parts[3].lower() if len(parts) > 3 else "body"
                    stat_map = {"body": char.stat_body, "mind": char.stat_mind, "soul": char.stat_soul}
                    if stat_key not in stat_map:
                        nh.append("[bold yellow]System:[/bold yellow] Unknown stat. Use body, mind, or soul.")
                    else:
                        r = hedged_check(stat_map[stat_key], target)
                        veredict = "PASSED" if r["success"] else "FAILED"
                        nh.append(
                            f"[bold {'green' if r['success'] else 'red'}]Engine:[/bold {'green' if r['success'] else 'red'}] "
                            f"Auto-7 ({r['rolled']}) + {stat_key.upper()}{r['total']-r['rolled']} = {r['total']} vs TN {target} — {veredict}"
                        )
        else:
            try:
                dcv = int(parts[1])
            except (IndexError, ValueError):
                nh.append("[bold yellow]System:[/bold yellow] Usage: /diceless <defender_cv> [AR] [extra_defences] [edge]")
            else:
                ar = int(parts[2]) if len(parts) > 2 else 0
                edef = int(parts[3]) if len(parts) > 3 else 0
                edge = parts[4].lower() if len(parts) > 4 else None
                if edge not in ("minor", "major"):
                    if edge is not None:
                        nh.append("[bold yellow]System:[/bold yellow] Edge must be minor or major — ignoring.")
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
                nh.append(
                    f"[bold white]Total Combat Roll[/bold white] — "
                    f"Attacker {char.name}: TCR {a['tcr']} (CV {a['combat_value']}+HP {a['hp_mod']}"
                    + (f"+Edge {a['edge_mod']}" if edge else "")
                    + f"-AR {a['armour_mod']}-Def {a['defence_mod']}) | "
                    f"Defender: TCR {d['tcr']} (CV {dcv})"
                )
                nh.append(
                    f"[bold {'green' if r['attacker_wins'] else 'red'}]Resolve:[/bold {'green' if r['attacker_wins'] else 'red'}] "
                    f"MoS {r['mos']} → {band_title} ({r['duration']}). {victor} wins — "
                    f"victor −{r['victor_hp_loss_pct']}% HP, opponent −{r['opponent_hp_loss_pct']}% HP."
                )
        handled = True

    elif cmd_lower.startswith("/maneuver"):
        parts = cmd.split()
        if len(parts) < 2:
            nh.append("[bold yellow]System:[/bold yellow] Usage: /maneuver <sub> (run '/maneuver list' for the menu).")
        else:
            techs = char.combat_techniques or []
            sub = parts[1].lower()
            if sub in ("usage", "help", "list"):
                nh.append("[bold yellow]System:[/bold yellow] Maneuver menu:")
                nh.append("[dim]  stance <aim|wait|total_defence> [consecutive_rounds] [ranged] — tactical action[/dim]")
                nh.append("[dim]  two-weapon <1|2> — 1 target minor obstacle, 2 targets major[/dim]")
                nh.append("[dim]  strike <dmg> [area] [autofire] [spreading] — flat wound damage[/dim]")
                nh.append("[dim]  touch [protected] — passive Minor Edge[/dim]")
                nh.append("[dim]  called <shot> — disarm_melee|disarm_ranged|reduce_armour|bypass_armour|vital_spot|weak_point_*[/dim]")
                nh.append("[dim]  grapple <defender_free_hands> [attacker_free_hands] [size_delta] — grab initiation[/dim]")
                nh.append("[dim]  grabbed <grappler_body> [much_stronger] [much_weaker] — the Grabbed condition[/dim]")
                nh.append("[dim]  escape <grappler_body> [damage_dealt] — break a grapple[/dim]")
                nh.append("[dim]  pin — the Pinned condition[/dim]")
                nh.append("[dim]  multi <num_targets> — dispersion across N defenders[/dim]")
            elif sub in ("stance", "aim", "wait", "total_defence"):
                stance = (parts[2] if sub == "stance" and len(parts) > 2 else sub).lower()
                try:
                    cr = int(parts[3]) if sub == "stance" and len(parts) > 3 else 1
                except ValueError:
                    nh.append("[bold yellow]System:[/bold yellow] consecutive_rounds must be an integer.")
                    stance = "invalid"
                ranged = len(parts) > 4 and parts[4].lower() in ("ranged", "true", "1") if sub == "stance" else False
                if stance not in ("aim", "wait", "total_defence"):
                    if stance != "invalid":
                        nh.append("[bold yellow]System:[/bold yellow] stance must be aim, wait, or total_defence.")
                else:
                    r = resolve_tactical_stance(stance, has_ranged=ranged, consecutive_rounds=cr)
                    if not r["valid"]:
                        nh.append(f"[bold red]Maneuver Denied:[/bold red] {r['reason']}")
                    elif stance == "total_defence":
                        nh.append(
                            f"[bold cyan]Maneuver:[/bold cyan] Total Defence — {_edge_label(r['defence_edge'])} to defence; attacks off this round."
                        )
                    else:
                        nh.append(
                            f"[bold cyan]Maneuver:[/bold cyan] {stance.title()} (round {cr}) — {_edge_label(r['attack_edge'])} to next attack."
                        )
            elif sub == "two-weapon":
                same = not (len(parts) > 2 and parts[2] in ("2", "two"))
                r = two_weapon_attack(same_target=same, techniques=techs)
                target_txt = "one target" if same else "two targets"
                if r["negated"]:
                    nh.append(f"[bold cyan]Maneuver:[/bold cyan] Two-Weapon attack ({target_txt}) — penalty negated by 'Two Weapons' technique.")
                else:
                    nh.append(f"[bold cyan]Maneuver:[/bold cyan] Two-Weapon attack ({target_txt}) — {_obstacle_label(r['obstacle'])}.")
            elif sub == "strike":
                try:
                    base_dmg = int(parts[2])
                except (IndexError, ValueError):
                    nh.append("[bold yellow]System:[/bold yellow] Usage: /maneuver strike <damage> [area] [autofire] [spreading]")
                else:
                    flags = [p.lower() for p in parts[3:]]
                    r = strike_to_wound(base_dmg, has_area="area" in flags,
                                        has_autofire="autofire" in flags,
                                        has_spreading="spreading" in flags)
                    if r["valid"]:
                        nh.append(f"[bold cyan]Maneuver:[/bold cyan] Strike to Wound — flat [bold white]{r['damage']} HP[/bold white] damage (un-multiplied).")
                    else:
                        nh.append(f"[bold red]Maneuver Denied:[/bold red] {r['reason']}")
            elif sub == "touch":
                protected = len(parts) > 2 and parts[2].lower() in ("protected", "called", "spot")
                r = touch_attack(called_spot=protected)
                if r["requires_called_shot"]:
                    nh.append(f"[bold cyan]Maneuver:[/bold cyan] Touching a protected spot — {_edge_label(r['edge'])} but the called-shot obstacle still applies.")
                else:
                    nh.append(f"[bold cyan]Maneuver:[/bold cyan] Touch attack — passive {_edge_label(r['edge'])}.")
            elif sub == "called":
                shot = " ".join(parts[2:]).lower()
                if not shot:
                    nh.append("[bold yellow]System:[/bold yellow] Usage: /maneuver called <shot>")
                else:
                    r = resolve_called_shot(shot, techs)
                    if not r["valid"]:
                        nh.append(f"[bold red]Maneuver Denied:[/bold red] {r['reason']}")
                    else:
                        ar_txt = {"ignore": "ignores armour", "half": "halves armour", "": "normal armour"}.get(r["ar_effect"], "normal armour")
                        nh.append(
                            f"[bold cyan]Called Shot:[/bold cyan] {shot.title()} — {_obstacle_label(r['obstacle'])}, "
                            f"{ar_txt}, damage ×{r['multiplier']}"
                            + (f", Body TN {r['body_tn']}" if r.get("body_tn") else "")
                            + (f", defender {_edge_label(r['defender_edge'])}" if r.get("defender_edge") else "")
                        )
            elif sub in ("grapple", "grab"):
                try:
                    dfh = int(parts[2])
                except (IndexError, ValueError):
                    nh.append("[bold yellow]System:[/bold yellow] Usage: /maneuver grapple <defender_free_hands> [attacker_free_hands] [size_delta]")
                else:
                    afh = int(parts[3]) if len(parts) > 3 else 2
                    sdelta = int(parts[4]) if len(parts) > 4 else 0
                    r = grapple_attack_edges(afh, dfh, sdelta)
                    target_txt = "much weaker (penalties escalate)" if r["much_weaker"] else "even footing"
                    nh.append(
                        f"[bold cyan]Maneuver:[/bold cyan] Grapple initiation — {_edge_label(r['edge'])} (hands {r['free_hand_delta']:+d}), {target_txt}."
                    )
            elif sub == "grabbed":
                try:
                    gbody = int(parts[2])
                except (IndexError, ValueError):
                    nh.append("[bold yellow]System:[/bold yellow] Usage: /maneuver grabbed <grappler_body> [much_stronger] [much_weaker]")
                else:
                    strong = len(parts) > 3 and parts[3].lower() in ("much_stronger", "strong", "true")
                    weak = len(parts) > 4 and parts[4].lower() in ("much_weaker", "weak", "true")
                    r = grabbed_condition(gbody, char.stat_body, target_much_stronger=strong, target_much_weaker=weak)
                    if r["paralyzed"]:
                        nh.append(f"[bold red]Grabbed:[/bold red] {char.name} is much weaker — completely paralyzed, no rolls permitted.")
                    else:
                        nh.append(
                            f"[bold cyan]Grabbed:[/bold cyan] {char.name} grappled by Body {gbody} vs Body {char.stat_body} — "
                            f"{_obstacle_label(r['melee_obstacle'])} on melee, {_obstacle_label(r['task_obstacle'])} on movement."
                        )
            elif sub in ("escape", "grapple-escape"):
                try:
                    gbody = int(parts[2])
                except (IndexError, ValueError):
                    nh.append("[bold yellow]System:[/bold yellow] Usage: /maneuver escape <grappler_body> [damage_dealt]")
                else:
                    dmg = int(parts[3]) if len(parts) > 3 else 0
                    r = escape_grapple(char.stat_body, gbody, dmg)
                    if r["auto_escape"]:
                        nh.append(f"[bold cyan]Escape:[/bold cyan] Pain Dissociation — {dmg} ≥ {r['threshold']} (5×Body {gbody}) — automatic escape.")
                    else:
                        nh.append(f"[bold cyan]Escape:[/bold cyan] Opposed Body roll vs {gbody}; or deal {r['threshold']} HP in one shot to auto-escape.")
            elif sub == "pin":
                r = pin_condition()
                nh.append(
                    f"[bold cyan]Pinned:[/bold cyan] no attack, no defence — {_obstacle_label(r['escape_obstacle'])} on escape rolls."
                )
            elif sub in ("multi", "dispersion", "multi-target"):
                try:
                    n = int(parts[2])
                except (IndexError, ValueError):
                    nh.append("[bold yellow]System:[/bold yellow] Usage: /maneuver multi <num_targets>")
                else:
                    r = multi_target_dispersion(n, techs)
                    nh.append(
                        f"[bold cyan]Maneuver:[/bold cyan] {n} targets, one attack roll — {_obstacle_label(r['obstacle'])}"
                        + (f", defenders get {_edge_label(r['defender_edge'])}" if r["defender_edge"] else "")
                        + (" (unified roll)" if r.get("unified_roll") else "")
                    )
            else:
                nh.append(f"[bold yellow]System:[/bold yellow] Unknown maneuver '{sub}'. Run '/maneuver list' for the menu.")
        handled = True

    elif cmd_lower == "/attack":
        if active_node.required_check:
            check_info = active_node.required_check
            stat_name = check_info.get("stat", "stat_body")
            skill_rank = check_info.get("skill", 0)
            difficulty = check_info.get("dv", 12)
            fail_damage = check_info.get("fail_damage", 0)
            stat_rank = getattr(char, stat_name, 6)
            nh.append(f"[bold red]Combat Action:[/bold red] Attacking the obstacle using {stat_name.replace('stat_', '').upper()}...")
            res = execute_action_check(stat_rank, skill_rank=skill_rank, difficulty_value=difficulty)
            roll, total, success = res["roll"], res["total"], res["success"]
            if success:
                nh.append(f"[bold green]TELEMETRY SUCCESS:[/bold green] Breached {active_node.title} obstacle! (Roll: {roll} + Rank: {stat_rank} = {total} vs DV: {difficulty})")
                active_node.required_check = None
                STORY_MAP[active_node.node_id]["required_check"] = None
                save_runtime_snapshot(WEB_SESSION_ID, char, active_node.node_id, setting_id, active_module_name, st.session_state.active_org)
            else:
                nh.append(f"[bold red]TELEMETRY FAILURE:[/bold red] Attack failed. (Roll: {roll} + Rank: {stat_rank} = {total} vs DV: {difficulty})")
                current_hp = char.current_hp if char.current_hp is not None else char.max_hp
                new_hp = max(0, current_hp - fail_damage)
                char.current_hp = new_hp
                try:
                    with get_db_connection() as conn:
                        conn.execute("UPDATE character_vitals SET current_hp = ? WHERE session_id = ? AND name = ?", (new_hp, WEB_SESSION_ID, char.name))
                except Exception:
                    pass
                nh.append(f"[bold red]Damage Applied:[/bold red] Took {fail_damage} damage. Current HP: {new_hp}/{char.max_hp}")
                st.session_state.char = char
        else:
            nh.append("[bold yellow]System:[/bold yellow] There is no active obstacle to attack in this area.")
        handled = True

    elif cmd_lower == "/loot":
        nh.append("[bold blue]Player:[/bold blue] Searching coordinates for equipment artifacts...")
        vitals = {
            "name": char.name,
            "stat_body": char.stat_body,
            "stat_mind": char.stat_mind,
            "stat_soul": char.stat_soul,
            "combat_techniques": char.combat_techniques,
            "skills": char.skills,
            "defects": char.defects,
            "shock_value": char.shock_value,
            "max_hp": char.max_hp,
            "max_ep": char.max_ep,
            "active_node": {"title": active_node.title, "node_id": active_node.node_id},
            "description": active_node.description or "",
        }
        try:
            from engine.llm_bridge import LLMBridge
            bridge = LLMBridge()
            compiled_prompt = bridge.compile_system_frame("besm_loot", vitals, {"title": active_node.title, "node_id": active_node.node_id})
            with st.spinner("AI Director is composing..."):
                response_dict = bridge.dispatch_ollama_turn(
                    model_name=ACTIVE_MODEL,
                    complete_context=compiled_prompt,
                    user_input="Player performs search action inside local stasis grid.",
                )
            if response_dict.get("success"):
                prose, item_data = bridge.inspect_llm_output(response_dict["response"])
                if item_data and "item_name" in item_data:
                    item_id = add_loot_to_inventory(WEB_SESSION_ID, item_data)
                    nh.append(f"[bold yellow]AI Director:[/bold yellow] {prose}")
                    nh.append(f"[bold green]Item Acquired:[/bold green] [bold white]{item_data['item_name']}[/bold white] (ID: {item_id}) Added to Inventory Ledger.")
                else:
                    fallback_item = {
                        "item_name": "Chronos Nanite Capacitor",
                        "item_type": "Accessory",
                        "attribute_granted": "stat_soul",
                        "raw_modifiers": "+1",
                    }
                    item_id = add_loot_to_inventory(WEB_SESSION_ID, fallback_item)
                    nh.append("[bold yellow]AI Director (Parser Fallback):[/bold yellow] You found a Chronos Nanite Capacitor (+1 SOUL)!")
            else:
                fallback_item = {
                    "item_name": "Rust Vibroblade",
                    "item_type": "Weapon",
                    "attribute_granted": "stat_body",
                    "raw_modifiers": "+1",
                }
                item_id = add_loot_to_inventory(WEB_SESSION_ID, fallback_item)
                nh.append("[bold yellow]AI Director (Offline Fallback):[/bold yellow] You discover a discarded Rust Vibroblade (+1 BODY)!")
        except Exception:
            nh.append("[bold red]System Error:[/bold red] Loot extraction failed.")
        handled = True

    # ── Director fallback: free text + examine → LLM (unchanged) ──────────
    elif cmd_lower == "examine" or not cmd_lower.startswith("/"):
        # Build vitals for LLM bridge
        vitals = {
            "name": char.name,
            "stat_body": char.stat_body,
            "stat_mind": char.stat_mind,
            "stat_soul": char.stat_soul,
            "combat_techniques": char.combat_techniques,
            "skills": char.skills,
            "defects": char.defects,
            "shock_value": char.shock_value,
            "max_hp": char.max_hp,
            "max_ep": char.max_ep,
            "active_node": {"title": active_node.title, "node_id": active_node.node_id},
            "description": active_node.description or "",
        }

        # Compile system frame (prompts/bound formatters)
        from engine.llm_bridge import LLMBridge
        bridge = LLMBridge()
        compiled_prompt = bridge.compile_system_frame(DEFAULT_RULES, vitals, {"title": active_node.title, "node_id": active_node.node_id})

        # Dispatch Ollama turn
        with st.spinner("AI Director is composing..."):
            response_dict = bridge.dispatch_ollama_turn(
                model_name=ACTIVE_MODEL,
                complete_context=compiled_prompt,
                user_input=player_input,
            )

        if response_dict.get("success"):
            prose, mechanical_data = bridge.inspect_llm_output(response_dict["response"])
            st.markdown(prose)

            # Apply mechanical payload if present
            if mechanical_data:
                if "hp_loss" in mechanical_data:
                    delta = mechanical_data["hp_loss"]
                    char.current_hp = max(0, char.current_hp - delta)
                    st.session_state.char = char
                if "item_gain" in mechanical_data:
                    item = mechanical_data["item_gain"]
                    add_loot_to_inventory(WEB_SESSION_ID, item)
                    st.success(f"Item acquired: {item.get('item_name', 'unknown')}")
                if "wallet_change" in mechanical_data:
                    delta = mechanical_data["wallet_change"]
                    st.session_state.wallet_balance = getattr(st.session_state, "wallet_balance", 0) + delta

            # Update narrative history
            nh.append(f"[bold blue]Player:[/bold blue] {player_input}")
            nh.append(f"[bold yellow]AI Director:[/bold yellow] {prose}")

            # Re-construct char in session state after mutation
            st.session_state.char = char
        else:
            st.error(f"LLM call failed: {response_dict.get('error', 'unknown error')}")
            nh.append(f"[bold red]System Error:[/bold red] LLM call failed: {response_dict.get('error', 'unknown')}")

    else:
        # Unknown /command — never sent to the LLM
        nh.append(f"[bold red]System:[/bold red] Unknown action '{player_input}'. Try /engine for the command list.")
        handled = True

    # CP-6: feed output persisted in session_state; refresh the frame to show it
    if handled:
        st.rerun()

else:
    st.info("Enter a command above or click **Examine Surroundings** to begin.")

# ── footer / session state summary ───────────────────────────────────────
with st.sidebar:
    st.divider()
    st.header("Session State")
    st.write(f"Setting: {st.session_state.setting_id}")
    st.write(f"Module: {active_module_name}")
    st.write(f"Active Node: {st.session_state.active_node_id}")
    st.write(f"Home Org: {st.session_state.active_org}")
    st.write(f"Character: {st.session_state.char.name}")
    st.write(f"HP: {st.session_state.char.current_hp}/{st.session_state.char.max_hp}")
    st.write(f"Narrative turns: {len([h for h in st.session_state.narrative_history if h.startswith('[bold')])}")