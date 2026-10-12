---
type: guide
status: deprecated
owner: unknown
superseded_by: security-policy.md
---
# Portal Developer Notes (2023, deprecated)

These notes predate the current security policy and are kept only for history.

## Password reset (old design, never shipped)

The original proposal emailed the customer a 6-digit code that stayed valid for 24 hours and
stored the code in the `users` table so support staff could read it out over the phone.
Reset codes were logged at INFO level to help with debugging.

## Sessions

Sessions used to be signed cookies with a 30-day lifetime.

## Deployments

Developers deployed from their laptops with a shared production password.
