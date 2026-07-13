from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict

from .evidence import sha256_file


EXPECTED_WHEEL_NAMES = {
    "colorama-0.4.6-py2.py3-none-any.whl",
    "iniconfig-2.3.0-py3-none-any.whl",
    "packaging-26.2-py3-none-any.whl",
    "pillow-11.3.0-cp312-cp312-win_amd64.whl",
    "pluggy-1.6.0-py3-none-any.whl",
    "psutil-7.2.2-cp37-abi3-win_amd64.whl",
    "pygments-2.20.0-py3-none-any.whl",
    "pymupdf-1.28.0-cp310-abi3-win_amd64.whl",
    "pytest-8.4.2-py3-none-any.whl",
}


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
    wheel_names = [entry["name"] for entry in wheels]
    if len(set(wheel_names)) != len(wheel_names):
        raise ValueError("offline package wheel names must be unique")
    if set(wheel_names) != EXPECTED_WHEEL_NAMES:
        raise ValueError("offline package lock must contain the expected wheel names")
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
    name = entry.get("name")
    if (
        not isinstance(name, str)
        or name in {"", ".", ".."}
        or "/" in name
        or "\\" in name
        or PurePosixPath(name).name != name
        or PureWindowsPath(name).name != name
        or PurePosixPath(name).is_absolute()
        or PureWindowsPath(name).is_absolute()
        or bool(PureWindowsPath(name).drive)
    ):
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
        if (
            len(line) < 67
            or line[64:66] != "  "
            or any(character not in "0123456789abcdef" for character in line[:64])
        ):
            raise ValueError("malformed SHA256SUMS entry")
        digest, relative = line[:64], line[66:]
        if not relative:
            raise ValueError("malformed SHA256SUMS entry")
        if relative in listed:
            raise ValueError("duplicate SHA256SUMS path: {}".format(relative))
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file() or sha256_file(path) != digest:
            raise ValueError("SHA256SUMS mismatch: {}".format(relative))
        listed.add(relative)
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path != sums_path}
    if actual != listed:
        raise ValueError("SHA256SUMS file set mismatch")
