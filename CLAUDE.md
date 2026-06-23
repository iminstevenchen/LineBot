# Karpathy Coding Guidelines

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

---

# 育兒導航全攻略 — LINE Bot

Taiwan parenting LINE Bot ("育兒小幫手") for new parents. Users ask questions; the bot retrieves context from a RAG knowledge base and answers using Gemini LLM with personalized context (baby age, region, interests).

## Tech Stack

- Python 3.11+, Flask 3.1, gunicorn
- LINE Bot SDK v3 (`linebot.v3`)
- Supabase PostgreSQL via `psycopg2` connection pool
- Gemini 2.5 Flash (`google-genai`) for LLM replies and history summarization
- AnythingLLM RAG API (teammate's server via Cloudflare Tunnel) with `rag_mock.py` fallback

## File Map

| File | Responsibility |
|---|---|
| `main.py` | Flask app, LINE webhook routes, Q&A orchestration |
| `config.py` | Loads `.env` and `config.ini`, exposes constants |
| `db.py` | PostgreSQL connection pool; user profiles and chat history CRUD |
| `llm.py` | Gemini wrapper: `build_rag_query`, `generate_reply`, `summarize_history` |
| `rag.py` | AnythingLLM API client with automatic fallback to `rag_mock` |
| `rag_mock.py` | Keyword-based mock RAG with 7 hardcoded 育兒 knowledge chunks |
| `onboarding.py` | 5-step onboarding state machine using Quick Reply and DatetimePicker |
| `rich_menu.py` | Standalone script: creates/updates the LINE rich menu (圖文選單) and sets it as default. Buttons send text that `main.py`'s existing command handling already understands — run manually, not imported by the app |
| `tests/test_conversation.py` | Local test script — simulates 4-turn conversation without LINE or ngrok |
| `docs/api.py` / `docs/api.js` | Teammate's AnythingLLM API reference (not imported anywhere) |
| `config.ini` | LINE channel keys — **GITIGNORED, never commit** |
| `.env` | DB URL, Gemini API key, RAG API URL — **GITIGNORED, never commit** |

## Environment Variables (`.env`)

```
DATABASE_URL=postgresql://...@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres
GEMINI_API_KEY=...
RAG_API_URL=https://YOUR-TUNNEL.trycloudflare.com/api/chat   # empty = use mock RAG
```

## Critical: Q&A Flow Order (`main.py`)

**DO NOT reorder these steps.** History must be fetched BEFORE `save_message` so the current message does not appear in its own context.

```python
history = db.get_recent_history(user_id, limit=20)  # fetch BEFORE saving current msg
db.save_message(user_id, "user", text)
rag_query = llm.build_rag_query(text, user_context, history)
rag_chunks = rag.query_rag(rag_query)
reply = llm.generate_reply(text, user_context, rag_chunks, history)
db.save_message(user_id, "assistant", reply)
db.trim_chat_history(user_id, keep=30)
```

## Onboarding State Machine

`new` → `waiting_nickname` → `waiting_birthday` → `waiting_gender` → `waiting_region` → `waiting_interests` → `done`

- Birthday is set via LINE DatetimePicker (PostbackEvent), not text input
- Q&A flow only activates when `onboarding_state == 'done'`
- Users can restart onboarding anytime by typing "修改資料"

## Safety Rules in `SYSTEM_PROMPT` (`llm.py`)

**DO NOT modify these without team approval:**

- No specific medical diagnoses ("your baby has X disease")
- No medication advice — always refer to doctor/pharmacist
- Breathing difficulty / seizures / unconsciousness → "請撥打 119 或立刻就醫"
- Suspected child abuse or domestic violence → 保護專線 113
- Self-harm risk → 安心專線 1925
- No Markdown formatting in responses (LINE renders `**bold**` as literal asterisks)

## Database Schema

### `user_profiles`
| Column | Type | Notes |
|---|---|---|
| `line_user_id` | VARCHAR(64) PK | LINE user ID |
| `user_nickname` | VARCHAR(50) | Baby's nickname |
| `baby_birthday_or_due_date` | DATE | Used to calculate baby age |
| `baby_gender` | VARCHAR(10) | 男 / 女 / 未知 |
| `region` | VARCHAR(50) | 縣市 |
| `interests` | TEXT | Comma-separated (e.g. "疫苗,健康檢查") |
| `onboarding_state` | VARCHAR(30) | State machine current state |

### `chat_histories`
| Column | Type | Notes |
|---|---|---|
| `message_id` | BIGSERIAL PK | Auto-increment |
| `line_user_id` | VARCHAR(64) FK | References `user_profiles` |
| `role` | VARCHAR(10) | `'user'` or `'assistant'` |
| `content` | TEXT | Message text |
| `created_at` | TIMESTAMPTZ | Auto-set |

Index: `idx_chat_histories_user_time ON (line_user_id, created_at DESC)`

## Memory System

- DB is trimmed to last 30 messages per user after every reply (`trim_chat_history(keep=30)`)
- LLM receives last 20 messages (`get_recent_history(limit=20)`)
- If history > 6 messages: older portion is summarized by Gemini; last 4 are kept verbatim
- Constants in `llm.py`: `_RECENT_KEEP = 4`, `_SUMMARY_THRESHOLD = 6`

## RAG API

`rag.py` calls the teammate's AnythingLLM server. The Cloudflare Tunnel URL changes on every restart.

- Update `.env`: `RAG_API_URL=https://NEW-URL.trycloudflare.com/api/chat`
- Expected request: `POST /api/chat` with `{"message": "..."}`
- Expected response: `{"answer": "..."}`
- If URL empty or unreachable → automatic fallback to `rag_mock.query_mock_rag()`

## Formatting Rules for LLM Responses

- Traditional Chinese (繁體中文) only
- **No Markdown**: no `**bold**`, `*italic*`, `# headers` — use `•`, `1. 2. 3.`, `【brackets】`, or emoji instead
- Max ~250 characters per reply
- Warmth and conversational tone (友善口語化)

## Running Locally

```bash
source venv/bin/activate
python main.py                    # Flask on port 8000

# Separate terminal — tunnel for LINE webhook:
ngrok http 8000
# Set webhook in LINE Developers Console:
# https://YOUR_NGROK_URL.ngrok-free.app/callback

# Test without LINE or ngrok:
cd tests && python test_conversation.py
```

## Key Constants

| Constant | Location | Value | Purpose |
|---|---|---|---|
| `GEMINI_MODEL` | `config.py` | `gemini-2.5-flash` | LLM model |
| `DB_POOL_MIN/MAX` | `config.py` | 1 / 5 | Connection pool size |
| `RAG_TIMEOUT` | `rag.py` | 60s | Request timeout to teammate's API |
| `_RECENT_KEEP` | `llm.py` | 4 | Raw history messages kept verbatim |
| `_SUMMARY_THRESHOLD` | `llm.py` | 6 | History length that triggers summarization |
| `keep=30` | `main.py` | 30 | Max DB rows per user |
