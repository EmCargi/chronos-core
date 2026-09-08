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
    # Isolate the web session DB — never touch live data/ (existing suite convention)
    sm.set_active_db_path(str(tmp_path / "chronos_web_session.db"))
    at = AppTest.from_file(BROWSER_FILE, default_timeout=30)
    at.run()
    return at


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
    ("/shock 30", "UNCONSCIOUS"),
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
    assert needle in joined, f"{cmd} should render '{needle}'"


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