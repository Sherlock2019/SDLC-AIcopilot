---
type: architecture
status: current
owner: Solution Architecture
---
# Customer Portal - Architecture

## Components

- **API service** - Python 3.12, FastAPI, one process per container. Modules: `main.py`
  (application wiring), `auth.py` (login, sessions, profile), `security.py` (hashing),
  `db.py` (data access), `config.py` (environment configuration).
- **Database** - SQLite for local development and tests, PostgreSQL in shared environments.
- **Frontend** - a static page that calls the API. It holds no business logic.
- **Notification service** - outbound email goes through `notifications.py`. No other
  module may talk to a mail provider.

## Approved technology (ARCH-1)

Python standard library, FastAPI, Pydantic, SQLite/PostgreSQL. New runtime dependencies,
message brokers, caches or external services require an architecture decision record and
architect approval before any code is written.

## Boundaries (ARCH-2)

Routers contain HTTP concerns only. Hashing and token handling live in `security.py`.
SQL lives next to the router that owns the table and always goes through `db.get_db`.

## Request flow

Client -> FastAPI router -> dependency (`get_db`, `get_current_user`) -> SQL -> response.
Sessions are opaque random tokens; only their SHA-256 hash is stored.

## Configuration (ARCH-3)

All configuration is read in `config.py` from environment variables with safe defaults.
A setting that has no safe default must be validated at start-up so a missing value fails
the deployment health check instead of failing customer requests later.

## Observability (ARCH-4)

Every endpoint logs one structured line per outcome with a stable event name and the
internal `user_id`. Logs never contain passwords, tokens or email addresses. Error rate
and latency are tracked per route.

## Non-goals

No multi-region deployment, no single sign-on, no admin interface.
