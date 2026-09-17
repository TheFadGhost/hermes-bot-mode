# Existing Telegram gateway ↔ Bot Mode

This bridge adds three tools to the existing Hermes plugin system. It does not run a Telegram client, start another poller, or replace the gateway.

## Backend setup

Configure a dedicated random secret of at least 32 characters and one authorized private Telegram user ID:

- `BOT_TELEGRAM_BRIDGE_OWNER_ID`
- `BOT_TELEGRAM_BRIDGE_SECRET`

The application integration constructs `TelegramBridge(store, messenger, task_manager, owner_id=..., secret=..., default_model=...)` and calls `.install_routes(api)`. The router prefix remains `/bot/api`. Disabled/missing configuration rejects every request. Keep the backend listener/internal routes on loopback or inside the trusted deployment network; use the existing reverse-proxy policy to deny `/bot/api/internal/` publicly.

Bridge endpoints are authenticated POST requests to `/internal/telegram/action`, `/internal/telegram/memory/sync`, `/internal/telegram/history/import` and `/internal/telegram/history/search`. Action permits bots/create/start/status/cancel/results. None accepts a URL, arbitrary HTTP method, SQL or filesystem path. Sync supplies a source-owner assertion from trusted configuration, which must match the backend's fixed owner; the model cannot provide or override it. Creation and message submission are idempotent for the same request ID and inputs; changed inputs with the same request ID are rejected. The plugin derives request identity from the actual Telegram message context. Repeating the request in a new Telegram message represents a new request.

Jobs run in Bot Mode and their status/results persist after the Telegram turn ends. Backend service restarts currently mark interrupted work failed; they do not resume it automatically. Pending approvals remain in Bot Mode. The bridge retrieves results on request; automatic Telegram completion messages are not implemented and must not be promised.

## Install into the existing Hermes home

Run the reviewed `integration/scripts/install-hermes-bridge.py --owner-id <telegram-id> --home <existing-hermes-home> --write-timer` as the home owner. Enter the same secret at its hidden prompt. Never place it in a command argument or chat. Existing bridge installation/config files are backed up with private permissions. `--reuse-config` keeps an existing configuration for the same owner.

The script installs a normal plugin in `<home>/plugins/bot-mode-bridge` and a mode-0600 `<home>/bot-mode-bridge.json`. A container's `HERMES_HOME` must point to the mounted version of that same home. The configured URL defaults to `http://127.0.0.1:9120/bot/api/internal/telegram`; the client refuses external hosts, proxies and redirects.

The installer does **not** enable the plugin or restart anything. Use the existing gateway environment's supported `hermes plugins enable bot-mode-bridge` command. Confirm the `bot_mode_bridge` toolset is included in Telegram's existing `platform_toolsets`; preserve all existing toolsets. Back up configuration before enabling. Restart only the original gateway during a reviewed quiet window so it discovers the plugin. No changes to `gateway/bot_mode.py` are required.

The plugin requires runtime session context to match platform `telegram`, configured user ID and identical private chat ID. Group chats, other users and missing context fail closed. The model never supplies those identity values.

## Shared memory behavior

- A five-minute one-shot systemd timer can read the existing `memories/USER.md` and `MEMORY.md` under the **same `.md.lock` flock files used by Hermes**. Each changed source gets a private content-addressed backup. Original files are never rewritten.
- File snapshots become shared Bot Mode memory with `telegram-file:<filename>` provenance. Unchanged content is not reimported. Changed content replaces the preceding source version. An explicitly empty file retires its imported revision chain; a missing file is skipped to prevent accidental deletion during a temporary mount problem. A manually deleted import stays deleted until its source content changes.
- Active shared Bot Mode facts are atomically written to `memories/BOT_MODE_SHARED.json`. Replacements and deletions disappear from that mirror on the next successful sync. Private bot memory and vault data are never queried or exported. Imports originating in USER/MEMORY are omitted from the mirror to prevent feedback loops.
- The `bot_mode_memory` tool searches that mirror, optionally refreshing first. Original Hermes has a small MEMORY.md prompt budget, so this bridge does not append an unbounded block into it. Bot Mode facts are available through shared-memory search, not silently inserted into every Telegram prompt. Edit mirrored facts in Bot Mode; editing the generated JSON is temporary and overwritten.
- Existing Telegram source text is not automatically deleted when an imported row is deleted in Bot Mode. Source documents remain authoritative for their own text. This avoids destructive rewrites of the user's original profile/history.

After review, activate the generated user timer using `systemctl --user daemon-reload` and `systemctl --user enable --now hermes-bot-mode-sync.timer`. If scheduling must survive logout, configure the host's usual user-service persistence. It makes one shared-memory request plus bounded history requests per run and does not poll Telegram. A failed sync preserves the last good mirror and all originals. Stop it with `systemctl --user disable --now hermes-bot-mode-sync.timer`.

## Exact visible conversation history

The same timer also imports the existing `<HERMES_HOME>/state.db` history. It opens SQLite with `mode=ro` and `query_only`, and selects only sessions whose source is Telegram, user ID **and** private chat ID equal the configured owner, and chat type is `dm`. Group chats, other users, CLI sessions and unowned sessions are excluded. No account IDs are embedded in source code.

Only nonempty user/assistant text is copied. Assistant tool-call rows, tool/system messages and separate reasoning columns are excluded. Compacted history remains available; inactive non-compacted (rewound) rows are skipped. Structured content contributes explicit text blocks only, never image URLs or reasoning blocks.

The backend inserts archive messages into the existing Chief's continuing home conversation, bootstrapping Chief only if needed. It creates no tasks, fake completions or model jobs. Each message retains original session ID, source message ID and precise source timestamp in metadata; displayed message time uses its original second. The unique owner/session/message mapping makes retries idempotent and lets a replay update that source record instead of duplicating it.

Each import request contains at most 50 messages and approximately 1.2 MB. A scheduled run sends at most ten batches, then resumes on the next run. An owner-bound local checkpoint advances only after backend acknowledgement; lost responses replay safely. Source database replacement or owner reconfiguration resets the cursor. Missing databases or unsupported older schemas are reported as unavailable without creating or modifying the original database. Original history is an append-oriented source: later edits/deletions behind the cursor are not automatically mirrored; reimporting a batch updates its mapped messages.

`bot_mode_history` searches visible Bot Mode conversations across the configured owner's inbox, including imported Telegram history. Search returns bounded excerpts and stable message IDs. Supplying `message_id` returns exact text in 12,000-character chunks; `next_offset` continues a long message. Other owners, isolated helper transcripts, system/tool messages and vault records are excluded. History remains searchable reference data instead of being injected wholesale into every model turn.

Upgrade plugin and backend together: sync checks the backend's owner fingerprint before writing its shared mirror or opening the history database. A configuration mismatch fails closed. No extra timer, Telegram poller or gateway credentials are required.

## Acceptance

Before live use, verify owner/private-DM binding, duplicate creation/start, status/results/cancel, cross-owner denial, secret rejection, shared/private isolation, import dedupe/replacement/empty-file deletion, and preservation of original documents. Then run one harmless Telegram task and inspect its confirmed result. Installation, provider/model execution and live gateway restart require a separate controlled deployment; fixture tests alone are not live acceptance.

