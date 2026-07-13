from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, Tuple

from .evidence import SCHEMA_VERSION, validate_validation_id
from .evidence_validation import OcrEvidenceValidation, validate_ocr_evidence


STATUS = "OCR_READY_E10_PENDING"
ARCHIVE_ENTRIES = (
    "review-summary.json",
    "ocr-readiness.md",
    "SHA256SUMS.txt",
)
RUN_SUMMARY_KEYS = {
    "validation_id",
    "execution_mode",
    "windows_session_id",
    "processed_pages",
    "duration_seconds",
    "pages_per_minute",
    "observed_peak_process_tree_rss_bytes",
    "recommended_workers",
    "sample_categories",
    "headless",
}
EXPECTED_SAMPLE_CATEGORIES = {
    "simplified_chinese_image",
    "mixed_chinese_english_image",
    "scanned_pdf_rotated_blank",
    "native_text_pdf",
    "corrupt_pdf",
    "encrypted_pdf",
}
SENSITIVE_KEY_PARTS = (
    "password",
    "token",
    "cookie",
    "authorization",
    "ocr_text",
    "path",
)
RESERVED_STATUS_WORDS = (
    "phase_0_passed",
    "ocr_ready_e10_pending",
    "phase_0_not_passed",
)
JSON_PATH_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_readiness_identifier(value: str, label: str) -> str:
    value = validate_validation_id(value)
    lowered = value.lower()
    if any(status in lowered for status in RESERVED_STATUS_WORDS):
        raise ValueError("{} contains a reserved status word".format(label))
    return value


def _validated_pair(
    campaign_id: str, interactive_dir: Path, scheduled_dir: Path
) -> Tuple[OcrEvidenceValidation, OcrEvidenceValidation]:
    campaign_id = _validate_readiness_identifier(campaign_id, "campaign_id")
    interactive = validate_ocr_evidence(
        Path(interactive_dir), expected_mode="interactive"
    )
    scheduled = validate_ocr_evidence(
        Path(scheduled_dir), expected_mode="scheduled"
    )
    if not interactive.ok:
        raise ValueError("interactive OCR evidence is invalid")
    if not scheduled.ok:
        raise ValueError("scheduled OCR evidence is invalid")
    if interactive.campaign_id != campaign_id:
        raise ValueError(
            "interactive OCR evidence campaign_id does not match declared campaign"
        )
    if scheduled.campaign_id != campaign_id:
        raise ValueError(
            "scheduled OCR evidence campaign_id does not match declared campaign"
        )
    _validate_readiness_identifier(
        interactive.validation_id, "interactive validation_id"
    )
    _validate_readiness_identifier(
        scheduled.validation_id, "scheduled validation_id"
    )
    if interactive.validation_id == scheduled.validation_id:
        raise ValueError(
            "interactive and scheduled runs must use different validation IDs"
        )
    return interactive, scheduled


def _report_text(
    campaign_id: str,
    interactive: OcrEvidenceValidation,
    scheduled: OcrEvidenceValidation,
) -> str:
    return "\n".join(
        (
            "# Umi-OCR OCR 侧就绪报告",
            "",
            "Campaign：{}".format(campaign_id),
            "",
            "交互运行：{}".format(interactive.validation_id),
            "计划任务运行：{}".format(scheduled.validation_id),
            "",
            "- [x] 普通 PowerShell 真实 OCR 验证",
            "- [x] 无登录用户计划任务真实 OCR 验证",
            "- [ ] e-cology 10 官方 SSO 验证",
            "",
            "状态：{}".format(STATUS),
            "",
            "Phase 0 尚未通过；不得开始正式 Web 开发。",
            "",
        )
    )


def _write_new_text(path: Path, text: str) -> None:
    path = Path(path)
    if path.exists():
        raise ValueError("output already exists")
    temporary = path.with_name(".{}.tmp".format(path.name))
    if temporary.exists():
        raise ValueError("temporary output already exists")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as target:
            target.write(text)
        if path.exists():
            raise ValueError("output already exists")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_staging_text(path: Path, text: str) -> None:
    with Path(path).open("x", encoding="utf-8", newline="\n") as target:
        target.write(text)


def build_ocr_readiness_report(
    campaign_id: str,
    interactive_dir: Path,
    scheduled_dir: Path,
    output_path: Path,
) -> bool:
    campaign_id = _validate_readiness_identifier(campaign_id, "campaign_id")
    interactive, scheduled = _validated_pair(
        campaign_id, interactive_dir, scheduled_dir
    )
    _write_new_text(
        Path(output_path), _report_text(campaign_id, interactive, scheduled)
    )
    return True


def _child_json_path(path: str, key: str) -> str:
    if JSON_PATH_IDENTIFIER.fullmatch(key):
        return "{}.{}".format(path, key)
    return "{}[{}]".format(path, json.dumps(key, ensure_ascii=True))


def _reject_sensitive_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("review summary keys must be strings")
            child_path = _child_json_path(path, key)
            lowered = key.lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                raise ValueError(
                    "review summary contains a sensitive key at {}".format(
                        child_path
                    )
                )
            _reject_sensitive_keys(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_keys(child, "{}[{}]".format(path, index))
    elif type(value) not in (str, int, float, bool):
        raise ValueError("review summary contains a disallowed value type")


def _require_number(value: Any, field: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("{} must be a finite number".format(field))


def _validate_run_summary(
    value: Any, expected_mode: str, expected_validation_id: str
) -> None:
    if not isinstance(value, dict) or set(value) != RUN_SUMMARY_KEYS:
        raise ValueError("review run summary contains non-allowlisted keys")
    if value["validation_id"] != expected_validation_id:
        raise ValueError("review run summary validation_id is inconsistent")
    validate_validation_id(value["validation_id"])
    if value["execution_mode"] != expected_mode:
        raise ValueError("review run summary execution_mode is inconsistent")
    integer_fields = (
        "windows_session_id",
        "processed_pages",
        "observed_peak_process_tree_rss_bytes",
        "recommended_workers",
    )
    for field in integer_fields:
        if type(value[field]) is not int:
            raise ValueError("{} must be an integer".format(field))
    for field in ("duration_seconds", "pages_per_minute"):
        _require_number(value[field], field)
    if type(value["headless"]) is not bool:
        raise ValueError("headless must be a boolean")
    categories = value["sample_categories"]
    if (
        not isinstance(categories, list)
        or len(categories) != len(EXPECTED_SAMPLE_CATEGORIES)
        or set(categories) != EXPECTED_SAMPLE_CATEGORIES
        or not all(isinstance(item, str) for item in categories)
    ):
        raise ValueError("sample_categories contains non-allowlisted values")


def _review_summary(
    campaign_id: str,
    interactive: OcrEvidenceValidation,
    scheduled: OcrEvidenceValidation,
) -> Dict[str, Any]:
    summary = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "status": STATUS,
        "interactive": {
            "validation_id": interactive.validation_id,
            **interactive.summary,
        },
        "scheduled": {
            "validation_id": scheduled.validation_id,
            **scheduled.summary,
        },
    }
    _reject_sensitive_keys(summary)
    if set(summary) != {
        "schema_version",
        "campaign_id",
        "status",
        "interactive",
        "scheduled",
    }:
        raise ValueError("review summary contains non-allowlisted keys")
    if summary["schema_version"] != SCHEMA_VERSION:
        raise ValueError("review summary schema_version is invalid")
    if summary["campaign_id"] != campaign_id:
        raise ValueError("review summary campaign_id is inconsistent")
    if summary["status"] != STATUS:
        raise ValueError("review summary status is invalid")
    _validate_run_summary(
        summary["interactive"], "interactive", interactive.validation_id
    )
    _validate_run_summary(
        summary["scheduled"], "scheduled", scheduled.validation_id
    )
    return summary


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def export_review_bundle(
    campaign_id: str,
    interactive_dir: Path,
    scheduled_dir: Path,
    output_zip: Path,
) -> Path:
    campaign_id = _validate_readiness_identifier(campaign_id, "campaign_id")
    interactive, scheduled = _validated_pair(
        campaign_id, interactive_dir, scheduled_dir
    )
    summary = _review_summary(campaign_id, interactive, scheduled)
    output_zip = Path(output_zip)
    staging = output_zip.parent / (output_zip.stem + ".staging")
    if output_zip.exists() or staging.exists():
        raise ValueError("review bundle output already exists")

    try:
        staging.mkdir()
        report = staging / "ocr-readiness.md"
        _write_new_text(
            report, _report_text(campaign_id, interactive, scheduled)
        )
        _write_staging_text(
            staging / "review-summary.json",
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
        )
        checksummed_entries = ARCHIVE_ENTRIES[:2]
        sums = [
            "{}  {}".format(
                hashlib.sha256((staging / name).read_bytes()).hexdigest(), name
            )
            for name in checksummed_entries
        ]
        _write_staging_text(
            staging / "SHA256SUMS.txt", "\n".join(sums) + "\n"
        )

        temporary_archive = staging / ".review.zip.tmp"
        with zipfile.ZipFile(
            temporary_archive, "x", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name in ARCHIVE_ENTRIES:
                archive.writestr(_zip_info(name), (staging / name).read_bytes())
        if output_zip.exists():
            raise ValueError("review bundle output already exists")
        temporary_archive.replace(output_zip)
    finally:
        if staging.exists():
            shutil.rmtree(str(staging))
    return output_zip
