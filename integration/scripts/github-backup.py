#!/usr/bin/env python3
"""Create an authenticated encrypted Bot Mode backup.

Run on the server. The recovery key is created beside the output, with mode
0600, and is deliberately excluded from the archive. The encrypted artifact
can be copied to the private backup repository only after restore testing.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sqlite3
import stat
import struct
import tarfile
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", type=Path, default=Path("/opt/hermes-bot-mode"))
    p.add_argument("--data-root", type=Path, default=Path("/var/lib/hermes-bot-mode"))
    p.add_argument("--output-dir", type=Path, default=Path("/var/lib/hermes-bot-backups"))
    p.add_argument("--key-dir", type=Path, default=Path("/var/lib/hermes-bot-keyring"))
    p.add_argument("--include", action="append", default=[], help="Additional path, if it exists")
    p.add_argument("--fixture", action="store_true", help="Create and verify a disposable local fixture")
    return p.parse_args()


def key_path(key_dir: Path, stamp: str) -> Path:
    return key_dir / f"recovery-{stamp}.key"


def write_key(path: Path) -> bytes:
    key = AESGCM.generate_key(bit_length=256)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(base64.urlsafe_b64encode(key) + b"\n")
    os.chmod(path, 0o600)
    return key


def read_key(path: Path) -> bytes:
    raw = base64.urlsafe_b64decode(path.read_bytes().strip())
    if len(raw) != 32:
        raise ValueError("recovery key must decode to 32 bytes")
    return raw


def existing_paths(args: argparse.Namespace) -> list[Path]:
    paths = [args.source_root, args.data_root]
    defaults = [
        Path("/opt/hermes/hermes-agent/hermes_cli/commands.py"),
        Path("/opt/hermes/hermes-agent/gateway/run.py"),
        Path("/opt/hermes/hermes-agent/gateway/bot_mode.py"),
        Path("/opt/hermes/login/app.py"),
        Path("/opt/hermes/.env"),
        Path("/opt/hermes/docker-compose.yml"),
        Path("/opt/hermes/hermes-agent/.env"),
    ]
    paths.extend(Path(x) for x in args.include)
    return list(dict.fromkeys(p for p in paths + defaults if p.exists()))


def snapshot_databases(paths: list[Path], temporary_root: Path) -> dict[Path, Path]:
    """Make consistent SQLite snapshots, including WAL-mode databases."""
    temporary_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshots: dict[Path, Path] = {}
    candidates: list[Path] = []
    for root in paths:
        if root.is_file() and root.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            candidates.append(root)
        elif root.is_dir():
            candidates.extend(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".db", ".sqlite", ".sqlite3"})
    for index, source in enumerate(candidates):
        target = temporary_root / f"sqlite-{index}.sqlite3"
        try:
            source_uri = f"file:{source.resolve()}?mode=ro"
            src = sqlite3.connect(source_uri, uri=True)
            dst = sqlite3.connect(target)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            snapshots[source] = target
        except sqlite3.Error as exc:
            raise RuntimeError(f"SQLite snapshot failed for {source}: {exc}") from exc
    return snapshots


def make_archive(paths: list[Path], archive_path: Path, overrides: dict[Path, Path] | None = None, excluded_roots: list[Path] | None = None) -> None:
    overrides = overrides or {}
    excluded_roots = [p.resolve() for p in (excluded_roots or [])]
    with tarfile.open(archive_path, "w:gz") as archive:
        def add(path: Path) -> None:
            resolved = path.resolve()
            if any(resolved == root or root in resolved.parents for root in excluded_roots):
                return
            if path.name.endswith(("-wal", "-shm")):
                return
            arcname = path.as_posix().lstrip("/")
            replacement = overrides.get(path)
            if replacement:
                archive.add(replacement, arcname=arcname, recursive=False)
                return
            archive.add(path, arcname=arcname, recursive=False)
            if path.is_dir():
                for child in sorted(path.iterdir()):
                    add(child)
        for path in paths:
            add(path)


def encrypt(archive_path: Path, output_path: Path, key: bytes, chunk_size: int = 4 * 1024 * 1024) -> str:
    """Encrypt independently authenticated chunks to bound memory use."""
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        handle.write(b"HBM2" + struct.pack(">I", chunk_size))
        with archive_path.open("rb") as source:
            index = 0
            while chunk := source.read(chunk_size):
                nonce = os.urandom(12)
                aad = b"hermes-bot-mode-backup-v2" + struct.pack(">Q", index)
                ciphertext = AESGCM(key).encrypt(nonce, chunk, aad)
                handle.write(struct.pack(">I", len(ciphertext)))
                handle.write(nonce)
                handle.write(ciphertext)
                index += 1
    os.chmod(output_path, 0o600)
    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def decrypt(path: Path, key: bytes) -> bytes:
    payload = path.read_bytes()
    if payload[:4] != b"HBM2":
        raise ValueError("not a Bot Mode backup")
    offset = 8
    index = 0
    output = bytearray()
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        offset += 4
        nonce = payload[offset:offset + 12]
        offset += 12
        ciphertext = payload[offset:offset + length]
        offset += length
        aad = b"hermes-bot-mode-backup-v2" + struct.pack(">Q", index)
        output.extend(AESGCM(key).decrypt(nonce, ciphertext, aad))
        index += 1
    return bytes(output)


def fixture() -> None:
    with tempfile.TemporaryDirectory(prefix="hbm-backup-test-") as tmp:
        root = Path(tmp)
        source = root / "source"
        data = root / "data"
        source.mkdir(); data.mkdir()
        (source / "README.md").write_text("generic source", encoding="utf-8")
        database = data / "bot-mode.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE checks (value TEXT)")
            connection.execute("INSERT INTO checks VALUES ('consistent snapshot')")
            connection.commit()
        finally:
            connection.close()
        snapshots = snapshot_databases([data], root / "snapshots")
        keyfile = root / "keys" / "recovery.key"
        archive = root / "fixture.tar.gz"
        encrypted = root / "fixture.hbm"
        make_archive([source, data], archive, snapshots)
        key = write_key(keyfile)
        digest = encrypt(archive, encrypted, key)
        recovered = root / "recovered.tar.gz"
        recovered.write_bytes(decrypt(encrypted, read_key(keyfile)))
        restored = root / "restored"
        restored.mkdir()
        with tarfile.open(recovered, "r:gz") as package:
            package.extractall(restored, filter="data")
        restored_db = next(restored.rglob(database.name))
        connection = sqlite3.connect(restored_db)
        try:
            row = connection.execute("SELECT value FROM checks").fetchone()
        finally:
            connection.close()
        if row != ("consistent snapshot",) or not recovered.read_bytes() or digest != hashlib.sha256(encrypted.read_bytes()).hexdigest():
            raise RuntimeError("fixture backup verification failed")
        if os.name != "nt" and stat.S_IMODE(keyfile.stat().st_mode) != 0o600:
            raise RuntimeError("recovery key is not mode 0600")
        print(f"fixture roundtrip ok: {digest}")


def main() -> None:
    args = parse_args()
    if args.fixture:
        fixture(); return
    paths = existing_paths(args)
    if not paths:
        raise SystemExit("no source or data paths exist")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    keyfile = key_path(args.key_dir, stamp)
    output = args.output_dir / f"bot-mode-{stamp}.hbm"
    with tempfile.TemporaryDirectory(prefix="hbm-backup-") as tmp:
        archive = Path(tmp) / "payload.tar.gz"
        snapshots = snapshot_databases(paths, Path(tmp) / "snapshots")
        make_archive(paths, archive, snapshots, excluded_roots=[args.key_dir])
        key = write_key(keyfile)
        digest = encrypt(archive, output, key)
    print(f"encrypted backup: {output}")
    print(f"recovery key (keep outside GitHub): {keyfile}")
    print(f"sha256: {digest}")
    print(f"included paths: {', '.join(map(str, paths))}")


if __name__ == "__main__":
    main()

