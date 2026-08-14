import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")

# Ensure config directory exists
os.makedirs(CONFIG_DIR, exist_ok=True)

# Default configuration settings
DEFAULTS = {
    "ACTIVE_MODEL": "llama3",
    "OLLAMA_URL": "http://localhost:11434/api/generate",
    "DEFAULT_RULES": "besm_shell",
    "DEFAULT_SETTING": "guild_rpg"
}

# Write defaults if settings.json does not exist
if not os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, indent=2)
    except Exception:
        pass

def load_settings() -> dict:
    """Loads configuration settings from disk with fallback defaults."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                # Merge defaults for any missing keys
                for k, v in DEFAULTS.items():
                    if k not in loaded:
                        loaded[k] = v
                return loaded
        except Exception:
            return DEFAULTS
    return DEFAULTS

SETTINGS = load_settings()
ACTIVE_MODEL = SETTINGS.get("ACTIVE_MODEL", "llama3")
OLLAMA_URL = SETTINGS.get("OLLAMA_URL", "http://localhost:11434/api/generate")
DEFAULT_RULES = SETTINGS.get("DEFAULT_RULES", "besm_shell")
DEFAULT_SETTING = SETTINGS.get("DEFAULT_SETTING", "guild_rpg")
