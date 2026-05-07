"""
chatbot/validator.py — Candidate Input Validation

All user-supplied values are validated BEFORE reaching the LLM or database.
This prevents:
  - Invalid data being stored (garbage email/phone)
  - Unnecessary LLM calls for clearly malformed input
  - GDPR accuracy principle violations (Art. 5(1)(d))

Each validator returns (is_valid: bool, result_or_error_message: str | list).
"""

import re
from typing import Tuple, Union


# ─────────────────────────────────────────────────────────
# Individual validators
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


def validate_phone(value: str) -> Tuple[bool, str]:
    """
    Validate phone number (international-friendly).
    Accepts 7–15 digits; allows +, spaces, dashes, parentheses.
    """
    cleaned = re.sub(r"[\s\-\(\)\+]", "", value.strip())
    if cleaned.isdigit() and 7 <= len(cleaned) <= 15:
        return True, value.strip()
    return False, (
        "Please enter a valid phone number (7–15 digits). "
        "Example: **+91 98765 43210** or **+1-555-123-4567**."
    )


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


def validate_tech_stack(value: str) -> Tuple[bool, list]:
    """
    Parse a comma-/newline-/semicolon-separated tech stack into a clean list.
    Requires at least one valid technology.
    """
    # Split on commas, semicolons, newlines, or " and "
    parts = re.split(r"[,;\n]+|\s+and\s+", value, flags=re.IGNORECASE)
    techs = [t.strip() for t in parts if t.strip() and len(t.strip()) >= 1]

    if not techs:
        return False, (
            "Please list at least one technology. "
            "You can separate them with commas — e.g. **Python, FastAPI, PostgreSQL, Docker**."
        )

    # Remove duplicates while preserving order
    seen, unique = set(), []
    for t in techs:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return True, unique


def validate_free_text(field: str, value: str,
                       min_len: int = 2) -> Tuple[bool, str]:
    """
    Generic validator for free-text fields (name, position, location).
    Ensures the input is non-empty and meets a minimum meaningful length.
    """
    cleaned = value.strip()
    if len(cleaned) >= min_len:
        return True, cleaned
    label = field.replace("_", " ").title()
    return False, f"Please provide your {label} (at least {min_len} characters)."


# ─────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────

def validate_field(field: str, value: str) -> Tuple[bool, Union[str, list]]:
    """
    Route to the correct validator for a given field name.

    Args:
        field: One of INFO_FIELDS (e.g. "email", "tech_stack")
        value: Raw string from user input

    Returns:
        (True, cleaned_value)  if valid
        (False, error_message) if invalid
    """
    dispatch = {
        "email": validate_email,
        "phone": validate_phone,
        "years_experience": validate_years_experience,
        "tech_stack": validate_tech_stack,
    }

    if field in dispatch:
        return dispatch[field](value)

    # Free-text fields: full_name, desired_position, current_location
    min_lengths = {
        "full_name": 2,
        "desired_position": 3,
        "current_location": 2,
    }
    return validate_free_text(field, value, min_len=min_lengths.get(field, 2))
