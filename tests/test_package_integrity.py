import hashlib
from pathlib import Path

import pytest

from umi_web_spike import __version__
from umi_web_spike.package_integrity import (
    load_supply_lock,
    verify_lock_entry,
    verify_locked_file,
    verify_sha256sums,
    write_sha256sums,
)


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


def _write_mutated_supply_lock(tmp_path, old, new):
    source = Path("packaging/offline-package.lock.json").read_text(encoding="utf-8")
    assert old in source
    target = tmp_path / "offline-package.lock.json"
    target.write_text(source.replace(old, new, 1), encoding="utf-8")
    return target


def test_repository_supply_lock_has_all_pinned_assets():
    lock = load_supply_lock("packaging/offline-package.lock.json")
    assert lock["tool_version"] == "0.2.0"
    assert __version__ == "0.2.0"
    assert lock["umi"]["sha256"] == "659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722"
    assert lock["python"]["sha256"] == "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
    assert len(lock["wheels"]) == 9
    assert {wheel["name"] for wheel in lock["wheels"]} == EXPECTED_WHEEL_NAMES
    assert lock["umi_layout"] == {
        "archive_root": "Umi-OCR_Rapid_v2.1.5",
        "data_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data",
        "runtime_python": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe",
        "plugin_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins",
        "plugin_name": "win7_x64_RapidOCR-json",
    }


def test_supply_lock_rejects_duplicate_wheel_name(tmp_path):
    lock_path = _write_mutated_supply_lock(
        tmp_path,
        '{"name":"pytest-8.4.2-py3-none-any.whl","size":365750,"sha256":"872f880de3fc3a5bdc88a11b39c9710c3497a547cfa9320bc3c5e62fbf272e79"}',
        '{"name":"colorama-0.4.6-py2.py3-none-any.whl","size":365750,"sha256":"872f880de3fc3a5bdc88a11b39c9710c3497a547cfa9320bc3c5e62fbf272e79"}',
    )
    with pytest.raises(ValueError, match="unique"):
        load_supply_lock(lock_path)


def test_supply_lock_rejects_missing_wheel(tmp_path):
    lock_path = _write_mutated_supply_lock(
        tmp_path,
        '    {"name":"colorama-0.4.6-py2.py3-none-any.whl","size":25335,"sha256":"4f1d9991f5acc0ca119f9d443620b77f9d6b33703e51011c16baf57afb285fc6"},\n',
        "",
    )
    with pytest.raises(ValueError, match="nine wheels"):
        load_supply_lock(lock_path)


def test_supply_lock_rejects_unexpected_wheel_name(tmp_path):
    lock_path = _write_mutated_supply_lock(
        tmp_path,
        "pytest-8.4.2-py3-none-any.whl",
        "surprise-8.4.2-py3-none-any.whl",
    )
    with pytest.raises(ValueError, match="expected wheel names"):
        load_supply_lock(lock_path)


@pytest.mark.parametrize(
    "name",
    [
        "../evil.whl",
        r"..\evil.whl",
        ".",
        "..",
        "/absolute/evil.whl",
        r"C:\absolute\evil.whl",
        r"C:relative-drive-evil.whl",
        r"\\server\share\evil.whl",
    ],
)
def test_lock_entry_rejects_non_basename_on_posix_and_windows(name):
    entry = {"name": name, "size": 1, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="basename"):
        verify_lock_entry(entry)


def test_locked_file_rejects_digest_change(tmp_path):
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


def test_locked_file_rejects_size_mismatch(tmp_path):
    payload = tmp_path / "asset.bin"
    payload.write_bytes(b"official")
    entry = {
        "name": "asset.bin",
        "size": 9,
        "sha256": hashlib.sha256(b"official").hexdigest(),
    }
    with pytest.raises(ValueError, match="size mismatch"):
        verify_locked_file(payload, entry)


def test_tree_sums_reject_tampered_file(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS.txt"
    write_sha256sums(tmp_path, sums)
    verify_sha256sums(tmp_path, sums)
    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="a.txt"):
        verify_sha256sums(tmp_path, sums)


def test_tree_sums_reject_unlisted_file(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS.txt"
    write_sha256sums(tmp_path, sums)
    (tmp_path / "unlisted.txt").write_text("unlisted", encoding="utf-8")
    with pytest.raises(ValueError, match="file set mismatch"):
        verify_sha256sums(tmp_path, sums)


def test_tree_sums_reject_duplicate_relative_path(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS.txt"
    write_sha256sums(tmp_path, sums)
    line = sums.read_text(encoding="utf-8")
    sums.write_text(line + line, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate.*a.txt"):
        verify_sha256sums(tmp_path, sums)


@pytest.mark.parametrize(
    "manifest",
    [
        "\n",
        "0" * 64 + " a.txt\n",
        "z" * 64 + "  a.txt\n",
        "0" * 64 + "  \n",
    ],
)
def test_tree_sums_reject_malformed_manifest(tmp_path, manifest):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text(manifest, encoding="utf-8")
    with pytest.raises(ValueError, match="malformed SHA256SUMS"):
        verify_sha256sums(tmp_path, sums)
