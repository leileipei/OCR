import hashlib
import json
from copy import deepcopy


PLUGIN = {"name": "ocr_paddle", "root": "C:\\Umi-OCR\\data\\plugins"}
INTERPRETER = {
    "executable": "C:\\Umi-OCR\\runtime\\python.exe",
    "version": "3.8.10",
}
CATEGORIES = {
    "simplified_chinese_image",
    "mixed_chinese_english_image",
    "scanned_pdf_rotated_blank",
    "native_text_pdf",
    "corrupt_pdf",
    "encrypted_pdf",
}


def _sample(root, category):
    expected = {
        "simplified_chinese_image": "ocr_success",
        "mixed_chinese_english_image": "ocr_success",
        "scanned_pdf_rotated_blank": "ocr_success",
        "native_text_pdf": "native_text_detected",
        "corrupt_pdf": "open_failed",
        "encrypted_pdf": "encrypted_rejected",
    }[category]
    input_path = root / "inputs" / "{}.dat".format(category)
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(("sample:" + category).encode("utf-8"))
    value = {
        "category": category,
        "path": str(input_path.resolve()),
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "expected": expected,
        "actual": expected,
        "ok": True,
    }
    if category in ("simplified_chinese_image", "mixed_chinese_english_image"):
        text = (
            "简体中文识别"
            if category == "simplified_chinese_image"
            else "中文 OCR English"
        )
        value.update(
            {
                "input_nonblank": True,
                "code": 100,
                "non_empty_text_blocks": 1,
                "ocr_text": text,
            }
        )
    elif category == "scanned_pdf_rotated_blank":
        value.update(
            {
                "source_has_text": False,
                "pages": 100,
                "rotated_pages": 1,
                "blank_pages": 1,
                "ocr_text": "识别文本",
                "output_contains_ocr_text": True,
            }
        )
    elif category == "native_text_pdf":
        value["source_has_text"] = True
    elif category == "corrupt_pdf":
        value["error"] = "FileDataError: cannot open broken document"
    elif category == "encrypted_pdf":
        value["needs_pass"] = True
    return value


def valid_evidence(root, validation_id, execution_mode):
    common = {
        "schema_version": "1.0",
        "validation_id": validation_id,
        "recorded_at_utc": "2026-07-13T04:05:06Z",
    }
    ocr_common = {**common, "execution_mode": execution_mode}
    official_document = root / "inputs" / "e10-official.pdf"
    official_document.parent.mkdir(parents=True, exist_ok=True)
    official_document.write_bytes(b"controlled official E10 document")
    e10 = {
        **common,
        "protocol": "oidc",
        "official_document_reference": "E10 官方统一身份接口文档 v10",
        "official_document_path": str(official_document.resolve()),
        "official_document_sha256": hashlib.sha256(
            official_document.read_bytes()
        ).hexdigest(),
        "login_endpoint": "https://oa.example.internal/sso/authorize",
        "verification_endpoint": "https://oa.example.internal/sso/userinfo",
        "external_user_id_field": "user_id",
        "department_id_field": "department_id",
        "test_login_succeeded": True,
        "disabled_account_rejected": True,
        "logout_behavior_verified": True,
        "ready": True,
    }
    image = {
        **ocr_common,
        "plugin": PLUGIN,
        "interpreter": INTERPRETER,
        "ok": True,
        "name": "ocr-image",
        "details": {
            "samples": [
                _sample(root, "simplified_chinese_image"),
                _sample(root, "mixed_chinese_english_image"),
            ]
        },
    }
    pdf = {
        **ocr_common,
        "plugin": PLUGIN,
        "interpreter": INTERPRETER,
        "ok": True,
        "name": "ocr-pdf",
        "details": {
            "searchable_text": True,
            "samples": [
                _sample(root, category)
                for category in CATEGORIES
                if category.endswith("pdf")
                or category.startswith(("scanned", "native", "corrupt", "encrypted"))
            ],
        },
    }
    scheduled = execution_mode == "scheduled"
    resources = {
        **ocr_common,
        "plugin": PLUGIN,
        "interpreter": INTERPRETER,
        "ok": True,
        "name": "resources",
        "details": {
            "observed_peak_process_tree_rss_bytes": 1024,
            "process_tree_cpu_seconds": 1.5,
            "duration_seconds": 60.0,
            "processed_pages": 100,
            "minimum_required_pages": 100,
            "pages_per_minute": 100.0,
            "sample_count": 2,
            "recommended_workers": 2,
            "worker_calculation_basis": "recommended_workers=min(memory_worker_limit,cpu_worker_limit,business_concurrency_limit); memory_worker_limit=max(1,floor(memory_budget_bytes/observed_peak_process_tree_rss_bytes)); cpu_worker_limit=max(1,floor(logical_cpu_count/2))",
            "memory_budget_bytes": 4096,
            "logical_cpu_count": 8,
            "memory_worker_limit": 4,
            "cpu_worker_limit": 4,
            "business_concurrency_limit": 2,
            "qt_loaded": False,
            "windows_session_id": 0 if scheduled else 1,
            "interactive_session": not scheduled,
            "headless": scheduled,
        },
    }
    manifest = {
        **ocr_common,
        "status": "completed",
        "passed": True,
        "evidence": None,
    }
    return {
        "e10.json": e10,
        "ocr-image.json": image,
        "ocr-pdf.json": pdf,
        "resources.json": resources,
        "manifest.json": manifest,
    }


def write_evidence(root, validation_id, execution_mode, mutate=None):
    evidence = deepcopy(valid_evidence(root, validation_id, execution_mode))
    if mutate:
        mutate(evidence)
    for name in ("e10.json", "ocr-image.json", "ocr-pdf.json", "resources.json"):
        (root / name).write_text(json.dumps(evidence[name]), encoding="utf-8")
    if evidence["manifest.json"].get("evidence") is None:
        evidence["manifest.json"]["evidence"] = {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("ocr-image.json", "ocr-pdf.json", "resources.json")
        }
    (root / "manifest.json").write_text(
        json.dumps(evidence["manifest.json"]), encoding="utf-8"
    )
    return evidence
