"""Headless smoke test: run Aerin Voss through the Shards Tourney labyrinth.

Drives the TUI's core play path offline (LLM patched, big-rig independent):
boot state -> load besm_ikaris + shards_tourney -> select Aerin Voss ->
navigate court -> vow (Soul gate) -> monster bait (Body hazard) ->
harpers college (lore) -> grand duel (Mind encounter) -> prize (reward chest)
-> compile the shell frame (Aerin loadout + node) -> dispatch one Director
turn (patched stream) and apply its mechanical payload.
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

# 2. Load Ikaris setting + the 6-node tourney module
setting = get_setting("besm_ikaris")
check("setting resolves", setting is not None,
      f"default_module={setting and setting.get('default_module')}")
story_map, module_name = load_campaign_module("besm_ikaris", "shards_tourney.json")
check("shards_tourney loads", module_name == "Tourney of the Nine Shards (besm_ikaris Starter)" and len(story_map) == 6,
      f"{module_name} | {len(story_map)} nodes")

# 3. Select Aerin Voss (Mageborn Sorcerer)
from engine.guild_roster import roster_dict_to_char
import sqlite3
cols = ['setting_id','name','rank_label','race','points_budget','stat_body','stat_mind','stat_soul','acv','dcv','max_hp','max_ep','card_json','source_path','ingested_at','sixth_guard','structural_fault','levers','combat_techniques','skills','defects','shock_value','md_source_path','gender']
row = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_ikaris' AND name='Aerin Voss'").fetchone()
aerin = roster_dict_to_char(dict(zip(cols, row)))
check("Aerin Voss selectable", aerin.name == "Aerin Voss" and aerin.max_hp == 45,
      f"{aerin.name} HP{aerin.max_hp}/EP{aerin.max_ep} ACV{aerin.base_acv}/DCV{aerin.base_dcv} [{aerin.race}]")

# Also verify the Dark Elf gatekeeper + Warlock moral thrall
row2 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_ikaris' AND name='Fenlaeth'").fetchone()
fenlaeth = roster_dict_to_char(dict(zip(cols, row2))) if row2 else None
check("Fenlaeth (Dark Elf) selectable", fenlaeth is not None and fenlaeth.race == "Dark Elf",
      f"{fenlaeth.name if fenlaeth else 'missing'} — {fenlaeth.race if fenlaeth else ''}")
row3 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_ikaris' AND name='Ronan the Oathless'").fetchone()
ronan = roster_dict_to_char(dict(zip(cols, row3))) if row3 else None
check("Ronan (Warlock) selectable", ronan is not None and "Marked" in str(ronan.defects) if ronan else False,
      f"{ronan.name if ronan else 'missing'} — Oathbreaker runes")

# 4. Navigate court -> vow
node = story_map["node_01_court"]
check("court has north exit", node["exits"].get("north") == "node_02_vow")
vow = story_map["node_02_vow"]
check("vow is a gate", vow["node_type"] == "gate")
check("vow check is Soul", vow["required_check"]["stat"] == "stat_soul")

# 5. Resolve the vow gate (Soul vs DV12)
rc = vow["required_check"]
res = execute_action_check(aerin.stat_soul, rc["skill"], rc["dv"])
check("vow check resolves", "success" in res and "roll" in res,
      f"stat={rc['stat']} skill={rc['skill']} dv={rc['dv']}")

# 6. Resolve the monster-bait hazard (Body vs DV13)
bait = story_map["node_03_monster_bait"]
check("monster bait is an encounter", bait["node_type"] == "encounter")
rcb = bait["required_check"]
resb = execute_action_check(aerin.stat_body, rcb["skill"], rcb["dv"])
check("drake check resolves", "success" in resb and "roll" in resb,
      f"stat={rcb['stat']} skill={rcb['skill']} dv={rcb['dv']} fail_damage={rcb['fail_damage']}")

# 7. Harpers College is lore (gate nexus)
harper = story_map["node_04_harpers_college"]
check("harper hall is lore node", harper["node_type"] == "lore")
check("harper hall leads to duel", harper["exits"].get("north") == "node_05_grand_duel")

# 8. Compile the shell frame with Aerin's loadout + the grand duel node
duel = story_map["node_05_grand_duel"]
vitals = build_vitals_with_full_loadout("besm_ikaris", aerin, "The Tourney Pavilion of Azaria")
bridge = lb.LLMBridge()
frame = bridge.compile_system_frame("besm_shell", vitals, duel)
check("shell carries Aerin name", "Aerin Voss" in frame)
check("shell carries Precise Aim", "Precise Aim" in frame)
check("shell carries Lightning Reflexes", "Lightning Reflexes" in frame)
check("shell carries Hubristic Channelling fault", "Hubristic Channelling" in frame)
check("shell carries Mana Hemorrhage guard", "Mana Hemorrhage" in frame)
check("shell carries High Circle title", "The High Circle" in frame)
check("shell carries vitals (HP/EP/ACV/DCV)", all(x in frame for x in ("45", "60", "ACV", "DCV")))
check("shell carries duel description", "duel" in frame.lower() or "circle" in frame.lower())

# 9. Dispatch one Director turn (patched stream, offline) + apply mechanical payload
def _fake_stream(self, model_name=None, complete_context="", user_input="", ctx=None):
    if ctx is not None:
        ctx["full_raw_text"] = (
            "Your staff flares, arcane bolt answering the Azure Spire's ward. "
            "[MECHANICAL PAYLOAD] {\"hp_loss\": 6, \"ep_loss\": 4}"
        )
    yield "Your staff flares, arcane bolt answering the Azure Spire's ward. "

lb.LLMBridge.dispatch_ollama_turn_stream = _fake_stream

ctx = {}
gen = bridge.dispatch_ollama_turn_stream(ctx=ctx, complete_context=frame, user_input="I strike the High Circle's ward with an arcane bolt!")
prose = "".join(gen)
check("director streams clean prose", "arcane bolt" in prose)
check("ctx captures mechanical payload", "[MECHANICAL PAYLOAD]" in ctx.get("full_raw_text", ""))

mech = bridge.inspect_llm_output(ctx["full_raw_text"])[1]
check("mechanical payload parsed", mech.get("hp_loss") == 6 and mech.get("ep_loss") == 4,
      f"hp_loss={mech.get('hp_loss')} ep_loss={mech.get('ep_loss')}")

# 10. Full navigation reachability: all 6 nodes reachable from court
from engine.verify_dungeon import _reachable_nodes
reachable = _reachable_nodes(story_map, "node_01_court")
check("all 6 nodes reachable", len(reachable) == 6, sorted(reachable))

# 11. Reward node has the victor's chest (/open target)
prize = story_map["node_06_prize"]
check("prize is reward node", prize["node_type"] == "reward")
check("prize has wooden chest", prize.get("chest", {}).get("tier") == "wooden")

print()
print(f"SMOKE TEST: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)