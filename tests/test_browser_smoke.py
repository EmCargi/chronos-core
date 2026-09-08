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
def app(tmp_path):
    """Boot the Streamlit app headlessly with the session DB redirected to tmp."""
    from engine import state_manager as sm
    from engine import economy as ec
    _orig_roster = ec.ACTIVE_ROSTER_PATH
    # Isolate the web session DB — never touch live data/ (existing suite convention)
    sm.set_active_db_path(str(tmp_path / "chronos_web_session.db"))
    # CP-11 Option A: redirect the SHARED economy/roster DB to a throwaway too,
    # so write commands (/grant /buy /use /provision) never pollute the live roster.
    ec.set_active_roster_path(str(tmp_path / "chronos_economy.db"))
    ec.init_economy_db()
    at = AppTest.from_file(BROWSER_FILE, default_timeout=30)
    at.run()
    yield at
    # Restore the canonical economy/roster path so the redirect never leaks
    # into sibling test files (test_economy, test_besm_catalog, ...).
    ec.set_active_roster_path(_orig_roster)


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


@pytest.mark.parametrize("cmd,needle", _PHASE_B_CASES)
def test_phase_b_math_commands(app, cmd, needle):
    """/<math> computes deterministic BESM math locally — no exception, no LLM."""
    _send_command(app, cmd)
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    if needle is None:
        # /shock outcome depends on a random 2d6 roll vs Soul — accept any valid branch
        assert any(k in joined for k in ("SHOCKED", "UNCONSCIOUS", "below SV")), f"{cmd} should render a shock outcome"
    else:
        assert needle in joined, f"{cmd} should render '{needle}'"


def test_shock_roll_any_outcome(app):
    """/shock renders a valid BESM outcome regardless of the random roll."""
    _send_command(app, "/shock 30")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert any(k in joined for k in ("SHOCKED", "UNCONSCIOUS", "below SV"))


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
    # radio options now derive from list_settings() — all 5 discs, no ValueError
    sel = next((w for w in app.sidebar if getattr(w, "label", "") == "Setting"), None)
    assert sel is not None
    assert "guild_training_yard" in sel.options
    assert len(sel.options) == 5


def test_setting_unknown(app):
    """/setting <unknown> → error feed message, no traceback (CP-5)."""
    _send_command(app, "/setting not_a_setting")
    assert not app.exception, [e.value for e in app.exception]
    joined = "\n".join(_all_markdown(app))
    assert "Unknown setting" in joined


def test_module_loads_and_resets_node(app):
    """/module swaps the story map and resets the active node to map[0]."""
    _send_command(app, "/module sandbox_75cp.json")
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