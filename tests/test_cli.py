import hashlib
import json
import sys
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw

import umi_web_spike.cli as cli_module
from umi_web_spike.cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CATEGORIES = {
    "simplified_chinese_image",
    "mixed_chinese_english_image",
    "scanned_pdf_rotated_blank",
    "native_text_pdf",
    "corrupt_pdf",
    "encrypted_pdf",
}


@pytest.fixture(autouse=True)
def _scheduled_windows_session(monkeypatch):
    monkeypatch.setattr(cli_module, "_windows_session_id", lambda: 0)


def _image(path, text):
    image = Image.new("RGB", (160, 80), "white")
    ImageDraw.Draw(image).text((10, 10), text, fill="black")
    image.save(path)


def _pdf(path, *, pages=1, native_text=False, encrypted=False):
    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=200, height=100)
        if native_text:
            page.insert_text((20, 50), "native text")
        if index == 0 and not native_text:
            page.set_rotation(90)
    kwargs = {}
    if encrypted:
        kwargs = {
            "encryption": fitz.PDF_ENCRYPT_AES_256,
            "owner_pw": "owner-secret",
            "user_pw": "user-secret",
        }
    document.save(path, **kwargs)
    document.close()


def _validation_args(
    tmp_path,
    *,
    validation_id="run-20260713-001",
    global_values=None,
    min_pages=1,
    scanned_pages=1,
    scanned_native_text=False,
    business_concurrency_limit=5,
    execution_mode="scheduled",
):
    samples = tmp_path / "samples"
    samples.mkdir()
    simplified = samples / "simplified.png"
    mixed = samples / "mixed.png"
    _image(simplified, "zh")
    _image(mixed, "zh EN")
    scanned = samples / "scan.pdf"
    _pdf(scanned, pages=scanned_pages, native_text=scanned_native_text)
    native = samples / "native.pdf"
    _pdf(native, native_text=True)
    corrupt = samples / "corrupt.pdf"
    corrupt.write_bytes(b"not a pdf")
    encrypted = samples / "encrypted.pdf"
    _pdf(encrypted, encrypted=True)

    manifest = tmp_path / "samples.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {"category": "simplified_chinese_image", "path": str(simplified)},
                    {"category": "mixed_chinese_english_image", "path": str(mixed)},
                    {"category": "scanned_pdf_rotated_blank", "path": str(scanned)},
                    {"category": "native_text_pdf", "path": str(native)},
                    {"category": "corrupt_pdf", "path": str(corrupt)},
                    {"category": "encrypted_pdf", "path": str(encrypted)},
                ]
            }
        ),
        encoding="utf-8",
    )
    global_options = tmp_path / "global.json"
    local_options = tmp_path / "local.json"
    global_options.write_text(json.dumps(global_values or {}), encoding="utf-8")
    local_options.write_text("{}", encoding="utf-8")
    output = tmp_path / "runs" / validation_id
    return output, [
        "validate-ocr",
        "--validation-id",
        validation_id,
        "--plugin-root",
        str(PROJECT_ROOT / "tests" / "fakes"),
        "--plugin-name",
        "fake_ocr_plugin",
        "--global-options-json",
        str(global_options),
        "--local-options-json",
        str(local_options),
        "--samples-manifest",
        str(manifest),
        "--output-dir",
        str(output),
        "--execution-mode",
        execution_mode,
        "--min-pages",
        str(min_pages),
        "--business-concurrency-limit",
        str(business_concurrency_limit),
    ]


def _read(output, name):
    return json.loads((output / name).read_text(encoding="utf-8"))


def test_validate_ocr_publishes_complete_unique_atomic_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path)

    assert main(args) == 0

    manifest = _read(output, "manifest.json")
    assert manifest["status"] == "completed"
    assert manifest["validation_id"] == "run-20260713-001"
    assert set(manifest["evidence"]) == {"ocr-image.json", "ocr-pdf.json", "resources.json"}
    for name, digest in manifest["evidence"].items():
        assert digest == hashlib.sha256((output / name).read_bytes()).hexdigest()
    evidence = [_read(output, name) for name in ("ocr-image.json", "ocr-pdf.json", "resources.json")]
    assert all(item["schema_version"] == "1.0" for item in evidence)
    assert all(item["validation_id"] == manifest["validation_id"] for item in evidence)
    assert all(item["recorded_at_utc"].endswith("Z") for item in evidence)
    assert all(item["execution_mode"] == "scheduled" for item in evidence)
    assert manifest["execution_mode"] == "scheduled"
    assert all(item["plugin"]["name"] == "fake_ocr_plugin" for item in evidence)
    assert all(Path(item["plugin"]["root"]).is_absolute() for item in evidence)
    assert all(item["interpreter"]["executable"] == sys.executable for item in evidence)

    sample_results = []
    for item in evidence[:2]:
        sample_results.extend(item["details"]["samples"])
    assert {sample["category"] for sample in sample_results} == REQUIRED_CATEGORIES
    assert all(sample["expected"] == sample["actual"] for sample in sample_results)
    assert all(sample["ok"] is True for sample in sample_results)
    for sample in sample_results:
        assert sample["input_sha256"] == hashlib.sha256(Path(sample["path"]).read_bytes()).hexdigest()
    scanned = next(sample for sample in sample_results if sample["category"] == "scanned_pdf_rotated_blank")
    assert scanned["rotated_pages"] >= 1
    assert scanned["blank_pages"] >= 1
    simplified = next(sample for sample in sample_results if sample["category"] == "simplified_chinese_image")
    mixed = next(sample for sample in sample_results if sample["category"] == "mixed_chinese_english_image")
    assert "中" in simplified["ocr_text"]
    assert "中" in mixed["ocr_text"] and "English" in mixed["ocr_text"]

    resources = evidence[2]
    details = resources["details"]
    assert resources["ok"] is True
    assert details["observed_peak_process_tree_rss_bytes"] > 0
    assert details["process_tree_cpu_seconds"] >= 0
    assert details["duration_seconds"] > 0
    assert details["processed_pages"] >= 1
    assert details["pages_per_minute"] > 0
    assert details["sample_count"] >= 1
    assert details["recommended_workers"] >= 1
    assert details["logical_cpu_count"] >= 1
    assert details["memory_worker_limit"] == max(1, details["memory_budget_bytes"] // details["observed_peak_process_tree_rss_bytes"])
    assert details["cpu_worker_limit"] == max(1, details["logical_cpu_count"] // 2)
    assert details["business_concurrency_limit"] == 5
    assert details["recommended_workers"] == min(details["memory_worker_limit"], details["cpu_worker_limit"], 5)
    assert details["worker_calculation_basis"] == "recommended_workers=min(memory_worker_limit,cpu_worker_limit,business_concurrency_limit); memory_worker_limit=max(1,floor(memory_budget_bytes/observed_peak_process_tree_rss_bytes)); cpu_worker_limit=max(1,floor(logical_cpu_count/2))"
    assert details["qt_loaded"] is False
    assert details["interactive_session"] is False
    assert details["headless"] is True
    assert details["windows_session_id"] == 0


def test_interactive_validation_requires_positive_windows_session_id(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cli_module, "_windows_session_id", lambda: 3)
    output, args = _validation_args(tmp_path, execution_mode="interactive")

    assert main(args) == 0

    resources = _read(output, "resources.json")
    assert resources["execution_mode"] == "interactive"
    assert resources["details"]["windows_session_id"] == 3
    assert resources["details"]["interactive_session"] is True
    assert resources["details"]["headless"] is False


@pytest.mark.parametrize(
    ("execution_mode", "session_id"),
    [("interactive", 0), ("scheduled", 2)],
)
def test_execution_mode_rejects_wrong_windows_session(
    tmp_path, monkeypatch, execution_mode, session_id
):
    monkeypatch.setattr(cli_module, "_windows_session_id", lambda: session_id)
    output, args = _validation_args(tmp_path, execution_mode=execution_mode)

    assert main(args) == 1
    assert _read(output, "resources.json")["ok"] is False


@pytest.mark.parametrize("with_old_file", [False, True])
def test_validate_ocr_refuses_to_reuse_even_empty_target_directory(tmp_path, monkeypatch, with_old_file):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path)
    output.mkdir(parents=True)
    marker = output / "old-success.json"
    if with_old_file:
        marker.write_text('{"ok": true}', encoding="utf-8")

    assert main(args) == 1
    if with_old_file:
        assert marker.read_text(encoding="utf-8") == '{"ok": true}'
    assert not (output / "manifest.json").exists()


def test_validation_exception_atomically_publishes_failed_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    monkeypatch.setenv("SUPER_SECRET_TOKEN", "must-not-leak")
    output, args = _validation_args(tmp_path, global_values={"raise_names": ["mixed.png"]})

    assert main(args) == 1
    manifest = _read(output, "manifest.json")
    assert manifest["status"] == "failed"
    assert manifest["validation_id"] == "run-20260713-001"
    assert isinstance(manifest["diagnostic"], str) and manifest["diagnostic"]
    assert "Traceback (most recent call last)" in manifest["traceback"]
    assert manifest["plugin"]["name"] == "fake_ocr_plugin"
    assert manifest["interpreter"]["executable"] == sys.executable
    assert set(manifest["environment_summary"]) == {"platform", "session_name", "process_id"}
    assert "must-not-leak" not in json.dumps(manifest)
    assert not list(output.parent.glob(".*.tmp"))


def test_nonblank_image_requires_nonempty_ocr_text(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path, global_values={"empty_names": ["simplified.png"]})

    assert main(args) == 1
    image = _read(output, "ocr-image.json")
    sample = next(item for item in image["details"]["samples"] if item["category"] == "simplified_chinese_image")
    assert sample["actual"] == "empty_ocr_text"
    assert sample["ok"] is False
    assert image["ok"] is False


@pytest.mark.parametrize(
    ("name", "text"),
    [("simplified.png", "English only"), ("mixed.png", "只有中文"), ("mixed.png", "   ")],
)
def test_image_language_coverage_uses_actual_ocr_text(tmp_path, monkeypatch, name, text):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path, global_values={"text_by_name": {name: text}})
    assert main(args) == 1
    image = _read(output, "ocr-image.json")
    sample = next(item for item in image["details"]["samples"] if Path(item["path"]).name == name)
    assert sample["ocr_text"] == text.strip()
    assert sample["ok"] is False


def test_blank_image_cannot_claim_positive_image_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path)
    manifest_path = Path(args[args.index("--samples-manifest") + 1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sample = next(item for item in manifest["samples"] if item["category"] == "simplified_chinese_image")
    Image.new("RGB", (160, 80), "white").save(sample["path"])

    assert main(args) == 1
    image = _read(output, "ocr-image.json")
    result = next(item for item in image["details"]["samples"] if item["category"] == "simplified_chinese_image")
    assert result["input_nonblank"] is False
    assert result["actual"] == "blank_input"


def test_scanned_pdf_with_existing_text_layer_cannot_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path, scanned_native_text=True)

    assert main(args) == 1
    pdf = _read(output, "ocr-pdf.json")
    sample = next(item for item in pdf["details"]["samples"] if item["category"] == "scanned_pdf_rotated_blank")
    assert sample["source_has_text"] is True
    assert sample["actual"] == "source_has_text"
    assert sample["ok"] is False


def test_default_resource_gate_requires_100_representative_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path, min_pages=100, scanned_pages=2)

    assert main(args) == 1
    resources = _read(output, "resources.json")
    assert resources["details"]["minimum_required_pages"] == 100
    assert resources["details"]["processed_pages"] < 100
    assert resources["ok"] is False


def test_validation_id_must_match_output_directory_name(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    _, args = _validation_args(tmp_path)
    args[args.index("--output-dir") + 1] = str(tmp_path / "runs" / "different-id")
    assert main(args) == 1


def test_min_pages_cannot_be_zero_to_bypass_resource_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path, min_pages=0)
    assert main(args) == 1
    assert _read(output, "manifest.json")["status"] == "failed"


def test_business_concurrency_limit_cannot_be_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONNAME", "Services")
    output, args = _validation_args(tmp_path, business_concurrency_limit=0)
    assert main(args) == 1
    assert _read(output, "manifest.json")["status"] == "failed"


def test_windows_script_uses_unique_run_and_manifest_contract():
    script = (PROJECT_ROOT / "scripts" / "run-windows-validation.ps1").read_text(encoding="utf-8")
    assert "[string]$ValidationId = ([guid]::NewGuid().ToString('N'))" in script
    assert "validation\\results\\runs" in script
    assert "'validation\\results\\live'" not in script
    assert "--validation-id $ValidationId" in script
    assert "--samples-manifest $SamplesManifest" in script
    assert "--min-pages $MinPages" in script
    assert "--business-concurrency-limit $BusinessConcurrencyLimit" in script
    assert "[int]$BusinessConcurrencyLimit = 5" in script
    assert "[int]$MinPages = 100" in script
