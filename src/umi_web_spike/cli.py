from __future__ import print_function

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz
import psutil

from .contracts import ProbeResult
from .pdf_probe import add_invisible_text_layer, render_pages
from .plugin_runner import PluginRunner


def _load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("options JSON must contain an object")
    return value


def _result_text(result) -> str:
    return "\n".join(block.text for block in result.blocks)


def _validate_ocr(args: argparse.Namespace) -> int:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()
    started = time.perf_counter()
    sampled_max_rss = process.memory_info().rss
    image_result = None
    page_results = []

    with PluginRunner(
        Path(args.plugin_root),
        args.plugin_name,
        _load_json(Path(args.global_options_json)),
    ) as runner:
        runner.start(_load_json(Path(args.local_options_json)))
        image_result = runner.run_path(Path(args.image))
        sampled_max_rss = max(sampled_max_rss, process.memory_info().rss)
        rendered = render_pages(Path(args.pdf), output / "pages")
        for page_path in rendered:
            page_results.append(runner.run_path(page_path))
            sampled_max_rss = max(sampled_max_rss, process.memory_info().rss)

    image_ok = image_result.code == 100
    ProbeResult(
        ok=image_ok,
        name="ocr-image",
        details={"code": image_result.code, "blocks": len(image_result.blocks)},
    ).write_json(output / "ocr-image.json")

    pdf_ok = bool(page_results) and all(result.code == 100 for result in page_results)
    searchable_text = False
    searchable_pdf = output / "searchable.pdf"
    if pdf_ok:
        add_invisible_text_layer(
            Path(args.pdf), searchable_pdf, [_result_text(result) for result in page_results]
        )
        with fitz.open(searchable_pdf) as document:
            searchable_text = any(page.get_text().strip() for page in document)
    ProbeResult(
        ok=pdf_ok and searchable_text,
        name="ocr-pdf",
        details={
            "pages": len(page_results),
            "codes": [result.code for result in page_results],
            "searchable_text": searchable_text,
            "output": str(searchable_pdf),
        },
    ).write_json(output / "ocr-pdf.json")

    qt_loaded = any(name.startswith(("PySide2", "PyQt")) for name in sys.modules)
    session_name = os.environ.get("SESSIONNAME", "")
    ProbeResult(
        ok=not qt_loaded,
        name="resources",
        details={
            "duration_seconds": round(time.perf_counter() - started, 3),
            "sampled_max_rss_bytes": sampled_max_rss,
            "qt_loaded": qt_loaded,
            "session_name": session_name,
            "headless": not qt_loaded and session_name.lower() == "services",
        },
    ).write_json(output / "resources.json")
    return 0 if image_ok and pdf_ok and searchable_text and not qt_loaded else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="umi-web-spike")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-ocr")
    for name in (
        "plugin-root",
        "plugin-name",
        "global-options-json",
        "local-options-json",
        "image",
        "pdf",
        "output-dir",
    ):
        validate.add_argument("--" + name, required=True)
    validate.set_defaults(handler=_validate_ocr)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
