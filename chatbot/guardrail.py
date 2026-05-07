"""
chatbot/guardrail.py — Pre-LLM Input Guardrail (v1.3)

Intercepts user messages BEFORE they reach the LLM.

Layered check order (fastest first):
  1. Question-starter pre-check  — catches "What is X?" even at 3 words
  2. Short-answer bypass (≤ 2 words) — "Yes", "No", "5 years", "John Doe"
  3. Consent/farewell stage bypass  — accept anything
  4. Whitelist phrases              — legitimate screening answers
  5. Regex pattern match            — structured off-topic patterns
  6. Phrase-contains match          — assistant-mode triggers

Changelog v1.3:
  - Added QUESTION_STARTERS pre-check (runs before length bypass)
    Fixes: "What is TensorFlow?" (3 words) was hitting bypass ≤ 4 check
  - Lowered short-answer threshold from ≤ 4 → ≤ 2
    Keeps "John Doe", "5 years", "Yes", "No" passing
    Closes the window for 3-word questions slipping through
"""

import re
from typing import Tuple

# ─────────────────────────────────────────────────────────────────────
# QUESTION STARTERS  — runs FIRST, before the short-answer bypass
# If input begins with any of these, always treat as off-topic
# (unless a whitelist phrase saves it later)
# ─────────────────────────────────────────────────────────────────────
QUESTION_STARTERS = (
    "what is ",
    "what are ",
    "what was ",
    "what were ",
    "what does ",
    "what do ",
    "how does ",
    "how do ",
    "how is ",
    "how to ",
    "how can ",
    "how did ",
    "who is ",
    "who was ",
    "who are ",
    "who invented ",
    "who created ",
    "who founded ",
    "where is ",
    "where was ",
    "when was ",
    "when did ",
    "why is ",
    "why does ",
    "why do ",
    "can you explain ",
    "could you explain ",
    "please explain ",
    "explain ",
    "define ",
    "describe ",
    "tell me about ",
    "tell me what ",
    "teach me ",
    "show me how ",
    "write me ",
    "write a ",
    "create a ",
    "build me ",
    "give me an example ",
    "give me a list ",
    "list the ",
    "list all ",
    "compare ",
)

# ─────────────────────────────────────────────────────────────────────
# REGEX PATTERNS  — structured off-topic query patterns
# ─────────────────────────────────────────────────────────────────────
GENERAL_KNOWLEDGE_PATTERNS = [
    # "What is/are X"
    r"\bwhat (is|are|was|were) (a |an |the )?\w+",
    # "How does/do X work"
    r"\bhow (does|do|did) .{1,50} work\b",
    r"\bhow \w+ works\b",
    # Captain/president/CEO
    r"\bwho (is|was) (the )?(president|prime minister|king|queen|ceo|founder|inventor)\b",
    # Explain / define
    r"\bexplain (me |to me )?(what|how|the concept|the difference|the meaning)\b",
    r"\bdefine \w+",
    # Write code
    r"\bwrite\b.{0,30}\b(code|script|program|function|class|module|algorithm)\b",
    r"\bcreate\b.{0,30}\b(code|script|program|function|class|module|algorithm)\b",
    r"\bbuild\b.{0,20}\b(app|application|website|tool|program|script)\b",
    # Tell me about
    r"\btell me (a |about |the )?(joke|story|fact|history|difference|advantage|disadvantage)\b",
    # Who invented
    r"\bwho (invented|discovered|created|founded|built|made) \w+",
    # When was X
    r"\bwhen (was|did|is) .{2,} (born|invented|discovered|created|founded|happen|release)",
    # Where is X
    r"\bwhere (is|was|are) .{2,} (located|situated|found|born|from)\b",
    # How many/much
    r"\bhow (many|much|far|long|old|tall|big|small|fast)\b",
    # Calculate / convert
    r"\b(calculate|compute|solve|convert|translate|summarise|summarize)\b",
    # Weather / news
    r"\b(weather|temperature|forecast|news|stock price|exchange rate)\b",
    # Give example
    r"\bgive me (an |a )?example of\b",
    # List best/top
    r"\blist (all|the|some|top|best|common) \w+",
    r"\bwhat are the (best|top|common|popular|latest|new|famous)\b",
    # How to install/use/set up
    r"\bhow to (install|use|set up|configure|deploy|run|start|build)\b",
    # pros and cons
    r"\b(pros and cons|advantages and disadvantages|difference between)\b",
    # Tutorial / introduction / overview
    r"\b(tutorial|introduction to|overview of|guide to|crash course)\b",
]

# ─────────────────────────────────────────────────────────────────────
# PHRASE LIST  — assistant-mode trigger phrases
# ─────────────────────────────────────────────────────────────────────
GENERAL_ASSISTANT_PHRASES = [
    "help me with",
    "can you help me understand",
    "i need help with",
    "do you know about",
    "what do you think about",
    "your opinion on",
    "compare and contrast",
    "show me how to",
    "i want to learn",
    "how to become",
    "career advice",
    "what should i learn",
    "which is better",
    "best way to",
    "can you code",
    "can you write",
    "can you debug",
    "fix my code",
    "review my code",
    "suggest me",
    "recommend me",
    "what language should",
    "which framework",
]

# ─────────────────────────────────────────────────────────────────────
# WHITELIST  — screening-answer phrases that override blocking
# ─────────────────────────────────────────────────────────────────────
SCREENING_SAFE_PHRASES = [
    "my experience",
    "i have worked",
    "i have used",
    "i've worked",
    "i've used",
    "in my previous",
    "in my current",
    "at my company",
    "we used",
    "we built",
    "i built",
    "i developed",
    "i worked on",
    "i designed",
    "i implemented",
    "i managed",
    "our team",
    "production system",
    "my stack",
    "i prefer",
    "for example",
    "years of experience",
    "i am applying",
    "i am interested",
    "next steps",
    "when will i hear",
    "gdpr",
    "delete my data",
    "access my data",
    "my rights",
    "in my opinion",
    "from my experience",
    "in my last",
    "at my previous",
]

# ─────────────────────────────────────────────────────────────────────
# CANNED REDIRECT (no LLM call)
# ─────────────────────────────────────────────────────────────────────
REDIRECT_RESPONSE = (
    "I'm set up **only** to conduct your recruitment screening — "
    "I'm not able to answer general questions or explain topics.\n\n"
    "Let's continue with your screening! 😊 "
    "Please respond to the question I asked."
)


# ─────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────

def check_input(user_input: str, stage: str) -> Tuple[bool, str]:
    """
    Classify user input as on-topic (True) or off-topic (False).

    Layered checks — fastest / most precise first:
      1. Question starter pre-check  (catches "What is X?" at any length)
      2. Short-answer bypass ≤ 2 words
      3. Stage bypass (CONSENT / FAREWELL / WRAP_UP)
      4. Whitelist phrases
      5. Regex patterns
      6. Assistant-mode phrases

    Returns:
        (True,  "")            → on-topic, proceed normally
        (False, redirect_msg)  → off-topic, return redirect immediately
    """
    text_lower = user_input.strip().lower()
    words      = text_lower.split()

    # ── Step 1: Question-starter pre-check ──────────────────────────
    # Run BEFORE the length bypass so "What is X?" (3 words) is caught.
    # Only overridden if a whitelist phrase appears in the message.
    for starter in QUESTION_STARTERS:
        if text_lower.startswith(starter):
            # Check whitelist override first
            for safe in SCREENING_SAFE_PHRASES:
                if safe in text_lower:
                    return True, ""
            # Not whitelisted — block regardless of length
            if stage not in ("CONSENT", "FAREWELL", "WRAP_UP"):
                return False, REDIRECT_RESPONSE
            break   # CONSENT/FAREWELL/WRAP_UP stages: continue to allow

    # ── Step 2: Short-answer bypass (≤ 2 words) ──────────────────────
    # Covers: "Yes", "No", "5", "5 years", "John Doe", "Python"
    if len(words) <= 2:
        return True, ""

    # ── Step 3: Stage bypass ─────────────────────────────────────────
    if stage in ("CONSENT", "FAREWELL", "WRAP_UP"):
        return True, ""

    # ── Step 4: Whitelist override ───────────────────────────────────
    for safe in SCREENING_SAFE_PHRASES:
        if safe in text_lower:
            return True, ""

    # ── Step 5: Regex patterns ───────────────────────────────────────
    for pattern in GENERAL_KNOWLEDGE_PATTERNS:
        if re.search(pattern, text_lower):
            return False, REDIRECT_RESPONSE

    # ── Step 6: Assistant-mode phrase check ─────────────────────────
    for phrase in GENERAL_ASSISTANT_PHRASES:
        if phrase in text_lower:
            return False, REDIRECT_RESPONSE

    return True, ""
