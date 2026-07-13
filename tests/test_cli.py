import json
import sys
from pathlib import Path

import fitz
from PIL import Image

from umi_web_spike.cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _validation_args(tmp_path, *, global_values=None, page_count=1):
    image = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), "white").save(image)

    pdf = tmp_path / "sample.pdf"
    document = fitz.open()
    for _ in range(page_count):
        document.new_page(width=200, height=100)
    document.save(pdf)
    document.close()

    global_options = tmp_path / "global.json"
    local_options = tmp_path / "local.json"
    global_options.write_text(json.dumps(global_values or {}), encoding="utf-8")
    local_options.write_text(json.dumps({}), encoding="utf-8")
    output = tmp_path / "results"

    return output, [
        "validate-ocr",
        "--plugin-root",
        str(PROJECT_ROOT / "tests" / "fakes"),
        "--plugin-name",
        "fake_ocr_plugin",
        "--global-options-json",
        str(global_options),
        "--local-options-json",
        str(local_options),
        "--image",
        str(image),
        "--pdf",
        str(pdf),
        "--output-dir",
        str(output),
    ]


def _read_result(output, name):
    return json.loads((output / f"{name}.json").read_text(encoding="utf-8"))


def test_validate_ocr_writes_success_probe_results(tmp_path):
    output, args = _validation_args(tmp_path)

    code = main(args)

    assert code == 0
    assert _read_result(output, "ocr-image") == {
        "ok": True,
        "name": "ocr-image",
        "details": {"code": 100, "blocks": 1},
    }
    pdf_result = _read_result(output, "ocr-pdf")
    assert pdf_result["ok"] is True
    assert pdf_result["name"] == "ocr-pdf"
    assert pdf_result["details"] == {
        "pages": 1,
        "codes": [100],
        "searchable_text": True,
        "output": str(output / "searchable.pdf"),
    }
    resources = _read_result(output, "resources")
    assert resources["ok"] is True
    assert resources["name"] == "resources"
    assert resources["details"]["duration_seconds"] >= 0
    assert resources["details"]["sampled_max_rss_bytes"] > 0
    assert resources["details"]["qt_loaded"] is False
    assert (output / "searchable.pdf").exists()


def test_validate_ocr_returns_one_when_image_ocr_fails(tmp_path):
    output, args = _validation_args(tmp_path, global_values={"fail_names": ["sample.png"]})

    code = main(args)

    assert code == 1
    assert _read_result(output, "ocr-image") == {
        "ok": False,
        "name": "ocr-image",
        "details": {"code": 500, "blocks": 0},
    }


def test_validate_ocr_returns_one_when_a_pdf_page_fails(tmp_path):
    output, args = _validation_args(
        tmp_path,
        global_values={"fail_names": ["page-000002.png"]},
        page_count=2,
    )

    code = main(args)

    assert code == 1
    pdf_result = _read_result(output, "ocr-pdf")
    assert pdf_result["ok"] is False
    assert pdf_result["name"] == "ocr-pdf"
    assert pdf_result["details"]["pages"] == 2
    assert pdf_result["details"]["codes"] == [100, 500]
    assert pdf_result["details"]["searchable_text"] is False


def test_validate_ocr_returns_one_when_qt_module_is_loaded(tmp_path, monkeypatch):
    output, args = _validation_args(tmp_path)
    monkeypatch.setitem(sys.modules, "PyQt6", object())

    code = main(args)

    assert code == 1
    resources = _read_result(output, "resources")
    assert resources["ok"] is False
    assert resources["name"] == "resources"
    assert resources["details"]["qt_loaded"] is True


def test_windows_script_uses_explicit_python_and_project_root():
    script = (PROJECT_ROOT / "scripts" / "run-windows-validation.ps1").read_text(
        encoding="utf-8"
    )

    assert "Push-Location $ProjectRoot" in script
    assert "& $PythonExe -m pytest -q" in script
    assert "Pop-Location" in script
    assert "Join-Path $ProjectRoot 'validation\\results\\live'" in script
