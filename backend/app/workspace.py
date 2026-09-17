"""Scoped workspace file handling with traversal and symlink checks."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import secrets
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .config import Settings
from .errors import APIError
from .security import safe_user_key


class Workspace:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.workspace_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def agent_root(self, user_id: str, agent_id: str) -> Path:
        user_root = self.root / safe_user_key(user_id)
        agent_root = user_root / agent_id
        user_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._assert_inside(user_root, self.root)
        self._reject_symlinks(user_root, self.root)
        agent_root.mkdir(mode=0o700, exist_ok=True)
        self._assert_inside(agent_root, self.root)
        self._reject_symlinks(agent_root, user_root)
        return agent_root

    @staticmethod
    def _assert_inside(path: Path, root: Path) -> None:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError as exc:
            raise APIError(400, "invalid_file_path", "File path is outside the agent workspace") from exc

    @staticmethod
    def _reject_symlinks(path: Path, root: Path) -> None:
        """Reject every existing symlink in a path, including its leaf."""

        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise APIError(400, "invalid_file_path", "File path is outside the agent workspace") from exc
        current = root
        for part in relative.parts:
            current = current / part
            try:
                if current.is_symlink():
                    raise APIError(400, "symlink_path", "Symlink paths are not allowed")
            except OSError as exc:
                raise APIError(400, "invalid_file_path", "File path cannot be inspected") from exc

    @classmethod
    def clean_relative_path(cls, raw_path: str) -> str:
        if not raw_path or len(raw_path) > 1024 or "\x00" in raw_path:
            raise APIError(400, "invalid_file_path", "A relative file path is required")
        # Browser clients send slash paths; reject backslashes explicitly so a
        # Windows host cannot interpret them as hidden separators.
        if "\\" in raw_path:
            raise APIError(400, "invalid_file_path", "Use a relative POSIX file path")
        if raw_path.startswith("/"):
            raise APIError(400, "invalid_file_path", "Absolute file paths are not allowed")
        pure = PurePosixPath(raw_path)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts) or (pure.parts and ":" in pure.parts[0]):
            raise APIError(400, "invalid_file_path", "Path traversal is not allowed")
        normalized = pure.as_posix()
        if normalized in {"", "."} or normalized.startswith("../"):
            raise APIError(400, "invalid_file_path", "Path traversal is not allowed")
        return normalized

    def path_for(self, user_id: str, agent_id: str, relative_path: str, *, must_exist: bool = False) -> Path:
        relative = self.clean_relative_path(relative_path)
        root = self.agent_root(user_id, agent_id)
        candidate = root.joinpath(*relative.split("/"))
        self._assert_inside(candidate, root)
        self._reject_symlinks(candidate, root)
        if must_exist and not candidate.is_file():
            raise APIError(404, "file_missing", "The stored file is missing")
        return candidate

    def save_stream(
        self,
        user_id: str,
        agent_id: str,
        relative_path: str,
        stream: BinaryIO,
        *,
        max_bytes: int,
    ) -> tuple[Path, int, str]:
        path = self.path_for(user_id, agent_id, relative_path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._assert_inside(path.parent, self.agent_root(user_id, agent_id))
        self._reject_symlinks(path.parent, self.agent_root(user_id, agent_id))
        if path.exists() or path.is_symlink():
            raise APIError(409, "file_exists", "A file already exists at that path")
        temp = path.parent / f".upload-{secrets.token_hex(16)}.tmp"
        total = 0
        digest = hashlib.sha256()
        fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            no_follow = getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(temp, flags | no_follow, 0o600)
            with os.fdopen(fd, "wb") as output:
                fd = None
                while True:
                    chunk = stream.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise APIError(413, "file_too_large", f"Files are limited to {max_bytes} bytes")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            # Recheck the destination immediately before replace.  The temp
            # file is private and the destination must not be a symlink.
            self._reject_symlinks(path, self.agent_root(user_id, agent_id))
            if path.exists() or path.is_symlink():
                raise APIError(409, "file_exists", "A file already exists at that path")
            os.replace(temp, path)
            return path, total, digest.hexdigest()
        except APIError:
            raise
        except OSError as exc:
            raise APIError(400, "file_write_failed", "The file could not be stored") from exc
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                if temp.exists() or temp.is_symlink():
                    temp.unlink()
            except OSError:
                pass

    @staticmethod
    def content_type(filename: str, supplied: str | None = None) -> str:
        if supplied and supplied != "application/octet-stream":
            return supplied[:255]
        return mimetypes.guess_type(filename)[0] or "application/octet-stream"

