import hashlib
import json

import pytest

from umi_web_spike import __version__
from umi_web_spike.package_integrity import (
    load_supply_lock,
    verify_locked_file,
    verify_sha256sums,
    write_sha256sums,
)


def test_repository_supply_lock_has_all_pinned_assets():
    lock = load_supply_lock("packaging/offline-package.lock.json")
    assert lock["tool_version"] == "0.2.0"
    assert __version__ == "0.2.0"
    assert lock["umi"]["sha256"] == "659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722"
    assert lock["python"]["sha256"] == "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
    assert len(lock["wheels"]) == 9
    assert lock["umi_layout"] == {
        "archive_root": "Umi-OCR_Rapid_v2.1.5",
        "data_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data",
        "runtime_python": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe",
        "plugin_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins",
        "plugin_name": "win7_x64_RapidOCR-json",
    }


def test_locked_file_rejects_size_or_digest_change(tmp_path):
    payload = tmp_path / "asset.bin"
    payload.write_bytes(b"official")
    entry = {
        "name": "asset.bin",
        "size": 8,
        "sha256": hashlib.sha256(b"official").hexdigest(),
    }
    verify_locked_file(payload, entry)
    payload.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_locked_file(payload, entry)


def test_tree_sums_reject_tampered_or_unlisted_files(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS.txt"
    write_sha256sums(tmp_path, sums)
    verify_sha256sums(tmp_path, sums)
    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="a.txt"):
        verify_sha256sums(tmp_path, sums)
