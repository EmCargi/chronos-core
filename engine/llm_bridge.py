import os
import re
import json
import time
import logging
from typing import Dict, Any, Tuple, Optional
from .config import ACTIVE_MODEL, DEFAULT_RULES, THIN_MODEL
from core.ollama import default_chain, post_json
from core.reasoning import strip_reasoning_tags

logger = logging.getLogger("ChronosCore.LLMBridge")


def _format_techniques(techniques: list) -> str:
    """Format combat techniques list as markdown bullets for shell prompt injection."""
    if not techniques:
        return "None"
    lines = []
    for t in techniques:
        lines.append(f"- **{t['name']}** (Level {t['level']}): {t['effect']}")
    return "\n".join(lines)


def _format_skills(skills: list) -> str:
    """Format skills list as markdown bullets for shell prompt injection."""
    if not skills:
        return "None"
    lines = []
    for s in skills:
        spec = f" — *{s['specialisation']}*" if s.get("specialisation") else ""
        lines.append(f"- **{s['name']}** Rank {s['rank']} [{s['stat']}]{spec}")
    return "\n".join(lines)


def _format_defects(defects: list) -> str:
    """Format defects list as markdown bullets for shell prompt injection."""
    if not defects:
        return "None"
    lines = []
    for d in defects:
        lines.append(f"- **{d['name']}** (Rank {d['rank']}, {d['cp']} CP): {d['trigger']}")
    return "\n".join(lines)


class LLMBridge:
    """
    Decoupled bridge to handle local LLM semantic queries, narrative generations,
    prompt template compiling, and response payload validation.

    Inference routes through the canonical Ollama fallback chain (dev/core/ollama.py) —
    big rig first, thin client as last resort. Per-engine model names so each
    machine serves the models it actually hosts.
    """
    def __init__(self):
        pass

    def compile_system_frame(self, prompt_type: Optional[str], character_vitals: dict, active_node: dict) -> str:
        """
        Reads target markdown asset rules files from disk (e.g., engine/prompts/besm_shell.md)
        and handles native string formatting replacements (substituting variables like
        {name}, {current_hp}, {node_description}).
        """
        p_type = prompt_type or DEFAULT_RULES
        base_dir = os.path.dirname(os.path.abspath(__file__))
        prompts_dir = os.path.join(base_dir, "prompts")
        prompt_file = os.path.join(prompts_dir, f"{p_type}.md")
        
        if not os.path.exists(prompt_file):
            logger.warning(f"Prompt asset {prompt_file} not found. Falling back to default shell.")
            prompt_file = os.path.join(prompts_dir, "besm_shell.md")
            
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                template = f.read()
        except Exception as e:
            logger.error(f"Error reading prompt template file: {e}")
            template = "Active Character: {name}\nActive Node: {title}\nDescription: {node_description}"
            
        # Build formatting replacements dictionary
        # Pre-format list fields (combat_techniques, skills, defects) as clean markdown
        replacements = {}
        for k, v in character_vitals.items():
            if k == "combat_techniques" and isinstance(v, list):
                replacements[k] = _format_techniques(v)
            elif k == "skills" and isinstance(v, list):
                replacements[k] = _format_skills(v)
            elif k == "defects" and isinstance(v, list):
                replacements[k] = _format_defects(v)
            else:
                replacements[k] = str(v)
        for k, v in active_node.items():
            replacements[k] = str(v)
            
        # Map node_description key specifically if available
        if "description" in active_node:
            replacements["node_description"] = str(active_node["description"])
            
        # Safe dict mapping to prevent KeyError on standard JSON braces or missing keys
        class SafeFormatter(dict):
            def __missing__(self, key):
                return f"{{{key}}}"
                
        return template.format_map(SafeFormatter(**replacements))

    def dispatch_ollama_turn(self, model_name: Optional[str], complete_context: str, user_input: str) -> dict:
        """Dispatch one inference turn through the Ollama fallback chain."""
        model = model_name or ACTIVE_MODEL
        chain = default_chain(model, THIN_MODEL)

        payload_builder = lambda m: {
            "model": m,
            "prompt": complete_context + user_input,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1024},
        }

        logger.info(f"Dispatching Ollama turn with model '{model}' via fallback chain...")
        start_time = time.time()

        try:
            data = post_json("/api/generate", payload_builder, chain)
            latency = time.time() - start_time
            logger.info(f"Ollama inference completed in {latency:.4f} seconds.")

            raw_text = data.get("response", "")
            return {
                "success": True,
                "response": strip_reasoning_tags(raw_text),
                "latency": latency,
                "raw": data,
            }
        except Exception as e:
            latency = time.time() - start_time
            logger.error(f"Failed to dispatch inference turn: {e}")
            return {
                "success": False,
                "error": str(e),
                "latency": latency,
            }

    def inspect_llm_output(self, raw_response: str) -> Tuple[str, dict]:
        """
        Uses regex to cleanly separate narrative string prose from closing mechanical payload.
        Includes a robust JSON character stack cleanup fallback for unbalanced tags.
        """
        # Tolerant opening/closing tag matching: the model may emit the closing tag as
        # [/MECHANICAL PAYLOAD], [/MECHANICAL SCHEDULED], or [/MECHANICAL], and may wrap the
        # whole block in markdown code fences. Match any [/MECHANICAL ...] close and strip
        # surrounding fence markers so the payload parses cleanly.
        pattern = r"(?:`)*\s*\[MECHANICAL PAYLOAD\](.*?)\[/MECHANICAL(?: [A-Z_]+)?\]\s*(?:`)*"
        # Fallback: the model occasionally drops the closing tag entirely, truncates it, or
        # adds trailing prose. Recover the payload from the opening tag to the end of string.
        fallback_pattern = r"\[MECHANICAL PAYLOAD\](.*?)\Z"
        match = re.search(pattern, raw_response, re.DOTALL)

        narrative_prose = raw_response
        mechanical_data = {}

        if match:
            raw_json_str = match.group(1).strip()
            # Remove the payload block (plus any fence markers) from the narrative prose
            narrative_prose = re.sub(pattern, "", raw_response, flags=re.DOTALL).strip()

            # Clean and parse JSON using stack fallback
            mechanical_data = self._clean_and_parse_json(raw_json_str)
        else:
            # No well-formed block: try the lenient fallback before giving up.
            fallback = re.search(fallback_pattern, raw_response, re.DOTALL)
            if fallback:
                logger.info("MECHANICAL PAYLOAD close tag missing or malformed; using fallback recovery.")
                raw_json_str = fallback.group(1).strip()
                narrative_prose = re.sub(
                    r"\[MECHANICAL PAYLOAD\](.*?)\Z", "", raw_response, flags=re.DOTALL
                ).strip()
                mechanical_data = self._clean_and_parse_json(raw_json_str)
            else:
                logger.warning("No [MECHANICAL PAYLOAD] brackets identified in the LLM output.")

        return narrative_prose, mechanical_data

    def _clean_and_parse_json(self, raw_json_str: str) -> dict:
        """
        Cleans and parses JSON with fallback brace-matching and regex extractors for safety.
        """
        cleaned = raw_json_str.strip()
        
        # Locate outer JSON bounds
        first_brace = cleaned.find('{')
        if first_brace == -1:
            logger.warning("JSON structure starting bracket missing from mechanical block.")
            return {}
            
        last_brace = cleaned.rfind('}')
        if last_brace == -1 or last_brace < first_brace:
            json_candidate = cleaned[first_brace:]
        else:
            json_candidate = cleaned[first_brace:last_brace + 1]
        
        # Clean trailing commas inside collections
        json_candidate = re.sub(r',\s*\}', '}', json_candidate)
        json_candidate = re.sub(r',\s*\]', ']', json_candidate)
        
        # Attempt standard JSON loading
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError as e:
            logger.warning(f"Standard JSON decode failed ({e}). Running character stack balancer.")
            
        # Character stack balancer fallback
        stack = []
        balanced_chars = []
        for char in json_candidate:
            if char == '{':
                stack.append('}')
                balanced_chars.append(char)
            elif char == '[':
                stack.append(']')
                balanced_chars.append(char)
            elif char in ('}', ']'):
                if stack and stack[-1] == char:
                    stack.pop()
                    balanced_chars.append(char)
                else:
                    continue
            else:
                balanced_chars.append(char)
                
        # Close any open structures safely
        while stack:
            balanced_chars.append(stack.pop())
            
        balanced_json_str = "".join(balanced_chars)
        
        try:
            return json.loads(balanced_json_str)
        except json.JSONDecodeError:
            logger.warning("Stack balanced parser failed. Using regex key-value extraction fallback.")
            
        # Regex key-value dictionary extractor
        extracted = {}
        matches = re.findall(r'"([^"]+)"\s*:\s*(?:"([^"]*)"|(\d+)|(true|false|null))', json_candidate)
        for m in matches:
            key = m[0]
            val_str = m[1]
            val_int = m[2]
            val_bool = m[3]
            if val_str:
                extracted[key] = val_str
            elif val_int:
                extracted[key] = int(val_int)
            elif val_bool:
                if val_bool == "true":
                    extracted[key] = True
                elif val_bool == "false":
                    extracted[key] = False
                else:
                    extracted[key] = None
                    
        return extracted

    def generate_narrative(self, prompt: str, system_context: str) -> str:
        """
        Legacy mock compatibility method.
        """
        logger.info("generate_narrative wrapper called.")
        return "Narrative generation stub: Decoupled local LLM response."
