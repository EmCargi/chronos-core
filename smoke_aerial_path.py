"""Headless smoke test: run Elyra through the Aerial Path (Vigil of the Blight).

Drives the TUI's core play path offline (LLM patched, big-rig independent):
boot state -> load besm_aradia + aerial_path -> select Elyra -> navigate vale ->
oath (Soul gate) -> storm-symbols (Mind hazard) -> the Whirl (lore gate) ->
blight (Body encounter) -> haven (reward chest) -> compile the shell frame
(Elyra loadout + node) -> dispatch one Director turn (patched stream) and
apply its mechanical payload.
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

# 2. Load Aradia setting + the 6-node aerial path module
setting = get_setting("besm_aradia")
check("setting resolves", setting is not None,
      f"default_module={setting and setting.get('default_module')}")
story_map, module_name = load_campaign_module("besm_aradia", "aerial_path.json")
check("aerial_path loads", module_name == "Aerial Path — The Vigil of the Blight (besm_aradia Starter)" and len(story_map) == 6,
      f"{module_name} | {len(story_map)} nodes")

# 3. Select Elyra (Sabaoth hunter)
from engine.guild_roster import roster_dict_to_char
import sqlite3
cols = ['setting_id','name','rank_label','race','points_budget','stat_body','stat_mind','stat_soul','acv','dcv','max_hp','max_ep','card_json','source_path','ingested_at','sixth_guard','structural_fault','levers','combat_techniques','skills','defects','shock_value','md_source_path','gender']
row = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_aradia' AND name='Elyra'").fetchone()
elyra = roster_dict_to_char(dict(zip(cols, row)))
check("Elyra selectable", elyra.name == "Elyra" and elyra.max_hp == 55,
      f"{elyra.name} HP{elyra.max_hp}/EP{elyra.max_ep} ACV{elyra.base_acv}/DCV{elyra.base_dcv} [{elyra.race}]")

# Also verify Mothwing (tainted moral thrall) + Vireo (Elarad gatekeeper)
row2 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_aradia' AND name='Mothwing'").fetchone()
mothwing = roster_dict_to_char(dict(zip(cols, row2))) if row2 else None
check("Mothwing (tainted fairy) selectable", mothwing is not None and "Tainted" in str(mothwing.defects) if mothwing else False,
      f"{mothwing.name if mothwing else 'missing'} — {mothwing.race if mothwing else ''}")
row3 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_aradia' AND name='Vireo'").fetchone()
vireo = roster_dict_to_char(dict(zip(cols, row3))) if row3 else None
check("Vireo (Elarad) selectable", vireo is not None and vireo.race == "Elarad",
      f"{vireo.name if vireo else 'missing'} — {vireo.race if vireo else ''}")

# 4. Navigate vale -> oath
node = story_map["node_01_vale"]
check("vale has north exit", node["exits"].get("north") == "node_02_oath")
oath = story_map["node_02_oath"]
check("oath is a gate", oath["node_type"] == "gate")
check("oath check is Soul", oath["required_check"]["stat"] == "stat_soul")

# 5. Resolve the oath gate (Soul vs DV12)
rc = oath["required_check"]
res = execute_action_check(elyra.stat_soul, rc["skill"], rc["dv"])
check("oath check resolves", "success" in res and "roll" in res,
      f"stat={rc['stat']} skill={rc['skill']} dv={rc['dv']}")

# 6. Resolve the storm-symbols hazard (Mind vs DV13)
storm = story_map["node_03_storm"]
check("storm is an encounter", storm["node_type"] == "encounter")
rcs = storm["required_check"]
ress = execute_action_check(elyra.stat_mind, rcs["skill"], rcs["dv"])
check("storm check resolves", "success" in ress and "roll" in ress,
      f"stat={rcs['stat']} skill={rcs['skill']} dv={rcs['dv']} fail_damage={rcs['fail_damage']}")

# 7. Whirl is lore (gate to Earth)
whirl = story_map["node_04_whirl"]
check("whirl is lore node", whirl["node_type"] == "lore")
check("whirl leads to blight", whirl["exits"].get("north") == "node_05_blight")

# 8. Compile the shell frame with Elyra's loadout + the blight node
blight = story_map["node_05_blight"]
vitals = build_vitals_with_full_loadout("besm_aradia", elyra, "Vale of Thorns — Sabaoth Encampment")
bridge = lb.LLMBridge()
frame = bridge.compile_system_frame("besm_shell", vitals, blight)
check("shell carries Elyra name", "Elyra" in frame)
check("shell carries Precise Aim", "Precise Aim" in frame)
check("shell carries Lightning Reflexes", "Lightning Reflexes" in frame)
check("shell carries Hunter's Focus fault", "Hunter's Focus" in frame)
check("shell carries Wing-Wound guard", "Wing-Wound" in frame)
check("shell carries Blight title", "Wormwood Blight's Edge" in frame)
check("shell carries vitals (HP/EP/ACV/DCV)", all(x in frame for x in ("55", "ACV", "DCV")))
check("shell carries blight description", "blight" in frame.lower() or "cancer" in frame.lower())

# 9. Dispatch one Director turn (patched stream, offline) + apply mechanical payload
def _fake_stream(self, model_name=None, complete_context="", user_input="", ctx=None):
    if ctx is not None:
        ctx["full_raw_text"] = (
            "You dive from the wing, storm-song flaring against the dark fairy's rush. "
            "[MECHANICAL PAYLOAD] {\"hp_loss\": 5, \"ep_loss\": 3}"
        )
    yield "You dive from the wing, storm-song flaring against the dark fairy's rush. "

lb.LLMBridge.dispatch_ollama_turn_stream = _fake_stream

ctx = {}
gen = bridge.dispatch_ollama_turn_stream(ctx=ctx, complete_context=frame, user_input="I storm-song the dark fairy off the ward!")
prose = "".join(gen)
check("director streams clean prose", "storm-song" in prose)
check("ctx captures mechanical payload", "[MECHANICAL PAYLOAD]" in ctx.get("full_raw_text", ""))

mech = bridge.inspect_llm_output(ctx["full_raw_text"])[1]
check("mechanical payload parsed", mech.get("hp_loss") == 5 and mech.get("ep_loss") == 3,
      f"hp_loss={mech.get('hp_loss')} ep_loss={mech.get('ep_loss')}")

# 10. Full navigation reachability: all 6 nodes reachable from vale
from engine.verify_dungeon import _reachable_nodes
reachable = _reachable_nodes(story_map, "node_01_vale")
check("all 6 nodes reachable", len(reachable) == 6, sorted(reachable))

# 11. Reward node has the haven chest (/open target)
haven = story_map["node_06_haven"]
check("haven is reward node", haven["node_type"] == "reward")
check("haven has wooden chest", haven.get("chest", {}).get("tier") == "wooden")

print()
print(f"SMOKE TEST: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)