from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .evidence import sha256_file


def load_supply_lock(path) -> Dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ValueError("offline package lock must use schema 1.0")
    if value.get("tool_version") != "0.2.0" or value.get("archive_name") != "umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip":
        raise ValueError("offline package version or archive name mismatch")
    for group in ("umi", "python"):
        verify_lock_entry(value.get(group))
    wheels = value.get("wheels")
    if not isinstance(wheels, list) or len(wheels) != 9:
        raise ValueError("offline package lock must contain nine wheels")
    for entry in wheels:
        verify_lock_entry(entry)
    expected_layout = {
        "archive_root": "Umi-OCR_Rapid_v2.1.5",
        "data_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data",
        "runtime_python": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe",
        "plugin_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins",
        "plugin_name": "win7_x64_RapidOCR-json",
    }
    if value.get("umi_layout") != expected_layout:
        raise ValueError("unexpected Umi-OCR Rapid v2.1.5 layout")
    return value


def verify_lock_entry(entry) -> None:
    if not isinstance(entry, dict):
        raise ValueError("lock entry must be an object")
    if not isinstance(entry.get("name"), str) or Path(entry["name"]).name != entry["name"]:
        raise ValueError("lock entry name must be a basename")
    if not isinstance(entry.get("size"), int) or isinstance(entry["size"], bool) or entry["size"] <= 0:
        raise ValueError("lock entry size must be a positive integer")
    digest = entry.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("lock entry SHA-256 is invalid")


def verify_locked_file(path, entry) -> None:
    verify_lock_entry(entry)
    candidate = Path(path)
    if candidate.name != entry["name"]:
        raise ValueError("locked filename mismatch")
    if candidate.stat().st_size != entry["size"]:
        raise ValueError("locked file size mismatch: {}".format(candidate.name))
    if sha256_file(candidate) != entry["sha256"]:
        raise ValueError("locked file SHA-256 mismatch: {}".format(candidate.name))


def write_sha256sums(root, output) -> None:
    root = Path(root).resolve()
    output = Path(output).resolve()
    files = sorted(path for path in root.rglob("*") if path.is_file() and path != output)
    lines = ["{}  {}".format(sha256_file(path), path.relative_to(root).as_posix()) for path in files]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_sha256sums(root, sums_path) -> None:
    root = Path(root).resolve()
    sums_path = Path(sums_path).resolve()
    listed = set()
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file() or sha256_file(path) != digest:
            raise ValueError("SHA256SUMS mismatch: {}".format(relative))
        listed.add(relative)
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path != sums_path}
    if actual != listed:
        raise ValueError("SHA256SUMS file set mismatch")
