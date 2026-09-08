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
    compute_tcr, resolve_diceless_combat, hedged_check,
    resolve_tactical_stance, two_weapon_attack, strike_to_wound,
    touch_attack, resolve_called_shot, grapple_attack_edges,
    grabbed_condition, escape_grapple, pin_condition, multi_target_dispersion,
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
)
from engine.state_manager import (
    get_db_connection, init_db as init_state_db, set_active_db_path,
    WEB_SESSION_DB_PATH,
)
from core.ollama import default_chain, post_json

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

# Display narrative history
for entry in st.session_state.narrative_history:
    st.markdown(entry)

# Command input
st.divider()
st.subheader("⚡ Command")
player_input = st.chat_input("Enter command...", key="chat_input")

WEB_SESSION_ID = "web_port_session"

# "Examine surroundings" button triggers an AI Director turn without chat input
if st.button("👁️ Examine Surroundings", type="primary", use_container_width=True):
    player_input = "examine"

# Command handler — mirrors chronos.py if/elif dispatch
if player_input:
    # Log the action
    log_narrative_turn(WEB_SESSION_ID, "Player", player_input)

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
            # Example: handle damage, healing, item acquisition
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
                # Simplified wallet update
                st.session_state.wallet_balance = getattr(st.session_state, "wallet_balance", 0) + delta

        # Update narrative history
        st.session_state.narrative_history.append(f"[bold blue]Player:[/bold blue] {player_input}")
        st.session_state.narrative_history.append(f"[bold yellow]AI Director:[/bold yellow] {prose}")

        # Re-construct char in session state after mutation
        st.session_state.char = char
    else:
        st.error(f"LLM call failed: {response_dict.get('error', 'unknown error')}")
        st.session_state.narrative_history.append(f"[bold red]System Error:[/bold red] LLM call failed: {response_dict.get('error', 'unknown')}")

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