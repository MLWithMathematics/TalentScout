"""
chatbot/validator.py — Candidate Input Validation  (v2.0)

All user-supplied values are validated BEFORE reaching the LLM or database.

v2.0 changes:
  - validate_phone    : Country-code-aware rules for 40+ countries / top-10 economies.
                        +91 + 5 digits now correctly rejected (needs exactly 10 sub-digits).
  - validate_tech_stack: Rejects vague inputs ("IDK", "N/A", etc.) using a
                        known-tech keyword set; proprietary/niche tech still accepted.
  - validate_position : NEW — dedicated validator for desired_position field.
                        Rejects "IDK", "Not sure", "anything", etc.
  - validate_location : NEW — cross-checks city+country against OpenStreetMap
                        Nominatim API; falls back gracefully if network is down.
  - validate_field    : Updated dispatch includes desired_position + current_location.

Each validator returns (is_valid: bool, result_or_error_message: str | list).
"""

import json
import re
import urllib.parse
import urllib.request
from typing import Tuple, Union


# ─────────────────────────────────────────────────────────
# SHARED VAGUE-RESPONSE BLOCK-LIST
# ─────────────────────────────────────────────────────────
# Exact-match (lowercased, stripped) inputs that are never valid answers.

VAGUE_RESPONSES: set = {
    "idk", "i don't know", "i dont know", "not sure", "no idea",
    "dunno", "n/a", "na", "none", "nil", "nothing", "unknown",
    "skip", "pass", "unsure", "?", "??", "...", "nope", "nah",
    "doesn't matter", "doesnt matter", "whatever", "undecided",
    "not decided", "not applicable", "tbd", "tba",
}

# Broader set used only for position (includes "open"/"flexible" etc.)
VAGUE_POSITION_RESPONSES: set = VAGUE_RESPONSES | {
    "any", "anything", "everything", "all",
    "open", "any role", "any position", "flexible",
    "open to anything", "open to anything", "no preference",
}


# ─────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────

def validate_email(value: str) -> Tuple[bool, str]:
    """
    Validate email format using RFC 5322 simplified regex.
    Returns (True, normalised_email) or (False, error_message).
    """
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    cleaned = value.strip()
    if re.match(pattern, cleaned):
        return True, cleaned.lower()
    return False, (
        "That doesn't look like a valid email address. "
        "Please enter something like **john.doe@example.com**."
    )


# ─────────────────────────────────────────────────────────
# PHONE — country-code-aware (top-10 economies + 40 countries)
# ─────────────────────────────────────────────────────────

# Maps country_code_string → (country_name, min_subscriber_digits, max_subscriber_digits)
# "subscriber digits" = digits AFTER the country code (so +91 XXXXXXXXXX = 10 sub-digits).
# Ordered longest-code-first for correct prefix matching.
COUNTRY_PHONE_RULES: dict = {
    # ── 3-digit codes (checked first) ────────────────────
    "880": ("Bangladesh",    10, 10),
    "966": ("Saudi Arabia",   9,  9),
    "971": ("UAE",            9,  9),
    "972": ("Israel",         8,  9),
    "973": ("Bahrain",        8,  8),
    "974": ("Qatar",          8,  8),
    "977": ("Nepal",          9, 10),
    # ── 2-digit codes ────────────────────────────────────
    "20":  ("Egypt",         10, 10),
    "27":  ("South Africa",   9,  9),
    "30":  ("Greece",        10, 10),
    "31":  ("Netherlands",    9,  9),
    "32":  ("Belgium",        8,  9),
    "33":  ("France",         9,  9),
    "34":  ("Spain",          9,  9),
    "39":  ("Italy",          9, 11),
    "40":  ("Romania",        9,  9),
    "41":  ("Switzerland",    9,  9),
    "43":  ("Austria",        7, 13),
    "44":  ("UK",            10, 10),
    "45":  ("Denmark",        8,  8),
    "46":  ("Sweden",         7,  9),
    "47":  ("Norway",         8,  8),
    "48":  ("Poland",         9,  9),
    "49":  ("Germany",       10, 12),
    "52":  ("Mexico",        10, 10),
    "54":  ("Argentina",     10, 11),
    "55":  ("Brazil",        10, 11),
    "56":  ("Chile",          9,  9),
    "57":  ("Colombia",      10, 10),
    "60":  ("Malaysia",       7,  9),
    "61":  ("Australia",      9,  9),
    "62":  ("Indonesia",      7, 11),
    "63":  ("Philippines",   10, 10),
    "64":  ("New Zealand",    8,  9),
    "65":  ("Singapore",      8,  8),
    "66":  ("Thailand",       8,  9),
    "81":  ("Japan",         10, 10),
    "82":  ("South Korea",   10, 11),
    "84":  ("Vietnam",        9, 10),
    "86":  ("China",         11, 11),
    "90":  ("Turkey",        10, 10),
    "91":  ("India",         10, 10),
    "92":  ("Pakistan",      10, 10),
    "94":  ("Sri Lanka",      9,  9),
    "95":  ("Myanmar",        7,  9),
    # ── 1-digit codes (checked last) ─────────────────────
    "1":   ("USA / Canada",  10, 10),
    "7":   ("Russia",        10, 10),
}


def validate_phone(value: str) -> Tuple[bool, str]:
    """
    Validate phone number with country-code-aware rules for 40+ countries.

    Behaviour:
      • Strips spaces, dashes, parentheses, dots, slashes before counting.
      • If number starts with '+':
          - Match longest known country code (3 → 2 → 1 digit).
          - Validate subscriber-digit count against that country's rule.
          - Unknown '+' prefix  →  accept if total 7–15 digits (ITU E.164).
      • No '+':
          - Generic 7–15 digit acceptance with a hint to include country code.

    Example failures caught:
      +91 12345        →  India needs 10 sub-digits; 5 provided  → REJECTED
      +1 5551234       →  USA needs 10 sub-digits; 7 provided    → REJECTED
      +86 1234567      →  China needs 11 sub-digits; 7 provided  → REJECTED
    """
    raw = value.strip()
    # Remove all formatting except the leading +
    stripped = re.sub(r"[\s\-\(\)\.\/ ]", "", raw)

    has_plus   = stripped.startswith("+")
    digits_str = stripped.lstrip("+")

    # Must be all digits after stripping the +
    if not digits_str or not digits_str.isdigit():
        return False, (
            "Please enter a valid phone number containing only digits. "
            "Example: **+91 98765 43210** or **+1 555 123 4567**."
        )

    total = len(digits_str)

    if has_plus:
        # Check 3-digit codes first, then 2-digit, then 1-digit
        for cc_len in (3, 2, 1):
            cc = digits_str[:cc_len]
            if cc in COUNTRY_PHONE_RULES:
                country, sub_min, sub_max = COUNTRY_PHONE_RULES[cc]
                sub_count = total - cc_len  # subscriber digit count

                if sub_min <= sub_count <= sub_max:
                    return True, raw  # ✓ valid

                # Wrong length → informative rejection
                expected_range = (
                    f"{sub_min} digits" if sub_min == sub_max
                    else f"{sub_min}–{sub_max} digits"
                )
                example_sub = "X" * sub_min
                # Format example in blocks of 5
                example_fmt = " ".join(
                    example_sub[i:i+5] for i in range(0, len(example_sub), 5)
                )
                return False, (
                    f"For **{country} (+{cc})**, the number after the country code "
                    f"must be **{expected_range}**, but you entered **{sub_count}**.\n"
                    f"Example: **+{cc} {example_fmt}**"
                )

        # Unknown country code with + — apply ITU E.164 range
        if 7 <= total <= 15:
            return True, raw
        return False, (
            f"A number with a country code should have **7–15 digits** total "
            f"(you entered {total}). Example: **+1 555 123 4567**."
        )

    else:
        # No country code — generic validation
        if 7 <= total <= 15:
            return True, raw
        return False, (
            "Please enter a valid phone number (**7–15 digits**). "
            "We recommend including your **country code** — "
            "e.g. **+91 98765 43210** or **+1 555 123 4567**."
        )


# ─────────────────────────────────────────────────────────
# YEARS OF EXPERIENCE
# ─────────────────────────────────────────────────────────

def validate_years_experience(value: str) -> Tuple[bool, str]:
    """
    Validate years of experience as a non-negative number ≤ 50.
    Accepts "3", "3.5", "3 years", "less than 1", "fresher" → 0.
    """
    lower = value.strip().lower()

    # Handle common fresher/intern terms
    if any(kw in lower for kw in ("fresher", "intern", "no experience", "less than 1")):
        return True, "0"

    # Try to extract first numeric value from the string
    match = re.search(r"\d+\.?\d*", value)
    if match:
        years = float(match.group())
        if 0 <= years <= 50:
            return True, str(years)

    return False, (
        "Please enter your years of professional experience as a number. "
        "Examples: **0**, **2**, **3.5**, **10**."
    )


# ─────────────────────────────────────────────────────────
# TECH STACK — known-keyword set for vague-input detection
# ─────────────────────────────────────────────────────────

KNOWN_TECH_KEYWORDS: set = {
    # Languages
    "python", "javascript", "typescript", "java", "c", "c++", "c#", "csharp",
    "go", "golang", "rust", "ruby", "php", "swift", "kotlin", "scala", "r",
    "matlab", "dart", "lua", "perl", "haskell", "elixir", "erlang", "clojure",
    "f#", "objective-c", "bash", "shell", "powershell", "groovy", "cobol",
    "fortran", "assembly", "solidity", "julia", "zig", "nim",
    # Frontend frameworks & tools
    "react", "angular", "vue", "vuejs", "nextjs", "nuxt", "svelte",
    "jquery", "bootstrap", "tailwind", "css", "html", "html5", "css3",
    "redux", "mobx", "gatsby", "vite", "webpack", "babel", "rollup",
    "storybook", "ember", "alpinejs", "htmx", "lit", "solid",
    # Backend frameworks
    "django", "flask", "fastapi", "spring", "springboot", "express", "expressjs",
    "nestjs", "laravel", "rails", "asp.net", ".net", "gin", "echo", "fiber",
    "actix", "axum", "phoenix", "sinatra", "hapi", "koa", "fastify",
    "sails", "adonis", "symfony", "codeigniter", "lumen", "slim",
    # Databases
    "postgresql", "postgres", "mysql", "mariadb", "sqlite", "mongodb", "redis",
    "elasticsearch", "cassandra", "dynamodb", "firebase", "firestore",
    "supabase", "cockroachdb", "clickhouse", "timescaledb", "neo4j",
    "couchdb", "influxdb", "oracle", "mssql", "sqlserver", "bigquery",
    "snowflake", "redshift", "pinecone", "weaviate", "chroma", "qdrant",
    # Cloud platforms
    "aws", "azure", "gcp", "digitalocean", "heroku", "vercel", "netlify",
    "cloudflare", "linode", "vultr", "railway", "render",
    # DevOps & infra
    "docker", "kubernetes", "k8s", "terraform", "ansible", "jenkins",
    "helm", "argocd", "prometheus", "grafana", "nginx", "apache",
    "caddy", "traefik", "vault", "consul", "pulumi", "chef", "puppet",
    "vagrant", "packer", "github actions", "gitlab ci", "circleci",
    "travis ci", "datadog", "newrelic", "elk", "splunk",
    # Mobile
    "react native", "flutter", "ios", "android", "ionic", "xamarin",
    "expo", "capacitor", "cordova", "swiftui", "jetpack",
    # ML / Data / AI
    "tensorflow", "pytorch", "scikit-learn", "sklearn", "keras", "opencv",
    "pandas", "numpy", "scipy", "matplotlib", "seaborn", "xgboost",
    "lightgbm", "spark", "kafka", "airflow", "mlflow", "langchain",
    "openai", "transformers", "dbt", "prefect", "dagster", "ray",
    # APIs & messaging
    "graphql", "rest", "grpc", "websocket", "rabbitmq", "celery",
    "oauth", "jwt", "openapi", "swagger", "protobuf", "mqtt", "nats",
    # Testing
    "pytest", "jest", "mocha", "cypress", "selenium", "playwright",
    "junit", "testng", "rspec", "vitest", "locust",
    # General tools
    "git", "github", "gitlab", "bitbucket", "linux", "unix",
    "memcached", "solr", "hadoop", "flink",
}


def validate_tech_stack(value: str) -> Tuple[bool, Union[list, str]]:
    """
    Parse a comma/semicolon/newline-separated tech stack into a clean list.

    Rejects:
      - Single vague responses ("IDK", "Not sure", "N/A", etc.)
      - Lists where every token is a vague word
      - Single 1–3 char tokens that are not in KNOWN_TECH_KEYWORDS

    Accepts:
      - Any list containing ≥ 1 non-vague, non-empty token.
      - Proprietary/niche tech not in KNOWN_TECH_KEYWORDS is accepted
        as long as the response is not entirely composed of vague words.
    """
    cleaned = value.strip()

    # ── Vague-entire-response check ──────────────────────
    if cleaned.lower() in VAGUE_RESPONSES:
        return False, (
            "Please list the actual technologies you work with — not just "
            "\"IDK\" or \"N/A\".\n\n"
            "For example: **Python, Django, PostgreSQL, Docker, AWS**\n"
            "Include your programming languages, frameworks, databases, "
            "cloud platforms, and tools."
        )

    # ── Split into individual tech tokens ────────────────
    parts = re.split(r"[,;\n]+|\s+and\s+", cleaned, flags=re.IGNORECASE)
    techs = [t.strip() for t in parts if t.strip()]

    if not techs:
        return False, (
            "Please list at least one technology. "
            "You can separate them with commas — "
            "e.g. **Python, FastAPI, PostgreSQL, Docker**."
        )

    # ── Filter out vague tokens ──────────────────────────
    valid_techs = [t for t in techs if t.lower() not in VAGUE_RESPONSES]

    if not valid_techs:
        return False, (
            "Please provide actual technology names, not just "
            "\"IDK\" or \"N/A\". "
            "Example: **Python, React, MongoDB, AWS**."
        )

    # ── Single very-short unknown token check ────────────
    # e.g. a single "XYZ" (3 chars, not in known set) is suspicious
    if len(valid_techs) == 1:
        sole = valid_techs[0].lower()
        if len(sole) <= 3 and sole not in KNOWN_TECH_KEYWORDS:
            return False, (
                f"**\"{valid_techs[0]}\"** doesn't look like a recognised technology.\n"
                "Please list your actual tech stack — for example:\n"
                "**Python, FastAPI, PostgreSQL, Docker, AWS, React**"
            )

    # ── De-duplicate (preserve order) ────────────────────
    seen: set = set()
    unique: list = []
    for t in valid_techs:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)

    return True, unique


# ─────────────────────────────────────────────────────────
# POSITION — rejects vague / unknown responses
# ─────────────────────────────────────────────────────────

def validate_position(value: str) -> Tuple[bool, str]:
    """
    Validate desired_position field.

    Rejects vague/unknown responses such as "IDK", "anything", "not sure".
    Accepts any meaningful tech role name (must contain at least one tech-related keyword).
    """
    cleaned = value.strip()
    lower   = cleaned.lower()

    if lower in VAGUE_POSITION_RESPONSES:
        return False, (
            "Please tell me the **specific role(s)** you're applying for. "
            "For example:\n"
            "**Backend Engineer**, **ML Engineer**, **DevOps Engineer**, "
            "**Full Stack Developer**, **Data Scientist**, **Android Developer**, "
            "**QA Engineer**, **Cloud Architect** …\n\n"
            "If you're interested in multiple roles, list them separated by commas."
        )

    if len(cleaned) < 3:
        return False, (
            "Please provide a valid position name (at least 3 characters). "
            "For example: **Backend Engineer** or **Data Scientist**."
        )

    # Basic heuristic to ensure it's an IT/Tech related role
    tech_role_keywords = {
        "engineer", "developer", "scientist", "analyst", "architect", "manager", 
        "admin", "devops", "qa", "designer", "programmer", "lead", "specialist", 
        "frontend", "backend", "fullstack", "full stack", "software", "data", "ml", "ai", "cloud"
    }
    
    if not any(kw in lower for kw in tech_role_keywords):
        return False, (
            "That doesn't look like a standard technology role. "
            "Please provide a valid IT/Tech position. "
            "For example: **Backend Engineer**, **Data Analyst**, or **Frontend Developer**."
        )

    return True, cleaned


# ─────────────────────────────────────────────────────────
# LOCATION — Nominatim API cross-check
# ─────────────────────────────────────────────────────────

def validate_location(value: str) -> Tuple[bool, str]:
    """
    Validate current_location against OpenStreetMap Nominatim.

    Rules:
      1. Reject vague responses.
      2. Require "City, Country" format (comma as separator).
      3. Call Nominatim to confirm the location exists.
      4. If API is unreachable, fall back to format-only acceptance.
    """
    cleaned = value.strip()
    lower   = cleaned.lower()

    # ── Vague check ──────────────────────────────────────
    if lower in VAGUE_RESPONSES:
        return False, (
            "Please provide your current city and country. "
            "Example: **Mumbai, India** or **Berlin, Germany**."
        )

    if len(cleaned) < 3:
        return False, (
            "Please provide your city and country — "
            "e.g. **New York, USA** or **Bangalore, India**."
        )

    # ── City + Country format check ──────────────────────
    if "," not in cleaned:
        # Give a targeted hint using their input as the city
        city_guess = cleaned.split()[0].capitalize() if cleaned else "YourCity"
        return False, (
            "Please provide your location as **City, Country**.\n"
            f"For example: **{city_guess}, India** or **{city_guess}, Germany**."
        )

    # ── Nominatim API call ───────────────────────────────
    try:
        query = urllib.parse.quote(cleaned)
        url   = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={query}&format=json&limit=1&addressdetails=1"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "TalentScout-HiringAssistant/2.0 (recruitment-bot)"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data:
            return True, cleaned     # ✓ Location verified

        return False, (
            f"I couldn't find **\"{cleaned}\"** on the map.\n"
            "Please double-check the spelling and use **City, Country** format — "
            "e.g. **Mumbai, India** or **Berlin, Germany**."
        )

    except Exception:
        # Network / timeout — fail open (accept with format already verified)
        return True, cleaned


# ─────────────────────────────────────────────────────────
# FREE TEXT (name only — no dedicated validator)
# ─────────────────────────────────────────────────────────

def validate_free_text(field: str, value: str,
                       min_len: int = 2) -> Tuple[bool, str]:
    """Generic validator for simple free-text fields (currently: full_name)."""
    cleaned = value.strip()
    if len(cleaned) >= min_len:
        return True, cleaned
    label = field.replace("_", " ").title()
    return False, f"Please provide your {label} (at least {min_len} characters)."


# ─────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────

def validate_field(field: str, value: str) -> Tuple[bool, Union[str, list]]:
    """
    Route to the correct validator for a given field name.

    Args:
        field: One of INFO_FIELDS (e.g. "email", "tech_stack")
        value: Raw string from user input

    Returns:
        (True,  cleaned_value)  if valid
        (False, error_message)  if invalid
    """
    dispatch = {
        "email":            validate_email,
        "phone":            validate_phone,
        "years_experience": validate_years_experience,
        "tech_stack":       validate_tech_stack,
        "desired_position": validate_position,
        "current_location": validate_location,
    }

    if field in dispatch:
        return dispatch[field](value)

    # Remaining free-text field: full_name
    min_lengths = {"full_name": 2}
    return validate_free_text(field, value, min_len=min_lengths.get(field, 2))
