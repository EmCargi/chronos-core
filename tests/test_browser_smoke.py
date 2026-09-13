"""Headless smoke test for the Chronos Core Streamlit web port (browser_chronos.py).

Verifies the web app boots cleanly in Streamlit's headless AppTest harness:
- No script-body exceptions (import + bootstrap + widget render)
- Key sidebar widgets present (model, setting, active node, home org)
- Vitals HUD metrics populated from the roster
- Web session DB isolated to a temp path (never touches live data/)

This satisfies the R4/CP-4 ruling: the web port must import cleanly without
invoking the browser UI loop.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

BROWSER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "browser_chronos.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Boot the Streamlit app headlessly with the session DB redirected to tmp."""
    from engine import state_manager as sm
    from engine import economy as ec
    from engine import guild_roster as gr
    from engine import disc_registry as dr
    _orig_roster = ec.ACTIVE_ROSTER_PATH
    _orig_db = sm.ACTIVE_DB_PATH
    _orig_sid = sm.ACTIVE_SESSION_ID
    # Isolate the web session DB — never touch live data/ (existing suite convention)
    sm.set_active_db_path(str(tmp_path / "chronos_web_session.db"))
    # CP-11 Option A: redirect the SHARED economy/roster DB to a throwaway too,
    # so write commands (/grant /buy /use /provision) never pollute the live roster.
    ec.set_active_roster_path(str(tmp_path / "chronos_economy.db"))
    # Neutralize the disc registry for tests (CP-3): the web boot calls
    # set_active_setting() at the head of the script loop, which would resolve
    # guild_rpg → the REAL shared DB and override the throwaway redirect above.
    # Point the shared fallback at the tmp DB, init a full roster schema there,
    # and disable disc discovery so every setting resolves to the isolated file.
    gr.set_active_roster_path(str(tmp_path / "chronos_economy.db"))
    monkeypatch.setattr(gr, "ROSTER_PATH", str(tmp_path / "chronos_economy.db"))
    monkeypatch.setattr(dr, "_resolve_disc_dir", lambda: None)
    gr.init_roster_db()          # creates settings/characters schema + seeds 13 settings
    # The live shared DB carries two runtime-registered settings beyond the
    # config DEFAULT_SETTINGS list — mirror them so the Setting radio matches.
    gr.register_setting("guild_training_yard", "Guild Training Yard", "Zarlen evaluation",
                        default_module="guild_training_yard_v1.json", character_label="Trainee")
    gr.register_setting("tomoe_volcano_package", "Tomoe Character Package", "Eldrakor Volcano",
                        default_module="tomoe_volcano_package_v1.json", character_label="Crimson Ronin")
    # Seed a minimal cast + home org so /char and /org switching tests resolve
    # (previously they read the live shared DB; the fixture now isolates).
    gr.upsert_character("guild_rpg", {
        "name": "Eira", "rank_label": "S-Rank", "race": "High Elf",
        "points_budget": 120, "stat_body": 7, "stat_mind": 9, "stat_soul": 8,
    }, "{}", "test.json")
    gr.upsert_character("guild_rpg", {
        "name": "Alex Mercer", "rank_label": "Unranked", "race": "Human",
        "points_budget": 75, "stat_body": 6, "stat_mind": 8, "stat_soul": 6,
    }, "{}", "test.json")
    gr.init_organizations_table()
    gr.upsert_organization("guild_rpg", {
        "name": "Aelthar Keldor", "organization_type": "guild", "scale_tier": "Regional",
        "leader": "Sylvara", "base_of_operations": "The Capital City",
    })
    ec.init_economy_db()
    at = AppTest.from_file(BROWSER_FILE, default_timeout=30)
    at.run()
    yield at
    # Restore EVERYTHING the app's boot mutates (session DB path + session id +
    # economy/roster path) so state never leaks into sibling test files.
    ec.set_active_roster_path(_orig_roster)
    sm.set_active_db_path(_orig_db)
    sm.set_active_session_id(_orig_sid)


def test_boots_without_exceptions(app):
    """The script body must execute cleanly — no Streamlit traceback."""
    assert not app.exception, [e.value for e in app.exception]


def test_title_renders(app):
    """Page title present."""
    assert app.title and app.title[0].value == "⚡ Chronos Core — Web Edition"


def test_sidebar_config_widgets_present(app):
    """Sidebar exposes the disc/roster selectors."""
    labels = {getattr(w, "label", "") for w in app.sidebar}
    assert "Model" in labels
    assert "Thin Model" in labels
    assert "Setting" in labels
    assert "Active Node" in labels


def test_vitals_metrics_populated(app):
    """Vitals HUD shows HP/EP/Shock/ACV/DCV metrics with real roster values."""
    metrics = {m.label: m.value for m in app.metric}
    assert "HP" in metrics
    assert "EP" in metrics
    assert "Shock Value" in metrics
    assert "ACV" in metrics
    assert "DCV" in metrics
    # HP/EP must be numeric pairs (current/max) — never blank
    assert "/" in metrics["HP"]
    assert "/" in metrics["EP"]


def test_chat_input_present(app):
    """The command handler is wired — st.chat_input exists."""
    assert len(app.chat_input) == 1


def test_active_node_selectable(app):
    """The Active Node selectbox renders with the module's node IDs."""
    sel = next((w for w in app.sidebar if getattr(w, "label", "") == "Active Node"), None)
    assert sel is not None
    assert len(sel.options) > 0


# ── Phase A: read-only display commands (zero LLM, zero writes) ─────────────

def _send_command(app, text):
    """Submit a chat command and re-run (display commands append + st.rerun)."""
    app.chat_input[0].set_value(text)
    app.run()


def _all_markdown(app):
    return [m.value for m in app.markdown]


def test_display_command_engine(app):
    """/engine lists the command palette without an LLM call."""
    _send_command(app, "/engine")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "BESM Engine Commands" in joined
    assert "/diceless <defender_cv>" in joined
    assert "/maneuver <subcommand>" in joined


def test_display_command_roster(app):
    """/roster renders the setting roster table."""
    _send_command(app, "/roster")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "roster" in joined
    assert "Guild Rank" in joined or "[A-Rank" in joined


def test_display_command_settings(app):
    """/settings lists registered settings with the active marker."""
    _send_command(app, "/settings")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Registered settings" in joined
    assert "guild_rpg" in joined


def test_display_command_wallet(app):
    """/wallet shows the active character's balance."""
    _send_command(app, "/wallet")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "wallet:" in joined
    assert "sp" in joined


def test_display_command_scv(app):
    """/scv computes the social combat value locally."""
    _send_command(app, "/scv")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Social Profile" in joined
    assert "SCV=" in joined


def test_display_command_inventory(app):
    """/inventory renders the character's owned items."""
    _send_command(app, "/inventory")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "inventory:" in joined


def test_display_command_greetings(app):
    """/greetings lists session starters — either tagged [Hub]/[Quest] rows or a
    graceful no-greetings fallback for unlinked (boss/threat) characters."""
    _send_command(app, "/greetings")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    # default boot char is a boss with no linked greetings → fallback path
    assert "session starters" in joined or "No greetings available" in joined


def test_display_command_unknown(app):
    """Unknown /commands get a usage warning, never an LLM call."""
    _send_command(app, "/not_a_real_command")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Unknown action" in joined


def test_rich_stripper_preserves_semantic_tags():
    """CP-9: the stripper removes Rich tags but keeps [Hub]/[Quest]/[D-Rank]."""
    from browser_chronos import _rich_to_markdown
    out = _rich_to_markdown("[dim][Hub][/dim] greeting [bold red]alert[/bold red] [D-Rank]")
    assert "[Hub]" in out
    assert "[D-Rank]" in out
    assert "[bold" not in out
    assert "[dim]" not in out


def test_greeting_list_tags_survive_stripper():
    """CP-9 end-to-end: format_greeting_list emits [dim][Hub][/dim]; the web
    stripper must leave the semantic [Hub]/[Quest] marker intact."""
    from browser_chronos import _rich_to_markdown
    from engine.guild_roster import init_roster_db, get_character_greetings, format_greeting_list
    init_roster_db()
    greetings = get_character_greetings("guild_rpg", "Eira")
    if not greetings:
        import pytest
        pytest.skip("Eira greeting markdown missing from vault")
    rendered = format_greeting_list(greetings)
    assert "[Hub]" in rendered or "[Quest]" in rendered
    cleaned = _rich_to_markdown(rendered)
    assert "[Hub]" in cleaned or "[Quest]" in cleaned
    assert "[dim]" not in cleaned


# ── Phase B: deterministic BESM math (zero LLM, zero writes) ────────────────

_PHASE_B_CASES = [
    ("/diceless 17", "Total Combat Roll"),
    ("/diceless hedge 10 mind", "Auto-7"),
    ("/shock 30", None),  # outcome depends on 2d6 roll vs Soul — asserted specially below
    ("/fall 5", "damage"),
    ("/range 20 5", "Minor Obstacle"),
    ("/size 3", "Size 3"),
    ("/defence 25 10 5 1", "Defence Pipeline"),
    ("/sanity severe", "trauma"),
    ("/recover", "Recovery Rates"),
    ("/maneuver stance aim 2 ranged", "Aim (round 2)"),
    ("/maneuver strike 12", "Strike to Wound"),
    ("/maneuver two-weapon 2", "Two-Weapon attack (two targets)"),
    ("/maneuver multi 3", "3 targets, one attack roll"),
    ("/maneuver called disarm_melee", "Called Shot:"),
    ("/resist poison 3", "Blight 3"),
    ("/attack", "no active obstacle"),
]


_SHOCK_OUTCOMES = ("SHOCKED", "UNCONSCIOUS", "below SV", "shock check PASSED")


@pytest.mark.parametrize("cmd,needle", _PHASE_B_CASES)
def test_phase_b_math_commands(app, cmd, needle):
    """/<math> computes deterministic BESM math locally — no exception, no LLM."""
    _send_command(app, cmd)
    if cmd == "/attack":
        # Default module (zarlen_training_grounds) boots onto node_01_guardian
        # which HAS a required_check. Navigate to an obstacle-free node first so
        # the /attack no-obstacle branch is what renders.
        app.session_state["active_node_id"] = "node_05_reward"
        app.run()
        _send_command(app, cmd)
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    if needle is None:
        # /shock outcome depends on a random 2d6 roll vs Soul + the char's SV —
        # accept any valid branch (incl. a passed shock check, not just a fail).
        assert any(k in joined for k in _SHOCK_OUTCOMES), f"{cmd} should render a shock outcome"
    else:
        assert needle in joined, f"{cmd} should render '{needle}'"


def test_shock_roll_any_outcome(app):
    """/shock renders a valid BESM outcome regardless of the random roll."""
    _send_command(app, "/shock 30")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert any(k in joined for k in _SHOCK_OUTCOMES)


def test_phase_b_bad_args_get_usage(app):
    """CP-5: bad args on a math command → usage warning, never a traceback."""
    _send_command(app, "/diceless not_a_number")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Usage: /diceless" in joined


def test_phase_b_maneuver_usage(app):
    """/maneuver list renders the maneuver menu."""
    _send_command(app, "/maneuver list")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Maneuver menu" in joined
    assert "called <shot>" in joined


# ── Phase D: greeting starts (node commit first — CP-4) ─────────────────────

def test_startgreeting_no_greetings_fallback(app):
    """/startgreeting on an unlinked character (boss) → graceful no-greetings
    message, never a traceback, node unchanged."""
    _send_command(app, "/startgreeting 1")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "No greetings available" in joined or "Usage: /startgreeting" in joined


def test_startgreeting_bad_index(app):
    """/startgreeting <out-of-range> → usage warning (CP-5), node unchanged."""
    _send_command(app, "/startgreeting 999")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "not found" in joined or "No greetings available" in joined


def test_startgreeting_non_numeric(app):
    """/startgreeting <non-numeric> → usage warning (CP-5), no traceback."""
    _send_command(app, "/startgreeting abc")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Usage: /startgreeting" in joined


# ── Phase C: economy writes — shared canonical roster DB (CP-11 Option A) ───

def test_grant_updates_wallet(app):
    """/grant writes to the shared economy DB; /wallet reflects it (CP-1 rerun)."""
    _send_command(app, "/grant 50")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Granted 50 sp" in joined
    assert "New balance: 50 sp" in joined
    _send_command(app, "/wallet")
    joined = "\n".join(_all_markdown(app))
    assert "wallet: 50 sp" in joined


def test_buy_unknown_item_graceful(app):
    """/buy <unknown> → purchase-failed feed message, never a traceback (CP-6H)."""
    _send_command(app, "/buy not_a_real_item")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Purchase Failed" in joined


def test_buy_bad_qty_usage(app):
    """/buy <item> abc → usage warning, no traceback (CP-5)."""
    _send_command(app, "/buy potion abc")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Quantity must be a positive integer" in joined


def test_buy_use_inventory_loop(app):
    """/grant → /buy → /use → /inventory: full economy loop on the shared DB."""
    _send_command(app, "/grant 100")
    _send_command(app, "/buy basic_healing_salve 2")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Bought 2x Basic Healing Salve" in joined
    _send_command(app, "/use basic_healing_salve")
    joined = "\n".join(_all_markdown(app))
    assert "Item Used" in joined
    _send_command(app, "/inventory")
    joined = "\n".join(_all_markdown(app))
    assert "Basic Healing Salve" in joined


def test_provision_preview_no_write(app):
    """/provision info (dry run) previews matches without committing."""
    _send_command(app, "/provision info archaic")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Preview: would seed" in joined
    assert "Re-run without 'info' to commit" in joined


def test_provision_usage(app):
    """/provision usage shows the filter help."""
    _send_command(app, "/provision usage")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "/provision usage" in joined
    assert "cap=800" in joined


# ── State-switching commands (/setting /module /char /org /orgs) ─────────────

def test_setting_switches_and_radio_does_not_crash(app):
    """/setting to a NON-radio disc (CP-12) must not crash the Setting radio."""
    _send_command(app, "/setting guild_training_yard")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Switched to setting 'guild_training_yard'" in joined
    # radio options derive from list_settings() — every registered disc, no ValueError
    from engine import guild_roster
    expected = [s["setting_id"] for s in guild_roster.list_settings()]
    sel = next((w for w in app.sidebar if getattr(w, "label", "") == "Setting"), None)
    assert sel is not None
    assert set(sel.options) == set(expected)  # all registered discs, incl. the 7 Multiverse + cyberpunk
    assert "guild_training_yard" in sel.options


def test_setting_unknown(app):
    """/setting <unknown> → error feed message, no traceback (CP-5)."""
    _send_command(app, "/setting not_a_setting")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Unknown setting" in joined


def test_module_loads_and_resets_node(app):
    """/module swaps the story map and resets the active node to map[0]."""
    _send_command(app, "/module zarlen_training_grounds_v1.json")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Loaded module" in joined


def test_module_empty_warns_and_aborts(app, tmp_path):
    """/module on a zero-node module → warn-and-abort, player stays anchored (CP-13)."""
    import json
    empty_module = tmp_path / "modules"
    empty_module.mkdir()
    (empty_module / "empty_test.json").write_text(json.dumps({"module_name": "empty_test", "nodes": {}}))
    from engine import guild_roster as gr
    _orig_base = gr.BASE_DIR
    gr.BASE_DIR = str(tmp_path)
    try:
        _send_command(app, "/module empty_test.json")
    finally:
        gr.BASE_DIR = _orig_base
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Module contains no nodes" in joined
    # node unchanged — no ghost state
    sel = next((w for w in app.sidebar if getattr(w, "label", "") == "Active Node"), None)
    assert sel is not None
    assert sel.value in sel.options


def test_char_switches(app):
    """/char rehydrates the active character (HUD vitals follow)."""
    _send_command(app, "/char Eira")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Active character set to Eira" in joined
    # HUD reflects Eira
    assert any("Character: Eira" in m.value for m in app.markdown)


def test_char_unknown(app):
    """/char <unknown> → error feed message, no traceback."""
    _send_command(app, "/char NotARealCharacter")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "No character" in joined


def test_org_switches(app):
    """/org sets the active guild."""
    _send_command(app, "/org Aelthar Keldor")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Active home guild set to Aelthar Keldor" in joined


def test_org_unknown(app):
    """/org <unknown> → error feed message, no traceback."""
    _send_command(app, "/org NotARealOrg")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "No organization" in joined


def test_orgs_lists(app):
    """/orgs lists organizations — must not be shadowed by /org (TUI shadow bug fixed)."""
    _send_command(app, "/orgs")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Organizations in" in joined


# ── Streaming Director turns (st.write_stream; LLM patched offline) ────────

def _patch_stream(monkeypatch, prose="", mech_tail="", chunks=None):
    """Replace dispatch_ollama_turn_stream with a canned generator + ctx fill.

    Mimics the real contract: yields clean prose chunks to the UI and fills
    ctx["full_raw_text"] with prose + the [MECHANICAL PAYLOAD] tail (CP-17).
    """
    from engine import llm_bridge as lb

    def _gen(self, model_name=None, complete_context="", user_input="", ctx=None):
        if ctx is not None:
            ctx["full_raw_text"] = prose + mech_tail
        for c in (chunks if chunks is not None else [prose]):
            yield c

    monkeypatch.setattr(lb.LLMBridge, "dispatch_ollama_turn_stream", _gen)


def _all_history(app):
    """The narrative feed's source of truth (CP-18: prose must persist pre-rerun)."""
    return app.session_state["narrative_history"]


def test_free_text_streams_director(app, monkeypatch):
    """Free text streams Director prose + applies the mechanical payload (HP drop)."""
    _patch_stream(monkeypatch, prose="The goblin staggers and falls. ",
                  mech_tail='[MECHANICAL PAYLOAD] {"hp_loss": 3}')
    hp_before = app.session_state["char"].current_hp
    _send_command(app, "I strike the goblin!")
    assert not app.exception, [e.value for e in app.exception]
    history = "\n".join(_all_history(app))
    assert "I strike the goblin!" in history
    assert "The goblin staggers and falls" in history
    assert "empty stream" not in history
    assert app.session_state["char"].current_hp == hp_before - 3


def test_free_text_empty_stream_error(app, monkeypatch):
    """An empty stream surfaces as a feed error, not a silent pass."""
    _patch_stream(monkeypatch)
    _send_command(app, "Hello?")
    assert not app.exception, [e.value for e in app.exception]
    history = "\n".join(_all_history(app))
    assert "empty stream" in history


def test_loot_streams_item(app, monkeypatch):
    """/loot streams the find + parses the mechanical item payload into inventory."""
    _patch_stream(monkeypatch, prose="You find a gleaming blade. ",
                  mech_tail='[MECHANICAL PAYLOAD] {"item_name": "Chrono Blade", "item_type": "Weapon", "raw_modifiers": "+1"}')
    _send_command(app, "/loot")
    assert not app.exception, [e.value for e in app.exception]
    history = "\n".join(_all_history(app))
    assert "Item Acquired" in history
    assert "Chrono Blade" in history


def test_loot_empty_stream_offline_fallback(app, monkeypatch):
    """/loot with an empty stream drops to the offline fallback item."""
    _patch_stream(monkeypatch)
    _send_command(app, "/loot")
    assert not app.exception, [e.value for e in app.exception]
    history = "\n".join(_all_history(app))
    assert "Offline Fallback" in history
    assert "Rust Vibroblade" in history


# ── /open generative chest loot (The Pydantic Weaver) ──────────────────────

def _inject_chest_node(app):
    """Point the loaded module at a synthetic labyrinth with a wooden chest."""
    chest_map = {
        "node_start": {"node_id": "node_start", "title": "Entrance", "description": "A gate.",
                       "node_type": "entrance", "stratum": 1, "exits": {"north": "node_chest"}},
        "node_chest": {"node_id": "node_chest", "title": "Wooden Chest", "description": "A weathered chest.",
                       "node_type": "chest", "stratum": 1, "chest": {"tier": "wooden"}, "exits": {}},
    }
    app.session_state["story_map"] = chest_map
    app.session_state["last_setting_id"] = app.session_state["setting_id"]
    app.session_state["active_node_id"] = "node_chest"
    app.run()


def test_open_without_chest_node(app):
    """/open on a chest-less node replies 'nothing to open' (no LLM, no write)."""
    _send_command(app, "/open")
    assert not app.exception, [e.value for e in app.exception]
    assert "There is nothing to open here." in "\n".join(_all_history(app))


def test_open_streams_chest_loot(app, monkeypatch):
    """/open streams the find + deposits the Pydantic-validated item."""
    _inject_chest_node(app)
    _patch_stream(monkeypatch, prose="Inside sits a single crimson vial. ",
                  mech_tail='[LOOT PAYLOAD] {"name":"Woodland Berry Tonic","item_type":"consumable",'
                            '"description":"A tart tonic.","item_cp":2,"effect_json":{"kind":"heal","hp":10}} '
                            '[/LOOT PAYLOAD]')
    _send_command(app, "/open")
    assert not app.exception, [e.value for e in app.exception]
    history = "\n".join(_all_history(app))
    assert "Chest Opened" in history
    assert "Woodland Berry Tonic" in history


def test_open_twice_idempotent(app, monkeypatch):
    """CP-1: the pre-dispatch lock blocks a second open (no double-drop)."""
    _inject_chest_node(app)
    _patch_stream(monkeypatch, prose="Inside sits a single crimson vial. ",
                  mech_tail='[LOOT PAYLOAD] {"name":"Woodland Berry Tonic","item_type":"consumable",'
                            '"description":"A tart tonic.","item_cp":2,"effect_json":{"kind":"heal","hp":10}} '
                            '[/LOOT PAYLOAD]')
    _send_command(app, "/open")
    _send_command(app, "/open")
    assert not app.exception, [e.value for e in app.exception]
    history = "\n".join(_all_history(app))
    assert history.count("Chest Opened") == 1
    assert "already been opened" in history


def test_open_empty_stream_rolls_back(app, monkeypatch):
    """A failed stream rolls back the open lock so the player can retry."""
    _inject_chest_node(app)
    _patch_stream(monkeypatch)
    _send_command(app, "/open")
    assert not app.exception, [e.value for e in app.exception]
    assert "creaks shut" in "\n".join(_all_history(app))
    _patch_stream(monkeypatch, prose="This time it works. ",
                  mech_tail='[LOOT PAYLOAD] {"name":"Retry Tonic","item_type":"consumable",'
                            '"description":"d.","item_cp":1,"effect_json":{"kind":"heal","hp":5}} '
                            '[/LOOT PAYLOAD]')
    _send_command(app, "/open")
    assert "Retry Tonic" in "\n".join(_all_history(app))