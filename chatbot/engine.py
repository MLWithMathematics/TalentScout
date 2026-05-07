"""
chatbot/engine.py — Conversation State Machine (v1.2)

Two-layer protection against off-topic responses:
  Layer 1 — Python guardrail (chatbot/guardrail.py):
             Intercepts message BEFORE the LLM sees it.
             Deterministic, zero-token, instant.
  Layer 2 — LLM system prompt (chatbot/prompts.py):
             Strict "interviewer only" persona baked into every API call.
             Catches edge cases the regex layer may miss.

Flow per message:
  user input
      │
      ▼
  exit keyword? ──yes──► FAREWELL (LLM generates goodbye)
      │no
      ▼
  guardrail.check_input()
      │off-topic ──────► return REDIRECT_RESPONSE (no LLM call)
      │on-topic
      ▼
  stage handler (CONSENT / INFO / TECH / WRAP_UP)
      │
      ▼
  LLM call (MASTER_SYSTEM_PROMPT + stage context)
      │
      ▼
  persist to DB → return response
"""

import json
import re
from typing import Any, Dict, Tuple

from chatbot.guardrail import check_input
from chatbot.llm_client import LLMClient
from chatbot.prompts import (
    MASTER_SYSTEM_PROMPT,
    get_question_generation_prompt,
    get_stage_prompt,
)
from chatbot.validator import validate_field
from config import EXIT_KEYWORDS, INFO_FIELDS
from data_management.database import CandidateDatabase


class ConversationEngine:
    """
    Orchestrates the full screening conversation lifecycle.

    Stage machine:
      CONSENT → GREETING → INFO_GATHERING → TECH_QUESTIONING → WRAP_UP / FAREWELL

    Every user message passes through:
      1. Exit keyword check  (Python — instant)
      2. Guardrail check     (Python — instant, no LLM cost)
      3. Stage handler       (Python logic + LLM call)
    """

    def __init__(self, provider: str):
        self._llm = LLMClient(provider)
        self._db  = CandidateDatabase()

    def switch_provider(self, provider: str) -> None:
        """Hot-swap LLM provider without losing session state."""
        self._llm = LLMClient(provider)

    # ── LLM call wrapper ─────────────────────────────────

    def _ask_llm(self, history: list, stage_ctx: str,
                 max_tokens: int = None) -> str:
        """Single wrapper so all LLM calls go through one point."""
        return self._llm.chat(
            MASTER_SYSTEM_PROMPT,
            history,
            stage_ctx,
            **({"max_tokens": max_tokens} if max_tokens else {}),
        )

    # ── Tech question generation ─────────────────────────

    def _generate_tech_questions(self, tech_stack: list,
                                 candidate_info: dict) -> list:
        """
        Generate the full technical question bank via LLM.
        Returns a flat list of question strings.
        Falls back to 3 generic questions if JSON parsing fails.
        """
        prompt = get_question_generation_prompt(tech_stack, candidate_info)
        raw    = self._llm.generate_questions(prompt)

        # Strip accidental markdown fences
        raw = re.sub(r"^```(?:json)?\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw)

        try:
            items = json.loads(raw)
            questions = [item["question"] for item in items if "question" in item]
            if questions:
                return questions
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Graceful fallback
        primary = tech_stack[0] if tech_stack else "your primary technology"
        return [
            f"Walk me through the most challenging system you built using "
            f"{primary}. What trade-offs did you make and why?",
            "Describe how you approached debugging a complex production issue. "
            "Take me through a real scenario you've faced.",
            "How do you ensure code quality and maintainability in a team environment?",
        ]

    # ── Exit detection ────────────────────────────────────

    def _is_exit(self, text: str) -> bool:
        return bool(set(text.lower().split()) & EXIT_KEYWORDS)

    # ── Field processing ──────────────────────────────────

    def _process_info_field(self, state: dict, user_input: str) -> dict:
        """
        Validate and persist the answer for the current info field.
        Advances to next field on success; sets validation_error on failure.
        """
        field    = state["current_field"]
        is_valid, result = validate_field(field, user_input)

        if is_valid:
            state["candidate_info"][field] = result
            state["validation_error"]      = None

            db_value = result if isinstance(result, list) else str(result)
            self._db.update_candidate(state["candidate_id"], field, db_value)

            idx = INFO_FIELDS.index(field)
            if idx + 1 < len(INFO_FIELDS):
                state["current_field"] = INFO_FIELDS[idx + 1]
            else:
                # All fields collected → generate questions
                stack = state["candidate_info"].get("tech_stack", [])
                if isinstance(stack, str):
                    stack = [stack]
                state["tech_questions"]  = self._generate_tech_questions(
                    stack, state["candidate_info"]
                )
                state["question_index"]  = 0
                state["stage"]           = "TECH_QUESTIONING"
        else:
            state["validation_error"] = result

        return state

    # ── Guardrail check ───────────────────────────────────

    def _is_off_topic(self, user_input: str,
                      stage: str) -> Tuple[bool, str]:
        """
        Run the Python pre-LLM guardrail.
        Returns (off_topic: bool, redirect_message: str).
        """
        on_topic, redirect = check_input(user_input, stage)
        return (not on_topic), redirect

    # ── Main message handler ──────────────────────────────

    def handle_message(self, user_input: str,
                       state: dict) -> Tuple[str, dict]:
        """
        Process one user turn.  Returns (response_text, updated_state).

        Called from app.py on every submission.
        """
        stage = state["stage"]

        # ── 1. Exit keyword (always first) ───────────────
        if self._is_exit(user_input) and stage not in ("CONSENT", "FAREWELL"):
            state["stage"] = "FAREWELL"
            state["chat_history"].append({"role": "user",      "content": user_input})
            response = self._ask_llm(state["chat_history"],
                                     get_stage_prompt("FAREWELL", state))
            state["chat_history"].append({"role": "assistant", "content": response})
            state["conversation_ended"] = True
            return response, state

        # ── 2. Python guardrail (before LLM) ─────────────
        # Skip for CONSENT — user may type anything as their consent answer
        if stage not in ("CONSENT", "FAREWELL", "WRAP_UP"):
            off_topic, redirect_msg = self._is_off_topic(user_input, stage)
            if off_topic:
                # Add exchange to history so LLM retains context
                state["chat_history"].append({"role": "user",      "content": user_input})
                state["chat_history"].append({"role": "assistant", "content": redirect_msg})
                return redirect_msg, state

        # ── 3. CONSENT ────────────────────────────────────
        if stage == "CONSENT":
            state["chat_history"].append({"role": "user", "content": user_input})
            lower   = user_input.strip().lower()
            agreed  = any(w in lower for w in
                          ("yes", "agree", "ok", "sure", "proceed",
                           "consent", "accept", "i do", "yep", "yeah"))
            declined= any(w in lower for w in
                          ("no", "decline", "refuse", "cancel", "nope"))

            if agreed:
                state["consent_given"] = True
                state["candidate_id"]  = self._db.create_candidate(consent=True)
                state["stage"]         = "GREETING"

            elif declined:
                msg = (
                    "Completely understood. Without your consent I can't proceed "
                    "with the screening, but you're welcome to reach out to our "
                    "human recruiters directly at **careers@talentscout.com**. "
                    "Your data has **not** been stored. Have a wonderful day! 👋"
                )
                state["chat_history"].append({"role": "assistant", "content": msg})
                state["conversation_ended"] = True
                return msg, state

            response = self._ask_llm(state["chat_history"],
                                     get_stage_prompt(state["stage"], state))
            state["chat_history"].append({"role": "assistant", "content": response})

            # ── Transition: GREETING → INFO_GATHERING ──────────────────────
            # The greeting LLM response ends with "What is your full name?".
            # We must move to INFO_GATHERING NOW so the very next user turn
            # (the candidate's name) is processed by _process_info_field
            # instead of falling through to the generic fallback which would
            # keep stage stuck as GREETING forever.
            if state["stage"] == "GREETING":
                state["stage"] = "INFO_GATHERING"

            return response, state

        # ── 4. INFO_GATHERING ─────────────────────────────
        if stage == "INFO_GATHERING":
            state = self._process_info_field(state, user_input)
            state["chat_history"].append({"role": "user", "content": user_input})

            # ── Validation guard: return error deterministically, no LLM ──
            # This guarantees email/phone/experience errors are ALWAYS shown
            # regardless of whether the LLM would honour the retry hint.
            if state["validation_error"]:
                error_msg = state["validation_error"]
                state["chat_history"].append({"role": "assistant", "content": error_msg})
                return error_msg, state

            response = self._ask_llm(state["chat_history"],
                                     get_stage_prompt(state["stage"], state))
            state["chat_history"].append({"role": "assistant", "content": response})
            return response, state

        # ── 5. TECH_QUESTIONING ───────────────────────────
        if stage == "TECH_QUESTIONING":
            q_idx     = state["question_index"]
            questions = state["tech_questions"]

            if "qa_log" not in state:
                state["qa_log"] = []

            # Log the answer to the current question
            if q_idx < len(questions):
                state["qa_log"].append({
                    "question": questions[q_idx],
                    "answer":   user_input,
                })
                self._db.update_qa_responses(state["candidate_id"],
                                             state["qa_log"])

            # Advance
            state["question_index"] += 1
            if state["question_index"] >= len(questions):
                state["stage"] = "WRAP_UP"

            state["chat_history"].append({"role": "user", "content": user_input})
            response = self._ask_llm(state["chat_history"],
                                     get_stage_prompt(state["stage"], state))
            state["chat_history"].append({"role": "assistant", "content": response})

            if state["stage"] == "WRAP_UP":
                state["conversation_ended"] = True

            return response, state

        # ── 6. WRAP_UP / FAREWELL ─────────────────────────
        if stage in ("WRAP_UP", "FAREWELL"):
            state["chat_history"].append({"role": "user", "content": user_input})
            response = self._ask_llm(state["chat_history"],
                                     get_stage_prompt("WRAP_UP", state))
            state["chat_history"].append({"role": "assistant", "content": response})
            state["conversation_ended"] = True
            return response, state

        # ── 7. Generic fallback ───────────────────────────
        state["chat_history"].append({"role": "user", "content": user_input})
        response = self._ask_llm(state["chat_history"],
                                 get_stage_prompt(stage, state))
        state["chat_history"].append({"role": "assistant", "content": response})
        return response, state


# ─────────────────────────────────────────────────────────
# Session state factory
# ─────────────────────────────────────────────────────────

def initialize_state() -> Dict[str, Any]:
    """Fresh session state for a new candidate. Called once on app load."""
    return {
        "stage":              "CONSENT",
        "candidate_id":       None,
        "consent_given":      False,
        "candidate_info":     {f: None for f in INFO_FIELDS},
        "current_field":      INFO_FIELDS[0],
        "tech_questions":     [],
        "question_index":     0,
        "qa_log":             [],
        "chat_history":       [],
        "validation_error":   None,
        "conversation_ended": False,
    }
