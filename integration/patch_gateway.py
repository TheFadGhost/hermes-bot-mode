"""Apply the small, verified Hermes gateway bot-mode integration patch.

Usage (operator-run on a checked-out Hermes source tree)::

    python integration/patch_gateway.py --root /opt/hermes/hermes-agent

The script edits only ``hermes_cli/commands.py``, ``gateway/run.py`` and adds
``gateway/bot_mode.py``.  It verifies exact anchors, creates one recoverable
``*.dad-bot-mode.bak`` per changed existing file, and refuses to overwrite an
unrecognized existing helper or silently patch a source revision it does not
understand.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


class PatchError(RuntimeError):
    """Raised when a source tree is not the expected Hermes revision."""


COMMAND_MARKER = "# DAD_BOT_MODE_COMMAND"
RUN_COLD_MARKER = "# DAD_BOT_MODE_COLD_DISPATCH"
RUN_ACTIVE_MARKER = "# DAD_BOT_MODE_ACTIVE_DISPATCH"
HELPER_MARKER = "# DAD_BOT_MODE_INTEGRATION"

COMMAND_ANCHOR = (
    '    CommandDef("start", "Acknowledge platform start pings without a reply", "Session",\n'
    "               gateway_only=True),\n"
)
COMMAND_INSERT = (
    f"{COMMAND_MARKER}\n"
    '    CommandDef("bot", "Open Dad Bot Mode from an authorized Telegram DM", "Session",\n'
    '               gateway_only=True, aliases=("botmode",)),\n'
)

COLD_ANCHOR = (
    '        if canonical == "help":\n'
    '            return await self._handle_help_command(event)\n\n'
    '        if canonical == "start":\n'
)
COLD_INSERT = (
    '        if canonical == "help":\n'
    '            return await self._handle_help_command(event)\n\n'
    f"        {RUN_COLD_MARKER}\n"
    '        if canonical == "bot":\n'
    '            from gateway.bot_mode import handle_bot_mode_command\n'
    '            return await handle_bot_mode_command(event)\n\n'
    '        if canonical == "start":\n'
)

ACTIVE_ANCHOR = (
    '            if _cmd_def_inner and _cmd_def_inner.name == "agents":\n'
    '                return await self._handle_agents_command(event)\n\n'
)
ACTIVE_INSERT = (
    '            if _cmd_def_inner and _cmd_def_inner.name == "agents":\n'
    '                return await self._handle_agents_command(event)\n\n'
    f"            {RUN_ACTIVE_MARKER}\n"
    '            if _cmd_def_inner and _cmd_def_inner.name == "bot":\n'
    '                from gateway.bot_mode import handle_bot_mode_command\n'
    '                return await handle_bot_mode_command(event)\n\n'
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def _backup(path: Path) -> Path:
    backup = path.with_name(path.name + ".dad-bot-mode.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def _replace_once(text: str, anchor: str, replacement: str, label: str) -> str:
    count = text.count(anchor)
    if count != 1:
        raise PatchError(f"expected exactly one {label} anchor; found {count}")
    return text.replace(anchor, replacement, 1)


def _copy_helper(root: Path, *, dry_run: bool) -> bool:
    source = Path(__file__).with_name("gateway_bot_mode.py")
    target = root / "gateway" / "bot_mode.py"
    helper_text = _read(source)
    if target.exists():
        existing = _read(target)
        if existing == helper_text:
            return False
        if HELPER_MARKER in existing:
            raise PatchError(f"existing helper differs from integration source: {target}")
        raise PatchError(f"refusing to overwrite unrecognized file: {target}")
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        _write(target, helper_text)
    return True


def patch_gateway(root: str | Path, *, dry_run: bool = False) -> list[str]:
    """Patch a Hermes source root and return changed relative paths."""

    root = Path(root).expanduser().resolve()
    commands = root / "hermes_cli" / "commands.py"
    runner = root / "gateway" / "run.py"
    if not root.is_dir() or not commands.is_file() or not runner.is_file():
        raise PatchError("--root must contain hermes_cli/commands.py and gateway/run.py")

    changed: list[str] = []

    command_text = _read(commands)
    if COMMAND_MARKER not in command_text:
        updated = _replace_once(
            command_text,
            COMMAND_ANCHOR,
            COMMAND_ANCHOR + COMMAND_INSERT,
            "command registry",
        )
        if not dry_run:
            _backup(commands)
            _write(commands, updated)
        changed.append(commands.relative_to(root).as_posix())
    elif 'CommandDef("bot"' not in command_text:
        raise PatchError(f"partial bot-mode command marker found in {commands}")

    runner_text = _read(runner)
    runner_changed = False
    if RUN_COLD_MARKER not in runner_text:
        runner_text = _replace_once(runner_text, COLD_ANCHOR, COLD_INSERT, "cold dispatch")
        runner_changed = True
    elif 'if canonical == "bot":' not in runner_text:
        raise PatchError(f"partial cold bot-mode marker found in {runner}")
    if RUN_ACTIVE_MARKER not in runner_text:
        runner_text = _replace_once(
            runner_text,
            ACTIVE_ANCHOR,
            ACTIVE_INSERT,
            "active dispatch",
        )
        runner_changed = True
    elif '_cmd_def_inner.name == "bot"' not in runner_text:
        raise PatchError(f"partial active bot-mode marker found in {runner}")
    if runner_changed:
        if not dry_run:
            _backup(runner)
            _write(runner, runner_text)
        changed.append(runner.relative_to(root).as_posix())

    if _copy_helper(root, dry_run=dry_run):
        changed.append("gateway/bot_mode.py")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Hermes source checkout to patch")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify anchors and report changes without writing files",
    )
    args = parser.parse_args()
    try:
        changed = patch_gateway(args.root, dry_run=args.dry_run)
    except PatchError as exc:
        parser.error(str(exc))
    action = "would change" if args.dry_run else "changed"
    print(f"gateway patch {action}: {', '.join(changed) if changed else 'already applied'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

