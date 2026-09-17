# Desktop lifecycle integration

The private supervisor imports `lifecycle.py`; deploy both files together and rebuild the desktop image for `start.sh` or `vnc_server.py` changes. Run one supervisor worker. The API never receives the Docker socket. Build the updated image before restarting the supervisor. Stopped containers without `dad-bot.desktop-version=2` are recreated automatically on their next start, preserving their bound UUID profile. Running old containers require Pause then Start; they are never replaced during active work.

- `BOT_DESKTOP_MAX_RUNNING` defaults to 1 (maximum 2).
- `BOT_DESKTOP_IDLE_TTL` defaults to 300 seconds (minimum 15).
- Container profiles remain in their existing private per-agent directories.
- Sleeping containers are stopped with restart policy `no`. They consume no browser CPU or RAM; the small supervisor remains running.
- Viewer leases expire after 45 seconds. Visible viewers heartbeat every 15 seconds. Read-only status calls do not renew leases.
- Task leases expire after 90 seconds; the backend renews them every 30 seconds until `release_task`.
- Leases and ownership generations persist atomically in `BOT_DESKTOP_DATA/desktop-leases.json`. Startup enumerates all labeled containers independently, disables automatic restarts, revokes old generations, applies VNC ownership policy, and resumes idle cleanup.

Backend integration:

```python
register_desktop_routes(api, store=store, desktop=desktop,
    current_session=current_session, require_origin=require_origin)
await desktop.create(agent_id, viewer_id=session.id)  # user Open
await desktop.create(agent_id, task_id=request.task_id, cancel_check=cancel_check)
await desktop.action(agent_id, params, task_id=request.task_id, cancel_check=cancel_check)
# Always in the owning task's finally, including failures and cancellation:
await desktop.release_task(agent_id, task_id)
```

`create` accepts `wait_timeout` (default60 seconds) and does not evict a live viewer, task, or action. Cancellation interrupts capacity waiting. `action` also accepts an explicit `generation`; authenticated task identity overrides any model-supplied fields.

The added authenticated routes are `POST /agents/{id}/desktop/control` with `{mode: "manual" | "bot"}`, and `POST /agents/{id}/desktop/heartbeat` with `{generation, visible}`. Both return `{desktop: ...}`. Lifecycle state includes `phase`, `control_mode`, and `generation`. Heartbeat optionally accepts a bounded `viewer_token` for independent full-screen viewer lifetimes; identity remains prefixed by the authenticated session.

A per-desktop lock covers model actions, screenshots, handoff, and stopping. Handoff asks the private local VNC manager to terminate only its x11vnc child (TERM, then bounded KILL if necessary), start a replacement with the correct input policy, and verify RFB readiness. Every old client is disconnected before manual input is enabled; bot mode starts with server-side view-only. Xvfb, Chromium, and the private profile remain running throughout. This avoids x11vnc remote-command starvation when a viewer stops reading framebuffer data. The viewer WebSocket additionally rejects stale generations. Old tasks must call computer_start again after ownership changes. Task cancellation keeps the lock until the bounded in-container action has completed.

Validation: `PYTHONPATH=backend python -m pytest backend/tests/test_desktop_lifecycle.py backend/tests/test_desktop_lifecycle_api.py`. Actual Docker/x11vnc, private-profile login persistence, and deployment require Linux smoke verification.

Run `python3 verify_vnc_handoff.py /usr/local/bin/desktop-vnc.py` inside an awake QA desktop for the blocked-client regression. It uses a separate temporary VNC port/control socket, checks repeated manual/bot transitions while a full-frame client stops reading, then verifies fresh pixels and enforced pointer input policy. It moves the QA pointer but does not change browser/profile data.

