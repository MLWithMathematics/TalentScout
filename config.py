"""
config.py — TalentScout Hiring Assistant Configuration
All application-wide constants, paths, and settings live here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────
# API CONFIGURATION — Multi-Provider
# ─────────────────────────────────────────────────────────

# Provider API keys — set whichever you have in .env
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY: str    = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY: str      = os.getenv("GROQ_API_KEY", "")

# Per-provider model names
PROVIDER_MODELS = {
    "Claude (Anthropic)":   "claude-sonnet-4-20250514",
    "Gemini 2.5 Flash":     "gemini-2.5-flash-preview-04-17",
    "Groq (Llama-3.3-70b)": "llama-3.3-70b-versatile",
}

DEFAULT_PROVIDER: str  = "Claude (Anthropic)"
MAX_TOKENS: int        = 1024   # Per LLM response
QA_GEN_MAX_TOKENS: int = 2000   # For question generation

# ─────────────────────────────────────────────────────────
# APPLICATION META
# ─────────────────────────────────────────────────────────
APP_TITLE: str   = "TalentScout Hiring Assistant"
APP_VERSION: str = "1.1.0"
COMPANY_NAME: str = "TalentScout Recruitment Agency"

# ─────────────────────────────────────────────────────────
# DATA STORAGE PATHS
# ─────────────────────────────────────────────────────────
DATA_DIR: Path       = Path("data")
DB_PATH: Path        = DATA_DIR / "talentscout.db"
KEY_PATH: Path       = DATA_DIR / ".encryption_key"
AUDIT_LOG_PATH: Path = DATA_DIR / "audit_log.json"

# ─────────────────────────────────────────────────────────
# GDPR & COMPLIANCE SETTINGS
# ─────────────────────────────────────────────────────────
DATA_RETENTION_DAYS: int         = 90
GDPR_CONTACT_EMAIL: str          = "dpo@talentscout.com"
GDPR_REQUEST_FULFILLMENT_DAYS: int = 30

# ─────────────────────────────────────────────────────────
# CONVERSATION FLOW
# ─────────────────────────────────────────────────────────
STAGES = [
    "CONSENT",
    "GREETING",
    "INFO_GATHERING",
    "TECH_QUESTIONING",
    "WRAP_UP",
    "FAREWELL",
]

EXIT_KEYWORDS = {"bye", "quit", "exit", "goodbye", "end", "stop", "done"}

# ─────────────────────────────────────────────────────────
# INFORMATION FIELDS (collected in order)
# ─────────────────────────────────────────────────────────
INFO_FIELDS = [
    "full_name",
    "email",
    "phone",
    "years_experience",
    "desired_position",
    "current_location",
    "tech_stack",
]

INFO_FIELD_LABELS = {
    "full_name":        "Full Name",
    "email":            "Email Address",
    "phone":            "Phone Number",
    "years_experience": "Years of Experience",
    "desired_position": "Desired Position(s)",
    "current_location": "Current Location",
    "tech_stack":       "Tech Stack (languages, frameworks, databases, tools)",
}

# Fields containing PII — encrypted at rest
PII_FIELDS = {"full_name", "email", "phone"}
