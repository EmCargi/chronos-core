import os
import sys
import json
import shutil
import logging
from datetime import datetime

# Ensure the root folder is on Python path to allow importing modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.models import CharacterSchema
from engine.guild_roster import init_roster_db, upsert_character, add_power_pack
from engine.llm_bridge import LLMBridge
from engine.config import ACTIVE_MODEL, DEFAULT_SETTING

logger = logging.getLogger("ChronosCore.BatchIngest")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DIR = os.path.join(BASE_DIR, "staging")
RAW_DIR = os.path.join(STAGING_DIR, "raw")
PROCESSED_DIR = os.path.join(STAGING_DIR, "processed")
FAILED_DIR = os.path.join(STAGING_DIR, "failed")

def run_auto_ingest() -> dict:
    """
    Scans staging/raw/ for JSON files, translates them using either local fallbacks
    or LLM mapping based on standard chara_card formats, validates them against
    CharacterSchema, persists them to the session DB, and routes them to processed/ or failed/.
    """
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    os.makedirs(FAILED_DIR, exist_ok=True)
    
    files = [f for f in os.listdir(RAW_DIR) if f.endswith(".json")]
    logger.info(f"Auto-Ingest sweep started. Identified {len(files)} files to ingest.")
    
    results = {
        "processed": [],
        "failed": []
    }
    
    if not files:
        return results
        
    bridge = LLMBridge()
    
    # Load prompt mapping instructions
    mapper_prompt_path = os.path.join(BASE_DIR, "engine", "prompts", "besm-mapper")
    mapper_instructions = ""
    if os.path.exists(mapper_prompt_path):
        try:
            with open(mapper_prompt_path, "r", encoding="utf-8") as f:
                mapper_instructions = f.read()
        except Exception as e:
            logger.error(f"Failed to read mapper prompt: {e}")

    for filename in files:
        raw_filepath = os.path.join(RAW_DIR, filename)
        
        try:
            with open(raw_filepath, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            failed_filepath = os.path.join(FAILED_DIR, filename)
            shutil.move(raw_filepath, failed_filepath)
            write_error_log(filename, f"Invalid JSON syntax: {e}")
            results["failed"].append((filename, "Invalid JSON syntax"))
            continue

        character_dict = None
        roster_meta = {
            "setting_id": DEFAULT_SETTING,
            "rank_label": "Unranked",
            "race": "Unknown",
            "acv": None,
            "dcv": None,
            "hp": None,
            "ep": None,
            "power_packs": [],
            "sixth_guard": "",
            "structural_fault": "",
            "levers": ""
        }
        
        # Resolve nested character data keys in ST v2/v3 cards
        inner_data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else {}
        name = inner_data.get("name", os.path.splitext(filename)[0])
        desc = str(inner_data.get("description", ""))
        
        # Extract the embedded SYSTEM DATA block (if any) for canonical-stats priority.
        import re as _re
        system_data_block = ""
        _sd_match = _re.search(r"\[SYSTEM DATA: BESM 4E MECHANICS\].*?(?=\n\[|\Z)", desc, _re.DOTALL)
        if _sd_match:
            system_data_block = _sd_match.group(0)
        
        # Parse optional canonical metadata lines from the SYSTEM DATA block.
        # Setting detection: [Setting: <id>] is authoritative; fall back to [Guild Rank:]
        # implying guild_rpg, then to the configured default.
        _setting_m = _re.search(r"\[Setting:\s*([^\]]+)\]", desc)
        if _setting_m:
            roster_meta["setting_id"] = _setting_m.group(1).strip()
        _rank_m = _re.search(r"\[(?:Guild\s*)?Rank:\s*([^\]]+)\]", desc)
        if _rank_m:
            roster_meta["rank_label"] = _rank_m.group(1).strip()
            if roster_meta["setting_id"] == DEFAULT_SETTING and "Guild" in _rank_m.group(0):
                roster_meta["setting_id"] = "guild_rpg"
        _tier_m = _re.search(r"\[Tier:\s*([^\]]+)\]", desc)
        if _tier_m:
            roster_meta["rank_label"] = _tier_m.group(1).strip()
            if roster_meta["setting_id"] == DEFAULT_SETTING and DEFAULT_SETTING == "guild_rpg":
                roster_meta["setting_id"] = "besm_disc"
        _cv_m = _re.search(r"\[Combat Values:\s*ACV\s*(\d+)\s*,\s*DCV\s*(\d+)\.\s*HP:?\s*(\d+)\.\s*EP:?\s*(\d+)\s*\.?\]", desc, _re.IGNORECASE)
        if _cv_m:
            roster_meta["acv"] = int(_cv_m.group(1))
            roster_meta["dcv"] = int(_cv_m.group(2))
            roster_meta["hp"] = int(_cv_m.group(3))
            roster_meta["ep"] = int(_cv_m.group(4))
        _race_m = _re.search(r"\[Race:\s*([^\]]+)\]", desc)
        if _race_m:
            roster_meta["race"] = _race_m.group(1).strip()
        else:
            known_races = ["High Elf", "Half-Elf", "Beastkin", "Dragonkin", "Human", "Elf", "Dwarf", "Orc", "Goblin"]
            for _race in known_races:
                if _re.search(rf"\b{_race}\b", desc):
                    roster_meta["race"] = _race
                    break
        _pp_m = _re.search(r"\[Power Packs:\s*([^\]]+)\]", desc)
        if _pp_m:
            _raw_packs = [p.strip() for p in _pp_m.group(1).split("+") if p.strip()]
            roster_meta["power_packs"] = [
                p for p in _raw_packs
                if not p.lower().startswith("none")
                and not p.lower().startswith("no ")
            ]
        
        # Narrative-syntax framework fields (Aelthar Keldor): Sixth Guard, Structural Fault,
        # and the Three Strategic Levers. Parsed from [Sixth Guard:], [Structural Fault:],
        # [Levers:] tags; injected into the runtime shell as AI Director context.
        _sixth_m = _re.search(r"\[Sixth Guard:\s*([^\]]+)\]", desc)
        if _sixth_m:
            roster_meta["sixth_guard"] = _sixth_m.group(1).strip()
        _fault_m = _re.search(r"\[Structural Fault:\s*([^\]]+)\]", desc)
        if _fault_m:
            roster_meta["structural_fault"] = _fault_m.group(1).strip()
        _levers_m = _re.search(r"\[Levers:\s*([^\]]+)\]", desc)
        if _levers_m:
            roster_meta["levers"] = _levers_m.group(1).strip()
        
        # Method 1 (AUTHORITATIVE): If the card embeds a SYSTEM DATA block, those stats are the
        # single source of truth. Parse them deterministically and do NOT let an LLM re-derive them.
        # Format example:
        # [Stats: Body 4, Mind 7, Soul 7]
        # [Points Budget: 222 / 249 CP]
        system_match = _re.search(r"\[Stats:\s*Body\s*(\d+)(?:\s*\([^]]*\))?\s*,\s*Mind\s*(\d+)(?:\s*\([^]]*\))?\s*,\s*Soul\s*(\d+)(?:\s*\([^]]*\))?\]", desc)
        if system_match:
            points_budget = 75
            stat_body = int(system_match.group(1))
            stat_mind = int(system_match.group(2))
            stat_soul = int(system_match.group(3))
            budget_match = _re.search(r"\[Points Budget:\s*(\d+)", desc)
            if budget_match:
                points_budget = int(budget_match.group(1))
            character_dict = {
                "name": name,
                "points_budget": points_budget,
                "stat_body": stat_body,
                "stat_mind": stat_mind,
                "stat_soul": stat_soul
            }
            logger.info(f"Parsed canonical SYSTEM DATA stats for: {name}")
        
        # Method 2: Try LLM translation if online (only for cards WITHOUT canonical SYSTEM DATA)
        if not character_dict and mapper_instructions:
            try:
                system_frame = f"""
                {mapper_instructions}
                
                You must translate the provided character card JSON into a valid CharacterSchema JSON payload.
                Ensure you output exactly one JSON structure at the very end of your response inside a [MECHANICAL PAYLOAD] tag:
                [MECHANICAL PAYLOAD]
                {{
                  "name": "<name of character>",
                  "points_budget": <integer (e.g. 75)>,
                  "stat_body": <integer 1-12>,
                  "stat_mind": <integer 1-12>,
                  "stat_soul": <integer 1-12>
                }}
                [/MECHANICAL PAYLOAD]
                """
                
                # Truncate the card to avoid overflow, but ALWAYS prepend the canonical SYSTEM DATA block if present.
                llm_input = json.dumps(raw_data)[:5000]
                if system_data_block:
                    llm_input = system_data_block + "\n\n" + llm_input
                
                response = bridge.dispatch_ollama_turn(
                    model_name=ACTIVE_MODEL,
                    complete_context=system_frame,
                    user_input=llm_input
                )
                
                if response.get("success"):
                    prose, payload = bridge.inspect_llm_output(response["response"])
                    if payload and all(k in payload for k in ["name", "stat_body", "stat_mind", "stat_soul"]):
                        character_dict = payload
                        logger.info(f"LLM translated sheet successfully for: {payload.get('name')}")
            except Exception as e:
                logger.error(f"LLM translation failed for {filename}: {e}")

        # Method 3: Offline rank-heuristic fallback (last resort, no SYSTEM DATA and LLM unavailable/failed)
        if not character_dict:
            logger.info(f"Executing offline local translator for: {filename}")
            
            # Simple rank parsing to map stats & points budget
            points_budget = 75
            stat_body = 6
            stat_mind = 7
            stat_soul = 7
            
            if "A-Rank" in desc or "A Rank" in desc:
                points_budget = 120
                stat_body = 8
                stat_mind = 9
                stat_soul = 8
            elif "B-Rank" in desc or "B Rank" in desc:
                points_budget = 90
                stat_body = 7
                stat_mind = 8
                stat_soul = 7
            elif "C-Rank" in desc or "C Rank" in desc:
                points_budget = 70
                stat_body = 6
                stat_mind = 7
                stat_soul = 7
                
            character_dict = {
                "name": name,
                "points_budget": points_budget,
                "stat_body": stat_body,
                "stat_mind": stat_mind,
                "stat_soul": stat_soul
            }

        try:
            # Instantiate Pydantic Schema to run type checks & budget bounds validations
            character = CharacterSchema(**character_dict)
            character.current_hp = character.max_hp
            character.current_ep = character.max_ep

            # Resolve canonical combat values from SYSTEM DATA (fall back to derived).
            acv = roster_meta["acv"] if roster_meta["acv"] is not None else character.base_acv
            dcv = roster_meta["dcv"] if roster_meta["dcv"] is not None else character.base_dcv
            max_hp = roster_meta["hp"] if roster_meta["hp"] is not None else character.max_hp
            max_ep = roster_meta["ep"] if roster_meta["ep"] is not None else character.max_ep

            # Commit to the canonical Guild RPG roster database (source of truth).
            init_roster_db()
            roster_row = {
                "name": character.name,
                "rank_label": roster_meta["rank_label"],
                "race": roster_meta["race"],
                "points_budget": character.points_budget,
                "stat_body": character.stat_body,
                "stat_mind": character.stat_mind,
                "stat_soul": character.stat_soul,
                "acv": acv,
                "dcv": dcv,
                "max_hp": max_hp,
                "max_ep": max_ep,
                "sixth_guard": roster_meta["sixth_guard"],
                "structural_fault": roster_meta["structural_fault"],
                "levers": roster_meta["levers"]
            }
            upsert_character(roster_meta["setting_id"], roster_row, json.dumps(raw_data), raw_filepath)
            for pack_name in roster_meta["power_packs"]:
                add_power_pack(roster_meta["setting_id"], character.name, pack_name, raw_filepath)
            logger.info(f"Committed canonical roster character: [{roster_meta['setting_id']}] {character.name} ({filename})")
            
            # Move to processed folder
            processed_filepath = os.path.join(PROCESSED_DIR, filename)
            shutil.move(raw_filepath, processed_filepath)
            results["processed"].append(filename)
            logger.info(f"Ingested and committed character: {character.name} ({filename})")
            
        except Exception as e:
            failed_filepath = os.path.join(FAILED_DIR, filename)
            shutil.move(raw_filepath, failed_filepath)
            write_error_log(filename, f"CharacterSchema validation failed: {e}")
            results["failed"].append((filename, str(e)))
            logger.error(f"Staging validation check failed for {filename}: {e}")
            
    return results

def write_error_log(filename: str, error_msg: str):
    log_name = f"{filename}_error.log"
    log_path = os.path.join(FAILED_DIR, log_name)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"File: {filename}\n")
            f.write(f"Error Details: {error_msg}\n")
    except Exception:
        pass

if __name__ == "__main__":
    res = run_auto_ingest()
    print(f"Auto-Ingest Complete. Processed: {len(res['processed'])}. Failed: {len(res['failed'])}.")
