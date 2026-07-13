# Umi-OCR Web Phase 0 Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Windows Server 上用可重复的探针验证无 QML OCR、PDF 流程和 e-cology 10 官方 SSO 边界，为正式 Web 开发给出可审计的继续/停止结论。

**Architecture:** 建立一个不包含正式 Web UI 的 Python 探针包。探针直接加载兼容 Umi-OCR `PluginInfo` 协议的 OCR 插件，独立验证 PDF 渲染与不可见文本层，并把 E10 官方接口证据、OCR 结果和资源数据汇总为阶段报告。

**Tech Stack:** Windows Server 2022 x64、Python 3.8.10（真实插件探针）与 Python 3.12（兼容性复测）、pytest、PyMuPDF、Pillow、psutil、PowerShell 5.1+

## Global Constraints

- 公司内网、Windows Server、e-cology 10、10–100 名用户。
- 首期负载为每天少于 1,000 页，同时 1–5 人提交任务。
- Web 后端与 OCR Worker 不共享 Python 虚拟环境。
- E10 只使用当前客户实例官方支持的 SSO 接口，不抓取登录网页、不共享 OA Cookie、不直连 OA 数据库。
- OCR 插件必须脱离 QML 和登录桌面会话运行；否则阶段 0 判定不通过。
- 文件和输出不得包含真实敏感业务数据；验证样本必须脱敏。
- 按用户要求，不执行 `git commit`，每个任务以测试通过和变更清单作为检查点。

---

## Execution Prerequisites

- 在隔离的 Windows Server 验证机上，从 [Umi-OCR v2.1.5 官方 Release](https://github.com/hiroi-sora/Umi-OCR/releases/tag/v2.1.5) 获取 RapidOCR 或 PaddleOCR 正式发行包，解压到 `C:\UmiOCRProbe\Umi-OCR`；
- 真实插件解释器使用 `C:\UmiOCRProbe\Umi-OCR\UmiOCR-data\runtime\python.exe`；
- 运行脚本时把 `UmiOCR-data\py_src\imports` 和 `UmiOCR-data\site-packages` 加入 `PYTHONPATH`；
- Python 3.12 只用于再次运行不加载真实插件的自动化测试，证明探针契约可以被后续现代 Web 后端复用；
- OA 管理员在执行 Task 4 前提供当前 E10 测试环境、官方接口文档和正常/禁用测试账号；
- 安全团队确认所有验证样本已经脱敏。

---

## File Map

- `pyproject.toml`：探针包元数据、运行依赖、pytest 配置。
- `src/umi_web_spike/contracts.py`：OCR 块、OCR 结果和探针结果的稳定数据契约。
- `src/umi_web_spike/plugin_runner.py`：脱离 QML 加载并运行 Umi OCR 插件。
- `src/umi_web_spike/pdf_probe.py`：PDF 渲染、页图像输出和不可见文本层验证。
- `src/umi_web_spike/e10_evidence.py`：记录并验证 E10 官方 SSO 接口证据。
- `src/umi_web_spike/report.py`：汇总探针产物并生成阶段 0 结论。
- `src/umi_web_spike/cli.py`：统一命令行入口。
- `tests/fakes/fake_ocr_plugin/__init__.py`：实现 Umi `PluginInfo` 协议的可控假插件。
- `tests/test_contracts.py`：结果契约测试。
- `tests/test_plugin_runner.py`：插件发现、生命周期和结果归一化测试。
- `tests/test_pdf_probe.py`：PDF 渲染和可搜索文本层测试。
- `tests/test_e10_evidence.py`：E10 证据完整性与安全规则测试。
- `tests/test_report.py`：继续/停止判定测试。
- `scripts/run-windows-validation.ps1`：在目标 Windows Server 上执行真实插件和样本验证。
- `validation/samples/README.md`：脱敏样本要求，不保存真实样本。
- `validation/results/.gitkeep`：探针结果目录。
- `docs/validation/phase-0-report.md`：由报告命令生成的最终证据摘要。

---

### Task 1: 建立探针包和稳定结果契约

**Files:**
- Create: `pyproject.toml`
- Create: `src/umi_web_spike/__init__.py`
- Create: `src/umi_web_spike/contracts.py`
- Create: `tests/test_contracts.py`

**Interfaces:**
- Consumes: 无。
- Produces: `OcrBlock.from_plugin_dict(value) -> OcrBlock`、`OcrResult.from_plugin_dict(value) -> OcrResult`、`ProbeResult.write_json(path) -> None`。

- [ ] **Step 1: 写结果契约的失败测试**

```python
# tests/test_contracts.py
import json

from umi_web_spike.contracts import OcrBlock, OcrResult, ProbeResult


def test_normalizes_umi_plugin_result(tmp_path):
    raw = {
        "code": 100,
        "data": [
            {
                "text": "示例",
                "score": 0.98,
                "box": [[1, 2], [11, 2], [11, 12], [1, 12]],
            }
        ],
    }
    result = OcrResult.from_plugin_dict(raw)
    assert result.code == 100
    assert result.blocks == (
        OcrBlock(
            text="示例",
            score=0.98,
            box=((1.0, 2.0), (11.0, 2.0), (11.0, 12.0), (1.0, 12.0)),
        ),
    )

    output = tmp_path / "probe.json"
    ProbeResult(ok=True, name="contracts", details={"blocks": 1}).write_json(output)
    assert json.loads(output.read_text(encoding="utf-8"))["ok"] is True


def test_rejects_malformed_success_result():
    try:
        OcrResult.from_plugin_dict({"code": 100, "data": "not-a-list"})
    except ValueError as error:
        assert "data must be a list" in str(error)
    else:
        raise AssertionError("malformed plugin result was accepted")
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `python -m pytest tests/test_contracts.py -v`  
Expected: FAIL，包含 `ModuleNotFoundError: No module named 'umi_web_spike'`。

- [ ] **Step 3: 添加包配置和最小契约实现**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling>=1.26,<2"]
build-backend = "hatchling.build"

[project]
name = "umi-web-spike"
version = "0.1.0"
requires-python = ">=3.8.10,<3.13"
dependencies = [
  "pillow>=10.4,<12",
  "pymupdf>=1.24,<2",
  "psutil>=6,<8",
]

[project.optional-dependencies]
test = ["pytest>=8.3,<9"]

[project.scripts]
umi-web-spike = "umi_web_spike.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/umi_web_spike"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

```python
# src/umi_web_spike/contracts.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class OcrBlock:
    text: str
    score: float
    box: Tuple[Tuple[float, float], ...]

    @classmethod
    def from_plugin_dict(cls, value: Dict[str, Any]) -> "OcrBlock":
        box = value.get("box")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("block.box must contain four points")
        points = tuple((float(point[0]), float(point[1])) for point in box)
        return cls(text=str(value["text"]), score=float(value["score"]), box=points)


@dataclass(frozen=True)
class OcrResult:
    code: int
    blocks: Tuple[OcrBlock, ...] = ()
    error: Optional[str] = None

    @classmethod
    def from_plugin_dict(cls, value: Dict[str, Any]) -> "OcrResult":
        code = int(value["code"])
        data = value.get("data")
        if code == 100:
            if not isinstance(data, list):
                raise ValueError("data must be a list for code 100")
            return cls(code=code, blocks=tuple(OcrBlock.from_plugin_dict(item) for item in data))
        return cls(code=code, error=str(data))


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    name: str
    details: Dict[str, Any]

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
```

```python
# src/umi_web_spike/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 4: 安装测试依赖并验证契约测试通过**

Run: `python -m pip install -e ".[test]"`  
Expected: exit 0。  
Run: `python -m pytest tests/test_contracts.py -v`  
Expected: 2 passed。

- [ ] **Step 5: 记录非 Git 检查点**

Run: `python -m pytest tests/test_contracts.py -q && git status --short`  
Expected: 测试通过；输出只包含本任务新增的未提交文件及此前确认的文档。

---

### Task 2: 实现无 QML 插件加载器

**Files:**
- Create: `src/umi_web_spike/plugin_runner.py`
- Create: `tests/fakes/fake_ocr_plugin/__init__.py`
- Create: `tests/test_plugin_runner.py`

**Interfaces:**
- Consumes: `OcrResult.from_plugin_dict(value)`。
- Produces: `PluginRunner(plugin_root, plugin_name, global_options)`、`start(local_options)`、`run_path(path) -> OcrResult`、`close()`。

- [ ] **Step 1: 创建符合 Umi 协议的假插件**

```python
# tests/fakes/fake_ocr_plugin/__init__.py
class FakeApi:
    def __init__(self, global_options):
        self.global_options = global_options
        self.started = False

    def start(self, local_options):
        self.started = True
        self.local_options = local_options
        return "[Success]"

    def runPath(self, path):
        if not self.started:
            return {"code": 900, "data": "not started"}
        return {
            "code": 100,
            "data": [{"text": path, "score": 1.0, "box": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        }

    def stop(self):
        self.started = False


PluginInfo = {
    "group": "ocr",
    "api_class": FakeApi,
    "global_options": {},
    "local_options": {},
}
```

- [ ] **Step 2: 写插件生命周期的失败测试**

```python
# tests/test_plugin_runner.py
from pathlib import Path

from umi_web_spike.plugin_runner import PluginRunner


def test_runs_plugin_without_qt_or_qml():
    plugin_root = Path(__file__).parent / "fakes"
    runner = PluginRunner(plugin_root, "fake_ocr_plugin", {"model": "fake"})
    runner.start({"language": "简体中文"})
    result = runner.run_path(Path("sample.png"))
    runner.close()

    assert result.code == 100
    assert result.blocks[0].text == "sample.png"


def test_rejects_non_ocr_plugin(tmp_path):
    package = tmp_path / "bad_plugin"
    package.mkdir()
    (package / "__init__.py").write_text("PluginInfo = {'group': 'other'}", encoding="utf-8")
    try:
        PluginRunner(tmp_path, "bad_plugin", {})
    except ValueError as error:
        assert "group must be ocr" in str(error)
    else:
        raise AssertionError("invalid plugin was accepted")
```

- [ ] **Step 3: 运行测试并确认加载器不存在**

Run: `python -m pytest tests/test_plugin_runner.py -v`  
Expected: FAIL，包含 `No module named 'umi_web_spike.plugin_runner'`。

- [ ] **Step 4: 实现插件加载和生命周期**

```python
# src/umi_web_spike/plugin_runner.py
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict

from .contracts import OcrResult


class PluginRunner:
    def __init__(self, plugin_root: Path, plugin_name: str, global_options: Dict[str, Any]):
        root = str(plugin_root.resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        module = importlib.import_module(plugin_name)
        info = getattr(module, "PluginInfo", None)
        if not isinstance(info, dict) or info.get("group") != "ocr":
            raise ValueError("PluginInfo.group must be ocr")
        api_class = info.get("api_class")
        if not callable(api_class):
            raise ValueError("PluginInfo.api_class must be callable")
        self._api = api_class(global_options)
        self._started = False

    def start(self, local_options: Dict[str, Any]) -> None:
        message = str(self._api.start(local_options))
        if message.startswith("[Error]"):
            raise RuntimeError(message)
        self._started = True

    def run_path(self, path: Path) -> OcrResult:
        if not self._started:
            raise RuntimeError("plugin has not been started")
        return OcrResult.from_plugin_dict(self._api.runPath(str(path)))

    def close(self) -> None:
        if self._started:
            self._api.stop()
            self._started = False

    def __enter__(self) -> "PluginRunner":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
```

- [ ] **Step 5: 验证插件测试不导入 Qt**

Run: `python -m pytest tests/test_plugin_runner.py -v`  
Expected: 2 passed。  
Run: `python -c "import sys; from pathlib import Path; from umi_web_spike.plugin_runner import PluginRunner; PluginRunner(Path('tests/fakes'), 'fake_ocr_plugin', {}); assert not any(name.startswith(('PySide2', 'PyQt')) for name in sys.modules)"`  
Expected: exit 0。

---

### Task 3: 验证 PDF 渲染和可搜索文本层

**Files:**
- Create: `src/umi_web_spike/pdf_probe.py`
- Create: `tests/test_pdf_probe.py`

**Interfaces:**
- Consumes: 文件路径和每页 OCR 文本。
- Produces: `render_pages(pdf_path, output_dir, dpi=150) -> Tuple[Path, ...]`、`add_invisible_text_layer(input_pdf, output_pdf, page_texts) -> None`。

- [ ] **Step 1: 写 PDF 行为的失败测试**

```python
# tests/test_pdf_probe.py
import fitz

from umi_web_spike.pdf_probe import add_invisible_text_layer, render_pages


def make_pdf(path):
    document = fitz.open()
    document.new_page(width=300, height=200)
    document.save(path)


def test_renders_every_page_and_adds_searchable_text(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "searchable.pdf"
    make_pdf(source)

    pages = render_pages(source, tmp_path / "pages", dpi=96)
    assert [path.name for path in pages] == ["page-000001.png"]

    add_invisible_text_layer(source, output, ["识别结果 ABC-123"])
    with fitz.open(output) as document:
        assert "ABC-123" in document[0].get_text()


def test_rejects_page_count_mismatch(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    try:
        add_invisible_text_layer(source, tmp_path / "out.pdf", [])
    except ValueError as error:
        assert "page count" in str(error)
    else:
        raise AssertionError("page count mismatch was accepted")
```

- [ ] **Step 2: 运行测试并确认 PDF 模块不存在**

Run: `python -m pytest tests/test_pdf_probe.py -v`  
Expected: FAIL，包含 `No module named 'umi_web_spike.pdf_probe'`。

- [ ] **Step 3: 实现逐页渲染和不可见文本层**

```python
# src/umi_web_spike/pdf_probe.py
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
```

- [ ] **Step 4: 运行 PDF 测试并检查输出可重新打开**

Run: `python -m pytest tests/test_pdf_probe.py -v`  
Expected: 2 passed。

- [ ] **Step 5: 明确阶段 0 与正式 PDF 合成的边界**

在 `pdf_probe.py` 文件开头加入：

```python
"""阶段 0 PDF 能力探针。

这里只验证 Windows 服务环境中的页面渲染和不可见文本层能力。
正式阶段必须使用 OCR 文本框坐标实现逐块对齐、字体回退和页面旋转处理，
并由真实样本集验收。
"""
```

Run: `python -m pytest tests/test_pdf_probe.py -q`  
Expected: 2 passed。

---

### Task 4: 建立 E10 官方 SSO 证据记录器

**Files:**
- Create: `src/umi_web_spike/e10_evidence.py`
- Create: `tests/test_e10_evidence.py`

**Interfaces:**
- Consumes: OA 管理员依据当前客户实例官方文档提供的验证结果。
- Produces: `E10Evidence.from_dict(value) -> E10Evidence`、`E10Evidence.write_json(path) -> None`。

- [ ] **Step 1: 写证据完整性的失败测试**

```python
# tests/test_e10_evidence.py
from umi_web_spike.e10_evidence import E10Evidence


VALID = {
    "protocol": "oidc",
    "official_document_reference": "E10 客户开放平台/统一身份接口文档版本 10",
    "login_endpoint": "https://oa.example.internal/sso/authorize",
    "verification_endpoint": "https://oa.example.internal/sso/userinfo",
    "external_user_id_field": "user_id",
    "department_id_field": "department_id",
    "test_login_succeeded": True,
    "disabled_account_rejected": True,
    "logout_behavior_verified": True,
}


def test_accepts_complete_official_evidence():
    evidence = E10Evidence.from_dict(VALID)
    assert evidence.ready is True


def test_rejects_database_or_cookie_integration():
    for protocol in ("database", "shared_cookie", "html_scraping"):
        value = {**VALID, "protocol": protocol}
        try:
            E10Evidence.from_dict(value)
        except ValueError as error:
            assert "unsupported or unsafe protocol" in str(error)
        else:
            raise AssertionError(f"unsafe protocol accepted: {protocol}")


def test_requires_stable_user_and_department_identifiers():
    value = {**VALID, "external_user_id_field": ""}
    try:
        E10Evidence.from_dict(value)
    except ValueError as error:
        assert "external_user_id_field" in str(error)
    else:
        raise AssertionError("missing stable user id was accepted")
```

- [ ] **Step 2: 运行测试并确认 E10 模块不存在**

Run: `python -m pytest tests/test_e10_evidence.py -v`  
Expected: FAIL，包含 `No module named 'umi_web_spike.e10_evidence'`。

- [ ] **Step 3: 实现协议白名单和证据验证**

```python
# src/umi_web_spike/e10_evidence.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse


ALLOWED_PROTOCOLS = {"oidc", "oauth2", "cas", "saml2", "official_ticket"}


@dataclass(frozen=True)
class E10Evidence:
    protocol: str
    official_document_reference: str
    login_endpoint: str
    verification_endpoint: str
    external_user_id_field: str
    department_id_field: str
    test_login_succeeded: bool
    disabled_account_rejected: bool
    logout_behavior_verified: bool

    @property
    def ready(self) -> bool:
        return self.test_login_succeeded and self.disabled_account_rejected and self.logout_behavior_verified

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "E10Evidence":
        protocol = str(value.get("protocol", "")).lower()
        if protocol not in ALLOWED_PROTOCOLS:
            raise ValueError(f"unsupported or unsafe protocol: {protocol}")
        for key in (
            "official_document_reference",
            "login_endpoint",
            "verification_endpoint",
            "external_user_id_field",
            "department_id_field",
        ):
            if not str(value.get(key, "")).strip():
                raise ValueError(f"{key} is required")
        for key in ("login_endpoint", "verification_endpoint"):
            if urlparse(str(value[key])).scheme != "https":
                raise ValueError(f"{key} must use https")
        return cls(**{field: value[field] for field in cls.__dataclass_fields__})

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["ready"] = self.ready
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 运行证据测试**

Run: `python -m pytest tests/test_e10_evidence.py -v`  
Expected: 3 passed。

- [ ] **Step 5: 由 OA 管理员在测试环境生成真实证据文件**

OA 管理员依据当前 E10 官方接口文档完成一次正常登录、一次禁用账号登录和一次退出验证，把验证值保存为 UTF-8 JSON，再运行：

```powershell
python -c "import json; from pathlib import Path; from umi_web_spike.e10_evidence import E10Evidence; p=Path('validation/results/e10.json'); E10Evidence.from_dict(json.loads(p.read_text(encoding='utf-8'))).write_json(p)"
```

Expected: exit 0，`validation/results/e10.json` 中 `test_login_succeeded`、`disabled_account_rejected`、`logout_behavior_verified` 均为 `true`。如果任何一项为 `false`，阶段 0 不通过，不开始正式认证开发。

---

### Task 5: 添加真实 Windows OCR/PDF 验证命令

**Files:**
- Create: `src/umi_web_spike/cli.py`
- Create: `tests/test_cli.py`
- Create: `scripts/run-windows-validation.ps1`
- Create: `validation/samples/README.md`
- Create: `validation/results/.gitkeep`

**Interfaces:**
- Consumes: `PluginRunner`、`render_pages`、`add_invisible_text_layer`、脱敏图片/PDF 和实际插件路径。
- Produces: `validation/results/ocr-image.json`、`ocr-pdf.json`、`resources.json`、`searchable.pdf`。

- [ ] **Step 1: 写 CLI 端到端失败测试**

```python
# tests/test_cli.py
import json

import fitz
from PIL import Image

from umi_web_spike.cli import main


def test_validate_ocr_with_fake_plugin(tmp_path):
    image = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), "white").save(image)
    pdf = tmp_path / "sample.pdf"
    document = fitz.open()
    document.new_page(width=200, height=100)
    document.save(pdf)

    global_options = tmp_path / "global.json"
    local_options = tmp_path / "local.json"
    global_options.write_text(json.dumps({}), encoding="utf-8")
    local_options.write_text(json.dumps({}), encoding="utf-8")
    output = tmp_path / "results"

    code = main(
        [
            "validate-ocr",
            "--plugin-root", "tests/fakes",
            "--plugin-name", "fake_ocr_plugin",
            "--global-options-json", str(global_options),
            "--local-options-json", str(local_options),
            "--image", str(image),
            "--pdf", str(pdf),
            "--output-dir", str(output),
        ]
    )

    assert code == 0
    assert (output / "ocr-image.json").exists()
    assert (output / "ocr-pdf.json").exists()
    assert (output / "resources.json").exists()
    assert (output / "searchable.pdf").exists()
```

- [ ] **Step 2: 运行测试并确认 CLI 尚未实现**

Run: `python -m pytest tests/test_cli.py -v`  
Expected: FAIL，包含 `No module named 'umi_web_spike.cli'`。

- [ ] **Step 3: 实现真实插件验证命令**

```python
# src/umi_web_spike/cli.py
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
    peak_rss = process.memory_info().rss
    image_result = None
    page_results = []

    with PluginRunner(
        Path(args.plugin_root),
        args.plugin_name,
        _load_json(Path(args.global_options_json)),
    ) as runner:
        runner.start(_load_json(Path(args.local_options_json)))
        image_result = runner.run_path(Path(args.image))
        peak_rss = max(peak_rss, process.memory_info().rss)
        rendered = render_pages(Path(args.pdf), output / "pages")
        for page_path in rendered:
            page_results.append(runner.run_path(page_path))
            peak_rss = max(peak_rss, process.memory_info().rss)

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
            "peak_rss_bytes": peak_rss,
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
```

参数包括：

```text
--plugin-root PATH
--plugin-name NAME
--global-options-json PATH
--local-options-json PATH
--image PATH
--pdf PATH
--output-dir PATH
```

命令执行以下实际流程：加载插件一次，识别图片；把 PDF 渲染为 PNG 并逐页识别；把每页文本写入不可见文本层；记录总耗时、峰值 RSS、插件返回码、文本块数、PDF 页数和输出路径。所有结果通过 `ProbeResult.write_json` 写入输出目录；任一 OCR 返回码不是 100 时进程退出码为 1。

- [ ] **Step 4: 为 CLI 使用假插件运行端到端验证**

Run: `python -m pytest tests/test_cli.py -v`  
Expected: 1 passed；临时输出目录包含图片结果、PDF 结果、资源数据和 `searchable.pdf`。

- [ ] **Step 5: 编写 Windows 验证脚本**

```powershell
# scripts/run-windows-validation.ps1
param(
  [string]$ProjectRoot = (Resolve-Path ".").Path,
  [Parameter(Mandatory=$true)][string]$UmiDataRoot,
  [Parameter(Mandatory=$true)][string]$PythonExe,
  [Parameter(Mandatory=$true)][string]$PluginRoot,
  [Parameter(Mandatory=$true)][string]$PluginName,
  [Parameter(Mandatory=$true)][string]$GlobalOptions,
  [Parameter(Mandatory=$true)][string]$LocalOptions,
  [Parameter(Mandatory=$true)][string]$Image,
  [Parameter(Mandatory=$true)][string]$Pdf
)

$ErrorActionPreference = "Stop"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$env:PYTHONPATH = "$ProjectRoot\src;$UmiDataRoot\py_src\imports;$UmiDataRoot\site-packages"
& $PythonExe -m umi_web_spike.cli validate-ocr `
  --plugin-root $PluginRoot `
  --plugin-name $PluginName `
  --global-options-json $GlobalOptions `
  --local-options-json $LocalOptions `
  --image $Image `
  --pdf $Pdf `
  --output-dir validation/results/live
exit $LASTEXITCODE
```

- [ ] **Step 6: 定义脱敏样本集合**

`validation/samples/README.md` 明确要求执行者在本地提供但不提交：

- 一张简体中文图片；
- 一张中英混排图片；
- 一份 10 页扫描 PDF，包含旋转页和空白页；
- 一份带原生文本层的 PDF；
- 一份损坏 PDF 和一份加密 PDF，用于失败分类；
- 所有样本不含姓名、身份证号、合同号或其他真实敏感信息。

- [ ] **Step 7: 在目标 Windows Server 的非交互会话执行真实验证**

先从普通 PowerShell 运行一次，再通过计划任务以“无论用户是否登录都运行”方式执行同一脚本。两次均要求：

- exit 0；
- 实际插件未导入 PySide2/PyQt；
- 图片和每个 PDF 页面返回 OCR 成功码；
- `searchable.pdf` 可由 PyMuPDF 打开且能提取非空文本；
- `resources.json` 记录峰值 RSS 和总耗时；
- 没有弹窗、桌面会话或 QML 引擎依赖。

任一条件失败时保存错误栈和环境信息，阶段 0 判定不通过。

---

### Task 6: 自动生成继续/停止报告

**Files:**
- Create: `src/umi_web_spike/report.py`
- Create: `tests/test_report.py`
- Modify: `src/umi_web_spike/cli.py`
- Create: `docs/validation/phase-0-report.md`（命令生成）

**Interfaces:**
- Consumes: E10、真实 OCR/PDF 和资源 JSON 证据。
- Produces: `build_report(results_dir, e10_path, report_path) -> bool`，返回 `True` 表示可以开始阶段 1；CLI 子命令 `build-report`。

- [ ] **Step 1: 写继续/停止规则的失败测试**

```python
# tests/test_report.py
import json

from umi_web_spike.report import build_report


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_report_passes_only_when_all_gates_pass(tmp_path):
    write(tmp_path / "e10.json", {"ready": True})
    write(tmp_path / "ocr-image.json", {"ok": True})
    write(tmp_path / "ocr-pdf.json", {"ok": True, "details": {"searchable_text": True}})
    write(tmp_path / "resources.json", {"ok": True, "details": {"headless": True}})

    report = tmp_path / "report.md"
    assert build_report(tmp_path, tmp_path / "e10.json", report) is True
    assert "结论：继续阶段 1" in report.read_text(encoding="utf-8")


def test_report_stops_when_headless_execution_fails(tmp_path):
    write(tmp_path / "e10.json", {"ready": True})
    write(tmp_path / "ocr-image.json", {"ok": True})
    write(tmp_path / "ocr-pdf.json", {"ok": True, "details": {"searchable_text": True}})
    write(tmp_path / "resources.json", {"ok": False, "details": {"headless": False}})

    assert build_report(tmp_path, tmp_path / "e10.json", tmp_path / "report.md") is False
```

- [ ] **Step 2: 运行测试并确认报告模块不存在**

Run: `python -m pytest tests/test_report.py -v`  
Expected: FAIL，包含 `No module named 'umi_web_spike.report'`。

- [ ] **Step 3: 实现硬性门槛汇总**

```python
# src/umi_web_spike/report.py
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _read_json(path: Path) -> Tuple[Dict[str, Any], str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return {}, "root is not an object"
        return value, ""
    except Exception as error:
        return {}, str(error)


def build_report(results_dir: Path, e10_path: Path, report_path: Path) -> bool:
    paths = {
        "e10": e10_path,
        "image": results_dir / "ocr-image.json",
        "pdf": results_dir / "ocr-pdf.json",
        "resources": results_dir / "resources.json",
    }
    values = {}
    errors = {}
    for name, path in paths.items():
        values[name], errors[name] = _read_json(path)

    e10 = values["e10"]
    image = values["image"]
    pdf = values["pdf"]
    resources = values["resources"]
    gates = {
        "E10 官方 SSO 验证": e10.get("ready") is True,
        "真实图片 OCR": image.get("ok") is True,
        "真实 PDF OCR": pdf.get("ok") is True,
        "PDF 可搜索文本": pdf.get("details", {}).get("searchable_text") is True,
        "无桌面会话运行": (
            resources.get("ok") is True
            and resources.get("details", {}).get("headless") is True
        ),
    }
    passed = all(gates.values()) and not any(errors.values())
    lines = ["# Umi-OCR Web 阶段 0 验证报告", ""]
    for label, ok in gates.items():
        lines.append("- [{}] {}".format("x" if ok else " ", label))
    lines.extend(["", "## 证据文件", ""])
    for name, path in paths.items():
        suffix = "" if not errors[name] else "；读取错误：{}".format(errors[name])
        lines.append("- `{}`: `{}`{}".format(name, path, suffix))
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "结论：继续阶段 1" if passed else "结论：停止，修复失败项后重新验证",
            "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return passed
```

缺少证据文件、JSON 无法解析或字段不存在都按失败处理，报告不得异常中止。

- [ ] **Step 4: 运行报告测试**

Run: `python -m pytest tests/test_report.py -v`  
Expected: 2 passed。

- [ ] **Step 5: 把报告生成接入 CLI**

在 `src/umi_web_spike/cli.py` 中加入：

```python
from .report import build_report


def _build_report(args: argparse.Namespace) -> int:
    passed = build_report(
        Path(args.results_dir), Path(args.e10), Path(args.output)
    )
    return 0 if passed else 1
```

并在 `build_parser()` 返回前加入：

```python
report = subparsers.add_parser("build-report")
report.add_argument("--results-dir", required=True)
report.add_argument("--e10", required=True)
report.add_argument("--output", required=True)
report.set_defaults(handler=_build_report)
```

Run: `umi-web-spike build-report --help`  
Expected: exit 0，帮助中包含 `--results-dir`、`--e10` 和 `--output`。

- [ ] **Step 6: 运行全套自动化测试**

Run: `python -m pytest -v`  
Expected: 全部通过，无 skipped、xfailed 或 warnings-as-errors。

- [ ] **Step 7: 在目标服务器生成正式阶段报告**

Run:

```powershell
umi-web-spike build-report --results-dir validation/results/live --e10 validation/results/e10.json --output docs/validation/phase-0-report.md
```

Expected: exit 0 且报告包含 `结论：继续阶段 1`。若退出码为 1 或报告为停止结论，不开始正式 Web 系统开发，而是根据失败项修改适配方案并重新执行阶段 0。

- [ ] **Step 8: 记录最终非 Git 检查点**

Run: `python -m pytest -q && git status --short`  
Expected: 测试全部通过；所有源文件、测试、验证 JSON 和报告保持未提交，交由用户审阅。

---

## Phase 0 Completion Criteria

阶段 0 只有在以下条件全部满足时完成：

- 假插件自动化测试证明加载器不依赖 Qt/QML；
- 真实 Umi OCR 插件在无登录用户的 Windows 计划任务中成功识别图片和 PDF；
- PDF 输出可以提取搜索文本；
- 已记录真实峰值内存、CPU/耗时和建议 Worker 数量；
- E10 官方接口完成正常、禁用账号和退出三项测试；
- `docs/validation/phase-0-report.md` 明确给出“继续阶段 1”；
- 用户审核所有工作区变更；
- 未创建 Git 提交。
