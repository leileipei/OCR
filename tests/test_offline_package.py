import json
import hashlib
import os
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from umi_web_spike.package_integrity import (
    load_supply_lock,
    validate_offline_requirements,
    verify_package_manifest,
)


ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = "umi-ocr-phase0/"


def _write_package_metadata(root, relative_paths):
    entries = []
    for relative in sorted(relative_paths):
        path = root / relative
        entries.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "tool_version": "0.2.0",
        "umi_version": "2.1.5",
        "engine": "RapidOCR",
        "files": entries,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    sums_paths = sorted(list(relative_paths) + ["manifest.json"])
    (root / "SHA256SUMS.txt").write_text(
        "".join(
            "{}  {}\n".format(hashlib.sha256((root / relative).read_bytes()).hexdigest(), relative)
            for relative in sums_paths
        ),
        encoding="utf-8",
    )


def test_package_manifest_verifier_rejects_unlisted_file(tmp_path):
    payload = tmp_path / "payload.txt"
    payload.write_text("locked", encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "tool_version": "0.2.0",
        "umi_version": "2.1.5",
        "engine": "RapidOCR",
        "files": [{"path": "payload.txt", "size": payload.stat().st_size, "sha256": digest}],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    manifest_digest = hashlib.sha256((tmp_path / "manifest.json").read_bytes()).hexdigest()
    (tmp_path / "SHA256SUMS.txt").write_text(
        "{}  manifest.json\n{}  payload.txt\n".format(manifest_digest, digest), encoding="utf-8"
    )
    verify_package_manifest(tmp_path)
    (tmp_path / "surprise.txt").write_text("not listed", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest file set mismatch"):
        verify_package_manifest(tmp_path)


def test_package_manifest_verifier_rejects_symlink(tmp_path):
    payload = tmp_path / "payload.txt"
    payload.write_text("locked", encoding="utf-8")
    alias = tmp_path / "alias.txt"
    try:
        alias.symlink_to(payload.name)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable")
    _write_package_metadata(tmp_path, ["alias.txt", "payload.txt"])
    with pytest.raises(ValueError, match="reparse|symlink"):
        verify_package_manifest(tmp_path)


def test_offline_requirements_are_an_exact_lock_projection(tmp_path):
    lock = load_supply_lock(ROOT / "packaging/offline-package.lock.json")
    requirements = tmp_path / "requirements.lock"
    requirements.write_text("colorama==0.4.6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly match"):
        validate_offline_requirements(lock, requirements)
    validate_offline_requirements(lock, ROOT / "packaging/requirements-offline.lock")


def test_supply_lock_symlink_is_rejected(tmp_path):
    target = tmp_path / "real-lock.json"
    target.write_bytes((ROOT / "packaging/offline-package.lock.json").read_bytes())
    alias = tmp_path / "offline-package.lock.json"
    try:
        alias.symlink_to(target.name)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError, match="reparse|symlink"):
        load_supply_lock(alias)


def test_builder_is_bound_to_repository_supply_lock():
    text = (ROOT / "scripts/build-offline-package.ps1").read_text(encoding="utf-8")
    lock = json.loads((ROOT / "packaging/offline-package.lock.json").read_text(encoding="utf-8"))
    assert "offline-package.lock.json" in text
    assert "Get-FileHash" in text
    assert "Length" in text
    assert lock["archive_name"] in text


def test_builder_fails_closed_and_uses_an_atomic_cache():
    text = (ROOT / "scripts/build-offline-package.ps1").read_text(encoding="utf-8")
    assert text.isascii(), "Windows PowerShell 5.1 must not decode non-ASCII script literals"
    assert "[char]0x73B0" in text and "[char]0x8BC1" in text
    assert "[switch]$OfflineCacheOnly" in text
    assert ".partial" in text
    assert "Invoke-WebRequest" in text
    assert "Move-Item" in text
    assert "--no-index" in text
    assert "--only-binary=:all:" in text
    assert "python312._pth" in text
    assert "Assert-ExactWheelhouse" in text
    assert "Count -ne 9" in text
    assert "*.dist-info" in text
    assert '"LICENSE*"' in text and '"COPYING*"' in text
    assert "New-DeterministicZip" in text
    assert "Compress-Archive" not in text
    assert "THIRD_PARTY_NOTICES.txt" in text
    assert "sbom.json" in text
    assert "load_supply_lock" in text
    assert "validate_offline_requirements" in text
    assert "Get-SafeContainedPath" in text
    assert "Assert-NoReparseTree" in text
    assert "UsedWheelKeys" in text
    assert "Get-SafeContainedPath -Root $RepositoryRoot -Path $LockPath" in text


def _real_archive():
    value = os.environ.get("BUILT_OFFLINE_PACKAGE")
    if not value:
        pytest.skip("real archive assertion runs in the Windows build job")
    archive = Path(value)
    assert archive.is_file(), "BUILT_OFFLINE_PACKAGE must point to a real ZIP"
    return archive


def _assert_safe_member(name):
    path = PurePosixPath(name)
    assert not path.is_absolute()
    assert ".." not in path.parts
    assert "\\" not in name
    assert not (path.parts and ":" in path.parts[0])


def test_built_archive_has_required_layout(tmp_path):
    archive = _real_archive()
    with zipfile.ZipFile(archive) as value:
        ordered_names = value.namelist()
        names = set(ordered_names)
        assert len(names) == len(ordered_names)
        assert ordered_names == sorted(ordered_names)
        for info in value.infolist():
            _assert_safe_member(info.filename)
            assert info.date_time == (2000, 1, 1, 0, 0, 0)
        value.extractall(tmp_path)
    required = {
        "umi-ocr-phase0/Start-Phase0Validation.ps1",
        "umi-ocr-phase0/Phase0.Package.psm1",
        "umi-ocr-phase0/Phase0.Scheduler.psm1",
        "umi-ocr-phase0/README-现场验证.md",
        "umi-ocr-phase0/SHA256SUMS.txt",
        "umi-ocr-phase0/manifest.json",
        "umi-ocr-phase0/sbom.json",
        "umi-ocr-phase0/licenses/Umi-OCR-MIT.txt",
        "umi-ocr-phase0/licenses/Python.txt",
        "umi-ocr-phase0/licenses/THIRD_PARTY_NOTICES.txt",
        "umi-ocr-phase0/vendor/Umi-OCR_Rapid_v2.1.5.7z.exe",
        "umi-ocr-phase0/runtime/python/python.exe",
        "umi-ocr-phase0/runtime/python/python312._pth",
        "umi-ocr-phase0/toolkit/src/umi_web_spike/cli.py",
        "umi-ocr-phase0/toolkit/scripts/phase0/Start-Phase0Validation.ps1",
        "umi-ocr-phase0/templates/samples.json",
    }
    assert required <= names
    with zipfile.ZipFile(archive) as value:
        readme = value.read("umi-ocr-phase0/README-现场验证.md").decode("utf-8-sig")
    assert "离线验证包管理员手册" in readme
    assert "OCR_READY_E10_PENDING" in readme
    release_root = tmp_path / "umi-ocr-phase0"
    verify_package_manifest(release_root)
    assert (release_root / "runtime/python/python312._pth").read_text(encoding="ascii").splitlines() == [
        "python312.zip",
        ".",
        "Lib",
        r"Lib\site-packages",
        r"..\..\toolkit\src",
        "import site",
    ]
    sbom = json.loads((release_root / "sbom.json").read_text(encoding="utf-8"))
    assert len(sbom["components"]) == 11
    for component in sbom["components"]:
        assert {"name", "version", "source_url", "sha256", "license_files"} <= set(component)
        assert len(component["sha256"]) == 64
        assert component["license_files"]
        assert all((release_root / relative).is_file() for relative in component["license_files"])
    digest_path = Path(str(archive) + ".sha256")
    digest_text = digest_path.read_text(encoding="utf-8")
    assert digest_text in {
        "{}  {}\n".format(hashlib.sha256(archive.read_bytes()).hexdigest(), archive.name),
        "{}  {}\r\n".format(hashlib.sha256(archive.read_bytes()).hexdigest(), archive.name),
    }
    digest, filename = digest_text.strip().split("  ", 1)
    assert filename == archive.name
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    external_sbom = archive.parent / "sbom.json"
    external_notices = archive.parent / "THIRD_PARTY_NOTICES.txt"
    assert external_sbom.is_file()
    assert external_notices.is_file()
    assert external_sbom.read_bytes() == (release_root / "sbom.json").read_bytes()
    assert external_notices.read_bytes() == (
        release_root / "licenses/THIRD_PARTY_NOTICES.txt"
    ).read_bytes()

    lock = load_supply_lock(ROOT / "packaging/offline-package.lock.json")
    component_keys = set()
    components_by_key = {}
    for component in sbom["components"]:
        normalized = component["name"].lower().replace("-", "_").replace(".", "_")
        key = (normalized, component["version"], component["sha256"])
        component_keys.add(key)
        components_by_key[key] = component
    expected_python = {
        (
            wheel["name"].split("-", 2)[0].lower().replace("-", "_").replace(".", "_"),
            wheel["name"].split("-", 2)[1],
            wheel["sha256"],
        )
        for wheel in lock["wheels"]
    }
    umi_key = ("umi_ocr rapid", "2.1.5", lock["umi"]["sha256"])
    python_key = ("cpython", "3.12.10", lock["python"]["sha256"])
    assert component_keys == expected_python | {umi_key, python_key}
    assert components_by_key[umi_key]["source_url"] == lock["umi"]["url"]
    assert components_by_key[python_key]["source_url"] == lock["python"]["url"]
    for key in expected_python:
        component = components_by_key[key]
        assert component["source_url"] == "https://pypi.org/project/{}/{}/".format(
            component["name"], component["version"]
        )


def test_package_manifest_excludes_work_and_sensitive_files():
    with zipfile.ZipFile(_real_archive()) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("umi-ocr-phase0/manifest.json"))
    lowered = "\n".join(names).lower()
    assert "/work/" not in lowered
    assert not any(PurePosixPath(name).name.lower().startswith(".env") for name in names)
    assert "e10.json" not in lowered
    assert "/samples/" not in lowered
    assert "/.git/" not in lowered
    assert manifest["schema_version"] == "1.0"
    assert manifest["tool_version"] == "0.2.0"
    assert manifest["umi_version"] == "2.1.5"
    assert manifest["engine"] == "RapidOCR"
    assert all(set(item) == {"path", "size", "sha256"} for item in manifest["files"])
    assert [item["path"] for item in manifest["files"]] == sorted(
        item["path"] for item in manifest["files"]
    )
