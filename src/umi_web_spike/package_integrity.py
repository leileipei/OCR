from __future__ import annotations

import json
import os
import re
import stat
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


def _absolute_path(path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_reparse_info(info) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_attribute)


def _assert_no_reparse_chain(path, require_leaf=True) -> Path:
    candidate = _absolute_path(path)
    chain = list(candidate.parents)[::-1] + [candidate]
    for index, part in enumerate(chain):
        try:
            info = os.lstat(str(part))
        except FileNotFoundError:
            if require_leaf or index != len(chain) - 1:
                raise ValueError("path does not exist: {}".format(part))
            continue
        if _is_reparse_info(info):
            raise ValueError("symlink or reparse point is forbidden: {}".format(part))
    return candidate


def _plain_files(root):
    root = _assert_no_reparse_chain(root)
    root_info = os.lstat(str(root))
    if not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("package root must be a directory")
    files = []

    def visit(directory):
        with os.scandir(str(directory)) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                if _is_reparse_info(info):
                    raise ValueError("symlink or reparse point is forbidden: {}".format(path))
                if stat.S_ISDIR(info.st_mode):
                    visit(path)
                elif stat.S_ISREG(info.st_mode):
                    files.append(path)
                else:
                    raise ValueError("non-regular package entry is forbidden: {}".format(path))

    visit(root)
    return root, files


def _normalize_distribution_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_offline_requirements(lock, requirements_path) -> None:
    """Require requirements.lock to be an exact name/version projection of wheels."""

    expected = set()
    for wheel in lock.get("wheels", []):
        parts = wheel["name"].split("-")
        if len(parts) < 5:
            raise ValueError("locked wheel filename is malformed")
        expected.add((_normalize_distribution_name(parts[0]), parts[1]))

    requirements_path = _assert_no_reparse_chain(requirements_path)
    actual = []
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
        if not match:
            raise ValueError("offline requirements must contain only exact name==version pins")
        actual.append((_normalize_distribution_name(match.group(1)), match.group(2)))
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("offline requirements must exactly match locked wheels")


def load_supply_lock(path) -> Dict[str, Any]:
    path = _assert_no_reparse_chain(path)
    value = json.loads(path.read_text(encoding="utf-8"))
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
    candidate = _assert_no_reparse_chain(path)
    if candidate.name != entry["name"]:
        raise ValueError("locked filename mismatch")
    if candidate.stat().st_size != entry["size"]:
        raise ValueError("locked file size mismatch: {}".format(candidate.name))
    if sha256_file(candidate) != entry["sha256"]:
        raise ValueError("locked file SHA-256 mismatch: {}".format(candidate.name))


def write_sha256sums(root, output) -> None:
    root, plain_files = _plain_files(root)
    output = _assert_no_reparse_chain(output, require_leaf=False)
    if os.path.commonpath((str(root), str(output))) != str(root):
        raise ValueError("SHA256SUMS output must stay inside root")
    files = sorted(path for path in plain_files if path != output)
    lines = ["{}  {}".format(sha256_file(path), path.relative_to(root).as_posix()) for path in files]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_sha256sums(root, sums_path) -> None:
    root, plain_files = _plain_files(root)
    sums_path = _assert_no_reparse_chain(sums_path)
    listed = set()
    listed_in_order = []
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
        relative_path = PurePosixPath(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or "\\" in relative
            or (relative_path.parts and ":" in relative_path.parts[0])
        ):
            raise ValueError("unsafe SHA256SUMS path: {}".format(relative))
        path = _assert_no_reparse_chain(root / relative_path)
        if os.path.commonpath((str(root), str(path))) != str(root) or not path.is_file() or sha256_file(path) != digest:
            raise ValueError("SHA256SUMS mismatch: {}".format(relative))
        listed.add(relative)
        listed_in_order.append(relative)
    if listed_in_order != sorted(listed_in_order):
        raise ValueError("SHA256SUMS paths must be sorted")
    actual = {path.relative_to(root).as_posix() for path in plain_files if path != sums_path}
    if actual != listed:
        raise ValueError("SHA256SUMS file set mismatch")


def verify_package_manifest(root) -> None:
    """Verify the release manifest and SHA256SUMS as strict file-set closures."""

    root, plain_files = _plain_files(root)
    manifest_path = root / "manifest.json"
    sums_path = root / "SHA256SUMS.txt"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "tool_version", "umi_version", "engine", "files"}:
        raise ValueError("package manifest fields mismatch")
    if (
        value["schema_version"] != "1.0"
        or value["tool_version"] != "0.2.0"
        or value["umi_version"] != "2.1.5"
        or value["engine"] != "RapidOCR"
        or not isinstance(value["files"], list)
    ):
        raise ValueError("package manifest metadata mismatch")

    expected_paths = {
        path.relative_to(root).as_posix() for path in plain_files if path not in {manifest_path, sums_path}
    }
    listed_paths = []
    for entry in value["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise ValueError("package manifest file entry mismatch")
        relative = entry["path"]
        if not isinstance(relative, str):
            raise ValueError("package manifest path must be a string")
        relative_path = PurePosixPath(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or "\\" in relative
            or (relative_path.parts and ":" in relative_path.parts[0])
        ):
            raise ValueError("unsafe package manifest path: {}".format(relative))
        path = _assert_no_reparse_chain(root / relative_path)
        if os.path.commonpath((str(root), str(path))) != str(root) or not path.is_file():
            raise ValueError("package manifest file missing: {}".format(relative))
        if entry["size"] != path.stat().st_size:
            raise ValueError("package manifest size mismatch: {}".format(relative))
        if entry["sha256"] != sha256_file(path):
            raise ValueError("package manifest SHA-256 mismatch: {}".format(relative))
        listed_paths.append(relative)

    if listed_paths != sorted(listed_paths) or len(listed_paths) != len(set(listed_paths)):
        raise ValueError("package manifest paths must be unique and sorted")
    if set(listed_paths) != expected_paths:
        raise ValueError("package manifest file set mismatch")
    verify_sha256sums(root, sums_path)
