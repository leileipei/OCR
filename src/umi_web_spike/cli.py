from __future__ import print_function

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import uuid
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz
import psutil
from PIL import Image

from .evidence import (
    envelope,
    execution_identity,
    sha256_file,
    utc_now,
    validate_validation_id,
    write_json,
    WORKER_CALCULATION_BASIS,
)
from .pdf_probe import add_invisible_text_layer, render_pages
from .plugin_runner import PluginRunner
from .readiness import build_ocr_readiness_report, export_review_bundle
from .report import build_report


EXPECTED_OUTCOMES = {
    "simplified_chinese_image": "ocr_success",
    "mixed_chinese_english_image": "ocr_success",
    "scanned_pdf_rotated_blank": "ocr_success",
    "native_text_pdf": "native_text_detected",
    "corrupt_pdf": "open_failed",
    "encrypted_pdf": "encrypted_rejected",
}
IMAGE_CATEGORIES = {"simplified_chinese_image", "mixed_chinese_english_image"}
PDF_CATEGORIES = set(EXPECTED_OUTCOMES) - IMAGE_CATEGORIES
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_PATTERN = re.compile(r"[A-Za-z]")


def _windows_session_id() -> int:
    if os.name != "nt":
        raise RuntimeError("Windows Session ID is only available on Windows")
    session_id = ctypes.c_ulong()
    succeeded = ctypes.windll.kernel32.ProcessIdToSessionId(
        os.getpid(), ctypes.byref(session_id)
    )
    if not succeeded:
        raise OSError(ctypes.get_last_error(), "ProcessIdToSessionId failed")
    return int(session_id.value)


def _load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON must contain an object: {}".format(path))
    return value


def _load_samples(path: Path) -> List[Dict[str, str]]:
    value = _load_json(path)
    samples = value.get("samples")
    if not isinstance(samples, list):
        raise ValueError("samples manifest must contain a samples array")
    normalized = []
    seen = set()
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError("sample {} must be an object".format(index))
        category = sample.get("category")
        raw_path = sample.get("path")
        if category not in EXPECTED_OUTCOMES or not isinstance(raw_path, str) or not raw_path:
            raise ValueError("sample {} has an invalid category or path".format(index))
        if category in seen:
            raise ValueError("sample category is duplicated: {}".format(category))
        seen.add(category)
        normalized.append({"category": category, "path": raw_path})
    missing = set(EXPECTED_OUTCOMES) - seen
    if missing:
        raise ValueError("samples manifest is missing categories: {}".format(", ".join(sorted(missing))))
    return normalized


class ProcessTreeSampler:
    def __init__(self, interval_seconds: float = 0.05):
        self._process = psutil.Process()
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="resource-sampler", daemon=True)
        self.peak_rss = 0
        self.first_cpu = None
        self.last_cpu = 0.0
        self.sample_count = 0
        self.qt_processes = set()

    def _sample(self) -> None:
        processes = [self._process]
        try:
            processes.extend(self._process.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
        rss = 0
        cpu = 0.0
        for process in processes:
            try:
                rss += process.memory_info().rss
                times = process.cpu_times()
                cpu += times.user + times.system
                identity = " ".join([process.name()] + process.cmdline()).lower()
                if any(name in identity for name in ("pyside", "pyqt", "qml", "qtwebengine")):
                    self.qt_processes.add(str(process.pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                continue
        self.peak_rss = max(self.peak_rss, rss)
        if self.first_cpu is None:
            self.first_cpu = cpu
        self.last_cpu = max(self.last_cpu, cpu)
        self.sample_count += 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self._interval)

    def start(self) -> None:
        self._sample()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        self._sample()

    @property
    def cpu_seconds(self) -> float:
        return max(0.0, self.last_cpu - (self.first_cpu or 0.0))


def _result_text(result) -> str:
    return "\n".join(block.text.strip() for block in result.blocks if block.text.strip())


def _base_sample(sample: Dict[str, str]) -> Dict[str, Any]:
    path = Path(sample["path"])
    category = sample["category"]
    return {
        "category": category,
        "path": str(path.resolve()),
        "input_sha256": sha256_file(path),
        "expected": EXPECTED_OUTCOMES[category],
    }


def _run_image_sample(runner: PluginRunner, sample: Dict[str, str]) -> Dict[str, Any]:
    result = _base_sample(sample)
    with Image.open(sample["path"]) as image:
        minimum, maximum = image.convert("L").getextrema()
    input_nonblank = minimum < 250 or maximum - minimum > 5
    result["input_nonblank"] = input_nonblank
    if not input_nonblank:
        result.update(
            {"actual": "blank_input", "ok": False, "code": None, "blocks": 0, "non_empty_text_blocks": 0}
        )
        return result
    plugin_result = runner.run_path(Path(sample["path"]))
    non_empty = sum(1 for block in plugin_result.blocks if block.text.strip())
    ocr_text = _result_text(plugin_result).strip()
    if plugin_result.code != 100:
        actual = "ocr_failed"
    elif non_empty == 0:
        actual = "empty_ocr_text"
    elif sample["category"] == "simplified_chinese_image" and not CJK_PATTERN.search(ocr_text):
        actual = "language_mismatch"
    elif sample["category"] == "mixed_chinese_english_image" and not (
        CJK_PATTERN.search(ocr_text) and LATIN_PATTERN.search(ocr_text)
    ):
        actual = "language_mismatch"
    else:
        actual = "ocr_success"
    result.update(
        {
            "actual": actual,
            "ok": actual == result["expected"],
            "code": plugin_result.code,
            "blocks": len(plugin_result.blocks),
            "non_empty_text_blocks": non_empty,
            "ocr_text": ocr_text,
        }
    )
    return result


def _source_text_and_encryption(path: Path) -> Tuple[bool, bool]:
    with fitz.open(path) as document:
        encrypted = bool(document.needs_pass)
        has_text = False if encrypted else any(page.get_text().strip() for page in document)
    return has_text, encrypted


def _run_scanned_pdf(
    runner: PluginRunner, sample: Dict[str, str], working_dir: Path
) -> Tuple[Dict[str, Any], int, bool]:
    result = _base_sample(sample)
    path = Path(sample["path"])
    source_has_text, encrypted = _source_text_and_encryption(path)
    result["source_has_text"] = source_has_text
    if encrypted:
        result.update({"actual": "encrypted_rejected", "ok": False, "pages": 0, "ocr_text": "", "output_contains_ocr_text": False})
        return result, 0, False
    if source_has_text:
        result.update({"actual": "source_has_text", "ok": False, "pages": len(fitz.open(path)), "ocr_text": "", "output_contains_ocr_text": False})
        return result, 0, False
    with fitz.open(path) as document:
        rotated_pages = sum(1 for page in document if page.rotation % 360 != 0)
        blank_pages = 0
        for page in document:
            pixels = page.get_pixmap(dpi=36, colorspace=fitz.csGRAY, alpha=False).samples
            if pixels and min(pixels) >= 250:
                blank_pages += 1
    pages = render_pages(path, working_dir / "pages")
    page_results = [runner.run_path(page) for page in pages]
    texts = [_result_text(item) for item in page_results]
    ocr_text = "\n".join(text for text in texts if text).strip()
    output = working_dir / "searchable.pdf"
    output_contains = False
    if pages and all(item.code == 100 for item in page_results) and ocr_text:
        add_invisible_text_layer(path, output, texts)
        with fitz.open(output) as document:
            extracted = "\n".join(page.get_text() for page in document)
        output_contains = all(text in extracted for text in texts if text)
    coverage_ok = rotated_pages > 0 and blank_pages > 0
    actual = "ocr_success" if output_contains and coverage_ok else "ocr_failed"
    result.update(
        {
            "actual": actual,
            "ok": actual == result["expected"],
            "pages": len(pages),
            "rotated_pages": rotated_pages,
            "blank_pages": blank_pages,
            "codes": [item.code for item in page_results],
            "ocr_text": ocr_text,
            "output_contains_ocr_text": output_contains,
            "output": "searchable.pdf",
        }
    )
    return result, len(pages), output_contains


def _run_classification_pdf(sample: Dict[str, str]) -> Dict[str, Any]:
    result = _base_sample(sample)
    category = sample["category"]
    path = Path(sample["path"])
    try:
        source_has_text, encrypted = _source_text_and_encryption(path)
        if encrypted:
            actual = "encrypted_rejected"
        elif source_has_text:
            actual = "native_text_detected"
        else:
            actual = "unexpected_pdf"
        result.update({"source_has_text": source_has_text, "needs_pass": encrypted})
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        actual = "open_failed"
        result["error"] = "{}: {}".format(type(error).__name__, error)
    result.update({"actual": actual, "ok": actual == result["expected"]})
    return result


def _resource_result(
    common: Dict[str, Any], identity: Dict[str, Any], sampler: ProcessTreeSampler,
    started: float, processed_pages: int, minimum_pages: int, business_concurrency_limit: int,
    execution_mode: str,
) -> Dict[str, Any]:
    duration = round(max(time.perf_counter() - started, 0.000001), 6)
    qt_loaded = bool(sampler.qt_processes) or any(name.startswith(("PySide", "PyQt")) for name in sys.modules)
    session_name = os.environ.get("SESSIONNAME", "")
    windows_session_id = _windows_session_id()
    interactive = windows_session_id > 0
    headless = not qt_loaded and windows_session_id == 0
    peak = max(1, sampler.peak_rss)
    try:
        memory_budget = int(psutil.virtual_memory().available * 0.7)
    except (OSError, PermissionError):
        memory_budget = peak
    logical_cpu_count = psutil.cpu_count(logical=True) or 1
    memory_worker_limit = max(1, memory_budget // peak)
    cpu_worker_limit = max(1, logical_cpu_count // 2)
    recommended = min(memory_worker_limit, cpu_worker_limit, business_concurrency_limit)
    details = {
        "observed_peak_process_tree_rss_bytes": sampler.peak_rss,
        "process_tree_cpu_seconds": round(sampler.cpu_seconds, 6),
        "duration_seconds": duration,
        "processed_pages": processed_pages,
        "minimum_required_pages": minimum_pages,
        "pages_per_minute": round(processed_pages * 60.0 / duration, 6),
        "sample_count": sampler.sample_count,
        "recommended_workers": recommended,
        "worker_calculation_basis": WORKER_CALCULATION_BASIS,
        "memory_budget_bytes": memory_budget,
        "logical_cpu_count": logical_cpu_count,
        "memory_worker_limit": memory_worker_limit,
        "cpu_worker_limit": cpu_worker_limit,
        "business_concurrency_limit": business_concurrency_limit,
        "qt_loaded": qt_loaded,
        "qt_processes": sorted(sampler.qt_processes),
        "session_name": session_name,
        "windows_session_id": windows_session_id,
        "interactive_session": interactive,
        "headless": headless,
    }
    session_ok = (
        execution_mode == "interactive"
        and interactive
        and windows_session_id > 0
    ) or (
        execution_mode == "scheduled"
        and not interactive
        and headless
        and windows_session_id == 0
    )
    ok = (
        details["observed_peak_process_tree_rss_bytes"] > 0
        and details["duration_seconds"] > 0
        and details["processed_pages"] >= minimum_pages
        and details["pages_per_minute"] > 0
        and details["sample_count"] > 0
        and not qt_loaded
        and session_ok
    )
    return {**common, **identity, "ok": ok, "name": "resources", "details": details}


def _execute_validation(args: argparse.Namespace, working_dir: Path) -> bool:
    validation_id = validate_validation_id(args.validation_id)
    campaign_id = validate_validation_id(args.campaign_id)
    if args.min_pages < 1:
        raise ValueError("min_pages must be at least 1")
    if args.business_concurrency_limit < 1:
        raise ValueError("business_concurrency_limit must be at least 1")
    recorded = utc_now()
    common = {
        **envelope(validation_id, campaign_id, recorded),
        "execution_mode": args.execution_mode,
    }
    identity = execution_identity(Path(args.plugin_root), args.plugin_name)
    samples = _load_samples(Path(args.samples_manifest))
    sampler = ProcessTreeSampler()
    started = time.perf_counter()
    image_samples = []
    pdf_samples = []
    processed_pages = 0
    searchable_text = False
    sampler.start()
    try:
        with PluginRunner(Path(args.plugin_root), args.plugin_name, _load_json(Path(args.global_options_json))) as runner:
            runner.start(_load_json(Path(args.local_options_json)))
            for sample in samples:
                category = sample["category"]
                if category in IMAGE_CATEGORIES:
                    image_samples.append(_run_image_sample(runner, sample))
                elif category == "scanned_pdf_rotated_blank":
                    result, pages, searchable = _run_scanned_pdf(runner, sample, working_dir)
                    pdf_samples.append(result)
                    processed_pages += pages
                    searchable_text = searchable
                else:
                    pdf_samples.append(_run_classification_pdf(sample))
    finally:
        sampler.stop()

    image_ok = len(image_samples) == len(IMAGE_CATEGORIES) and all(item["ok"] is True for item in image_samples)
    pdf_ok = len(pdf_samples) == len(PDF_CATEGORIES) and all(item["ok"] is True for item in pdf_samples) and searchable_text
    image_evidence = {**common, **identity, "ok": image_ok, "name": "ocr-image", "details": {"samples": image_samples}}
    pdf_evidence = {**common, **identity, "ok": pdf_ok, "name": "ocr-pdf", "details": {"searchable_text": searchable_text, "samples": pdf_samples}}
    resources = _resource_result(
        common, identity, sampler, started, processed_pages, args.min_pages,
        args.business_concurrency_limit, args.execution_mode,
    )
    write_json(working_dir / "ocr-image.json", image_evidence)
    write_json(working_dir / "ocr-pdf.json", pdf_evidence)
    write_json(working_dir / "resources.json", resources)
    passed = image_ok and pdf_ok and resources["ok"] is True
    evidence_digests = {
        name: sha256_file(working_dir / name)
        for name in ("ocr-image.json", "ocr-pdf.json", "resources.json")
    }
    write_json(
        working_dir / "manifest.json",
        {**common, "status": "completed", "evidence": evidence_digests, "passed": passed},
    )
    return passed


def _validate_ocr(args: argparse.Namespace) -> int:
    output = Path(args.output_dir)
    try:
        validation_id = validate_validation_id(args.validation_id)
        campaign_id = validate_validation_id(args.campaign_id)
    except ValueError:
        return 1
    if output.name != validation_id:
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        return 1
    temporary = output.parent / (".{}.{}.tmp".format(validation_id, uuid.uuid4().hex))
    temporary.mkdir()
    passed = False
    try:
        try:
            passed = _execute_validation(args, temporary)
        except Exception as error:
            identity = execution_identity(Path(args.plugin_root), args.plugin_name)
            write_json(
                temporary / "manifest.json",
                {
                    **envelope(validation_id, campaign_id, utc_now()),
                    "execution_mode": args.execution_mode,
                    "status": "failed",
                    "diagnostic": "{}: {}".format(type(error).__name__, error),
                    "traceback": traceback.format_exc(),
                    **identity,
                    "environment_summary": {
                        "platform": platform.platform(),
                        "session_name": os.environ.get("SESSIONNAME", ""),
                        "process_id": os.getpid(),
                    },
                },
            )
        temporary.rename(output)
    except OSError:
        return 1
    finally:
        if temporary.exists():
            shutil.rmtree(str(temporary))
    return 0 if passed else 1


def _build_report(args: argparse.Namespace) -> int:
    return 0 if build_report(Path(args.results_dir), Path(args.e10), Path(args.output)) else 1


def _build_ocr_readiness(args: argparse.Namespace) -> int:
    try:
        succeeded = build_ocr_readiness_report(
            args.campaign_id,
            Path(args.interactive_dir),
            Path(args.scheduled_dir),
            Path(args.output),
        )
    except (OSError, ValueError):
        return 1
    return 0 if succeeded else 1


def _export_review_bundle(args: argparse.Namespace) -> int:
    try:
        export_review_bundle(
            args.campaign_id,
            Path(args.interactive_dir),
            Path(args.scheduled_dir),
            Path(args.output),
        )
    except (OSError, ValueError):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="umi-web-spike")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-ocr")
    for name in (
        "validation-id", "campaign-id", "plugin-root", "plugin-name", "global-options-json",
        "local-options-json", "samples-manifest", "output-dir",
    ):
        validate.add_argument("--" + name, required=True)
    validate.add_argument("--min-pages", type=int, default=100)
    validate.add_argument("--business-concurrency-limit", type=int, default=5)
    validate.add_argument(
        "--execution-mode", choices=("interactive", "scheduled"), required=True
    )
    validate.set_defaults(handler=_validate_ocr)
    report = subparsers.add_parser("build-report")
    report.add_argument("--results-dir", required=True)
    report.add_argument("--e10", required=True)
    report.add_argument("--output", required=True)
    report.set_defaults(handler=_build_report)
    readiness = subparsers.add_parser("build-ocr-readiness")
    readiness.add_argument("--campaign-id", required=True)
    readiness.add_argument("--interactive-dir", required=True)
    readiness.add_argument("--scheduled-dir", required=True)
    readiness.add_argument("--output", required=True)
    readiness.set_defaults(handler=_build_ocr_readiness)
    review = subparsers.add_parser("export-review-bundle")
    review.add_argument("--campaign-id", required=True)
    review.add_argument("--interactive-dir", required=True)
    review.add_argument("--scheduled-dir", required=True)
    review.add_argument("--output", required=True)
    review.set_defaults(handler=_export_review_bundle)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
