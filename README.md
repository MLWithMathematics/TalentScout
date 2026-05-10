# 🤖 TalentScout — AI Hiring Assistant

**A GDPR-Compliant, AI-Powered Candidate Screening Chatbot**
Built with Python · Streamlit · Multi-LLM (Claude, Gemini, Groq) · PostgreSQL

---

## 📌 Project Overview

TalentScout's Hiring Assistant automates the initial screening of technology candidates through a structured, conversational interface. It collects candidate profiles, generates technology-specific technical questions, and stores all data securely — fully compliant with GDPR (EU) 2016/679.

### What it does

| Phase | Description |
|-------|-------------|
| 1. Consent | Obtains informed, explicit GDPR consent before any data collection |
| 2. Profile | Gathers name, email, phone, experience, desired role, location, tech stack |
| 3. Technical Q&A | Generates 3–5 scenario-based questions per declared technology |
| 4. Wrap-up | Explains next steps; reminds candidate of their GDPR rights |

> **No automated hiring decisions are made.** Every screening is reviewed by a human recruiter. Candidates may request human review at any time (GDPR Art. 22).

---

## 🏗️ Architecture

```
talentscout/
├── app.py                      ← Streamlit UI (entry point)
├── config.py                   ← All constants, paths, settings
├── requirements.txt
├── .env.example                ← Environment variable template
├── .gitignore
│
├── chatbot/
│   ├── engine.py               ← Conversation state machine + LLM orchestration
│   ├── prompts.py              ← All prompt templates (master + per-stage)
│   └── validator.py            ← Input validation (email, phone, years, etc.)
│
└── data_management/
    ├── database.py             ← GDPR-compliant PostgreSQL/SQLite + Fernet encryption
    ├── encryption.py           ← AES-128 / Fernet field-level encryption
    └── audit_logger.py         ← Append-only GDPR audit trail
```

### Data flow

```
User Input
    ↓
app.py          → Intercept exit keywords, render UI
    ↓
engine.py       → Validate input, update state, persist to DB
    ↓
prompts.py      → Build MASTER_SYSTEM_PROMPT + stage context
    ↓
LLM API         → Generate response (Claude, Gemini, Groq)
    ↓
database.py     → Encrypt PII, write to PostgreSQL/SQLite
    ↓
audit_logger.py → Append audit entry (no PII in logs)
    ↓
app.py          → Render assistant message
```

---

## ⚡ Installation

### Prerequisites
- Python 3.10+
- An LLM API key (Anthropic, Gemini, or Groq)
- (Production) PostgreSQL Database (e.g., Neon.tech)
- (Production) Render Account

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/yourorg/talentscout-hiring-assistant.git
cd talentscout-hiring-assistant

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate          # macOS/Linux
# OR
venv\Scripts\activate             # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your preferred LLM API key (e.g., ANTHROPIC_API_KEY)
# For production, add DATABASE_URL and ENCRYPTION_KEY

# 5. Run the application
streamlit run app.py
```

The app opens at **http://localhost:8501** in your browser.

---

## 🚀 Deployment (Render + Neon)

To deploy TalentScout for free using Render (Web Service) and Neon (Serverless PostgreSQL):

1. **Generate Encryption Key:**
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Save this as `ENCRYPTION_KEY` in your environment. Keep it safe to prevent data loss!

2. **Neon Database Setup:**
   Create a free project at [neon.tech](https://neon.tech) and copy your PostgreSQL connection string.

3. **Render Web Service Setup:**
   - Log in to the [Render Dashboard](https://dashboard.render.com) and create a **New Web Service**.
   - Connect your GitHub repository.
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
   - **Instance Type**: Free tier.
   - Add these **Environment Variables**:
     - `PYTHON_VERSION`: `3.11.0`
     - `DATABASE_URL`: *(Your Neon connection string)*
     - `ENCRYPTION_KEY`: *(Key generated in step 1)*
     - `ANTHROPIC_API_KEY` (or `GEMINI_API_KEY` / `GROQ_API_KEY`)

> **Note:** Render's free tier spins down after 15 minutes of inactivity. The next request will take ~50s to wake up.

---

## 🖥️ Usage Guide

### Candidate Experience

1. **Open the app** → Read the GDPR notice on the welcome screen
2. **Give consent** → Type "Yes" to begin (or "No" to exit without data collection)
3. **Complete your profile** → The chatbot asks one field at a time:
   - Full name, email, phone, years of experience, desired role, location, tech stack
4. **Answer technical questions** → 5 questions tailored to your declared technologies
5. **Receive wrap-up** → Next steps and how to contact TalentScout

### Exit at any time
Type any of: `bye`, `quit`, `exit`, `goodbye`, `stop`, `done` → graceful exit

### GDPR Rights (sidebar panel)
| Button | GDPR Article | What it does |
|--------|-------------|--------------|
| 📥 Access My Data | Art. 15 | View all stored data |
| ✏️ Correct My Data | Art. 16 | Fix any inaccurate field |
| 📤 Export CSV | Art. 20 | Download data in machine-readable format |
| 🗑️ Delete All Data | Art. 17 | Permanently erase all records |
| 👤 Request Human Review | Art. 22 | Flag for human recruiter review |

---

## 🔒 GDPR Compliance Details

### Legal Basis
- **Art. 6(1)(a)**: Explicit informed consent obtained before any data collection
- **Art. 7**: Consent timestamp recorded; withdrawal available at any time
- **Art. 13**: Full transparency at session start (data collected, purpose, retention, rights)

### Data Protection by Design (Art. 25)
- **Encryption at rest**: All PII fields (name, email, phone) encrypted using Fernet (AES-128-CBC + HMAC-SHA256) before writing to PostgreSQL/SQLite
- **Pseudonymisation**: Internal logs use only the candidate UUID, never name/email/phone
- **Masking**: UI displays masked values only (e.g. `j***@gmail.com`, `XXXXX1234`)
- **Minimisation**: Only fields necessary for recruitment are collected

### Data Retention (Art. 5(1)(e))
- Records are auto-deleted after **90 days** (enforced at application startup)
- Retention deadline is stored per-candidate and enforced by `_purge_expired_records()`

### Candidate Rights Fulfilment (Art. 12)
| Right | Implementation | SLA |
|-------|---------------|-----|
| Access (Art. 15) | `db.get_candidate()` | Instant |
| Rectification (Art. 16) | `db.rectify_candidate()` | Instant |
| Erasure (Art. 17) | `db.delete_candidate()` | Instant |
| Portability (Art. 20) | `db.export_candidate_csv()` | Instant download |
| Human Review (Art. 22) | `db.request_human_review()` | 30-day SLA |

### AI Transparency (Art. 22)
- AI identity is **always disclosed** — never hidden
- Chatbot explicitly states: "You are talking to an AI, not a human"
- Every session includes: "No automated hiring decision is made"
- Human review button is **always visible** in the sidebar
- `ai_decision_explanation` column reserved in DB for recruiter notes

### Audit Trail (Art. 5(2) — Accountability)
All data operations are logged to `data/audit_log.json`:
```json
{
  "timestamp": "2026-05-06T10:30:00Z",
  "action": "CREATE",
  "candidate_id": "uuid-v4-here",
  "performed_by": "SYSTEM",
  "details": "Candidate record created; consent recorded",
  "legal_basis": "Consent (Art. 6(1)(a) GDPR)"
}
```
> Audit logs contain **zero raw PII** — only UUIDs and action types.

### DPIA (Data Protection Impact Assessment) — Art. 35
A DPIA was conducted for the AI screening component:
- **Risk**: AI could systematically disadvantage certain groups
- **Mitigation**: Technical questions are generated with explicit bias exclusion in the prompt; protected characteristics are forbidden in all question generation
- **Residual risk**: LOW — human review is always the final gate before any decision

---

## 🧠 Prompt Engineering Design

### Three-layer prompt architecture

```
Layer 1: MASTER_SYSTEM_PROMPT (always present)
         → Defines AI identity, GDPR rules, hard limits, tone
         → Prevents any topic drift regardless of user input

Layer 2: Stage-specific context block (dynamic, per-turn)
         → Injected at every API call alongside the master prompt
         → Tells Claude exactly what its job is right now
         → Contains the current field to collect / current question to ask

Layer 3: Rolling conversation history
         → All messages sent on every API call
         → Provides coherent multi-turn context and memory
```

### Key prompting decisions

| Design Choice | Reason |
|---------------|--------|
| "One field at a time" enforced in stage prompt | Prevents overwhelming candidates |
| "Never evaluate the answer" in Q&A prompt | Keeps assessment neutral; avoids bias signalling |
| Protected characteristics explicitly listed in question gen prompt | Satisfies GDPR Art. 9 and equality law requirements |
| `get_question_generation_prompt()` requests JSON output | Deterministic parsing; no regex fragility |
| Fallback questions if JSON parse fails | Graceful degradation; screening never breaks |
| Seniority calibration in question gen | Junior/mid/senior questions are meaningfully different |
| Exit keywords intercepted in Python (not LLM) | Instant, reliable; LLM not involved in control flow |

### Question generation design
Questions are generated **once** after the tech stack is declared, stored as a flat list, and asked **one at a time**. This approach:
- Avoids repeated API calls per question
- Allows progress tracking (`question_index`)
- Enables the full Q&A log to be persisted per candidate

---

## 🚀 Challenges and Solutions 

1. **LLM answering general queries instead of screening**
   - **Challenge**: The LLM would sometimes get distracted and answer general knowledge or coding queries from the candidate.
   - **Solution**: Implemented a two-layer protection system. Layer 1 uses a Python-based guardrail (`chatbot/guardrail.py`) to deterministically intercept off-topic messages *before* they reach the LLM. Layer 2 enforces a strict "interviewer only" persona via the `MASTER_SYSTEM_PROMPT` to catch any edge cases.

2. **Inconsistent Phone and Email Verification**
   - **Challenge**: The LLM was failing to properly catch incorrectly formatted emails or phone numbers during the profile gathering stage.
   - **Solution**: Moved validation out of the LLM prompt and into deterministic Python functions (`chatbot/validator.py`). User input is now validated via robust regex patterns for email (`validate_email`) and phone (`validate_phone`) *before* being processed, guaranteeing that only valid data is stored and immediate feedback is given on errors.

3. **Skipping or grouping Gathering Information Prompts**
   - **Challenge**: The LLM was struggling to ask for one piece of information at a time (name, phone, email, etc.), often overwhelming the user by asking for multiple fields at once.
   - **Solution**: Built a structured state machine in `chatbot/engine.py` (`_process_info_field`). It strictly enforces collecting exactly one `current_field` at a time sequentially from an `INFO_FIELDS` list. The LLM is forced to focus only on the current missing field, and the app only advances to the next field upon successful Python-based validation of the current one.

4. **Phone Number Accepted Incomplete Numbers (e.g. +91 12345)**
   - **Challenge**: The old `validate_phone()` only stripped formatting and checked if total digit count was between 7–15. It never verified how many digits came after the country code, so +91 (India) + 5 digits = 7 total digits passed silently.
   - **Solution**: A `COUNTRY_PHONE_RULES` dictionary was added to `chatbot/validator.py` covering 40+ countries. The validator now strips the country code prefix, counts subscriber digits, and cross-checks against the rule (e.g., India must have exactly 10 digits after +91).

5. **Tech Stack & Position Accepted "IDK", "N/A", Gibberish**
   - **Challenge**: Inputs like "IDK" or "N/A" were passing length checks. Position only checked for length >= 2, allowing "ok" or "na" to pass as valid job roles.
   - **Solution**: Added a `VAGUE_RESPONSES` blocklist and a `KNOWN_TECH_KEYWORDS` set of 150+ industry technologies. A dedicated `validate_position()` function was created to reject vague roles like "anything" and ensure roles contain tech-related keywords (e.g., "Engineer", "Developer").

6. **Location Was Not Verified Against Real-World Data**
   - **Challenge**: Location only checked string length, allowing fictional or vague entries like "Moon City" or "Somewhere" to pass.
   - **Solution**: Created `validate_location()` which enforces a "City, Country" format and performs live API verification using **OpenStreetMap Nominatim**. It confirms the location exists on the map while failing gracefully (accepting format-only) if the network is unreachable.

7. **LLM Generating Generic Role-Based Questions**
   - **Challenge**: When generating the technical question bank, the LLM would occasionally ignore the explicitly provided tech stack and instead generate generic questions based on the job role or position (e.g. asking "What makes a great backend engineer?" instead of focusing on Python or PostgreSQL).
   - **Solution**: Updated `chatbot/prompts.py` (v1.3) by adding a strong "PRIMARY DIRECTIVE" block to the `get_question_generation_prompt`. This explicitly forbids generating questions based on the job role and enforces that every question must revolve strictly around a technology from the candidate's declared tech stack. The Greeting and Info Gathering prompts were also made more explicit to prime the candidate that their tech stack drives the Q&A.

---

## 💡 Recent UX Improvements

### 🆕 Exit Confirmation Dialog
To prevent accidental session termination, a safety gate was implemented for all `EXIT_KEYWORDS` (e.g., *exit, quit, stop*).

- **How it works**: If a user types an exit word during active screening, `app.py` intercepts the input and displays a styled warning dialog instead of the chat box.
- **Choices**:
  - **✅ Yes, Exit**: Forwards the request to the engine to end the session gracefully.
  - **❌ No, Continue**: Clears the exit state and resumes the session exactly where it was.
- **Smart Logic**: The dialog is automatically bypassed during non-active stages (CONSENT, FAREWELL, WRAP_UP) to ensure a smooth flow during the beginning and end of the journey.

---

## 🔧 Technical Details

| Component | Technology | Version |
|-----------|-----------|---------|
| UI Framework | Streamlit | ≥ 1.35 |
| LLM Support | Claude, Gemini, Groq | Multi-provider |
| Encryption | Fernet (AES-128-CBC) | cryptography ≥ 42 |
| Database | PostgreSQL / SQLite | psycopg2-binary / Built-in |
| Deployment | Render Web Service | Free Tier |
| Config | python-dotenv | ≥ 1.0 |

### Multi-Model Support
- **Claude Sonnet 4**: Default choice, best balance of intelligence and speed
- **Gemini 2.5 Flash**: Fast and capable alternative
- **Groq (Llama 3.1 8B)**: Ultra-fast open-weight model serving

---

## 🔑 Security Notes

| Measure | Detail |
|---------|--------|
| API key | Stored in `.env` only; never committed to git |
| Encryption key | `data/.encryption_key` — chmod 600 (owner only) |
| PII in DB | Always encrypted; plaintext never written to disk |
| PII in logs | Never stored; only UUID + action type |
| PII in UI | Always masked for display |
| Data at deletion | Immediate SQL DELETE; no soft-delete |
| Session data | Streamlit `session_state` only; no cookies, no local storage |

---

## 🐛 Troubleshooting

| Issue | Fix |
|-------|-----|
| `API Key not set` | Copy `.env.example` to `.env` and add your LLM API key |
| `ModuleNotFoundError: psycopg2` | Run `pip install psycopg2-binary` |
| Data not persisting | Check `DATABASE_URL` is correct or `data/` is writable |
| Chat not starting | Refresh the browser; check terminal for Python errors |
| Encryption key error | Delete `data/.encryption_key` and restart (creates a new key — existing encrypted data will be unreadable) |

---

## 📄 License

MIT License — see `LICENSE` file for details.

ML Engineer - Shubhankar 

---

*Built with ❤️ for TalentScout — where technology meets talent.*

