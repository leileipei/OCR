from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .e10_evidence import E10Evidence
from .evidence_validation import validate_ocr_evidence


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


def build_report(results_dir: Path, e10_path: Path, report_path: Path) -> bool:
    results_dir = Path(results_dir)
    paths = {
        "e10": Path(e10_path),
        "image": results_dir / "ocr-image.json",
        "pdf": results_dir / "ocr-pdf.json",
        "resources": results_dir / "resources.json",
        "manifest": results_dir / "manifest.json",
    }
    ocr_validation = validate_ocr_evidence(
        results_dir, expected_mode="scheduled"
    )
    errors: Dict[str, List[str]] = {
        source: list(messages)
        for source, messages in ocr_validation.errors.items()
    }
    e10_value, errors["e10"] = _read_json(paths["e10"])

    e10_validation_id = None
    try:
        e10_evidence = E10Evidence.from_dict(e10_value)
        e10_validation_id = e10_evidence.validation_id
        if not e10_evidence.ready:
            errors["e10"].append(
                "E10 三项真实验证必须全部通过，ready 必须为 true"
            )
    except (ValueError, TypeError, KeyError) as error:
        errors["e10"].append("E10 完整证据无效：{}".format(error))

    if (
        ocr_validation.validation_id is None
        or e10_validation_id != ocr_validation.validation_id
    ):
        errors["e10"].append(
            "validation_id 与 scheduled OCR 证据不一致，禁止跨运行混用证据"
        )

    passed = ocr_validation.ok and not errors["e10"]
    all_errors = [message for messages in errors.values() for message in messages]
    lines = ["# Umi-OCR Web 阶段 0 验证报告", "", "## 硬性门槛", ""]
    gates = (
        ("E10 官方 SSO 完整证据", not errors["e10"]),
        (
            "同一 validation_id 与执行身份",
            not any(
                "validation_id" in message or "身份" in message
                for message in all_errors
            ),
        ),
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
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "结论：继续阶段 1" if passed else "结论：停止，修复失败项后重新验证",
            "",
        ]
    )
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return passed
