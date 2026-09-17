# Hermes Bot Mode

Bot Mode is a self-hostable messenger for persistent AI Bots, durable conversations, bounded memory, optional routines, and optional desktop automation. The public package contains source and generic setup examples; private application data, browser profiles, runtime authentication, and deployment credentials stay outside the repository.

## Features

- React and TypeScript messenger with desktop and mobile layouts
- FastAPI backend with SQLite persistence, search, files, groups, approvals, and task streaming
- Optional Codex app-server runtime, Composio/OpenRouter provider configuration, and Telegram bridge
- Optional Docker desktop supervisor with per-Bot browser profiles and noVNC viewing
- Optional learned skills and scheduled routines when configured

## Setup

Read [docs/public-setup.md](docs/public-setup.md), then configure a private environment file from `backend/.env.example` or `integration/bot-mode.env.example`. Create the data directory with `sudo install -d -o 10001 -g 10001 -m 700 /var/lib/hermes-bot-mode`. Generate each secret with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`, using different values for `BOT_SESSION_SECRET` and `BOT_INTERNAL_SECRET`. Keep the private environment file and data volume outside the checkout.

For a local operator login after the service is running:

```sh
OWNER_ID=your-stable-owner-id
docker exec -i dad-bot-mode python - --user-id "$OWNER_ID" < integration/scripts/operator-login.py
```

The link is one-use and short-lived. Do not print it in logs or share it. Use the Telegram numeric user ID when the optional bridge is enabled; otherwise choose a stable private owner ID. Telegram sign-in is optional; when the bridge is configured, use the documented `/bot` flow instead.

The Compose template runs the service as UID/GID 10001 and mounts `/var/lib/hermes-bot-mode` at `/data`. On a host deployment, create that directory with `sudo install -d -o 10001 -g 10001 -m 700 /var/lib/hermes-bot-mode`; do not reuse a personal home directory or bind mount unrelated files. Desktop automation requires Docker, the desktop image, and its supervisor configuration.

## License

Application code is MIT licensed. See the vendored SlopMonster attribution and pinned upstream commit under `skills/slopmonster` before redistribution. Review third-party dependency licenses and service terms separately.
