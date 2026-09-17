# Hermes bot mode backend contract

The standalone service listens on `127.0.0.1:9120` and exposes its API under
`/bot/api`. The existing Hermes gateway is the only caller of the internal
nonce endpoint. The browser uses the same HTTPS origin for all other calls.

## Telegram login

The gateway calls:

```http
POST http://127.0.0.1:9120/bot/api/internal/auth/nonce
Authorization: Bearer ${BOT_INTERNAL_SECRET}
Content-Type: application/json

{"user_id":"123456789","chat_id":"123456789"}
```

The endpoint is loopback-only in production. It returns `201` with an opaque
nonce, expiry, and a link containing the nonce in the URL fragment:

```json
{
  "nonce": "<opaque value>",
  "nonce_id": "<uuid>",
  "user_id": "123456789",
  "expires_at": 1789587364,
  "url": "https://example.invalid/bot/#nonce=<opaque value>"
}
```

The page must read and remove the fragment, then send a same-origin request:

```http
POST /bot/api/auth/exchange
Origin: https://example.invalid
Content-Type: application/json

{"nonce":"<opaque value>"}
```

Only this POST consumes the nonce. Consumption and session creation are one
SQLite transaction. Replay, expiry, and malformed values return:

```json
{"error":{"code":"nonce_invalid","message":"The login link is invalid, expired, or already used"}}
```

The successful response sets an HttpOnly, Secure, SameSite=Lax cookie named
`__Secure-dad_bot_session` in production with `Path=/bot`. Development uses a
non-Secure `dad_bot_session` cookie so local HTTP tests work. Session state is
stored as a keyed hash and supports `POST /auth/logout` and
`POST /auth/revoke-all`.

## Authenticated resources

Authenticated JSON resources use the current session's Telegram `user_id` as
the owner. Mutating requests require a matching `Origin` from
`BOT_ALLOWED_ORIGINS` (or the configured public URL).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/auth/me` | Session and owner |
| POST | `/auth/logout` | Revoke this session |
| POST | `/auth/revoke-all` | Revoke every owner session |
| GET/POST | `/auth/sessions[/{id}/revoke]` | Inspect or revoke one owner session |
| GET/POST/PATCH/DELETE | `/agents[/{id}]` | Agent CRUD; desktop state starts unavailable |
| GET/POST | `/conversations[/{id}]` | Conversation persistence |
| GET | `/conversations/{id}/messages` | Durable messages |
| POST | `/conversations/{id}/messages` | Store user message and return `202` task |
| GET | `/tasks/{id}` | Durable task status and errors |
| GET | `/tasks/{id}/events` | Authenticated `text/event-stream` |
| POST | `/tasks/{id}/cancel` | Cancel a task |
| GET | `/tasks/{id}/approvals` | Runtime approval state |
| POST | `/tasks/{id}/approvals/{approval_id}` | Runtime approval decision |
| GET/POST/PATCH/DELETE | `/memory[/{id}]` | Shared/private memory CRUD |
| GET | `/memory/search?q=...` | FTS5 retrieval with owner/agent ACL |
| GET/POST/DELETE | `/files[/{id}]` | Scoped workspace file metadata |
| GET | `/files/{id}/download` | Scoped file download |
| GET/PATCH | `/settings` | Owner settings |
| GET/POST | `/onboarding`, `/onboarding/complete` | First-run state |
| GET | `/activity` | Recent audit events |
| GET | `/activity/events` | Authenticated audit SSE |
| GET | `/runtime/status` | Real runtime availability |
| GET/POST/GET | `/runtime/account`, `/runtime/login`, `/runtime/usage` | Optional Codex account flow |
| POST | `/conversations/{id}/compact` | Optional runtime compaction |

Errors are always shaped as `{ "error": { "code": "...", "message": "..." } }`.
Runtime-unavailable chat tasks fail durably with `error.code` set to
`runtime_unavailable`; the service never substitutes a demo assistant answer.

