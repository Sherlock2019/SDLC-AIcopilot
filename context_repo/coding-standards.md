---
type: standard
status: current
owner: Platform Engineering
---
# Coding Standards

## General

- **CS-1** Python 3.12, formatted and linted with ruff. Lines up to 120 characters.
- **CS-2** Public functions carry type hints. Request and response bodies are Pydantic models
  with explicit length limits on every string field.
- **CS-3** No new runtime dependency without an approved architecture decision (see ARCH-1).

## Data access

- **CS-4** SQL is always parameterized. Building SQL with f-strings, `%` formatting, `+`
  concatenation or `.format()` is forbidden, including for values that "cannot" be user input.
- **CS-5** One database connection per request, obtained from the `get_db` dependency.

## Errors and logging

- **CS-6** Raise `HTTPException` with a stable, human-readable `detail`. Never return stack traces.
- **CS-7** Use the module logger (`logging.getLogger("portal.<module>")`) with `%s` placeholders.
  Log event names and internal identifiers only. Never log secrets, tokens, passwords or email.
- **CS-8** Do not catch bare `Exception` unless the handler re-raises or logs and converts to a
  defined error response.

## Tests

- **CS-9** Every new endpoint ships with API tests, negative tests and security tests.
- **CS-10** Total line coverage must stay above 80 percent. A change may not lower coverage.
- **CS-11** Tests must not depend on wall-clock sleeps. Patch the clock instead.

## Change management

- **CS-12** All changes arrive through a pull request from a feature branch. Nobody, human or
  AI, commits directly to `main`.
- **CS-13** Pipeline definitions under `.github/workflows/` are owned by Platform Engineering
  and change only with CODEOWNER approval.
