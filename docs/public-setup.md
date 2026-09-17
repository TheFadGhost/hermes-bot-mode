# Public setup

This repository is intended for people who want to run Bot Mode on their own host. It contains source and generic examples only. It does not include application data, browser profiles, Codex authentication, production deployment files, screenshots, logs, or real environment values.

The MIT licensed application code is independent of the runtime and third-party services. Review each dependency's license before redistribution. The vendored SlopMonster writing helper is separately attributed as MIT licensed and pinned to the upstream commit recorded in `skills/slopmonster/UPSTREAM_COMMIT`; retain that attribution when redistributing. Composio, OpenRouter, and Telegram are optional integrations; configure their own accounts and credentials only in private operator configuration. Desktop automation is optional and works only when Docker, the desktop image, and its supervisor are configured.

## Prerequisites

- Linux host with Docker Engine and Docker Compose v2
- A reachable HTTPS origin if browser sessions or Telegram sign-in are enabled
- An operator-managed model/runtime account
- Optional accounts for Composio, OpenRouter, Telegram, or other configured integrations
- At least 0.75 CPU and 2 GiB RAM for the service, plus storage for SQLite and workspaces

## Configure

1. Copy `backend/.env.example` or `integration/bot-mode.env.example` to a private environment file outside Git.
2. Replace every secret placeholder with independent random values of at least 32 bytes.
3. Set `BOT_PUBLIC_BASE_URL` and `BOT_ALLOWED_ORIGINS` to the deployment's own HTTPS origin.
4. Choose a writable data directory owned by the service user. Keep the SQLite database, workspaces, runtime auth, and desktop profiles outside the checkout.
5. Authenticate the selected model/runtime as the operator. Do not put refresh tokens or API keys in this repository.

## Run the standalone service

From the repository root:

```sh
docker compose --env-file /path/to/private/bot-mode.env -f integration/compose.bot-mode.yml build
docker compose --env-file /path/to/private/bot-mode.env -f integration/compose.bot-mode.yml up -d
```

The compose template uses local loopback defaults and a data bind mount. Review the network, origin, resource, and reverse-proxy settings for the target host before exposing it. The Telegram gateway patch scripts are optional integration code and require an operator-controlled Hermes checkout; they do not provide authentication by themselves.

## Verify and operate

```sh
curl -fsS http://127.0.0.1:9120/bot/api/healthz
PYTHONPATH=backend python -m pytest backend/tests integration/tests
```

Keep production data and secrets in a separate backup process. For a private backup, first make a consistent database snapshot, include only the required source/config and encrypted data artifact, retain the encryption key outside GitHub, verify restore, and delete plaintext temporary archives.

The private backup helper is `integration/scripts/github-backup.py`. Install its `cryptography` dependency in the operator environment, run it on the server after quiescing writes, and keep the printed recovery key outside GitHub. It snapshots `.sqlite`, `.sqlite3`, and `.db` files with SQLite's backup API and excludes `-wal`/`-shm` sidecars; use `--include /path/to/full-hermes-home` when a complete original Hermes home is required. Use `--fixture` to verify the encryption/decryption path without touching real data.

## Public repository hygiene

Before publishing, run `integration/scripts/github-stage-public.ps1` and inspect the staging directory. Search the staging tree for hostnames, usernames, tokens, `.env`, database files, workspaces, browser profiles, logs, screenshots, and personal Telegram identifiers. Publish only after a human review of the generated file list and a clean secret scan.

