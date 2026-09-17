# Hermes Bot Mode

Bot Mode is a self-hostable messenger for persistent AI Bots, durable conversations, bounded memory, optional routines, and optional desktop automation. The public package contains source and generic setup examples; private application data, browser profiles, runtime authentication, and deployment credentials stay outside the repository.

## Features

- React and TypeScript messenger with desktop and mobile layouts
- FastAPI backend with SQLite persistence, search, files, groups, approvals, and task streaming
- Optional Codex app-server runtime, Composio/OpenRouter provider configuration, and Telegram bridge
- Optional Docker desktop supervisor with per-Bot browser profiles and noVNC viewing
- Optional learned skills and scheduled routines when configured

## Setup

Read [docs/public-setup.md](docs/public-setup.md), then configure a private environment file from `backend/.env.example` or `integration/bot-mode.env.example`. Use an HTTPS origin for remote access and generate independent random session/internal secrets. Keep the data volume outside the checkout.

For a local operator login after the service is running:

```sh
PYTHONPATH=backend python integration/scripts/operator-login.py --user-id YOUR_OWNER_ID
```

The link is one-use and short-lived. Do not print it in logs or share it. Telegram sign-in is optional; when the bridge is configured, use the documented `/bot` flow instead.

The Compose template runs the service as its configured container user and mounts a dedicated data directory at `/data`. On a host deployment, create that directory with the UID/GID required by the image and keep ownership consistent; do not reuse a personal home directory or bind mount unrelated files. Desktop automation requires Docker, the desktop image, and its supervisor configuration.

## License

Application code is MIT licensed. See the vendored SlopMonster attribution and pinned upstream commit under `skills/slopmonster` before redistribution. Review third-party dependency licenses and service terms separately.
