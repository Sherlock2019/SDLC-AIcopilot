---
type: architecture
status: current
owner: Customer Identity
---
# Database Schema

## users

| Column | Type | Notes |
|--------|------|-------|
| id | integer, primary key | Internal identifier. Safe to log. |
| email | text, unique | Stored lowercase. Personal data, never logged. |
| full_name | text | Personal data. |
| password_hash | text | `pbkdf2_sha256$iterations$salt$hash` |
| created_at | real | Unix timestamp |

## sessions

| Column | Type | Notes |
|--------|------|-------|
| token_hash | text, primary key | SHA-256 of the bearer token |
| user_id | integer, foreign key users.id | |
| expires_at | real | Unix timestamp |

## Rules for new tables

- **DB-1** Anything that works like a credential (session, reset token, API key) is stored as a
  hash in a column named `<thing>_hash`. The plaintext value is never stored.
- **DB-2** Time-limited rows carry `created_at` and `expires_at`. Single-use rows carry a
  nullable `used_at`.
- **DB-3** Schema changes are additive and idempotent (`CREATE TABLE IF NOT EXISTS`). Dropping
  or renaming a column needs a migration plan approved by an architect.
- **DB-4** Add an index for every lookup used on a request path.
