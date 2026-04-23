# Database Structure — License Management Platform

> **Engine:** PostgreSQL 16
> **ORM:** SQLAlchemy 2.x async (asyncpg driver)
> **Migrations:** Alembic
> **Conventions:** `snake_case` | UUID PKs (`gen_random_uuid()`) | `created_at` / `updated_at` on all tables | soft-delete via `deleted_at` where applicable

---

## Table Summary (11 tables)

| Table | Description |
|---|---|
| `users` | All accounts (super_admin, admin, client) |
| `refresh_tokens` | JWT refresh tokens (rotated on use) |
| `plans` | Basic / Pro / Enterprise (seeded, not admin-editable) |
| `applications` | Client-registered apps that use the validation API |
| `licenses` | Core entity; tracks state machine lifecycle |
| `license_transitions` | Append-only state change log |
| `license_keys` | RSA-2048 key pair per license |
| `notifications` | In-app and email notification records |
| `usage_records` | Monthly aggregate usage per license |
| `audit_logs` | Append-only security and admin event log |
| `webhooks` + `webhook_deliveries` | Schema defined in migration; API routes deferred to Phase 6 |

---

## 1. `users`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK, `gen_random_uuid()` |
| `email` | VARCHAR(255) | UNIQUE (partial: `WHERE deleted_at IS NULL`), NOT NULL |
| `password_hash` | VARCHAR(255) | NOT NULL |
| `name` | VARCHAR(150) | NOT NULL |
| `company_name` | VARCHAR(200) | NULLABLE |
| `phone` | VARCHAR(50) | NULLABLE |
| `avatar_url` | TEXT | NULLABLE |
| `role` | ENUM | NOT NULL, default `'client'` — values: `super_admin`, `admin`, `client` |
| `status` | ENUM | NOT NULL, default `'pending_verification'` — values: `active`, `suspended`, `pending_verification` |
| `email_verified` | BOOLEAN | NOT NULL, default `false` |
| `email_verify_token` | VARCHAR(255) | NULLABLE, UNIQUE |
| `email_verify_expires_at` | TIMESTAMPTZ | NULLABLE |
| `password_reset_token` | VARCHAR(255) | NULLABLE, UNIQUE |
| `password_reset_expires_at` | TIMESTAMPTZ | NULLABLE |
| `last_login_at` | TIMESTAMPTZ | NULLABLE |
| `last_login_ip` | VARCHAR(45) | NULLABLE |
| `email_opt_in` | BOOLEAN | NOT NULL, default `true` |
| `in_app_opt_in` | BOOLEAN | NOT NULL, default `true` |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `deleted_at` | TIMESTAMPTZ | NULLABLE |

**Indexes:** `INDEX` on `role`, `status`

> `email_opt_in` / `in_app_opt_in` replace the separate `notification_preferences` table.
> Email verify and password reset tokens are stored here with expiry columns — no separate tokens table.

---

## 2. `refresh_tokens`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `user_id` | UUID | FK → `users.id`, NOT NULL |
| `token_hash` | VARCHAR(255) | UNIQUE, NOT NULL — SHA-256 of actual token |
| `expires_at` | TIMESTAMPTZ | NOT NULL |
| `revoked` | BOOLEAN | NOT NULL, default `false` |
| `revoked_at` | TIMESTAMPTZ | NULLABLE |
| `ip_address` | VARCHAR(45) | NULLABLE |
| `user_agent` | TEXT | NULLABLE |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

**Indexes:** `INDEX` on `user_id`, `UNIQUE INDEX` on `token_hash`

---

## 3. `plans`

Seeded with three rows (Basic, Pro, Enterprise) via Alembic migration `0002`. No admin CRUD.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `name` | VARCHAR(100) | UNIQUE, NOT NULL — e.g., `Pro` |
| `slug` | VARCHAR(100) | UNIQUE, NOT NULL — e.g., `pro` |
| `description` | TEXT | NULLABLE |
| `features` | JSONB | NOT NULL — array of feature key strings, e.g., `["advanced_ai", "export_pdf"]` |
| `limits` | JSONB | NOT NULL — `{"max_users": 50, "api_calls_per_month": 100000, "storage_gb": 20}` |
| `is_active` | BOOLEAN | NOT NULL, default `true` |
| `sort_order` | INTEGER | NOT NULL, default `0` |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

> JSONB replaces the `features` + `plan_features` junction tables from the original schema. Three fixed plans don't need a relational feature catalog.

---

## 4. `applications`

Client-registered applications that call the validation API.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `app_code` | VARCHAR(100) | UNIQUE, NOT NULL |
| `name` | VARCHAR(200) | NOT NULL |
| `description` | TEXT | NULLABLE |
| `owner_id` | UUID | FK → `users.id`, NOT NULL |
| `environment` | ENUM | NOT NULL, default `'production'` — values: `production`, `staging`, `development` |
| `api_key_hash` | VARCHAR(255) | NULLABLE — hashed API key for machine-to-machine auth |
| `is_active` | BOOLEAN | NOT NULL, default `true` |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `deleted_at` | TIMESTAMPTZ | NULLABLE |

**Indexes:** `UNIQUE INDEX` on `app_code`, `INDEX` on `owner_id`

---

## 5. `licenses`

Core entity. Tracks the full lifecycle.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `license_number` | VARCHAR(50) | UNIQUE, NOT NULL — e.g., `LIC-2025-0001` |
| `client_id` | UUID | FK → `users.id`, NOT NULL |
| `application_id` | UUID | FK → `applications.id`, NOT NULL |
| `plan_id` | UUID | FK → `plans.id`, NOT NULL |
| `status` | ENUM | NOT NULL, default `'requested'` — values: `requested`, `in_progress`, `active`, `suspended`, `revoked`, `expired` |
| `notes` | TEXT | NULLABLE — client notes at request time |
| `admin_notes` | TEXT | NULLABLE |
| `requested_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `activated_at` | TIMESTAMPTZ | NULLABLE |
| `expires_at` | TIMESTAMPTZ | NULLABLE |
| `suspended_at` | TIMESTAMPTZ | NULLABLE |
| `revoked_at` | TIMESTAMPTZ | NULLABLE |
| `revoked_by` | UUID | FK → `users.id`, NULLABLE |
| `revoke_reason` | TEXT | NULLABLE |
| `custom_limits` | JSONB | NULLABLE — Enterprise per-license overrides to `plans.limits` |
| `custom_features` | JSONB | NULLABLE — feature overrides beyond plan |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

**Indexes:** `INDEX` on `client_id`, `status`, `expires_at`; `UNIQUE INDEX` on `license_number`

> `completed` status removed — `active` is the sole terminal-positive state.

---

## 6. `license_transitions`

Append-only. Never updated or deleted.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `license_id` | UUID | FK → `licenses.id`, NOT NULL |
| `from_status` | VARCHAR(50) | NULLABLE — `NULL` on initial creation |
| `to_status` | VARCHAR(50) | NOT NULL |
| `actor_id` | UUID | FK → `users.id`, NULLABLE — `NULL` for system (cron) transitions |
| `note` | TEXT | NULLABLE |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

**Indexes:** `INDEX` on `license_id`, `created_at`

---

## 7. `license_keys`

One RSA-2048 key pair per license. Generated once.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `license_id` | UUID | FK → `licenses.id`, UNIQUE, NOT NULL |
| `public_key` | TEXT | NOT NULL — PEM-encoded |
| `private_key_encrypted` | TEXT | NOT NULL — AES-256-GCM ciphertext, base64-encoded |
| `encryption_iv` | TEXT | NOT NULL — AES-GCM IV, base64-encoded |
| `generated_by` | UUID | FK → `users.id`, NOT NULL |
| `private_key_first_downloaded_at` | TIMESTAMPTZ | NULLABLE |
| `private_key_first_downloaded_by` | UUID | FK → `users.id`, NULLABLE |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

**Indexes:** `UNIQUE INDEX` on `license_id`

> `encryption_key_id` removed — master key comes from `MASTER_ENCRYPTION_KEY` env var.
> No `key_version` or `previous_public_key` — no key rotation in scope.
> Private key access events are written to `audit_logs` instead of a separate `key_access_logs` table.

---

## 8. `notifications`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `user_id` | UUID | FK → `users.id`, NOT NULL |
| `license_id` | UUID | FK → `licenses.id`, NULLABLE |
| `type` | ENUM | NOT NULL — values: `license_requested`, `license_in_progress`, `license_active`, `license_expiring`, `license_expired`, `license_suspended`, `license_revoked`, `usage_warning`, `system` |
| `title` | VARCHAR(255) | NOT NULL |
| `message` | TEXT | NOT NULL |
| `channel` | ENUM | NOT NULL — values: `in_app`, `email` |
| `is_read` | BOOLEAN | NOT NULL, default `false` |
| `read_at` | TIMESTAMPTZ | NULLABLE |
| `sent_at` | TIMESTAMPTZ | NULLABLE |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

**Indexes:** `INDEX` on `user_id`, `(user_id, is_read)`, `license_id`

> Push channel removed. `metadata` JSONB removed. In-app delivery is via 30-second client polling.

---

## 9. `usage_records`

Monthly aggregated usage per license. No raw event table.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `license_id` | UUID | FK → `licenses.id`, NOT NULL |
| `year` | SMALLINT | NOT NULL |
| `month` | SMALLINT | NOT NULL — 1–12 |
| `api_calls_count` | BIGINT | NOT NULL, default `0` |
| `active_users_count` | INTEGER | NOT NULL, default `0` |
| `storage_used_mb` | BIGINT | NOT NULL, default `0` |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

**Constraints:** `UNIQUE(license_id, year, month)`

> Counters are incremented via direct SQL `UPDATE ... SET api_calls_count = api_calls_count + 1` on the validation endpoint. No Redis.

---

## 10. `audit_logs`

Append-only. Never updated or deleted.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `actor_id` | UUID | FK → `users.id`, NULLABLE — `NULL` = system |
| `actor_role` | VARCHAR(50) | NULLABLE — role at time of action |
| `action` | VARCHAR(200) | NOT NULL — e.g., `auth.login`, `key.private_downloaded`, `license.transition` |
| `resource_type` | VARCHAR(100) | NULLABLE — e.g., `license`, `user`, `license_key` |
| `resource_id` | UUID | NULLABLE |
| `old_value` | JSONB | NULLABLE |
| `new_value` | JSONB | NULLABLE |
| `ip_address` | VARCHAR(45) | NULLABLE |
| `request_id` | UUID | NULLABLE — HTTP request correlation ID |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

**Indexes:** `INDEX` on `actor_id`, `(resource_type, resource_id)`, `action`, `created_at`

> Absorbs all key access logging — no separate `key_access_logs` table.

---

## 11. `webhooks` + `webhook_deliveries`

Schema defined in migration `0001`. No API routes until Phase 6.

### `webhooks`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `license_id` | UUID | FK → `licenses.id`, NOT NULL |
| `url` | TEXT | NOT NULL |
| `secret_hash` | VARCHAR(255) | NOT NULL — HMAC signing secret (hashed) |
| `events` | TEXT[] | NOT NULL — e.g., `['license.activated', 'license.revoked']` |
| `is_active` | BOOLEAN | NOT NULL, default `true` |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

### `webhook_deliveries`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `webhook_id` | UUID | FK → `webhooks.id`, NOT NULL |
| `event_type` | VARCHAR(100) | NOT NULL |
| `payload` | JSONB | NOT NULL |
| `response_status` | SMALLINT | NULLABLE |
| `response_body` | TEXT | NULLABLE — truncated to 2000 chars |
| `attempt_count` | SMALLINT | NOT NULL, default `1` |
| `succeeded` | BOOLEAN | NOT NULL, default `false` |
| `next_retry_at` | TIMESTAMPTZ | NULLABLE — exponential backoff |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `NOW()` |

---

## Entity Relationships

```
users (1) ──── (many) refresh_tokens
users (1) ──── (many) licenses           [as client]
users (1) ──── (many) audit_logs         [as actor]
users (1) ──── (many) applications       [as owner]

licenses (1) ──── (many) license_transitions
licenses (1) ──── (1)    license_keys
licenses (1) ──── (many) usage_records
licenses (1) ──── (many) notifications
licenses (1) ──── (many) webhooks

webhooks (1) ──── (many) webhook_deliveries

plans (1) ──── (many) licenses
applications (1) ──── (many) licenses
```

---

## Alembic Migrations

| File | Content |
|---|---|
| `0001_initial_schema.py` | All 11 tables (including webhook tables) |
| `0002_seed_plans.py` | INSERT Basic, Pro, Enterprise rows into `plans` |
| `0003_chatbot_tables.py` | `chatbot_sessions`, `chatbot_messages`, `chatbot_feedback`, `knowledge_base_articles` — added in Phase 7 only |

---

## Removed Tables (vs. original schema)

| Table | Reason |
|---|---|
| `features` | Replaced by `plans.features` JSONB array |
| `plan_features` | Replaced by `plans.features` JSONB array |
| `notification_preferences` | Replaced by `users.email_opt_in` / `in_app_opt_in` columns |
| `key_access_logs` | Folded into `audit_logs` |
| `usage_events` | Raw event log removed; monthly aggregate is sufficient |
| `chatbot_sessions` | Deferred to Phase 7 migration |
| `chatbot_messages` | Deferred to Phase 7 migration |
| `chatbot_feedback` | Deferred to Phase 7 migration |
| `knowledge_base_articles` | Deferred to Phase 7 migration |
