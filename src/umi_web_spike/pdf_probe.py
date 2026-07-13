"""阶段 0 PDF 能力探针。

这里只验证 Windows 服务环境中的页面渲染和不可见文本层能力。
正式阶段必须使用 OCR 文本框坐标实现逐块对齐、字体回退和页面旋转处理，
并由真实样本集验收。
"""

from pathlib import Path
from typing import List, Sequence, Tuple

import fitz


def render_pages(pdf_path: Path, output_dir: Path, dpi: int = 150) -> Tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: List[Path] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document):
            target = output_dir / f"page-{index + 1:06d}.png"
            page.get_pixmap(dpi=dpi, alpha=False).save(target)
            rendered.append(target)
    return tuple(rendered)


def add_invisible_text_layer(
    input_pdf: Path, output_pdf: Path, page_texts: Sequence[str]
) -> None:
    with fitz.open(input_pdf) as document:
        if len(document) != len(page_texts):
            raise ValueError("page count does not match OCR text count")
        for page, text in zip(document, page_texts):
            page.insert_text((1, 1), text, fontsize=1, render_mode=3, overlay=True)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_pdf, garbage=4, deflate=True)
