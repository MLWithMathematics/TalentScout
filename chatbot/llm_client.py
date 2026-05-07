"""
chatbot/llm_client.py — Unified Multi-Provider LLM Client

Wraps Claude (Anthropic), Gemini 2.5 Flash (Google), and Groq (Llama-3)
behind a single interface so the rest of the app never cares which model
is active. Provider is selected at runtime via the Streamlit sidebar.

Supported providers
-------------------
Provider Name            | SDK used              | Key env var
-------------------------|-----------------------|--------------------
Claude (Anthropic)       | anthropic             | ANTHROPIC_API_KEY
Gemini 2.5 Flash         | google-genai          | GEMINI_API_KEY
Groq (Llama-3.3-70b)     | groq                  | GROQ_API_KEY

Both `chat()` and `generate_questions()` accept the same arguments
regardless of provider — all translation happens inside this module.
"""

from __future__ import annotations

from typing import List, Dict

from config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    PROVIDER_MODELS,
    MAX_TOKENS,
    QA_GEN_MAX_TOKENS,
)


# ─────────────────────────────────────────────────────────
# Provider availability check
# ─────────────────────────────────────────────────────────

def available_providers() -> List[str]:
    """
    Return a list of providers whose API key is set in the environment.
    Used by the Streamlit sidebar to show only usable options.
    """
    providers = []
    if ANTHROPIC_API_KEY:
        providers.append("Claude (Anthropic)")
    if GEMINI_API_KEY:
        providers.append("Gemini 2.5 Flash")
    if GROQ_API_KEY:
        providers.append("Groq (Llama-3.3-70b)")
    return providers


# ─────────────────────────────────────────────────────────
# Unified client
# ─────────────────────────────────────────────────────────

class LLMClient:
    """
    Single interface for all three LLM providers.

    Usage:
        client = LLMClient(provider="Gemini 2.5 Flash")
        reply  = client.chat(system_prompt, history, stage_context)
        qs     = client.generate_questions(prompt_text)
    """

    def __init__(self, provider: str):
        """
        Initialise the correct SDK client for the chosen provider.

        Args:
            provider: One of the keys in PROVIDER_MODELS
        """
        self.provider = provider
        self.model    = PROVIDER_MODELS[provider]
        self._client  = None   # lazy-initialised below

        if provider == "Claude (Anthropic)":
            import anthropic
            self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        elif provider == "Gemini 2.5 Flash":
            from google import genai
            self._client = genai.Client(api_key=GEMINI_API_KEY)

        elif provider == "Groq (Llama-3.3-70b)":
            from groq import Groq
            self._client = Groq(api_key=GROQ_API_KEY)

        else:
            raise ValueError(f"Unknown provider: {provider}")

    # ── Internal per-provider callers ────────────────────

    def _chat_claude(self, system: str,
                     messages: List[Dict], max_tokens: int) -> str:
        """Call Claude via the Anthropic messages API."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return response.content[0].text.strip()

    def _chat_gemini(self, system: str,
                     messages: List[Dict], max_tokens: int) -> str:
        """
        Call Gemini via google-genai.
        Gemini uses a 'contents' list; system instruction is a separate field.
        We convert the OpenAI-style message list to Gemini's format.
        """
        from google.genai import types

        # Convert {role, content} → Gemini Content objects
        # Gemini roles: "user" | "model"  (no "assistant")
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part(text=msg["content"])],
                )
            )

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=0.7,
        )

        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return response.text.strip()

    def _chat_groq(self, system: str,
                   messages: List[Dict], max_tokens: int) -> str:
        """
        Call Groq via its OpenAI-compatible SDK.
        Prepend system message to the messages list.
        """
        groq_messages = [{"role": "system", "content": system}] + messages
        response = self._client.chat.completions.create(
            model=self.model,
            messages=groq_messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()

    # ── Public API ───────────────────────────────────────

    def chat(self, system: str, messages: List[Dict],
             stage_context: str, max_tokens: int = MAX_TOKENS) -> str:
        """
        Send a chat turn to the active provider.

        Args:
            system:        Master system prompt (GDPR guardrails etc.)
            messages:      Rolling conversation history [{role, content}]
            stage_context: Current stage instruction block (appended to system)
            max_tokens:    Token budget for this response

        Returns:
            Assistant reply as a plain string
        """
        combined_system = system + "\n\n" + stage_context

        if self.provider == "Claude (Anthropic)":
            return self._chat_claude(combined_system, messages, max_tokens)
        elif self.provider == "Gemini 2.5 Flash":
            return self._chat_gemini(combined_system, messages, max_tokens)
        elif self.provider == "Groq (Llama-3.3-70b)":
            return self._chat_groq(combined_system, messages, max_tokens)

    def generate_questions(self, prompt: str) -> str:
        """
        One-shot question generation call (no conversation history).
        Uses QA_GEN_MAX_TOKENS for a larger budget.

        Args:
            prompt: Full question-generation prompt (system + instructions combined)

        Returns:
            Raw model output (should be JSON — parsed by engine.py)
        """
        single_turn = [{"role": "user", "content": prompt}]

        if self.provider == "Claude (Anthropic)":
            return self._chat_claude("", single_turn, QA_GEN_MAX_TOKENS)

        elif self.provider == "Gemini 2.5 Flash":
            # For Gemini one-shot: pass the prompt directly, no system
            from google.genai import types
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=QA_GEN_MAX_TOKENS,
                    temperature=0.4,   # lower = more deterministic JSON
                ),
            )
            return response.text.strip()

        elif self.provider == "Groq (Llama-3.3-70b)":
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=QA_GEN_MAX_TOKENS,
                temperature=0.4,
            )
            return response.choices[0].message.content.strip()
