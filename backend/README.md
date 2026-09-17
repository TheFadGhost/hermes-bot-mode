# Hermes bot mode backend

Run the service from this directory with:

```sh
uvicorn app.main:app --host 127.0.0.1 --port 9120
```

Set `BOT_ENV=production`, `BOT_INTERNAL_SECRET`, `BOT_SESSION_SECRET`,
`BOT_PUBLIC_BASE_URL`, and `BOT_ALLOWED_ORIGINS` before exposing it through the
existing HTTPS proxy. Production refuses to start without both 32-byte-or-
longer secrets, an HTTPS base URL, an origin allowlist, and a Secure cookie.
Keep the database/workspace paths on a private local volume. The default
runtime is explicitly unavailable; set `BOT_RUNTIME=codex` only when the real
Codex app-server adapter is installed and its account has been connected.

The existing Hermes gateway should call
`POST /bot/api/internal/auth/nonce` over loopback using the bearer secret. The
browser consumes that nonce only with `POST /bot/api/auth/exchange`; see
[`API_CONTRACT.md`](API_CONTRACT.md) for request and response shapes.

Run checks with:

```sh
python -m pytest -q
```


