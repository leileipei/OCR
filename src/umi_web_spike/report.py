from __future__ import annotations

import json
import re
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Tuple

from .e10_evidence import E10Evidence
from .evidence import (
    SCHEMA_VERSION,
    WORKER_CALCULATION_BASIS,
    is_utc_timestamp,
    sha256_file,
    validate_validation_id,
)


EXPECTED_OUTCOMES = {
    "simplified_chinese_image": "ocr_success",
    "mixed_chinese_english_image": "ocr_success",
    "scanned_pdf_rotated_blank": "ocr_success",
    "native_text_pdf": "native_text_detected",
    "corrupt_pdf": "open_failed",
    "encrypted_pdf": "encrypted_rejected",
}
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _read_json(path: Path) -> Tuple[Dict[str, Any], List[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, ["文件不存在"]
    except json.JSONDecodeError as error:
        return {}, ["JSON 无效：第 {} 行第 {} 列".format(error.lineno, error.colno)]
    except (UnicodeDecodeError, OSError) as error:
        return {}, ["文件读取失败：{}".format(error)]
    if not isinstance(value, dict):
        return {}, ["根节点必须是对象"]
    return value, []


def _error(errors: Dict[str, List[str]], source: str, message: str) -> None:
    errors[source].append(message)


def _require_bool(value: Dict[str, Any], key: str, source: str, errors: Dict[str, List[str]], expected: bool) -> bool:
    actual = value.get(key)
    if not isinstance(actual, bool):
        _error(errors, source, "{} 必须是真布尔值".format(key))
        return False
    if actual is not expected:
        _error(errors, source, "{} 必须为 {}".format(key, str(expected).lower()))
        return False
    return True


def _validate_common(source: str, value: Dict[str, Any], errors: Dict[str, List[str]]) -> None:
    if value.get("schema_version") != SCHEMA_VERSION:
        _error(errors, source, "schema_version 必须为 {}".format(SCHEMA_VERSION))
    try:
        validate_validation_id(value.get("validation_id"))
    except ValueError as error:
        _error(errors, source, str(error))
    if not is_utc_timestamp(value.get("recorded_at_utc")):
        _error(errors, source, "recorded_at_utc 必须是 UTC ISO-8601 时间")


def _validate_identity(source: str, value: Dict[str, Any], errors: Dict[str, List[str]]) -> None:
    plugin = value.get("plugin")
    if not isinstance(plugin, dict):
        _error(errors, source, "plugin 必须是对象")
    else:
        for field in ("name", "root"):
            if not isinstance(plugin.get(field), str) or not plugin[field].strip():
                _error(errors, source, "plugin.{} 必须是非空字符串".format(field))
        root = plugin.get("root")
        if isinstance(root, str) and not (Path(root).is_absolute() or PureWindowsPath(root).is_absolute()):
            _error(errors, source, "plugin.root 必须是绝对路径")
    interpreter = value.get("interpreter")
    if not isinstance(interpreter, dict):
        _error(errors, source, "interpreter 必须是对象")
    else:
        for field in ("executable", "version"):
            if not isinstance(interpreter.get(field), str) or not interpreter[field].strip():
                _error(errors, source, "interpreter.{} 必须是非空字符串".format(field))
        executable = interpreter.get("executable")
        if isinstance(executable, str) and not (Path(executable).is_absolute() or PureWindowsPath(executable).is_absolute()):
            _error(errors, source, "interpreter.executable 必须是绝对路径")


def _validate_sample(sample: Any, source: str, errors: Dict[str, List[str]]) -> Optional[str]:
    if not isinstance(sample, dict):
        _error(errors, source, "样本记录必须是对象")
        return None
    category = sample.get("category")
    if category not in EXPECTED_OUTCOMES:
        _error(errors, source, "样本类别无效：{}".format(category))
        return None
    expected = EXPECTED_OUTCOMES[category]
    if sample.get("expected") != expected:
        _error(errors, source, "{} 的 expected 不符合固定门槛".format(category))
    if sample.get("actual") != expected:
        _error(errors, source, "{} 的实际结果与预期不一致".format(category))
    _require_bool(sample, "ok", source, errors, True)
    if not isinstance(sample.get("path"), str) or not sample["path"].strip():
        _error(errors, source, "{} 缺少样本路径".format(category))
    digest = sample.get("input_sha256")
    if not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
        _error(errors, source, "{} 的输入 SHA-256 无效".format(category))
    else:
        sample_path = Path(sample.get("path", ""))
        if not sample_path.is_absolute() or not sample_path.is_file():
            _error(errors, source, "{} 的样本路径必须是存在的绝对文件路径".format(category))
        elif sha256_file(sample_path) != digest:
            _error(errors, source, "{} 的输入 SHA-256 与实际文件不一致".format(category))
    if category in ("simplified_chinese_image", "mixed_chinese_english_image"):
        if sample.get("input_nonblank") is not True:
            _error(errors, source, "{} 输入图片必须实际检测为非空白".format(category))
        if sample.get("code") != 100:
            _error(errors, source, "{} OCR code 必须为 100".format(category))
        if not _positive_number(sample.get("non_empty_text_blocks"), integer=True):
            _error(errors, source, "{} 必须包含非空 OCR 文本块".format(category))
        ocr_text = sample.get("ocr_text")
        if not isinstance(ocr_text, str) or not ocr_text.strip():
            _error(errors, source, "{} 必须记录非空 OCR 文本".format(category))
        elif category == "simplified_chinese_image" and not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", ocr_text):
            _error(errors, source, "简体中文图片 OCR 文本必须实际包含 CJK 字符")
        elif category == "mixed_chinese_english_image" and not (
            re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", ocr_text)
            and re.search(r"[A-Za-z]", ocr_text)
        ):
            _error(errors, source, "中英混排图片 OCR 文本必须同时包含 CJK 与拉丁字母")
    elif category == "scanned_pdf_rotated_blank":
        if sample.get("source_has_text") is not False:
            _error(errors, source, "扫描 PDF 源文件必须确认无文本层")
        if not _positive_number(sample.get("pages"), integer=True):
            _error(errors, source, "扫描 PDF 页数必须为正整数")
        if not _positive_number(sample.get("rotated_pages"), integer=True):
            _error(errors, source, "扫描 PDF 必须实际包含旋转页")
        if not _positive_number(sample.get("blank_pages"), integer=True):
            _error(errors, source, "扫描 PDF 必须实际包含空白页")
        if not isinstance(sample.get("ocr_text"), str) or not sample["ocr_text"].strip():
            _error(errors, source, "扫描 PDF 必须包含本次 OCR 产生的文本")
        _require_bool(sample, "output_contains_ocr_text", source, errors, True)
    elif category == "native_text_pdf" and sample.get("source_has_text") is not True:
        _error(errors, source, "原生 PDF 必须实际检测到文本层")
    elif category == "corrupt_pdf":
        if not isinstance(sample.get("error"), str) or not sample["error"].strip():
            _error(errors, source, "损坏 PDF 必须记录打开失败诊断")
    elif category == "encrypted_pdf" and sample.get("needs_pass") is not True:
        _error(errors, source, "加密 PDF 必须实际检测到密码保护")
    return category


def _positive_number(value: Any, integer: bool = False, allow_zero: bool = False) -> bool:
    if isinstance(value, bool):
        return False
    expected_type = int if integer else (int, float)
    if not isinstance(value, expected_type):
        return False
    return value >= 0 if allow_zero else value > 0


def _validate_resources(
    value: Dict[str, Any], errors: Dict[str, List[str]], scanned_pdf_pages: Optional[int]
) -> None:
    source = "resources"
    _require_bool(value, "ok", source, errors, True)
    details = value.get("details")
    if not isinstance(details, dict):
        _error(errors, source, "details 必须是对象")
        return
    positive_fields = (
        "observed_peak_process_tree_rss_bytes", "duration_seconds", "processed_pages",
        "pages_per_minute", "sample_count", "recommended_workers", "memory_budget_bytes",
        "logical_cpu_count", "memory_worker_limit", "cpu_worker_limit",
        "business_concurrency_limit",
    )
    integer_fields = {
        "observed_peak_process_tree_rss_bytes", "processed_pages", "sample_count",
        "recommended_workers", "memory_budget_bytes", "logical_cpu_count",
        "memory_worker_limit", "cpu_worker_limit", "business_concurrency_limit",
    }
    for field in positive_fields:
        if not _positive_number(details.get(field), integer=field in integer_fields):
            _error(errors, source, "{} 必须为正数".format(field))
    if not _positive_number(details.get("process_tree_cpu_seconds"), allow_zero=True):
        _error(errors, source, "process_tree_cpu_seconds 必须为非负数")
    minimum = details.get("minimum_required_pages")
    if not _positive_number(minimum, integer=True) or minimum < 100:
        _error(errors, source, "minimum_required_pages 正式门槛不得低于 100")
    processed = details.get("processed_pages")
    if isinstance(processed, int) and not isinstance(processed, bool) and isinstance(minimum, int) and processed < minimum:
        _error(errors, source, "processed_pages 未达到页数门槛")
    if scanned_pdf_pages is None or processed != scanned_pdf_pages:
        _error(errors, source, "processed_pages 必须等于扫描 PDF 实际页数")
    duration = details.get("duration_seconds")
    pages_per_minute = details.get("pages_per_minute")
    if _positive_number(duration) and _positive_number(processed, integer=True):
        expected_rate = round(processed * 60.0 / duration, 6)
        if pages_per_minute != expected_rate:
            _error(errors, source, "pages_per_minute 与页数/耗时复算不一致")
    peak = details.get("observed_peak_process_tree_rss_bytes")
    memory_budget = details.get("memory_budget_bytes")
    logical_cpu = details.get("logical_cpu_count")
    business_limit = details.get("business_concurrency_limit")
    if all(_positive_number(item, integer=True) for item in (peak, memory_budget, logical_cpu, business_limit)):
        expected_memory_limit = max(1, memory_budget // peak)
        expected_cpu_limit = max(1, logical_cpu // 2)
        if details.get("memory_worker_limit") != expected_memory_limit:
            _error(errors, source, "memory_worker_limit 复算不一致")
        if details.get("cpu_worker_limit") != expected_cpu_limit:
            _error(errors, source, "cpu_worker_limit 复算不一致")
        expected_recommended = min(expected_memory_limit, expected_cpu_limit, business_limit)
        if details.get("recommended_workers") != expected_recommended:
            _error(errors, source, "recommended_workers 复算不一致")
    if details.get("worker_calculation_basis") != WORKER_CALCULATION_BASIS:
        _error(errors, source, "worker_calculation_basis 与固定计算口径不一致")
    _require_bool(details, "qt_loaded", source, errors, False)
    _require_bool(details, "interactive_session", source, errors, False)
    _require_bool(details, "headless", source, errors, True)


def build_report(results_dir: Path, e10_path: Path, report_path: Path) -> bool:
    paths = {
        "e10": Path(e10_path),
        "image": Path(results_dir) / "ocr-image.json",
        "pdf": Path(results_dir) / "ocr-pdf.json",
        "resources": Path(results_dir) / "resources.json",
        "manifest": Path(results_dir) / "manifest.json",
    }
    values: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, List[str]] = {}
    for source, path in paths.items():
        values[source], errors[source] = _read_json(path)

    for source, value in values.items():
        _validate_common(source, value, errors)

    try:
        e10_evidence = E10Evidence.from_dict(values["e10"])
        if not e10_evidence.ready:
            _error(errors, "e10", "E10 三项真实验证必须全部通过，ready 必须为 true")
    except (ValueError, TypeError, KeyError) as error:
        _error(errors, "e10", "E10 完整证据无效：{}".format(error))

    validation_ids = {value.get("validation_id") for value in values.values() if isinstance(value.get("validation_id"), str)}
    if len(validation_ids) != 1:
        for source in values:
            _error(errors, source, "validation_id 不一致，禁止跨运行混用证据")

    identities = []
    for source in ("image", "pdf", "resources"):
        _validate_identity(source, values[source], errors)
        identities.append((values[source].get("plugin"), values[source].get("interpreter")))
    if len({json.dumps(identity, sort_keys=True, ensure_ascii=True) for identity in identities}) != 1:
        for source in ("image", "pdf", "resources"):
            _error(errors, source, "插件或解释器身份不一致")

    _require_bool(values["image"], "ok", "image", errors, True)
    _require_bool(values["pdf"], "ok", "pdf", errors, True)
    image_details = values["image"].get("details")
    pdf_details = values["pdf"].get("details")
    categories = []
    categories_by_source: Dict[str, List[str]] = {"image": [], "pdf": []}
    for source, details in (("image", image_details), ("pdf", pdf_details)):
        if not isinstance(details, dict) or not isinstance(details.get("samples"), list):
            _error(errors, source, "details.samples 必须是数组")
            continue
        validated = [_validate_sample(sample, source, errors) for sample in details["samples"]]
        categories.extend(validated)
        categories_by_source[source].extend(item for item in validated if item)
    expected_by_source = {
        "image": {"simplified_chinese_image", "mixed_chinese_english_image"},
        "pdf": set(EXPECTED_OUTCOMES) - {"simplified_chinese_image", "mixed_chinese_english_image"},
    }
    for source, expected_categories in expected_by_source.items():
        if set(categories_by_source[source]) != expected_categories or len(categories_by_source[source]) != len(expected_categories):
            _error(errors, source, "{} 证据中的样本类别归属不正确".format(source))
    actual_categories = [item for item in categories if item]
    if set(actual_categories) != set(EXPECTED_OUTCOMES) or len(actual_categories) != len(EXPECTED_OUTCOMES):
        _error(errors, "image", "样本类别必须完整且每类恰好一个")
        _error(errors, "pdf", "样本类别必须完整且每类恰好一个")
    if isinstance(pdf_details, dict):
        _require_bool(pdf_details, "searchable_text", "pdf", errors, True)

    scanned_pdf_pages = None
    if isinstance(pdf_details, dict) and isinstance(pdf_details.get("samples"), list):
        for sample in pdf_details["samples"]:
            if isinstance(sample, dict) and sample.get("category") == "scanned_pdf_rotated_blank":
                pages = sample.get("pages")
                if isinstance(pages, int) and not isinstance(pages, bool):
                    scanned_pdf_pages = pages
                break
    _validate_resources(values["resources"], errors, scanned_pdf_pages)
    manifest = values["manifest"]
    if manifest.get("status") != "completed":
        _error(errors, "manifest", "manifest.status 必须为 completed")
    _require_bool(manifest, "passed", "manifest", errors, True)
    expected_evidence = {"ocr-image.json", "ocr-pdf.json", "resources.json"}
    manifest_evidence = manifest.get("evidence")
    if not isinstance(manifest_evidence, dict) or set(manifest_evidence) != expected_evidence:
        _error(errors, "manifest", "manifest.evidence 必须是三个证据文件的 SHA-256 映射")
    else:
        for name, digest in manifest_evidence.items():
            evidence_path = Path(results_dir) / name
            if not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
                _error(errors, "manifest", "manifest.evidence.{} 摘要无效".format(name))
            elif not evidence_path.is_file() or sha256_file(evidence_path) != digest:
                _error(errors, "manifest", "manifest.evidence.{} 与实际文件不一致".format(name))

    passed = not any(errors.values())
    lines = ["# Umi-OCR Web 阶段 0 验证报告", "", "## 硬性门槛", ""]
    gates = (
        ("E10 官方 SSO 完整证据", not errors["e10"]),
        ("同一 validation_id 与执行身份", not any("validation_id" in error or "身份" in error for entries in errors.values() for error in entries)),
        ("真实图片 OCR 非空文本", not errors["image"]),
        ("真实 PDF OCR 与完整样本覆盖", not errors["pdf"]),
        ("100 页资源与无界面门槛", not errors["resources"]),
        ("原子运行清单", not errors["manifest"]),
    )
    for label, ok in gates:
        lines.append("- [{}] {}".format("x" if ok else " ", label))
    lines.extend(["", "## 证据文件与诊断", ""])
    for source, path in paths.items():
        lines.append("- `{}`: `{}`".format(source, path))
        for error in errors[source]:
            lines.append("  - {}".format(error))
    lines.extend(["", "## 结论", "", "结论：继续阶段 1" if passed else "结论：停止，修复失败项后重新验证", ""])
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return passed
