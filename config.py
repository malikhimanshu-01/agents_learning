# ─── Azure OpenAI Configuration ──────────────────────────────────────────────
# All secrets (key, endpoint) live in .env — only non-secret config here.
#
# AZURE_OPENAI_DEPLOYMENT options (must match your Azure deployment names):
#   "gpt-4o"          – Best balance of quality and speed
#   "gpt-4o-mini"     – Cheaper, still solid for most agents
#   "gpt-4.1"         – Latest GPT-4.1 (if deployed in your Azure resource)
#
# API_VERSION options:
#   "2024-12-01-preview"   – Latest preview (supports all features)
#   "2024-08-01-preview"   – Stable preview
# ─────────────────────────────────────────────────────────────────────────────

import os
from dotenv import load_dotenv

load_dotenv()

AZURE_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

# Token limits per agent role
TOKENS_STANDARD = 4096    # planner, evaluator
TOKENS_LARGE    = 8192    # architect, redesigner
TOKENS_ARM      = 16000   # arm_generator — ARM templates can be very large
