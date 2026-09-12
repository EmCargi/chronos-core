"""Headless smoke test: run Korrath through the Pilgrimage of Bloods.

Drives the TUI's core play path offline (LLM patched, big-rig independent):
boot state -> load besm_bazaroth + pilgrimage_of_bloods -> select Korrath ->
navigate shadowlands -> brand (Soul gate) -> plain (Mind hazard) -> cauldron
(lore gate) -> drakes (Body encounter) -> trees (reward chest) -> compile the
shell frame (Korrath loadout + node) -> dispatch one Director turn (patched
stream) and apply its mechanical payload.
"""
import sys

sys.path.insert(0, "/home/megane/dev")
sys.path.insert(0, ".")

from engine.guild_roster import (
    init_roster_db, load_campaign_module, get_setting,
    build_vitals_with_full_loadout,
)
from engine.economy import init_economy_db
from engine.state_manager import init_db
from engine.models import execute_action_check
from engine import llm_bridge as lb

PASS = []


def check(label, cond, detail=""):
    PASS.append(cond)
    print(f"{'✅' if cond else '❌'} {label}" + (f" — {detail}" if detail else ""))


# 1. Boot engine state
init_db()
init_roster_db()
init_economy_db()

# 2. Load Bazaroth setting + the 6-node pilgrimage module
setting = get_setting("besm_bazaroth")
check("setting resolves", setting is not None,
      f"default_module={setting and setting.get('default_module')}")
story_map, module_name = load_campaign_module("besm_bazaroth", "pilgrimage_of_bloods.json")
check("pilgrimage loads", module_name == "The Pilgrimage of Bloods (besm_bazaroth Starter)" and len(story_map) == 6,
      f"{module_name} | {len(story_map)} nodes")

# 3. Select Korrath (Infernal King's legion initiate)
from engine.guild_roster import roster_dict_to_char
import sqlite3
cols = ['setting_id','name','rank_label','race','points_budget','stat_body','stat_mind','stat_soul','acv','dcv','max_hp','max_ep','card_json','source_path','ingested_at','sixth_guard','structural_fault','levers','combat_techniques','skills','defects','shock_value','md_source_path','gender']
row = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_bazaroth' AND name='Korrath'").fetchone()
korrath = roster_dict_to_char(dict(zip(cols, row)))
check("Korrath selectable", korrath.name == "Korrath" and korrath.max_hp == 60,
      f"{korrath.name} HP{korrath.max_hp}/EP{korrath.max_ep} ACV{korrath.base_acv}/DCV{korrath.base_dcv} [{korrath.race}]")

# Also verify Nyra (captive Asrai moral thrall) + Morrow (wraith gatekeeper)
row2 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_bazaroth' AND name='Nyra'").fetchone()
nyra = roster_dict_to_char(dict(zip(cols, row2))) if row2 else None
check("Nyra (captive Asrai) selectable", nyra is not None and nyra.race == "Asrai",
      f"{nyra.name if nyra else 'missing'} — {nyra.race if nyra else ''}")
row3 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_bazaroth' AND name='Morrow the Wraith-Speaker'").fetchone()
morrow = roster_dict_to_char(dict(zip(cols, row3))) if row3 else None
check("Morrow (Wraith-Speaker) selectable", morrow is not None and morrow.race == "Wraith",
      f"{morrow.name if morrow else 'missing'} — {morrow.race if morrow else ''}")

# 4. Navigate shadowlands -> brand
node = story_map["node_01_shadowlands"]
check("shadowlands has north exit", node["exits"].get("north") == "node_02_brand")
brand = story_map["node_02_brand"]
check("brand is a gate", brand["node_type"] == "gate")
check("brand check is Soul", brand["required_check"]["stat"] == "stat_soul")

# 5. Resolve the brand gate (Soul vs DV12)
rc = brand["required_check"]
res = execute_action_check(korrath.stat_soul, rc["skill"], rc["dv"])
check("brand check resolves", "success" in res and "roll" in res,
      f"stat={rc['stat']} skill={rc['skill']} dv={rc['dv']}")

# 6. Resolve the Plain of Despair hazard (Mind vs DV13)
plain = story_map["node_03_plain"]
check("plain is an encounter", plain["node_type"] == "encounter")
rcp = plain["required_check"]
resp = execute_action_check(korrath.stat_mind, rcp["skill"], rcp["dv"])
check("plain check resolves", "success" in resp and "roll" in resp,
      f"stat={rcp['stat']} skill={rcp['skill']} dv={rcp['dv']} fail_damage={rcp['fail_damage']}")

# 7. Cauldron is lore (wayline resonance)
cauldron = story_map["node_04_cauldron"]
check("cauldron is lore node", cauldron["node_type"] == "lore")
check("cauldron leads to drakes", cauldron["exits"].get("north") == "node_05_drakes")

# 8. Compile the shell frame with Korrath's loadout + the drake node
drakes = story_map["node_05_drakes"]
vitals = build_vitals_with_full_loadout("besm_bazaroth", korrath, "The Shadowlands")
bridge = lb.LLMBridge()
frame = bridge.compile_system_frame("besm_shell", vitals, drakes)
check("shell carries Korrath name", "Korrath" in frame)
check("shell carries Brutal", "Brutal" in frame)
check("shell carries Lethal Blow", "Lethal Blow" in frame)
check("shell carries The Hunger fault", "The Hunger" in frame)
check("shell carries Brand-Severance guard", "Brand-Severance" in frame)
check("shell carries drake title", "The Hell Drake Nest" in frame)
check("shell carries vitals (HP/EP/ACV/DCV)", all(x in frame for x in ("60", "ACV", "DCV")))
check("shell carries drake description", "drake" in frame.lower() or "tree" in frame.lower())

# 9. Dispatch one Director turn (patched stream, offline) + apply mechanical payload
def _fake_stream(self, model_name=None, complete_context="", user_input="", ctx=None):
    if ctx is not None:
        ctx["full_raw_text"] = (
            "You cleave a drake from the Tree's shadow, blood-metal singing. "
            "[MECHANICAL PAYLOAD] {\"hp_loss\": 6, \"ep_loss\": 3}"
        )
    yield "You cleave a drake from the Tree's shadow, blood-metal singing. "

lb.LLMBridge.dispatch_ollama_turn_stream = _fake_stream

ctx = {}
gen = bridge.dispatch_ollama_turn_stream(ctx=ctx, complete_context=frame, user_input="I blood-cleave the drake off the Fruit!")
prose = "".join(gen)
check("director streams clean prose", "blood-cleave" in prose or "drake" in prose)
check("ctx captures mechanical payload", "[MECHANICAL PAYLOAD]" in ctx.get("full_raw_text", ""))

mech = bridge.inspect_llm_output(ctx["full_raw_text"])[1]
check("mechanical payload parsed", mech.get("hp_loss") == 6 and mech.get("ep_loss") == 3,
      f"hp_loss={mech.get('hp_loss')} ep_loss={mech.get('ep_loss')}")

# 10. Full navigation reachability: all 6 nodes reachable from shadowlands
from engine.verify_dungeon import _reachable_nodes
reachable = _reachable_nodes(story_map, "node_01_shadowlands")
check("all 6 nodes reachable", len(reachable) == 6, sorted(reachable))

# 11. Reward node has the Fruit chest (/open target)
trees = story_map["node_06_trees"]
check("trees is reward node", trees["node_type"] == "reward")
check("trees has wooden chest", trees.get("chest", {}).get("tier") == "wooden")

print()
print(f"SMOKE TEST: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)