import json
import os
from typing import Optional

CONFIG_FILE = "config.json"
LOCAL_CONFIG_FILE = os.environ.get("ARXIVC_LOCAL_CONFIG_FILE", "config.local.json")

# Defaults
DEFAULT_CATEGORIES = ['astro-ph', 'gr-qc', 'hep-th', 'quant-ph', 'math.GT', 'cs.LG', 'cs.AI']
DEFAULT_KEYWORDS = [
    'HII galaxies', 
    'Cosmology', 
    'Dark Energy', 
    'Hubble constant tension',
    'Star formation',
    'Massive stars',
    'Machine Learning',
    'Generative Models'
]
DEFAULT_WARMUP_MODELS = False
DEFAULT_NOTION_TOKEN = ""
DEFAULT_NOTION_DATABASE_ID = ""

# Global cache
CATEGORIES = []
KEYWORDS = []
VAULT_PATH = ""
MAX_RESULTS = 200
WARMUP_MODELS = DEFAULT_WARMUP_MODELS
NOTION_TOKEN = DEFAULT_NOTION_TOKEN
NOTION_DATABASE_ID = DEFAULT_NOTION_DATABASE_ID

def _load_json_file(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"Error loading config file {path}: {e}")
        return {}

def _coerce_string_list(value, fallback):
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items if items else list(fallback)
    return list(fallback)

def load_config():
    global CATEGORIES, KEYWORDS, VAULT_PATH, WARMUP_MODELS, NOTION_TOKEN, NOTION_DATABASE_ID
    # Public defaults live in config.json. Personal/local overrides live in config.local.json.
    # Local settings take precedence and should stay out of git.
    data = _load_json_file(CONFIG_FILE)
    local_data = _load_json_file(LOCAL_CONFIG_FILE)
    if local_data:
        data.update(local_data)

    CATEGORIES = _coerce_string_list(data.get("categories"), DEFAULT_CATEGORIES)
    KEYWORDS = _coerce_string_list(data.get("keywords"), DEFAULT_KEYWORDS)
    VAULT_PATH = str(data.get("vault_path", "") or "").strip()
    WARMUP_MODELS = bool(data.get("warmup_models", DEFAULT_WARMUP_MODELS))
    NOTION_TOKEN = str(data.get("notion_token", DEFAULT_NOTION_TOKEN) or "")
    NOTION_DATABASE_ID = str(data.get("notion_database_id", DEFAULT_NOTION_DATABASE_ID) or "")

def save_config(
    categories,
    keywords,
    vault_path="",
    warmup_models=DEFAULT_WARMUP_MODELS,
    notion_token: Optional[str] = None,
    notion_database_id: Optional[str] = None,
):
    global CATEGORIES, KEYWORDS, VAULT_PATH, WARMUP_MODELS, NOTION_TOKEN, NOTION_DATABASE_ID
    CATEGORIES = _coerce_string_list(categories, DEFAULT_CATEGORIES)
    KEYWORDS = _coerce_string_list(keywords, DEFAULT_KEYWORDS)
    VAULT_PATH = vault_path
    WARMUP_MODELS = bool(warmup_models)
    if notion_token is not None:
        NOTION_TOKEN = notion_token
    if notion_database_id is not None:
        NOTION_DATABASE_ID = notion_database_id

    payload = {
        'categories': CATEGORIES,
        'keywords': KEYWORDS,
        'vault_path': VAULT_PATH,
        'warmup_models': WARMUP_MODELS,
        'notion_token': NOTION_TOKEN,
        'notion_database_id': NOTION_DATABASE_ID,
    }
    target_file = LOCAL_CONFIG_FILE or CONFIG_FILE
    parent = os.path.dirname(target_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target_file, 'w', encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

# Load on import
load_config()

# API Keys
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
