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