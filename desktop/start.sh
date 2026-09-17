#!/bin/sh
set -eu
# This container owns display :99. Docker stop/start preserves /tmp, so stale
# X locks from a terminated process must not prevent the next boot.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
# Exactly one container owns this persistent profile; a replaced container has
# a different hostname, so Chromium cannot clear its own stale singleton links.
rm -f /profile/SingletonLock /profile/SingletonSocket /profile/SingletonCookie
pids=""
cleanup() {
    trap - EXIT TERM INT
    if [ -n "${browser_pid:-}" ]; then
        kill "$browser_pid" 2>/dev/null || true
        # Allow Chromium to flush this desktop's profile, then bound shutdown.
        (sleep 8; kill -KILL "$browser_pid" 2>/dev/null || true) &
        shutdown_guard=$!
        wait "$browser_pid" 2>/dev/null || true
        kill "$shutdown_guard" 2>/dev/null || true
    fi
    for pid in $pids; do kill "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
}
trap 'cleanup; exit 0' TERM INT
trap cleanup EXIT
Xvfb :99 -screen 0 1366x900x24 -nolisten tcp &
pids="$pids $!"
attempt=0
until xdotool getdisplaygeometry >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 50 ] || exit 1
    sleep 0.1
done
openbox &
pids="$pids $!"
python3 /usr/local/bin/desktop-vnc.py serve &
pids="$pids $!"
websockify --web /usr/share/novnc 0.0.0.0:6080 localhost:5900 &
pids="$pids $!"
# Browser runs as an unprivileged user within its own capped container.
chromium --no-sandbox --disable-dev-shm-usage --no-first-run --no-default-browser-check --disable-background-networking --password-store=basic --user-data-dir=/profile --window-size=1366,860 --restore-last-session &
browser_pid=$!
pids="$pids $browser_pid"
# Do not leave a healthy-looking web server around a dead display/browser.
while :; do
    for pid in $pids; do kill -0 "$pid" 2>/dev/null || exit 1; done
    sleep 2
done

