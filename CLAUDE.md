# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**B2B SaaS License Management Platform** — handles the full lifecycle of software license provisioning: client request → RSA key generation → public key delivery → JWT-based offline validation.

**Stack:**
- Backend: Python 3.12 + FastAPI (single monolith) — managed with `uv`
- ORM: SQLAlchemy 2.x async + asyncpg
- Migrations: Alembic
- Database: PostgreSQL 16 (only persistent store — no Redis)
- Frontend: React 18 + Vite + React Router 6 + TanStack Query + Tailwind CSS (Node.js v24)
- Infrastructure: docker-compose.yml (Postgres + FastAPI)

## Architecture

Single FastAPI monolith. No microservices, no API Gateway, no Redis, no message queue.

```
React Frontend (single app, role-gated routes)
        ↓
FastAPI Monolith  (/api/v1/*)
        ↓
PostgreSQL 16
```

**Directory layout:**
```
PFE v3/
├── backend/                     # Python FastAPI monolith (uv-managed)
│   ├── pyproject.toml           # dependencies (uv add ...)
│   ├── uv.lock
│   ├── .env.example
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py              # app factory, middleware, router mount
│   │   ├── config.py            # pydantic-settings
│   │   ├── db/                  # SQLAlchemy async session + base
│   │   ├── models/              # ORM models (one file per domain)
│   │   ├── schemas/             # Pydantic v2 request/response
│   │   ├── api/v1/              # Routers: auth, users, licenses, keys, plans, notifications, validation, audit, health
│   │   │   └── deps.py          # get_current_user, require_admin, require_super_admin
│   │   ├── services/            # Business logic (routers call services, not DB directly)
│   │   ├── core/
│   │   │   ├── state_machine.py # VALID_TRANSITIONS dict + can_transition() pure function
│   │   │   ├── crypto.py        # RSA-2048 keygen, AES-256-GCM encrypt/decrypt
│   │   │   ├── jwt.py           # RS256 sign/verify
│   │   │   └── security.py      # bcrypt hash/verify
│   │   ├── workers/
│   │   │   └── scheduler.py     # APScheduler: hourly expiry cron, daily warning emails
│   │   └── email/               # fastapi-mail sender + Jinja2 templates
│   ├── alembic/
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       └── 0002_seed_plans.py
│   └── tests/
├── frontend/                    # React app (Vite, Node.js v24)
│   └── (created via: npm create vite@latest . -- --template react-ts)
└── docker-compose.yml           # at project root — runs Postgres + backend
```

## Core Design Rules

**Frontend enforces nothing** — all validation, RBAC, and state checks live in the backend.

**License state machine is strict:**
```
requested → in_progress → active → suspended/revoked → expired (auto via cron)
```
- `core/state_machine.py` is the single source of truth for allowed transitions
- `can_transition(from_status, to_status, actor_role) -> bool` — pure function, no DB
- Transition to `active` has a second guard: a `license_keys` row must exist
- Every transition written to `license_transitions` (append-only)

**Asymmetric key flow:**
1. Admin generates RSA-2048 key pair
2. Private key encrypted with AES-256-GCM using `MASTER_ENCRYPTION_KEY` env var; stored encrypted in DB
3. Private key never returned in list endpoints; every access logged to `audit_logs`
4. Public key delivered to client after `active` status; used to verify offline JWTs

**JWT:** RS256, 15-min access tokens in response body + 7-day refresh tokens in httpOnly cookie. Refresh tokens stored as SHA-256 hash in DB and rotated on every use.

## Database Conventions

- `snake_case` for all table/column names
- UUID primary keys (`gen_random_uuid()`)
- `created_at` / `updated_at` on every table
- Soft-delete via `deleted_at` where applicable
- `audit_logs` and `license_transitions` are **append-only** — no UPDATE or DELETE

**11 tables:** `users`, `refresh_tokens`, `plans`, `applications`, `licenses`, `license_transitions`, `license_keys`, `notifications`, `usage_records`, `audit_logs`, `webhooks`/`webhook_deliveries` (schema only until Phase 6)

**Plans** (`Basic`, `Pro`, `Enterprise`) are seeded via Alembic migration `0002`. No admin CRUD — features/limits stored as JSONB columns on `plans`.

**Usage counters** incremented via direct SQL `UPDATE ... SET api_calls_count = api_calls_count + 1` on the validation endpoint. No Redis.

## Security

- Passwords: bcrypt, 12 salt rounds
- Rate limiting on `/auth/login` and `/auth/forgot-password` via `slowapi`
- Private key: never in list responses; decrypted in memory only; every access to `key.private_downloaded` logged in `audit_logs`
- Parameterized queries only (SQLAlchemy ORM handles this)

## Roles

| Role | Capabilities |
|------|-------------|
| `super_admin` | Full access; can download private keys |
| `admin` | Manages licenses, transitions states, generates keys |
| `client` | Requests licenses, downloads public key (after `active`) |

## Development Phases

1. **Phase 0** — Scaffold (docker-compose, Alembic, `/health`)
2. **Phase 1** — Auth + Users
3. **Phase 2** — License Lifecycle + State Machine
4. **Phase 3** — Key Generation + Validation (core thesis feature)
5. **Phase 4** — React Frontend
6. **Phase 5** — Notifications + APScheduler + Audit log API
7. **Phase 6** — Webhooks + CI/CD (time permitting)
8. **Phase 7** — AI Chatbot (LangChain RAG router in same FastAPI app)

## Common Commands

All backend commands run from the `backend/` directory.

```bash
# Add a dependency
uv add fastapi sqlalchemy asyncpg

# Install all dependencies
uv sync

# Start dev server
uv run uvicorn app.main:app --reload --port 8000

# Run migrations
uv run alembic upgrade head

# Create a new migration
uv run alembic revision --autogenerate -m "description"

# Run tests
uv run pytest tests/ -v

# Run single test file
uv run pytest tests/test_license_state_machine.py -v
```

Frontend commands from `frontend/`:

```bash
# Bootstrap (first time only)
npm create vite@latest . -- --template react-ts

npm install
npm run dev
```

From project root:

```bash
# Start Postgres (and backend if Dockerfile is ready)
docker-compose up -d
```
