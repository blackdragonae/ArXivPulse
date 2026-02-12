import json
import os

CONFIG_FILE = "config.json"

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

def load_config():
    global CATEGORIES, KEYWORDS, VAULT_PATH, WARMUP_MODELS, NOTION_TOKEN, NOTION_DATABASE_ID
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                CATEGORIES = data.get('categories', DEFAULT_CATEGORIES)
                KEYWORDS = data.get('keywords', DEFAULT_KEYWORDS)
                VAULT_PATH = data.get('vault_path', "")
                WARMUP_MODELS = bool(data.get('warmup_models', DEFAULT_WARMUP_MODELS))
                NOTION_TOKEN = data.get('notion_token', DEFAULT_NOTION_TOKEN)
                NOTION_DATABASE_ID = data.get('notion_database_id', DEFAULT_NOTION_DATABASE_ID)
        except Exception as e:
            print(f"Error loading config: {e}")
            CATEGORIES = DEFAULT_CATEGORIES
            KEYWORDS = DEFAULT_KEYWORDS
            VAULT_PATH = ""
            WARMUP_MODELS = DEFAULT_WARMUP_MODELS
            NOTION_TOKEN = DEFAULT_NOTION_TOKEN
            NOTION_DATABASE_ID = DEFAULT_NOTION_DATABASE_ID
    else:
        CATEGORIES = DEFAULT_CATEGORIES
        KEYWORDS = DEFAULT_KEYWORDS
        VAULT_PATH = ""
        WARMUP_MODELS = DEFAULT_WARMUP_MODELS
        NOTION_TOKEN = DEFAULT_NOTION_TOKEN
        NOTION_DATABASE_ID = DEFAULT_NOTION_DATABASE_ID
        save_config(CATEGORIES, KEYWORDS, VAULT_PATH, WARMUP_MODELS, NOTION_TOKEN, NOTION_DATABASE_ID)

def save_config(
    categories,
    keywords,
    vault_path="",
    warmup_models=DEFAULT_WARMUP_MODELS,
    notion_token: str = None,
    notion_database_id: str = None,
):
    global CATEGORIES, KEYWORDS, VAULT_PATH, WARMUP_MODELS, NOTION_TOKEN, NOTION_DATABASE_ID
    CATEGORIES = categories
    KEYWORDS = keywords
    VAULT_PATH = vault_path
    WARMUP_MODELS = bool(warmup_models)
    if notion_token is not None:
        NOTION_TOKEN = notion_token
    if notion_database_id is not None:
        NOTION_DATABASE_ID = notion_database_id
    
    with open(CONFIG_FILE, 'w') as f:
        json.dump({
            'categories': CATEGORIES,
            'keywords': KEYWORDS,
            'vault_path': VAULT_PATH,
            'warmup_models': WARMUP_MODELS,
            'notion_token': NOTION_TOKEN,
            'notion_database_id': NOTION_DATABASE_ID,
        }, f, indent=2)

# Load on import
load_config()

# API Keys
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
