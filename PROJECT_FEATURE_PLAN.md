# License Management Platform — Feature Plan

> **Stack:** Backend → Python (FastAPI) | Frontend → React | AI Chatbot → Python (FastAPI, same monolith, Phase 7)
> **Architecture:** Single FastAPI monolith | JWT RS256 | State-machine license pipeline

---

## 1. Project Overview

### Goal
B2B SaaS License Management Platform handling the full lifecycle of software license provisioning: client request → RSA key generation → public key delivery → JWT-based offline validation.

### Core Principles
- Single FastAPI monolith — no microservices, no API Gateway
- Frontend enforces nothing — all validation/authorization on the backend
- Strict state machine: transitions are validated by a pure function before any DB write
- Private keys never leave the server decrypted (except intentional super_admin download)
- No Redis, no RabbitMQ — PostgreSQL + in-process workers are sufficient

### Architecture

```
React Frontend (single app, role-gated routes)
        ↓
FastAPI Monolith (Python)
        ↓
PostgreSQL 16
```

### Roles

| Role | Capabilities |
|------|-------------|
| `super_admin` | Full access; can download private keys; manage admins |
| `admin` | Manage licenses, transition states, generate keys |
| `client` | Request licenses, view own licenses, download public key |

---

## 2. Tech Stack

| Concern | Choice |
|---|---|
| Runtime | Python 3.12 |
| Web framework | FastAPI 0.115.x |
| ORM | SQLAlchemy 2.x async + asyncpg |
| Migrations | Alembic |
| Password hashing | passlib[bcrypt], 12 rounds |
| JWT | python-jose[cryptography], RS256 |
| Crypto | cryptography lib (RSA-2048, AES-256-GCM) |
| Email | fastapi-mail + Jinja2 templates, via BackgroundTasks |
| Rate limiting | slowapi (in-memory) |
| Scheduling | APScheduler 3.x (in-process) |
| Validation/settings | Pydantic v2 + pydantic-settings |
| Frontend | React 18 + Vite + React Router 6 + TanStack Query + Tailwind CSS |
| Infrastructure | docker-compose.yml (Postgres 16 + FastAPI) |

---

## 3. Authentication & User Management

### Auth Endpoints
- `POST /api/v1/auth/register` — register client; fields: `name`, `email`, `password`, `company_name`, `phone`; sends email verification
- `POST /api/v1/auth/login` — returns JWT access token (15 min, RS256) in body + refresh token in httpOnly cookie (7 days)
- `POST /api/v1/auth/refresh` — rotate refresh token silently
- `POST /api/v1/auth/logout` — revoke refresh token
- `POST /api/v1/auth/forgot-password` — send password reset email
- `POST /api/v1/auth/reset-password/{token}` — reset password (one-time token)
- `GET /api/v1/auth/verify-email/{token}` — verify email (one-time token)

Email verify and password reset tokens are stored as columns on `users` (not a separate table) with an expiry timestamp.

### Profile
- `GET /api/v1/users/me`
- `PUT /api/v1/users/me` — name, phone, company
- `PUT /api/v1/users/me/password` — requires current password

### Admin User Management
- `GET /api/v1/admin/users` — list (paginated, filterable)
- `GET /api/v1/admin/users/{id}`
- `PUT /api/v1/admin/users/{id}/role` — change role
- `PUT /api/v1/admin/users/{id}/status` — activate / suspend

### Security
- bcrypt, 12 salt rounds
- RS256 JWT; access token 15 min, refresh token 7 days
- Refresh token stored as SHA-256 hash in DB, rotated on every use
- Rate limiting: 5 attempts / 15 min on `/auth/login` and `/auth/forgot-password` via slowapi
- IP + user-agent logged on login; all events written to `audit_logs`

---

## 4. License Request & State Pipeline

### State Machine

```
requested → in_progress → active → suspended → revoked
                                  ↓            ↓
                                expired (cron, hourly)
```

**Rules:**
- Transitions are validated by `core/state_machine.py` — a pure function with no DB dependency
- Only `admin`/`super_admin` can trigger transitions (except `expired`, which is system/cron only)
- Transition to `active` requires a `license_keys` row to exist for the license
- Every transition is written to `license_transitions` (append-only)

### Client License API
- `POST /api/v1/licenses/request` — body: `{ app_code, plan_id, notes }`; status = `requested`
- `GET /api/v1/licenses/my` — own licenses, paginated
- `GET /api/v1/licenses/my/{id}`
- `GET /api/v1/licenses/my/{id}/public-key` — PEM download (only after `active`)

### Admin License API
- `GET /api/v1/admin/licenses` — filter by status, plan, client, date range
- `GET /api/v1/admin/licenses/{id}`
- `PUT /api/v1/admin/licenses/{id}/status` — transition state (body: `{ new_status, note? }`)
- `PUT /api/v1/admin/licenses/{id}/suspend`
- `PUT /api/v1/admin/licenses/{id}/revoke` — body: `{ reason }`
- `PUT /api/v1/admin/licenses/{id}/reactivate` — suspended → active
- `PUT /api/v1/admin/licenses/{id}/extend` — update `expires_at`

---

## 5. Asymmetric Key Generation & Management

### Flow
1. Admin transitions license to `in_progress`
2. Admin calls `POST /admin/licenses/{id}/keys/generate`
3. Backend generates RSA-2048 key pair
4. Private key encrypted with AES-256-GCM using `MASTER_ENCRYPTION_KEY` from env; stored in DB
5. Admin transitions license to `active`
6. Client can now download the public key PEM

### Key Endpoints
- `POST /api/v1/admin/licenses/{id}/keys/generate` — idempotent (returns existing if already generated); requires status `in_progress`
- `GET /api/v1/admin/licenses/{id}/keys/public` — re-download public key anytime
- `GET /api/v1/admin/licenses/{id}/keys/private` — `super_admin` only; decrypted in memory, never stored decrypted; access logged to `audit_logs`

### Security
- Private key never returned in list endpoints
- `GET .../keys/private` writes an `audit_log` entry with `action = "key.private_downloaded"`
- No key rotation (out of scope)

---

## 6. License Validation Service

### Online Validation (for client applications)
- `POST /api/v1/validate` — body: `{ license_id, app_code, feature? }`
  ```json
  Response: { "allowed": true, "plan": "pro", "expires_at": "...", "features": [...], "limits": {...} }
  ```
- Increments `usage_records.api_calls_count` (direct SQL, no Redis)
- Returns `{ allowed: false, reason: "suspended" }` for suspended/revoked/expired licenses

### Offline Validation (JWT-based)
- `POST /api/v1/validate/token` — issues a JWT signed with the license's RSA private key
  - Payload: `{ license_id, tenant_id, plan, features[], limits{}, exp, iat }`
  - Client application verifies with the stored public key — no server call needed

---

## 7. Plans

Three fixed plans seeded via Alembic migration — no admin CRUD UI:

| Feature | Basic | Pro | Enterprise |
|---|---|---|---|
| Max Users | 5 | 50 | Unlimited |
| API Calls/month | 10,000 | 100,000 | Custom |
| Storage | 2 GB | 20 GB | Custom |
| Advanced AI | ❌ | ✅ | ✅ |
| PDF Export | ❌ | ✅ | ✅ |
| Priority Support | ❌ | ❌ | ✅ |
| Custom Features | ❌ | ❌ | ✅ |

Enterprise licenses can have `custom_limits` / `custom_features` JSONB overrides on the `licenses` row.

- `GET /api/v1/plans` — public, read-only list

---

## 8. Admin Dashboard (React)

### Routes
- `/admin` — summary cards (total/active/pending/expiring soon), recent transitions feed
- `/admin/licenses` — filterable table (status, plan, client, date range)
- `/admin/licenses/:id` — detail: state transition timeline, client info, plan summary, key management panel (generate button, public key copy, private key download for super_admin), status transition button + confirmation modal
- `/admin/users` — user list, role/status management
- `/admin/notifications` — notification list, mark read

---

## 9. Client Portal (React)

### Routes
- `/portal` — active license card with status badge + expiry countdown, usage bars (API calls, users, storage), recent notifications
- `/portal/request` — 4-step wizard: choose app → select plan (feature comparison table) → notes → review & submit
- `/portal/licenses/:id` — status, features list, public key viewer + copy + PEM download, transition history timeline
- `/portal/profile` — update personal/company info, change password

---

## 10. Notification System

### Channels
- **Email** — via `fastapi-mail` + Jinja2 templates, sent as FastAPI `BackgroundTask`
- **In-app** — stored in `notifications` table; React frontend polls `GET /api/v1/notifications/my?unread=true` every 30 seconds (no WebSocket)

### Notification Types
- `license_requested` → admin (email + in-app)
- `license_in_progress` → client (email + in-app)
- `license_active` → client (email + in-app)
- `license_expiring` → client + admin (email) — sent 30, 15, 7, 1 day(s) before
- `license_expired` → client + admin (email)
- `license_suspended` → client (email + in-app)
- `license_revoked` → client (email + in-app)

### Notification API
- `GET /api/v1/notifications/my` — own notifications, paginated; `?unread=true` filter
- `PUT /api/v1/notifications/{id}/read`
- `PUT /api/v1/notifications/read-all`

### Scheduled Jobs (APScheduler, in-process)
- **Hourly:** query `WHERE status IN ('active','suspended') AND expires_at < NOW()` → transition to `expired`, notify
- **Daily 00:00 UTC:** query licenses expiring in exactly 30/15/7/1 days → send warning emails

---

## 11. Applications & Integration

Clients register their applications to use the license validation API.

- `POST /api/v1/applications` — register app: `{ app_code, name, environment }`
- `GET /api/v1/applications` — own registered apps
- Machine-to-machine auth: API key hash stored on `applications.api_key_hash`

---

## 12. Usage Tracking

- `GET /api/v1/usage/{license_id}` — current month summary (admin or own license)
- `GET /api/v1/usage/{license_id}/history` — monthly history

Usage is incremented directly in `usage_records` via SQL `UPDATE ... SET api_calls_count = api_calls_count + 1` on every validation call. No Redis, no raw event log.

Limit enforcement: `POST /validate` checks `usage_records` counters against `plans.limits` and returns `{ allowed: false, reason: "limit_reached" }` when exceeded.

---

## 13. Audit Logs

Append-only table. Never updated or deleted.

- `GET /api/v1/audit/logs` — paginated, super_admin only; filter by action, resource_type, date range

Logged events: `auth.login`, `auth.failed_login`, `auth.logout`, `auth.password_reset`, `user.role_changed`, `user.suspended`, `license.transition`, `license.created`, `key.generated`, `key.private_viewed`, `key.private_downloaded`

---

## 14. Infrastructure

### Environments
- `development` — `docker-compose.yml` (Postgres 16 + FastAPI)
- `staging/production` — same docker-compose with Gunicorn (4 Uvicorn workers)

### Health Check
- `GET /health` → `{ "status": "ok", "db": "connected", "uptime": ... }`

---

## Development Phases

| Phase | Features | Est. Effort |
|---|---|---|
| **Phase 0** | Scaffold: project structure, docker-compose, Alembic init, /health | 1–2 days |
| **Phase 1** | Auth + Users: register/login/refresh, RBAC, email verify, password reset | 4–5 days |
| **Phase 2** | License Lifecycle: state machine, CRUD, plans seeded | 5–6 days |
| **Phase 3** | Key Generation + Validation: RSA keygen, AES encryption, validate endpoint, offline JWT | 5–6 days |
| **Phase 4** | React Frontend: admin dashboard + client portal | 7–10 days |
| **Phase 5** | Notifications + Scheduling: emails, in-app, APScheduler cron, audit log API | 3–4 days |
| **Phase 6** | Webhooks + CI/CD (time permitting) | 3–4 days |
| **Phase 7** | AI Chatbot: LangChain/LlamaIndex RAG router inside the same FastAPI app | TBD |

---

## Deferred / Out of Scope

- Key rotation
- Redis, RabbitMQ, Kafka, Socket.io
- S3 / CDN file storage (avatar upload)
- Firebase push notifications
- Kubernetes / Docker Swarm
- Prometheus / Grafana
- Plan CRUD admin UI (plans are seeded)
- Webhook delivery UI (Phase 6)
- AI Chatbot (Phase 7)
