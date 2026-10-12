---
type: incident
status: current
owner: Site Reliability Engineering
---
# Incident History

## INC-2025-014 - Session tokens written to debug logs

- **Symptom** Security review found bearer tokens in application logs.
- **Root cause** A debug statement logged the full request headers.
- **Fix** Removed the statement, rotated sessions, added a log-scanning test.
- **Lesson** Tokens of any kind must never reach a logger (now SEC-9, CS-7).

## INC-2025-022 - Login returned 500 after schema change

- **Symptom** `POST /login` returned HTTP 500 for all customers for 41 minutes.
- **Root cause** A column was renamed in code but the migration was not part of the release.
- **Fix** Rolled back the release, then shipped code and migration together.
- **Lesson** The most recent change is the first suspect. Roll back before debugging.

## INC-2025-031 - Account enumeration through the sign-up form

- **Symptom** Automated traffic used different error messages to discover valid emails.
- **Root cause** "Email already registered" versus "Invalid email" responses.
- **Fix** One generic response for both cases (now SEC-3, SEC-11, API-5).
- **Lesson** Any endpoint that accepts an email must behave identically for known and unknown accounts.

## INC-2026-004 - Pipeline change deployed an unreviewed build

- **Symptom** A feature branch build reached production without review.
- **Root cause** A workflow file edit on a branch removed the branch filter from the deploy job.
  The automation account that made the edit had general repository write access.
- **Fix** CODEOWNER approval for `.github/workflows/`, a separate deployment identity, and
  removal of workflow write access from every automation account.
- **Lesson** Write access to pipeline definitions is production access. Audit what an identity
  can reach, not only what it was granted.
