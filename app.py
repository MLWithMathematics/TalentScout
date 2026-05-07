"""
app.py — TalentScout AI Hiring Assistant — Main Streamlit Application

Entry point: `streamlit run app.py`

UI Structure:
  ┌──────────────────────┬──────────────────────────────────────────┐
  │   SIDEBAR            │   MAIN CHAT AREA                         │
  │──────────────────────│──────────────────────────────────────────│
  │ • LLM Provider picker│ • Chat bubbles (assistant + candidate)    │
  │ • Progress bar       │ • Stage indicator                         │
  │ • Profile card       │ • Text input                              │
  │ • GDPR Rights panel  │                                          │
  │   – Access           │                                          │
  │   – Rectify          │                                          │
  │   – Delete           │                                          │
  │   – Export CSV       │                                          │
  │   – Human review     │                                          │
  │ • AI Disclosure      │                                          │
  └──────────────────────┴──────────────────────────────────────────┘
"""

import streamlit as st

from chatbot.engine import ConversationEngine, initialize_state
from chatbot.llm_client import available_providers
from config import (
    APP_TITLE,
    APP_VERSION,
    COMPANY_NAME,
    DATA_RETENTION_DAYS,
    DEFAULT_PROVIDER,
    GDPR_CONTACT_EMAIL,
    GDPR_REQUEST_FULFILLMENT_DAYS,
    INFO_FIELDS,
    PROVIDER_MODELS,
)
from data_management.database import CandidateDatabase
from data_management.encryption import EncryptionManager

# ─────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────────────────
st.markdown("""
<style>
.ts-header {
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    padding: 1.4rem 2rem;
    border-radius: 14px;
    color: white;
    margin-bottom: 1.2rem;
}
.ts-header h1 { margin: 0; font-size: 1.75rem; font-weight: 700; }
.ts-header p  { margin: 4px 0 0; font-size: 0.88rem; opacity: 0.85; }

.badge-green  { background:#28a745; color:#fff; padding:3px 10px; border-radius:20px; font-size:.72rem; font-weight:700; }
.badge-blue   { background:#007bff; color:#fff; padding:3px 10px; border-radius:20px; font-size:.72rem; font-weight:700; }
.badge-purple { background:#6f42c1; color:#fff; padding:3px 10px; border-radius:20px; font-size:.72rem; font-weight:700; }

.stage-bar {
    border-left: 4px solid #302b63;
    background: #f5f3ff;
    padding: 8px 16px;
    border-radius: 4px;
    font-size: .85rem;
    margin-bottom: .9rem;
    color: #333;
}
.info-card {
    background: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 7px;
    font-size: .83rem;
    line-height: 1.5;
}
.gdpr-box {
    background: #fff8e1;
    border: 1px solid #ffc107;
    border-radius: 8px;
    padding: 11px 13px;
    font-size: .78rem;
    margin-bottom: .9rem;
    line-height: 1.6;
}
.ai-box {
    background: #e8f4fd;
    border: 1px solid #90caf9;
    border-radius: 8px;
    padding: 10px 13px;
    font-size: .78rem;
    line-height: 1.6;
}
.provider-box {
    background: #f0f0ff;
    border: 1px solid #9b8ef8;
    border-radius: 8px;
    padding: 10px 13px;
    font-size: .78rem;
    margin-bottom: .6rem;
    line-height: 1.6;
}
.ended-box {
    background: #e8f5e9;
    border: 1px solid #a5d6a7;
    border-radius: 8px;
    padding: 14px;
    text-align: center;
    font-size: .9rem;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# SESSION STATE INITIALISATION
# ─────────────────────────────────────────────────────────

def _init_session() -> None:
    """Initialise all session-level objects on first load."""
    if "provider" not in st.session_state:
        # Pick the first available provider automatically
        avail = available_providers()
        st.session_state.provider = avail[0] if avail else DEFAULT_PROVIDER

    if "state" not in st.session_state:
        st.session_state.state            = initialize_state()
        st.session_state.engine           = ConversationEngine(st.session_state.provider)
        st.session_state.db               = CandidateDatabase()
        st.session_state.enc              = EncryptionManager()
        st.session_state.messages         = []
        st.session_state.started          = False
        st.session_state.gdpr_del_confirm = False


_init_session()


# ─────────────────────────────────────────────────────────
# Stage helpers
# ─────────────────────────────────────────────────────────

STAGE_META = {
    "CONSENT":          ("📋", "Consent",             0.05),
    "GREETING":         ("👋", "Welcome",              0.12),
    "INFO_GATHERING":   ("📝", "Profile",              None),
    "TECH_QUESTIONING": ("🔧", "Technical Assessment", None),
    "WRAP_UP":          ("✅", "Wrap-up",              0.95),
    "FAREWELL":         ("👋", "Farewell",             1.00),
}


def _progress(state: dict) -> float:
    stage = state["stage"]
    meta  = STAGE_META.get(stage, ("", stage, 0.0))

    if stage == "INFO_GATHERING":
        filled = sum(1 for f in INFO_FIELDS if state["candidate_info"].get(f))
        return 0.12 + (filled / len(INFO_FIELDS)) * 0.38

    if stage == "TECH_QUESTIONING":
        total = len(state["tech_questions"])
        done  = state["question_index"]
        return 0.50 + ((done / total) * 0.45 if total else 0)

    return meta[2] if meta[2] is not None else 0.0


def _stage_label(stage: str) -> str:
    meta = STAGE_META.get(stage, ("📍", stage, 0))
    return f"{meta[0]} {meta[1]}"


# ─────────────────────────────────────────────────────────
# Provider badge helper
# ─────────────────────────────────────────────────────────

PROVIDER_BADGES = {
    "Claude (Anthropic)":   ("🟠", "#FF6B35"),
    "Gemini 2.5 Flash":     ("🔵", "#4285F4"),
    "Groq (Llama-3.3-70b)": ("🟣", "#6f42c1"),
}

PROVIDER_NOTES = {
    "Claude (Anthropic)":   "Best instruction-following. Recommended for production.",
    "Gemini 2.5 Flash":     "Fast + large context. Great for complex tech stacks.",
    "Groq (Llama-3.3-70b)": "Ultra-fast inference. Ideal for quick iterations.",
}


# ─────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────

def _render_sidebar(state: dict, db: CandidateDatabase,
                    enc: EncryptionManager) -> None:
    with st.sidebar:
        st.markdown(f"## 🎯 {COMPANY_NAME}")
        st.markdown(
            '<span class="badge-green">✓ GDPR</span>&nbsp;'
            '<span class="badge-blue">🤖 AI</span>&nbsp;'
            '<span class="badge-purple">⚡ Multi-LLM</span>',
            unsafe_allow_html=True,
        )
        st.markdown("---")

        # ── LLM Provider Selector ─────────────────────────
        st.markdown("### ⚡ LLM Provider")
        avail = available_providers()

        if not avail:
            st.error(
                "⚠️ No API keys found!\n\n"
                "Add at least one to your `.env` file:\n"
                "- `ANTHROPIC_API_KEY`\n"
                "- `GEMINI_API_KEY`\n"
                "- `GROQ_API_KEY`"
            )
        else:
            current_provider = st.session_state.provider
            # Show only providers with valid API keys
            chosen = st.selectbox(
                "Active model",
                options=avail,
                index=avail.index(current_provider) if current_provider in avail else 0,
                help="Switch LLM provider without restarting your session.",
                key="provider_select",
            )

            if chosen != st.session_state.provider:
                st.session_state.provider = chosen
                st.session_state.engine.switch_provider(chosen)
                st.success(f"✅ Switched to **{chosen}**")

            icon, _ = PROVIDER_BADGES.get(chosen, ("🤖", "#333"))
            model   = PROVIDER_MODELS[chosen]
            note    = PROVIDER_NOTES.get(chosen, "")
            st.markdown(
                f'<div class="provider-box">'
                f'{icon} <strong>{chosen}</strong><br>'
                f'<code style="font-size:.7rem">{model}</code><br>'
                f'<span style="color:#555;font-size:.72rem">{note}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # ── Progress ──────────────────────────────────────
        stage = state["stage"]
        st.markdown(f"**Stage:** {_stage_label(stage)}")
        st.progress(_progress(state))
        if stage == "TECH_QUESTIONING":
            total = len(state["tech_questions"])
            done  = state["question_index"]
            st.caption(f"Question {done} of {total}")
        st.markdown("---")

        # ── Profile Card ──────────────────────────────────
        st.markdown("### 📋 Your Profile")
        info    = state["candidate_info"]
        has_data= any(v for v in info.values() if v)

        if not has_data:
            st.caption("Your profile will appear here as we go. 🙂")
        else:
            labels = {
                "full_name":        "👤 Name",
                "email":            "📧 Email",
                "phone":            "📞 Phone",
                "years_experience": "🗓️ Experience",
                "desired_position": "💼 Position",
                "current_location": "📍 Location",
                "tech_stack":       "💻 Tech Stack",
            }
            for field, label in labels.items():
                val = info.get(field)
                if not val:
                    continue
                if field == "email":
                    display = enc.mask_email(val)
                elif field == "phone":
                    display = enc.mask_phone(val)
                elif field == "full_name":
                    display = enc.mask_name(val)
                elif isinstance(val, list):
                    display = ", ".join(val)
                else:
                    display = str(val)
                st.markdown(
                    f'<div class="info-card"><strong>{label}</strong><br>{display}</div>',
                    unsafe_allow_html=True,
                )

        st.markdown("---")

        # ── GDPR Rights Panel ─────────────────────────────
        st.markdown("### 🔒 Your GDPR Rights")
        st.markdown(f"""
<div class="gdpr-box">
<strong>Controller:</strong> {COMPANY_NAME}<br>
<strong>DPO:</strong> {GDPR_CONTACT_EMAIL}<br>
<strong>Legal Basis:</strong> Consent — Art. 6(1)(a)<br>
<strong>Retention:</strong> {DATA_RETENTION_DAYS} days auto-delete<br>
<strong>SLA:</strong> {GDPR_REQUEST_FULFILLMENT_DAYS} days
</div>
""", unsafe_allow_html=True)

        candidate_id = state.get("candidate_id")

        if not candidate_id:
            st.caption("Rights panel activates after consent is given.")
        else:
            # Art. 15 — Access
            if st.button("📥 Access My Data (Art. 15)", use_container_width=True):
                data = db.get_candidate(candidate_id)
                db.log_gdpr_request(candidate_id, "ACCESS")
                if data:
                    safe = {k: v for k, v in data.items()
                            if k not in ("full_name_enc", "email_enc", "phone_enc")}
                    if safe.get("full_name"):
                        safe["full_name"] = enc.mask_name(safe["full_name"])
                    if safe.get("email"):
                        safe["email"]     = enc.mask_email(safe["email"])
                    if safe.get("phone"):
                        safe["phone"]     = enc.mask_phone(safe["phone"])
                    st.json(safe)

            # Art. 16 — Rectification
            with st.expander("✏️ Correct My Data (Art. 16)"):
                field_opts = {
                    "full_name":        "Full Name",
                    "email":            "Email",
                    "phone":            "Phone",
                    "desired_position": "Desired Position",
                    "current_location": "Location",
                    "years_experience": "Years of Experience",
                }
                chosen_field = st.selectbox("Field to correct",
                                            list(field_opts.values()))
                new_val = st.text_input("New value")
                if st.button("Submit Correction", use_container_width=True):
                    field_key = next(
                        k for k, v in field_opts.items() if v == chosen_field
                    )
                    db.rectify_candidate(candidate_id, field_key, new_val)
                    state["candidate_info"][field_key] = new_val
                    st.success(f"✅ {chosen_field} updated!")

            # Art. 20 — Portability
            if st.button("📤 Export CSV (Art. 20)", use_container_width=True):
                csv_str = db.export_candidate_csv(candidate_id)
                if csv_str:
                    st.download_button(
                        label="⬇️ Download CSV",
                        data=csv_str,
                        file_name="my_talentscout_data.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

            # Art. 17 — Erasure
            st.markdown("---")
            if st.button("🗑️ Delete ALL My Data (Art. 17)",
                         use_container_width=True):
                st.session_state.gdpr_del_confirm = True

            if st.session_state.gdpr_del_confirm:
                st.error("⚠️ This permanently deletes **all** your data. Cannot be undone.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Confirm", type="primary",
                                 use_container_width=True):
                        db.delete_candidate(candidate_id)
                        state["candidate_id"] = None
                        st.session_state.gdpr_del_confirm = False
                        st.success("All data permanently deleted.")
                with c2:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state.gdpr_del_confirm = False
                        st.rerun()

            # Art. 22 — Human Review
            st.markdown("---")
            if st.button("👤 Request Human Review (Art. 22)",
                         use_container_width=True):
                db.request_human_review(candidate_id)
                db.log_gdpr_request(candidate_id, "HUMAN_REVIEW")
                st.success(
                    f"✅ Human review requested — recruiter contacts you "
                    f"within {GDPR_REQUEST_FULFILLMENT_DAYS} days."
                )

        # ── AI Transparency ───────────────────────────────
        st.markdown("---")
        st.markdown("""
<div class="ai-box">
<strong>🤖 AI Transparency — GDPR Art. 22</strong><br>
Screening is AI-assisted. <strong>No automated hiring decisions.</strong>
A human recruiter reviews all responses. Request human review anytime.
</div>
""", unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🔄 Start New Session", use_container_width=True):
            provider_backup = st.session_state.provider
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.session_state.provider = provider_backup
            st.rerun()

        st.caption(f"v{APP_VERSION} | {COMPANY_NAME}")


# ─────────────────────────────────────────────────────────
# CONSENT MESSAGE (shown once on load)
# ─────────────────────────────────────────────────────────

CONSENT_MESSAGE = f"""
Hello! Welcome to **{COMPANY_NAME}**'s AI-powered hiring assistant. 👋

---

### 🤖 Please Read Before We Begin

**You are speaking with an AI assistant, not a human recruiter.**
This is an automated initial screening tool. A human recruiter will
review all your responses before any hiring decision is made.

---

### What We Collect & Why

| Data | Purpose |
|------|---------|
| Name, Email, Phone | Candidate identification & contact |
| Experience, Role, Location | Role matching |
| Tech Stack | Technical question generation |
| Q&A Answers | Initial proficiency assessment |

---

### Your GDPR Rights (Always Available in Sidebar)

Under GDPR you can **access, correct, delete, or export** your data
at any time using the left sidebar panel.

- 🔒 PII encrypted at rest (AES-128 Fernet)
- 🗓️ Auto-deleted after **{DATA_RETENTION_DAYS} days**
- 🚫 Never sold or shared with third parties
- 👤 Human review of AI screening available on request (Art. 22)
- 📧 Data Protection Officer: `{GDPR_CONTACT_EMAIL}`

---

**Do you give your informed consent to proceed?**
*(Type **Yes** to begin or **No** to exit without data collection)*
"""


# ─────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────

def main() -> None:
    state  = st.session_state.state
    engine = st.session_state.engine
    db     = st.session_state.db
    enc    = st.session_state.enc

    _render_sidebar(state, db, enc)

    # Header
    provider_icon = PROVIDER_BADGES.get(
        st.session_state.provider, ("🤖", "#333")
    )[0]
    st.markdown(f"""
<div class="ts-header">
  <h1>🤖 TalentScout Hiring Assistant</h1>
  <p>
    {provider_icon} Powered by <strong>{st.session_state.provider}</strong>
    &nbsp;•&nbsp; GDPR Compliant &nbsp;•&nbsp; Human Review Available
  </p>
</div>
""", unsafe_allow_html=True)

    # Stage bar
    ended_tag = " &nbsp;|&nbsp; ⚠️ Session Ended" if state["conversation_ended"] else ""
    st.markdown(
        f'<div class="stage-bar">📍 <strong>Stage:</strong> '
        f'{_stage_label(state["stage"])}{ended_tag}</div>',
        unsafe_allow_html=True,
    )

    # Chat history
    for msg in st.session_state.messages:
        avatar = "🤖" if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # Auto-start: show consent message
    if not st.session_state.started:
        st.session_state.started = True
        st.session_state.messages.append(
            {"role": "assistant", "content": CONSENT_MESSAGE}
        )
        state["chat_history"].append(
            {"role": "assistant", "content": CONSENT_MESSAGE}
        )
        st.rerun()

    # Input
    if not state["conversation_ended"]:
        user_input = st.chat_input("Type your response here…")
        if user_input:
            st.session_state.messages.append(
                {"role": "user", "content": user_input}
            )
            with st.spinner(f"Thinking via {st.session_state.provider}…"):
                response, updated_state = engine.handle_message(user_input, state)
            st.session_state.state = updated_state
            st.session_state.messages.append(
                {"role": "assistant", "content": response}
            )
            st.rerun()
    else:
        st.markdown("""
<div class="ended-box">
✅ <strong>Screening complete!</strong><br>
Use the sidebar to exercise your GDPR rights or click <em>Start New Session</em>.
</div>
""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
