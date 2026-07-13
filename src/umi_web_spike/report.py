from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _read_json(path: Path) -> Tuple[Dict[str, Any], List[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, ["文件不存在"]
    except json.JSONDecodeError as error:
        return {}, ["JSON 无效：第 {} 行第 {} 列".format(error.lineno, error.colno)]
    except UnicodeDecodeError:
        return {}, ["文件不是有效的 UTF-8 文本"]
    except OSError as error:
        return {}, ["文件读取失败：{}".format(error)]
    if not isinstance(value, dict):
        return {}, ["根节点必须是对象"]
    return value, []


def _boolean_gate(
    value: Dict[str, Any], field_path: Tuple[str, ...], errors: List[str]
) -> bool:
    current: Any = value
    for index, key in enumerate(field_path):
        if not isinstance(current, dict):
            parent = ".".join(field_path[:index])
            errors.append("{} 必须是对象".format(parent or "根节点"))
            return False
        if key not in current:
            errors.append("缺少字段：{}".format(".".join(field_path)))
            return False
        current = current[key]
    if not isinstance(current, bool):
        errors.append("{} 必须是布尔 true 或 false；硬门槛必须是布尔 true".format(".".join(field_path)))
        return False
    return current is True


def build_report(results_dir: Path, e10_path: Path, report_path: Path) -> bool:
    paths = {
        "e10": Path(e10_path),
        "image": Path(results_dir) / "ocr-image.json",
        "pdf": Path(results_dir) / "ocr-pdf.json",
        "resources": Path(results_dir) / "resources.json",
    }
    values: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, List[str]] = {}
    for name, path in paths.items():
        values[name], errors[name] = _read_json(path)

    gates = (
        ("E10 官方 SSO 验证", "e10", ("ready",)),
        ("真实图片 OCR", "image", ("ok",)),
        ("真实 PDF OCR", "pdf", ("ok",)),
        ("PDF 可搜索文本", "pdf", ("details", "searchable_text")),
        ("资源探针成功", "resources", ("ok",)),
        ("无桌面会话运行", "resources", ("details", "headless")),
    )
    gate_results = []
    for label, source, field_path in gates:
        gate_results.append(
            (label, _boolean_gate(values[source], field_path, errors[source]))
        )

    passed = all(ok for _, ok in gate_results) and not any(errors.values())
    lines = ["# Umi-OCR Web 阶段 0 验证报告", "", "## 硬性门槛", ""]
    for label, ok in gate_results:
        lines.append("- [{}] {}".format("x" if ok else " ", label))
    lines.extend(["", "## 证据文件", ""])
    for name, path in paths.items():
        lines.append("- `{}`: `{}`".format(name, path))
        for error in errors[name]:
            lines.append("  - 读取/结构错误：{}".format(error))
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "结论：继续阶段 1"
            if passed
            else "结论：停止，修复失败项后重新验证",
            "",
        ]
    )
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return passed
