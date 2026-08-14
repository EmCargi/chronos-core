import os
import sys
import json
import logging
from typing import Optional

# Ensure the root folder is on Python path to allow importing modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.models import CharacterSchema
from engine.state_manager import save_runtime_snapshot, init_db
from engine.llm_bridge import LLMBridge
from engine.config import ACTIVE_MODEL

logger = logging.getLogger("ChronosCore.CharWizard")

def get_budget_limit(power_level: str) -> int:
    """Returns CP limit based on power level."""
    level = power_level.strip().lower()
    if "human" in level:
        return 49
    elif "heroic" in level:
        return 74
    else:
        return 120

def run_character_wizard():
    print("====================================================")
    print("      🌟 CHRONOS CORE CHARACTER CREATOR WIZARD 🌟   ")
    print("====================================================")
    
    char_name = input("Enter Character Name: ").strip() or "Unnamed Operative"
    narrative_concept = input("Enter Narrative Concept (e.g. Cybernetic Detective): ").strip() or "Standard Agent"
    power_level = input("Enter Power Level (Human [25-49 CP] / Heroic [50-74 CP]): ").strip() or "Human"
    genre = input("Enter Genre (e.g. Cyberpunk / Sci-Fi): ").strip() or "Sci-Fi"
    
    budget_limit = get_budget_limit(power_level)
    print(f"\n[System] Power Level set to '{power_level}' with CP Budget Limit: {budget_limit}")
    print("[System] Constructing core attributes using BESM Character Creator template...")
    
    # 1. Load System Prompt from besm-ai-dm/BESM Character Creator.md
    creator_prompt_path = os.environ.get("BESM_PROMPT_PATH", "/home/megane/dev/besm-ai-dm/BESM Character Creator.md")
    if not os.path.exists(creator_prompt_path):
        possible_paths = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../..", "besm-ai-dm", "BESM Character Creator.md")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "besm-ai-dm", "BESM Character Creator.md")),
            "/home/megane/dev/sandbox/besm-ai-dm/BESM Character Creator.md",
            "besm-ai-dm/BESM Character Creator.md"
        ]
        for p in possible_paths:
            if os.path.exists(p):
                creator_prompt_path = p
                break
    creator_prompt = ""
    if os.path.exists(creator_prompt_path):
        try:
            with open(creator_prompt_path, "r", encoding="utf-8") as f:
                creator_prompt = f.read()
        except Exception as e:
            logger.error(f"Failed to read stored prompt template: {e}")
            
    # Compile initial context
    context = f"""
    {creator_prompt}
    
    Target Parameters:
    Name: {char_name}
    Concept: {narrative_concept}
    Power Level: {power_level} (CP Budget: {budget_limit})
    Genre: {genre}
    
    At the very end of your response, you MUST output a mechanical payload matching our Pydantic validation structure in the following format:
    [MECHANICAL PAYLOAD]
    {{
      "name": "{char_name}",
      "points_budget": {budget_limit},
      "stat_body": <integer 1-12>,
      "stat_mind": <integer 1-12>,
      "stat_soul": <integer 1-12>
    }}
    [/MECHANICAL PAYLOAD]
    """
    
    bridge = LLMBridge()
    
    # Recalibration loop details
    max_retries = 3
    retry_count = 0
    validated_char_dict = None
    
    # We execute a loop to retrieve and validate LLM output
    while retry_count < max_retries:
        print(f"[System] Dispatching request to Ollama ({ACTIVE_MODEL})... (Attempt {retry_count + 1}/{max_retries})")
        
        response = bridge.dispatch_ollama_turn(
            model_name=ACTIVE_MODEL,
            complete_context=context,
            user_input=f"Generate the mechanical sheet for {char_name}."
        )
        
        if not response.get("success"):
            print("[Warning] Local inference server offline or returned error. Activating local generator fallback...")
            break
            
        raw_response = response.get("response", "")
        prose, payload = bridge.inspect_llm_output(raw_response)
        
        # Verify JSON properties exist
        if not payload or not all(k in payload for k in ["stat_body", "stat_mind", "stat_soul"]):
            print("[Warning] JSON payload missing required Tri-Stat fields. Recalibrating context...")
            context += f"\n\nError: Please make sure to return exactly 'stat_body', 'stat_mind', and 'stat_soul' in the payload."
            retry_count += 1
            continue
            
        # Calculate CP spent
        stat_body = int(payload.get("stat_body", 6))
        stat_mind = int(payload.get("stat_mind", 6))
        stat_soul = int(payload.get("stat_soul", 6))
        cp_spent = (stat_body + stat_mind + stat_soul) * 2
        
        print(f"[System] Audit: Spent {cp_spent} CP of {budget_limit} CP limit.")
        
        if cp_spent > budget_limit:
            print(f"[Warning] Budget limit violated ({cp_spent} spent > {budget_limit} allowed). Triggering Recalibration Loop...")
            # Append feedback error message to recalibrate
            error_feedback = f"\n\nError: The generated stats spent {cp_spent} CP, which exceeds the budget limit of {budget_limit} CP. Please reduce the stats so that (stat_body + stat_mind + stat_soul) * 2 <= {budget_limit}."
            context += error_feedback
            retry_count += 1
        else:
            # Valid budget!
            print(f"[Success] Character stats audited successfully within the {budget_limit} CP budget limit!")
            validated_char_dict = {
                "name": char_name,
                "points_budget": budget_limit,
                "stat_body": stat_body,
                "stat_mind": stat_mind,
                "stat_soul": stat_soul
            }
            break
            
    # Fallback to local generator if not validated
    if not validated_char_dict:
        print("[System] Using local deterministic builder to construct a balanced operative...")
        if budget_limit <= 49: # Human
            stat_body, stat_mind, stat_soul = 6, 7, 7 # Spent (6+7+7)*2 = 40 CP
        else: # Heroic
            stat_body, stat_mind, stat_soul = 8, 9, 8 # Spent (8+9+8)*2 = 50 CP
            
        validated_char_dict = {
            "name": char_name,
            "points_budget": budget_limit,
            "stat_body": stat_body,
            "stat_mind": stat_mind,
            "stat_soul": stat_soul
        }
        
    # Instantiate Pydantic Schema to trigger clamping & validation checks
    try:
        character = CharacterSchema(**validated_char_dict)
        character.current_hp = character.max_hp
        character.current_ep = character.max_ep
        print(f"\n[Success] CharacterSchema initialized: {character.name}")
        print(f"Stats -> Body: {character.stat_body}, Mind: {character.stat_mind}, Soul: {character.stat_soul}")
        print(f"Vitals -> HP: {character.max_hp}, EP: {character.max_ep}")
    except Exception as e:
        print(f"[Error] Pydantic validation failed: {e}")
        return
        
    # 4. Persistence Loop
    session_id = "chronos_interactive_session"
    
    # Load starting node from five_room_dungeon_v1.json if it exists
    module_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modules", "five_room_dungeon_v1.json")
    starting_node = "node_01_guardian"
    if os.path.exists(module_path):
        try:
            with open(module_path, "r", encoding="utf-8") as f:
                mod_data = json.load(f)
                starting_node = mod_data.get("starting_node", "node_01_guardian")
        except Exception:
            pass
            
    try:
        init_db()
        save_runtime_snapshot(session_id, character, starting_node)
        print(f"[Success] Character '{character.name}' saved to SQLite as the active player entity.")
        print(f"[System] Active node reset to: '{starting_node}'.")
    except Exception as e:
        print(f"[Error] Failed to persist character state to database: {e}")

if __name__ == "__main__":
    run_character_wizard()
