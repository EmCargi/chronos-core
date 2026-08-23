"""Hub-anchored greeting starts: classification + node construction.

Verifies that domestic (guild-hall) greetings anchor a session to the active
org's guildhall node, while field greetings open on a generic quest node.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

import engine.guild_roster as gr
from chronos import CharacterSchema, build_greeting_start

CHAR = CharacterSchema(name="Eira", stat_body=7, stat_mind=9, stat_soul=8)


def test_classify_greeting_domestic_guild_hall():
    g = {"scene": "The guild hall was bustling with life at midday.", "text": "Near the massive hearth", "opening": "Excuse me"}
    assert gr.classify_greeting(g) == "domestic"


def test_classify_greeting_domestic_library():
    g = {"scene": "It was a quiet afternoon in the guild's library.", "text": "Sunlight filtered through the shelves", "opening": "We should stop"}
    assert gr.classify_greeting(g) == "domestic"


def test_classify_greeting_field_forest():
    g = {"scene": "The deep forest was unnaturally quiet.", "text": "For five long days you tracked the beast", "opening": "It would attack"}
    assert gr.classify_greeting(g) == "field"


def test_classify_greeting_field_quest():
    g = {"scene": "The quest had been a success after five hard days.", "text": "You returned weary", "opening": "You weren't supposed to come"}
    assert gr.classify_greeting(g) == "field"


def test_classify_greeting_neutral_unknown():
    g = {"scene": "A letter arrives by courier at dawn.", "text": "The seal is unfamiliar", "opening": "..."}
    assert gr.classify_greeting(g) == "neutral"


def test_format_greeting_list_tags_hub_and_quest():
    greetings = [
        {"scene": "The guild hall was alive with morning energy.", "text": "A few adventurers stood at the reception", "opening": "Good morning"},
        {"scene": "The deep forest was unnaturally quiet.", "text": "You tracked the beast for days", "opening": "It would attack"},
    ]
    out = gr.format_greeting_list(greetings)
    assert "[Hub]" in out
    assert "[Quest]" in out


def test_build_greeting_start_domestic_anchors_to_hub():
    g = {"scene": "The guild hall was bustling.", "text": "Near the hearth", "opening": "Excuse me"}
    kind, node, text = build_greeting_start(CHAR, g, "Aelthar Keldor", 0)
    assert kind == "domestic"
    assert node.node_id == "hub_guildhall"
    assert "Aelthar Keldor Guildhall" == node.title
    assert "Excuse me" in text


def test_build_greeting_start_field_keeps_quest_node():
    g = {"scene": "The deep forest was unnaturally quiet.", "text": "You tracked the beast", "opening": "It would attack"}
    kind, node, text = build_greeting_start(CHAR, g, "Aelthar Keldor", 1)
    assert kind == "field"
    assert node.node_id == "greeting_2"
    assert "Greeting 2" in node.title


def test_build_greeting_start_no_org_falls_back_to_guildhall():
    g = {"scene": "The guild tavern was warm.", "text": "A tankard awaits", "opening": "Ah"}
    kind, node, text = build_greeting_start(CHAR, g, "", 0)
    assert kind == "domestic"
    assert node.title == "Guildhall"
