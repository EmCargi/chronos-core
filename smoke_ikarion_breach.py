"""Headless smoke test: run Kai Voss through the Ikarion Breach.

Drives the TUI's core play path offline (LLM patched, big-rig independent):
boot state -> load besm_imago + ikarion_breach -> select Kai Voss ->
navigate neo_edo -> press (Soul gate) -> arena (Mind hazard) -> ikarion
(lore gate) -> fault_zone (Body encounter) -> server (reward chest) ->
compile the shell frame (Kai loadout + node) -> dispatch one Director turn
(patched stream) and apply its mechanical payload.
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

# 2. Load Imago setting + the 6-node Ikarion breach module
setting = get_setting("besm_imago")
check("setting resolves", setting is not None,
      f"default_module={setting and setting.get('default_module')}")
story_map, module_name = load_campaign_module("besm_imago", "ikarion_breach.json")
check("ikarion_breach loads", module_name == "Ikarion Breach — Neo-Evolution Grand Prix (besm_imago Starter)" and len(story_map) == 6,
      f"{module_name} | {len(story_map)} nodes")

# 3. Select Kai Voss (Typhon neomorph trainer)
from engine.guild_roster import roster_dict_to_char
import sqlite3
cols = ['setting_id','name','rank_label','race','points_budget','stat_body','stat_mind','stat_soul','acv','dcv','max_hp','max_ep','card_json','source_path','ingested_at','sixth_guard','structural_fault','levers','combat_techniques','skills','defects','shock_value','md_source_path','gender']
row = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_imago' AND name='Kai Voss'").fetchone()
kai = roster_dict_to_char(dict(zip(cols, row)))
check("Kai Voss selectable", kai.name == "Kai Voss" and kai.max_hp == 50,
      f"{kai.name} HP{kai.max_hp}/EP{kai.max_ep} ACV{kai.base_acv}/DCV{kai.base_dcv} [{kai.race}]")

# Also verify Bolt (Xyconal'd neomorph moral thrall) + Ari (Monad gatekeeper)
row2 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_imago' AND name='Bolt'").fetchone()
bolt = roster_dict_to_char(dict(zip(cols, row2))) if row2 else None
check("Bolt (neomorph) selectable", bolt is not None and bolt.race == "Neomorph",
      f"{bolt.name if bolt else 'missing'} — {bolt.race if bolt else ''}")
row3 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_imago' AND name='Ari'").fetchone()
ari = roster_dict_to_char(dict(zip(cols, row3))) if row3 else None
check("Ari (Monad engineer) selectable", ari is not None and ari.race == "Human",
      f"{ari.name if ari else 'missing'} — gate-sense")

# 4. Navigate neo_edo -> press
node = story_map["node_01_neo_edo"]
check("neo_edo has north exit", node["exits"].get("north") == "node_02_press")
press = story_map["node_02_press"]
check("press is a gate", press["node_type"] == "gate")
check("press check is Soul", press["required_check"]["stat"] == "stat_soul")

# 5. Resolve the press gate (Soul vs DV12)
rc = press["required_check"]
res = execute_action_check(kai.stat_soul, rc["skill"], rc["dv"])
check("press check resolves", "success" in res and "roll" in res,
      f"stat={rc['stat']} skill={rc['skill']} dv={rc['dv']}")

# 6. Resolve the monster-out hazard (Mind vs DV13)
arena = story_map["node_03_arena"]
check("arena is an encounter", arena["node_type"] == "encounter")
rca = arena["required_check"]
resa = execute_action_check(kai.stat_mind, rca["skill"], rca["dv"])
check("arena check resolves", "success" in resa and "roll" in resa,
      f"stat={rca['stat']} skill={rca['skill']} dv={rca['dv']} fail_damage={rca['fail_damage']}")

# 7. Ikarion server is lore (gate to Ikaris)
ikarion = story_map["node_04_ikarion"]
check("ikarion is lore node", ikarion["node_type"] == "lore")
check("ikarion leads to fault zone", ikarion["exits"].get("north") == "node_05_fault_zone")

# 8. Compile the shell frame with Kai's loadout + the fault zone node
fault = story_map["node_05_fault_zone"]
vitals = build_vitals_with_full_loadout("besm_imago", kai, "Neo Edo — Grand Prix Arena")
bridge = lb.LLMBridge()
frame = bridge.compile_system_frame("besm_shell", vitals, fault)
check("shell carries Kai name", "Kai Voss" in frame)
check("shell carries Precise Aim", "Precise Aim" in frame)
check("shell carries Steady Hand", "Steady Hand" in frame)
check("shell carries Trainer's Pride fault", "Trainer's Pride" in frame)
check("shell carries Pet-Loss guard", "Pet-Loss" in frame)
check("shell carries fault zone title", "The Fault Zone Pursuit" in frame)
check("shell carries vitals (HP/EP/ACV/DCV)", all(x in frame for x in ("50", "ACV", "DCV")))
check("shell carries fault zone description", "fault zone" in frame.lower() or "gang" in frame.lower())

# 9. Dispatch one Director turn (patched stream, offline) + apply mechanical payload
def _fake_stream(self, model_name=None, complete_context="", user_input="", ctx=None):
    if ctx is not None:
        ctx["full_raw_text"] = (
            "You vault a mutant gang's barricade, exo-hand crackling. "
            "[MECHANICAL PAYLOAD] {\"hp_loss\": 5, \"ep_loss\": 3}"
        )
    yield "You vault a mutant gang's barricade, exo-hand crackling. "

lb.LLMBridge.dispatch_ollama_turn_stream = _fake_stream

ctx = {}
gen = bridge.dispatch_ollama_turn_stream(ctx=ctx, complete_context=frame, user_input="I overclock the exo-hand and clear the barricade!")
prose = "".join(gen)
check("director streams clean prose", "exo-hand" in prose or "barricade" in prose)
check("ctx captures mechanical payload", "[MECHANICAL PAYLOAD]" in ctx.get("full_raw_text", ""))

mech = bridge.inspect_llm_output(ctx["full_raw_text"])[1]
check("mechanical payload parsed", mech.get("hp_loss") == 5 and mech.get("ep_loss") == 3,
      f"hp_loss={mech.get('hp_loss')} ep_loss={mech.get('ep_loss')}")

# 10. Full navigation reachability: all 6 nodes reachable from neo_edo
from engine.verify_dungeon import _reachable_nodes
reachable = _reachable_nodes(story_map, "node_01_neo_edo")
check("all 6 nodes reachable", len(reachable) == 6, sorted(reachable))

# 11. Reward node has the breach server chest (/open target)
server = story_map["node_06_server"]
check("server is reward node", server["node_type"] == "reward")
check("server has wooden chest", server.get("chest", {}).get("tier") == "wooden")

print()
print(f"SMOKE TEST: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)