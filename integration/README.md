# Dad bot mode local integration

This directory owns the deployment seam between the existing Hermes Telegram
gateway, the existing aiohttp login proxy, and the separate bot-mode service.
It does not own the FastAPI application or React source.

The Telegram gateway keeps its existing single polling process. After the
gateway patch, `/bot` and `/botmode` are built-in gateway commands. The normal
Hermes authorization gate runs first; the handler then requires a Telegram DM
whose normalized `chat_id` equals `user_id`. It sends exactly:

```http
POST http://127.0.0.1:9120/bot/api/internal/auth/nonce
X-Bot-Internal-Secret: $BOT_INTERNAL_SECRET
Content-Type: application/json

{"user_id":"<telegram-user-id>"}
```

The service returns a JSON object containing `url` and `expires_at`. The URL
uses `/bot/#nonce=...`; a browser GET never consumes the nonce. The service
atomically consumes it when its exchange endpoint receives the nonce and then
sets the scoped authenticated session cookie.

## Source patching

Run these commands only from an operator-controlled checkout or deployment
step. They were not run against the production host during implementation.

```sh
python integration/patch_gateway.py --root /opt/hermes/hermes-agent
python integration/patch_proxy.py --app /opt/hermes/login/app.py
```

Each script checks exact source anchors, refuses partial or unknown patches,
and preserves one `*.dad-bot-mode.bak` copy of every changed existing file.
The gateway patch changes only the command registry and dispatch; it adds the
small `gateway/bot_mode.py` request handler. The proxy patch adds explicit
`/bot` routes before its existing dashboard catch-all, streams HTTP/SSE
responses, and forwards cookies through a WebSocket bridge for future realtime
routes.

The proxy container must be rebuilt using the deployment's existing login
orchestration after patching `app.py`; this integration does not replace that
proxy application or guess its compose project.

## Service template

Build the dedicated service from the bot-mode root so the Dockerfile can copy
the separately-owned backend and frontend trees:

```sh
# The container runs as uid/gid 10001 and stores the SQLite DB, workspaces,
# Codex auth state and runtime state in this host directory.
install -d -m 700 -o 10001 -g 10001 /var/lib/hermes-bot-mode
chown 10001:10001 /var/lib/hermes-bot-mode
docker compose -f integration/compose.bot-mode.yml build
docker compose -f integration/compose.bot-mode.yml up -d
```

The compose file uses host networking but binds the app to `127.0.0.1:9120`,
mounts only `/var/lib/hermes-bot-mode` as `/data`, and starts one backend
process. The image pins `@openai/codex` to `0.154.0`; the backend owns its
single app-server stdio child and uses `/data/codex` for `CODEX_HOME`. Codex
device-code authentication is performed by the operator in that service
context; no Hermes credentials are copied into the bot-mode volume.

The starting service ceiling is 0.75 CPU, 2 GiB RAM, 256 processes and a 256
MiB temporary filesystem. Adjust it only after observing the existing dad
gateway/dashboard workload.

