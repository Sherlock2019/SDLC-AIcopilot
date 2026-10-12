---
type: standard
status: current
owner: API Guild
---
# API Guidelines

## Resource design

- **API-1** Paths are lowercase, hyphenated nouns: `/password-reset/request`, not `/resetPassword`.
- **API-2** `POST` for actions that change state. `GET` endpoints have no side effects.
- **API-3** Request and response bodies are JSON objects, never bare arrays or strings.

## Status codes

- **API-4** `200` success with a body, `202` accepted for work whose outcome is delivered
  out of band (for example an email), `400` invalid business input, `401` unauthenticated,
  `404` unknown resource, `422` schema validation failure, `429` rate limited.
- **API-5** An endpoint that must not reveal whether a resource exists returns the same status
  and body in both cases (see SEC-3 and SEC-11). Do not use `404` there.

## Errors

- **API-6** Error bodies have the shape `{"detail": "<stable message>"}`. Messages are safe to
  show to a customer and never include internal identifiers, SQL or stack traces.

## Compatibility

- **API-7** Existing endpoints are not changed in a breaking way. Add fields, never rename or
  remove them without a version bump.
- **API-8** Every new endpoint appears in the OpenAPI schema with a tag and typed models.

## Limits

- **API-9** Every string field declares `max_length`. Bodies larger than 64 KB are rejected.
