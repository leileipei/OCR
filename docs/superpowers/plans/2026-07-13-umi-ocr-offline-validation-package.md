# Umi-OCR Phase 0 Offline Validation Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建并发布一个包含官方 Umi-OCR Rapid v2.1.5、独立测试运行时、分阶段 Windows 向导和脱敏证据导出的完整离线 Phase 0 验证包。

**Architecture:** 供应链锁文件固定所有外部资产的名称、大小和 SHA-256；同一 PowerShell 构建器在本地 Windows 与 GitHub Actions 中组装包。Python 负责证据验证、OCR 独立就绪报告和脱敏审核包，PowerShell 负责包校验、现场状态机、Umi 原包准备与计划任务生命周期。缺少 E10 时只允许 `OCR_READY_E10_PENDING`，现有完整 Phase 0 报告继续 fail-closed。

**Tech Stack:** Python 3.8.10 grammar / CPython 3.12.10 embeddable x64、pytest 8.4.2、PowerShell 5.1+、Windows Task Scheduler、GitHub Actions、GitHub CLI、Umi-OCR Rapid v2.1.5。

## Global Constraints

- 官方 Umi-OCR 资产固定为 `Umi-OCR_Rapid_v2.1.5.7z.exe`，大小 `103369422` 字节，SHA-256 `659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722`。
- 便携测试运行时固定为官方 `python-3.12.10-embed-amd64.zip`，大小 `11133606` 字节，SHA-256 `4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3`。
- 初始工具版本固定为 `0.2.0`，成品名固定为 `umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip`。
- 大型二进制、wheel、解压运行时、构建缓存、成品 ZIP 和现场证据不得进入 Git 历史。
- Umi-OCR 官方自解压包保持字节不变；复制前后均验证 SHA-256。
- 内网执行完全离线；现场脚本不得在运行阶段调用 `Invoke-WebRequest`、`curl`、`pip download` 或其他联网命令。
- Umi-OCR Python 3.8 只运行真实插件探针；CPython 3.12.10 便携运行时只运行自动化测试、证据工具和审核包导出。
- 正式 OCR 样本固定为六类，扫描 PDF 至少 100 页；样本和完整 OCR 文本不得进入 Release 或脱敏审核包。
- 每次完整现场活动使用唯一 `campaign_id`；interactive 与 scheduled 执行必须使用两个不同 `validation_id`，campaign 状态文件记录关联。
- E10 暂时跳过；完整 Phase 0 报告在 E10 证据缺失时必须返回非零退出码并保持停止结论。
- 所有新增 Python 代码必须通过 Python 3.8 grammar 检查。
- 每个任务先观察 RED，再实现 GREEN；每个任务单独提交并接受代码审查后再继续。

---

## File Map

- `packaging/offline-package.lock.json`：工具、Umi、Python 和 wheel 的不可变供应链锁。
- `packaging/requirements-offline.lock`：便携运行时的精确 Python 依赖版本。
- `packaging/licenses/Umi-OCR-MIT.txt`：Umi-OCR MIT 许可证副本。
- `src/umi_web_spike/package_integrity.py`：文件/目录摘要、锁文件和 `SHA256SUMS` 验证。
- `src/umi_web_spike/evidence_validation.py`：从现有完整报告中提取可复用 OCR 证据验证接口。
- `src/umi_web_spike/readiness.py`：双运行 OCR 就绪报告和脱敏审核包。
- `tests/__init__.py`、`tests/evidence_fixtures.py`：跨测试复用的严格证据 fixture。
- `tests/test_package_integrity.py`：锁文件、文件大小、哈希和目录清单测试。
- `tests/test_readiness.py`：OCR pending 状态、双运行一致性和脱敏测试。
- `scripts/phase0/Phase0.Package.psm1`：离线包校验、Preflight、Prepare、SelfTest 和状态文件。
- `scripts/phase0/Phase0.Scheduler.psm1`：计划任务定义、安装、收集和确认清理。
- `scripts/phase0/Start-Phase0Validation.ps1`：现场管理员唯一入口。
- `scripts/build-offline-package.ps1`：本地与 CI 共享的离线包构建器。
- `tests/test_powershell_contract.py`：PowerShell 入口、离线约束、路径和调度器契约测试。
- `tests/test_offline_package.py`：构建目录、清单、便携运行时和篡改测试。
- `templates/samples.json`：六类样本路径模板。
- `templates/global-options.json`、`templates/local-options.json`：不含秘密的插件配置模板。
- `docs/validation/offline-package-runbook.md`：管理员操作、状态、错误和 E10 恢复说明。
- `.github/workflows/test.yml`：Linux/macOS/Windows 测试矩阵。
- `.github/workflows/build-offline-package.yml`：Windows 完整包构建 Artifact。
- `.github/workflows/release-offline-package.yml`：标签触发 Draft Release。

---

### Task 1: 锁定供应链并实现包完整性接口

**Files:**
- Create: `packaging/offline-package.lock.json`
- Create: `packaging/requirements-offline.lock`
- Create: `packaging/licenses/Umi-OCR-MIT.txt`
- Create: `src/umi_web_spike/package_integrity.py`
- Create: `tests/test_package_integrity.py`
- Modify: `.gitignore`
- Modify: `pyproject.toml`
- Modify: `src/umi_web_spike/__init__.py`

**Interfaces:**
- Consumes: `src/umi_web_spike/evidence.py::sha256_file(path)`。
- Produces: `load_supply_lock(path) -> Dict[str, Any]`、`verify_locked_file(path, entry) -> None`、`write_sha256sums(root, output) -> None`、`verify_sha256sums(root, sums_path) -> None`。

- [ ] **Step 1: 写供应链锁和篡改检测的失败测试**

```python
# tests/test_package_integrity.py
import hashlib
import json

import pytest

from umi_web_spike import __version__
from umi_web_spike.package_integrity import (
    load_supply_lock,
    verify_locked_file,
    verify_sha256sums,
    write_sha256sums,
)


def test_repository_supply_lock_has_all_pinned_assets():
    lock = load_supply_lock("packaging/offline-package.lock.json")
    assert lock["tool_version"] == "0.2.0"
    assert __version__ == "0.2.0"
    assert lock["umi"]["sha256"] == "659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722"
    assert lock["python"]["sha256"] == "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
    assert len(lock["wheels"]) == 9
    assert lock["umi_layout"] == {
        "archive_root": "Umi-OCR_Rapid_v2.1.5",
        "data_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data",
        "runtime_python": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe",
        "plugin_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins",
        "plugin_name": "win7_x64_RapidOCR-json",
    }


def test_locked_file_rejects_size_or_digest_change(tmp_path):
    payload = tmp_path / "asset.bin"
    payload.write_bytes(b"official")
    entry = {
        "name": "asset.bin",
        "size": 8,
        "sha256": hashlib.sha256(b"official").hexdigest(),
    }
    verify_locked_file(payload, entry)
    payload.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_locked_file(payload, entry)


def test_tree_sums_reject_tampered_or_unlisted_files(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS.txt"
    write_sha256sums(tmp_path, sums)
    verify_sha256sums(tmp_path, sums)
    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="a.txt"):
        verify_sha256sums(tmp_path, sums)
```

- [ ] **Step 2: 运行测试并确认模块不存在**

Run: `.venv/bin/python -m pytest tests/test_package_integrity.py -v`
Expected: FAIL，包含 `ModuleNotFoundError: No module named 'umi_web_spike.package_integrity'`。

- [ ] **Step 3: 创建精确锁文件**

```json
{
  "schema_version": "1.0",
  "tool_version": "0.2.0",
  "archive_name": "umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip",
  "umi": {
    "name": "Umi-OCR_Rapid_v2.1.5.7z.exe",
    "url": "https://github.com/hiroi-sora/Umi-OCR/releases/download/v2.1.5/Umi-OCR_Rapid_v2.1.5.7z.exe",
    "size": 103369422,
    "sha256": "659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722"
  },
  "python": {
    "name": "python-3.12.10-embed-amd64.zip",
    "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
    "size": 11133606,
    "sha256": "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
  },
  "umi_layout": {
    "archive_root": "Umi-OCR_Rapid_v2.1.5",
    "data_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data",
    "runtime_python": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe",
    "plugin_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins",
    "plugin_name": "win7_x64_RapidOCR-json"
  },
  "wheels": [
    {"name":"colorama-0.4.6-py2.py3-none-any.whl","size":25335,"sha256":"4f1d9991f5acc0ca119f9d443620b77f9d6b33703e51011c16baf57afb285fc6"},
    {"name":"iniconfig-2.3.0-py3-none-any.whl","size":7484,"sha256":"f631c04d2c48c52b84d0d0549c99ff3859c98df65b3101406327ecc7d53fbf12"},
    {"name":"packaging-26.2-py3-none-any.whl","size":100195,"sha256":"5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e"},
    {"name":"pillow-11.3.0-cp312-cp312-win_amd64.whl","size":6986324,"sha256":"a6444696fce635783440b7f7a9fc24b3ad10a9ea3f0ab66c5905be1c19ccf17d"},
    {"name":"pluggy-1.6.0-py3-none-any.whl","size":20538,"sha256":"e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746"},
    {"name":"psutil-7.2.2-cp37-abi3-win_amd64.whl","size":137737,"sha256":"eb7e81434c8d223ec4a219b5fc1c47d0417b12be7ea866e24fb5ad6e84b3d988"},
    {"name":"pygments-2.20.0-py3-none-any.whl","size":1231151,"sha256":"81a9e26dd42fd28a23a2d169d86d7ac03b46e2f8b59ed4698fb4785f946d0176"},
    {"name":"pymupdf-1.28.0-cp310-abi3-win_amd64.whl","size":19773102,"sha256":"e01e90fd86abfeb37ceb921eddb951f988a11d45ff6ce6b7664f2039849068ec"},
    {"name":"pytest-8.4.2-py3-none-any.whl","size":365750,"sha256":"872f880de3fc3a5bdc88a11b39c9710c3497a547cfa9320bc3c5e62fbf272e79"}
  ]
}
```

`packaging/requirements-offline.lock` 必须逐行包含：

```text
colorama==0.4.6
iniconfig==2.3.0
packaging==26.2
pillow==11.3.0
pluggy==1.6.0
psutil==7.2.2
pygments==2.20.0
pymupdf==1.28.0
pytest==8.4.2
```

`packaging/licenses/Umi-OCR-MIT.txt` 必须保存以下官方许可文本：

```text
MIT License

Copyright (c) 2023 hiroi-sora

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: 实现严格完整性函数**

```python
# src/umi_web_spike/package_integrity.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .evidence import sha256_file


def load_supply_lock(path) -> Dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ValueError("offline package lock must use schema 1.0")
    if value.get("tool_version") != "0.2.0" or value.get("archive_name") != "umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip":
        raise ValueError("offline package version or archive name mismatch")
    for group in ("umi", "python"):
        verify_lock_entry(value.get(group))
    wheels = value.get("wheels")
    if not isinstance(wheels, list) or len(wheels) != 9:
        raise ValueError("offline package lock must contain nine wheels")
    for entry in wheels:
        verify_lock_entry(entry)
    expected_layout = {
        "archive_root": "Umi-OCR_Rapid_v2.1.5",
        "data_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data",
        "runtime_python": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe",
        "plugin_root": "Umi-OCR_Rapid_v2.1.5/UmiOCR-data/plugins",
        "plugin_name": "win7_x64_RapidOCR-json",
    }
    if value.get("umi_layout") != expected_layout:
        raise ValueError("unexpected Umi-OCR Rapid v2.1.5 layout")
    return value


def verify_lock_entry(entry) -> None:
    if not isinstance(entry, dict):
        raise ValueError("lock entry must be an object")
    if not isinstance(entry.get("name"), str) or Path(entry["name"]).name != entry["name"]:
        raise ValueError("lock entry name must be a basename")
    if not isinstance(entry.get("size"), int) or isinstance(entry["size"], bool) or entry["size"] <= 0:
        raise ValueError("lock entry size must be a positive integer")
    digest = entry.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("lock entry SHA-256 is invalid")


def verify_locked_file(path, entry) -> None:
    verify_lock_entry(entry)
    candidate = Path(path)
    if candidate.name != entry["name"]:
        raise ValueError("locked filename mismatch")
    if candidate.stat().st_size != entry["size"]:
        raise ValueError("locked file size mismatch: {}".format(candidate.name))
    if sha256_file(candidate) != entry["sha256"]:
        raise ValueError("locked file SHA-256 mismatch: {}".format(candidate.name))


def write_sha256sums(root, output) -> None:
    root = Path(root).resolve()
    output = Path(output).resolve()
    files = sorted(path for path in root.rglob("*") if path.is_file() and path != output)
    lines = ["{}  {}".format(sha256_file(path), path.relative_to(root).as_posix()) for path in files]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_sha256sums(root, sums_path) -> None:
    root = Path(root).resolve()
    sums_path = Path(sums_path).resolve()
    listed = set()
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file() or sha256_file(path) != digest:
            raise ValueError("SHA256SUMS mismatch: {}".format(relative))
        listed.add(relative)
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path != sums_path}
    if actual != listed:
        raise ValueError("SHA256SUMS file set mismatch")
```

- [ ] **Step 5: 忽略所有构建和现场产物**

把 `pyproject.toml` 的 `project.version` 和 `src/umi_web_spike/__init__.py` 的 `__version__` 同时改为 `0.2.0`，两者必须与 supply lock 一致。

然后在 `.gitignore` 追加：

```gitignore
/build/
/dist/
/downloads/
/wheelhouse/
/work/
*.zip
*.7z.exe
*.whl
```

- [ ] **Step 6: 运行聚焦和全量测试**

Run: `.venv/bin/python -m pytest tests/test_package_integrity.py -v`
Expected: 3 passed。
Run: `.venv/bin/python -m pytest -q`
Expected: 100 passed，0 failed。

- [ ] **Step 7: 提交 Task 1**

```bash
git add .gitignore packaging pyproject.toml src/umi_web_spike/__init__.py src/umi_web_spike/package_integrity.py tests/test_package_integrity.py
git commit -m "feat: lock offline package supply chain"
```

---

### Task 2: 提取可复用 OCR 证据验证器

**Files:**
- Create: `src/umi_web_spike/evidence_validation.py`
- Create: `tests/__init__.py`
- Create: `tests/evidence_fixtures.py`
- Create: `tests/test_evidence_validation.py`
- Modify: `src/umi_web_spike/cli.py`
- Modify: `src/umi_web_spike/report.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_report.py`

**Interfaces:**
- Consumes: 现有 `ocr-image.json`、`ocr-pdf.json`、`resources.json`、`manifest.json` 和实际样本文件。
- Produces: `validate_ocr_evidence(results_dir, expected_mode) -> OcrEvidenceValidation`，其中 `expected_mode` 只能是 `interactive` 或 `scheduled`；结果包含 `ok: bool`、`validation_id: Optional[str]`、`errors: Dict[str, Tuple[str, ...]]`、`summary: Dict[str, Any]`。

- [ ] **Step 1: 写验证器与现有完整报告一致的失败测试**

```python
# tests/test_evidence_validation.py
from umi_web_spike.evidence_validation import validate_ocr_evidence
from tests.evidence_fixtures import write_evidence


def test_reusable_validator_accepts_same_evidence_as_full_report(tmp_path):
    write_evidence(tmp_path, validation_id="run-scheduled-20260713", execution_mode="scheduled")
    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")
    assert validation.ok is True
    assert validation.validation_id == "run-scheduled-20260713"
    assert validation.summary["processed_pages"] == 100
    assert validation.summary["execution_mode"] == "scheduled"


def test_reusable_validator_rejects_tampered_manifest(tmp_path):
    write_evidence(tmp_path, validation_id="run-scheduled-20260713", execution_mode="scheduled")
    (tmp_path / "ocr-image.json").write_text("{}", encoding="utf-8")
    validation = validate_ocr_evidence(tmp_path, expected_mode="scheduled")
    assert validation.ok is False
    assert any("SHA-256" in item for item in validation.errors["manifest"])


def test_interactive_and_scheduled_session_rules_are_distinct(tmp_path):
    write_evidence(tmp_path, validation_id="run-interactive-20260713", execution_mode="interactive")
    assert validate_ocr_evidence(tmp_path, expected_mode="interactive").ok is True
    assert validate_ocr_evidence(tmp_path, expected_mode="scheduled").ok is False
```

- [ ] **Step 2: 运行测试并确认接口不存在**

Run: `.venv/bin/python -m pytest tests/test_evidence_validation.py -v`
Expected: FAIL，包含 `No module named 'umi_web_spike.evidence_validation'`。

- [ ] **Step 3: 把现有 OCR 验证逻辑搬到独立模块**

实现不可变结果类型：

```python
# src/umi_web_spike/evidence_validation.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class OcrEvidenceValidation:
    ok: bool
    validation_id: Optional[str]
    errors: Dict[str, Tuple[str, ...]]
    summary: Dict[str, Any]


def validate_ocr_evidence(results_dir: Path, expected_mode: str) -> OcrEvidenceValidation:
    """执行 report.py 当前 image/pdf/resources/manifest 的全部严格校验。

    必须复用原有 SHA-256、样本类别、语种、页数、资源公式、身份和
    validation_id 检查；不得创建弱化版条件。interactive 要求 Qt/QML 未加载且
    interactive_session=true 且 Windows Session ID 大于 0；scheduled 要求 Qt/QML 未加载、
    interactive_session=false、headless=true 且 Windows Session ID 等于 0。
    """
```

具体迁移规则：

1. 把 `tests/test_report.py` 中的证据 fixture 移到 `tests/evidence_fixtures.py`，提供 `write_evidence(root, validation_id, execution_mode)`；`tests/__init__.py` 为空文件；
2. 将 `report.py` 中与 E10 无关的 `_validate_common`、`_validate_identity`、`_validate_sample`、`_validate_resources`、manifest 哈希和资源复算逻辑移动到新模块；
3. `cli validate-ocr` 增加必填 `--execution-mode interactive|scheduled`，并把模式写入 image/pdf/resources/manifest 四个 envelope；
4. 在 Windows 使用 `ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ...)` 记录 `windows_session_id`；非 Windows 自动化测试通过 monkeypatch 注入值；
5. `_resource_result` 在 interactive 模式要求 `interactive_session=true` 且 Session ID > 0，在 scheduled 模式要求 `interactive_session=false`、`headless=true` 且 Session ID == 0；两种模式都要求资源、页数、语种、PDF 和 Qt/QML 门槛；
6. `summary` 只返回允许公开的字段：`execution_mode`、`windows_session_id`、`processed_pages`、`duration_seconds`、`pages_per_minute`、`observed_peak_process_tree_rss_bytes`、`recommended_workers`、`sample_categories`、`headless`；
7. `summary` 不返回样本路径或 OCR 文本；
8. `report.build_report()` 固定调用 `validate_ocr_evidence(results_dir, expected_mode="scheduled")`，再叠加 E10 完整验证，并要求 E10 `validation_id` 与 scheduled OCR `validation_id` 相同；
9. 所有现有测试更新 execution mode 后必须保持通过。

- [ ] **Step 4: 运行聚焦测试和报告回归**

Run: `.venv/bin/python -m pytest tests/test_evidence_validation.py tests/test_cli.py tests/test_report.py -v`
Expected: 新增 3 项与所有现有 CLI/报告测试通过，0 failed。

- [ ] **Step 5: 提交 Task 2**

```bash
git add src/umi_web_spike/evidence_validation.py src/umi_web_spike/cli.py src/umi_web_spike/report.py tests/__init__.py tests/evidence_fixtures.py tests/test_evidence_validation.py tests/test_cli.py tests/test_report.py
git commit -m "refactor: expose strict OCR evidence validator"
```

---

### Task 3: 生成 OCR 独立就绪报告和脱敏审核包

**Files:**
- Create: `src/umi_web_spike/readiness.py`
- Create: `tests/test_readiness.py`
- Modify: `src/umi_web_spike/cli.py`

**Interfaces:**
- Consumes: 两个独立验证目录 `interactive_dir` 与 `scheduled_dir`，均由 `validate_ocr_evidence()` 校验。
- Produces: `build_ocr_readiness_report(campaign_id, interactive_dir, scheduled_dir, output_path) -> bool`、`export_review_bundle(campaign_id, interactive_dir, scheduled_dir, output_zip) -> Path`；CLI 子命令 `build-ocr-readiness` 与 `export-review-bundle`。

- [ ] **Step 1: 写双运行和脱敏的失败测试**

```python
# tests/test_readiness.py
import json
import zipfile

from umi_web_spike.readiness import build_ocr_readiness_report, export_review_bundle
from tests.evidence_fixtures import write_evidence


def test_readiness_requires_interactive_and_scheduled_runs(tmp_path):
    interactive = tmp_path / "interactive"
    scheduled = tmp_path / "scheduled"
    interactive.mkdir()
    scheduled.mkdir()
    write_evidence(interactive, validation_id="run-interactive-20260713", execution_mode="interactive")
    write_evidence(scheduled, validation_id="run-scheduled-20260713", execution_mode="scheduled")
    report = tmp_path / "ocr-readiness.md"
    assert build_ocr_readiness_report("campaign-20260713-001", interactive, scheduled, report) is True
    text = report.read_text(encoding="utf-8")
    assert "OCR_READY_E10_PENDING" in text
    assert "PHASE_0_PASSED" not in text


def test_review_bundle_contains_allowlisted_summary_only(tmp_path):
    interactive = tmp_path / "interactive"
    scheduled = tmp_path / "scheduled"
    interactive.mkdir()
    scheduled.mkdir()
    write_evidence(interactive, validation_id="run-interactive-20260713", execution_mode="interactive")
    write_evidence(scheduled, validation_id="run-scheduled-20260713", execution_mode="scheduled")
    bundle = export_review_bundle("campaign-20260713-001", interactive, scheduled, tmp_path / "review.zip")
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        payload = "\n".join(archive.read(name).decode("utf-8") for name in names)
    assert names == {"review-summary.json", "ocr-readiness.md", "SHA256SUMS.txt"}
    assert "ocr_text" not in payload
    assert "official_document_path" not in payload
    assert str(tmp_path) not in payload


def test_review_bundle_rejects_failed_or_cross_run_input(tmp_path):
    interactive = tmp_path / "interactive"
    scheduled = tmp_path / "scheduled"
    interactive.mkdir()
    scheduled.mkdir()
    write_evidence(interactive, validation_id="run-interactive-20260713", execution_mode="interactive")
    write_evidence(scheduled, validation_id="run-scheduled-20260713", execution_mode="scheduled")
    (scheduled / "ocr-pdf.json").write_text("{}", encoding="utf-8")
    try:
        export_review_bundle("campaign-20260713-001", interactive, scheduled, tmp_path / "review.zip")
    except ValueError as error:
        assert "scheduled" in str(error)
    else:
        raise AssertionError("failed evidence was exported")
```

- [ ] **Step 2: 运行测试并确认模块不存在**

Run: `.venv/bin/python -m pytest tests/test_readiness.py -v`
Expected: FAIL，包含 `No module named 'umi_web_spike.readiness'`。

- [ ] **Step 3: 实现严格的 OCR-only 结果与审核包**

```python
# src/umi_web_spike/readiness.py
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from .evidence import validate_validation_id
from .evidence_validation import validate_ocr_evidence


def _validated_pair(interactive_dir, scheduled_dir):
    interactive = validate_ocr_evidence(Path(interactive_dir), expected_mode="interactive")
    scheduled = validate_ocr_evidence(Path(scheduled_dir), expected_mode="scheduled")
    if not interactive.ok:
        raise ValueError("interactive OCR evidence is invalid")
    if not scheduled.ok:
        raise ValueError("scheduled OCR evidence is invalid")
    if interactive.validation_id == scheduled.validation_id:
        raise ValueError("interactive and scheduled runs must use different validation IDs")
    return interactive, scheduled


def build_ocr_readiness_report(campaign_id, interactive_dir, scheduled_dir, output_path) -> bool:
    validate_validation_id(campaign_id)
    interactive, scheduled = _validated_pair(interactive_dir, scheduled_dir)
    lines = [
        "# Umi-OCR OCR 侧就绪报告",
        "",
        "Campaign：{}".format(campaign_id),
        "",
        "- [x] 普通 PowerShell 真实 OCR 验证",
        "- [x] 无登录用户计划任务真实 OCR 验证",
        "- [ ] e-cology 10 官方 SSO 验证",
        "",
        "状态：OCR_READY_E10_PENDING",
        "",
        "此状态不是 PHASE_0_PASSED；不得开始正式 Web 开发。",
        "",
    ]
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return True


def export_review_bundle(campaign_id, interactive_dir, scheduled_dir, output_zip):
    validate_validation_id(campaign_id)
    interactive, scheduled = _validated_pair(interactive_dir, scheduled_dir)
    output_zip = Path(output_zip)
    staging = output_zip.parent / (output_zip.stem + ".staging")
    if staging.exists() or output_zip.exists():
        raise ValueError("review bundle output already exists")
    staging.mkdir()
    report = staging / "ocr-readiness.md"
    build_ocr_readiness_report(campaign_id, interactive_dir, scheduled_dir, report)
    summary = {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "status": "OCR_READY_E10_PENDING",
        "interactive": interactive.summary,
        "scheduled": scheduled.summary,
    }
    (staging / "review-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files = sorted(path for path in staging.iterdir() if path.name != "SHA256SUMS.txt")
    sums = ["{}  {}".format(hashlib.sha256(path.read_bytes()).hexdigest(), path.name) for path in files]
    (staging / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.iterdir()):
            archive.write(path, path.name)
    for path in staging.iterdir():
        path.unlink()
    staging.rmdir()
    return output_zip
```

实现时还必须：

- 对 `summary` 进行递归允许列表检查，只允许 `str/int/float/bool/list` 和定义的键；
- 拒绝键名含 `password`、`token`、`cookie`、`authorization`、`ocr_text`、`path`；
- 不从原始日志复制任何文本到审核包；
- ZIP 条目使用固定顺序和 UTC 时间 `1980-01-01`，便于同输入生成稳定结构。

- [ ] **Step 4: 把两个命令接入 CLI**

在 `cli.py` 中增加：

```python
readiness = subparsers.add_parser("build-ocr-readiness")
readiness.add_argument("--campaign-id", required=True)
readiness.add_argument("--interactive-dir", required=True)
readiness.add_argument("--scheduled-dir", required=True)
readiness.add_argument("--output", required=True)

review = subparsers.add_parser("export-review-bundle")
review.add_argument("--campaign-id", required=True)
review.add_argument("--interactive-dir", required=True)
review.add_argument("--scheduled-dir", required=True)
review.add_argument("--output", required=True)
```

处理器成功返回 `0`；输入无效、输出已存在或写入失败返回 `1`，同时不保留半成品 ZIP。

- [ ] **Step 5: 运行聚焦和全量测试**

Run: `.venv/bin/python -m pytest tests/test_readiness.py tests/test_cli.py -v`
Expected: 0 failed。
Run: `.venv/bin/python -m pytest -q`
Expected: 0 failed。

- [ ] **Step 6: 提交 Task 3**

```bash
git add src/umi_web_spike/readiness.py src/umi_web_spike/cli.py tests/test_readiness.py
git commit -m "feat: add OCR readiness and redacted review bundle"
```

---

### Task 4: 实现 PowerShell 包校验、Preflight、Prepare 和 SelfTest

**Files:**
- Create: `scripts/phase0/Phase0.Package.psm1`
- Create: `scripts/phase0/Start-Phase0Validation.ps1`
- Create: `tests/test_powershell_contract.py`

**Interfaces:**
- Consumes: Release 根目录、`SHA256SUMS.txt`、官方 Umi 资产、便携 Python 和 `toolkit`。
- Produces: `Test-Phase0Package`、`Invoke-Phase0Preflight`、`Invoke-Phase0Prepare`、`Invoke-Phase0SelfTest`、`Get-Phase0State`、`Set-Phase0State`、`Write-Phase0Failure`；入口参数 `-Action Preflight|Prepare|SelfTest`。

- [ ] **Step 1: 写 PowerShell 契约失败测试**

```python
# tests/test_powershell_contract.py
from pathlib import Path


ROOT = Path(__file__).parents[1]
ENTRY = ROOT / "scripts/phase0/Start-Phase0Validation.ps1"
PACKAGE = ROOT / "scripts/phase0/Phase0.Package.psm1"


def test_entrypoint_exposes_initial_offline_actions():
    text = ENTRY.read_text(encoding="utf-8")
    for action in ("Preflight", "Prepare", "SelfTest"):
        assert action in text
    runtime_scripts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "scripts/phase0").glob("*.ps*")
    )
    assert "Invoke-WebRequest" not in runtime_scripts
    assert "curl" not in runtime_scripts
    assert "pip download" not in runtime_scripts


def test_package_module_uses_atomic_state_and_refuses_overwrite():
    text = PACKAGE.read_text(encoding="utf-8")
    assert "Move-Item" in text
    assert "Test-Path $FinalPath" in text
    assert "SHA256SUMS.txt" in text
    assert "OCR_READY_E10_PENDING" in text
    assert "Write-Phase0Failure" in text
    assert "Get-ChildItem Env:" not in text
```

- [ ] **Step 2: 运行测试并确认脚本不存在**

Run: `.venv/bin/python -m pytest tests/test_powershell_contract.py -v`
Expected: FAIL，包含 `FileNotFoundError`。

- [ ] **Step 3: 实现 Phase0.Package.psm1 的状态与原子写入**

模块必须以严格模式开始：

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$AllowedTransitions = @{
  'NEW' = @('PREFLIGHT_PASSED', 'PREFLIGHT_FAILED')
  'PREFLIGHT_PASSED' = @('PREPARED', 'PREPARE_FAILED')
  'PREPARED' = @('SELF_TEST_PASSED', 'SELF_TEST_FAILED')
  'SELF_TEST_PASSED' = @('INTERACTIVE_OCR_PASSED', 'INTERACTIVE_OCR_FAILED')
  'INTERACTIVE_OCR_PASSED' = @('SCHEDULED_OCR_PASSED', 'SCHEDULED_OCR_FAILED')
  'SCHEDULED_OCR_PASSED' = @('OCR_READY_E10_PENDING')
  'OCR_READY_E10_PENDING' = @('E10_READY')
  'E10_READY' = @('PHASE_0_PASSED')
}

function Write-AtomicUtf8Json {
  param([Parameter(Mandatory=$true)][string]$FinalPath, [Parameter(Mandatory=$true)]$Value)
  if (Test-Path $FinalPath) { throw "Refusing to overwrite $FinalPath" }
  $TempPath = "$FinalPath.$([guid]::NewGuid().ToString('N')).tmp"
  $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $TempPath -Encoding UTF8
  Move-Item -LiteralPath $TempPath -Destination $FinalPath
}
```

`Set-Phase0State` 必须读取当前 campaign 状态、验证 `$AllowedTransitions`、写入新的 attempt 记录，然后原子更新形如 `work/campaigns/campaign-20260713-001/state.json` 的路径。状态文件只包含 campaign ID、interactive/scheduled validation ID、状态、UTC 时间、attempt 编号和证据相对路径。

`Write-Phase0Failure` 只写入 action、campaign ID、validation ID、异常类型、`ScriptStackTrace`、Windows/PowerShell 版本、进程 ID 和 `SESSIONNAME`；不得枚举环境变量、命令行、Credential 或样本内容。失败 JSON 写到新的 attempt 目录并通过 `Write-AtomicUtf8Json` 发布。

- [ ] **Step 4: 实现三个动作**

`Test-Phase0Package`：逐行解析 `SHA256SUMS.txt`，使用 `Get-FileHash -Algorithm SHA256` 复算，拒绝缺文件、多余文件和摘要不一致；只忽略运行时创建的整个 `work/` 子树，其他未列入文件一律失败。
`Invoke-Phase0Preflight`：验证 64 位 Windows Server、PowerShell >= 5.1、管理员身份、可用磁盘 >= 5GB、包路径不含控制字符、所有清单文件通过；输出 `preflight.json`。
`Invoke-Phase0Prepare`：再次校验 Umi 官方摘要，解压到形如 `work/campaigns/campaign-20260713-001/umi` 的 campaign 目录。实际命令固定为 `& $UmiAsset -y "-o$UmiRoot"`；完成后依据 lock 中 `umi_layout` 精确确认 `Umi-OCR_Rapid_v2.1.5/UmiOCR-data/runtime/python.exe`、`UmiOCR-data/plugins` 和插件目录 `win7_x64_RapidOCR-json` 存在；输出 `run-context.json`。
`Invoke-Phase0SelfTest`：执行：

```powershell
& "$PackageRoot\runtime\python\python.exe" -m pytest "$PackageRoot\toolkit\tests" -q
if ($LASTEXITCODE -ne 0) { throw "Portable self-test failed: $LASTEXITCODE" }
```

动作不得下载依赖或写入系统 Python。

- [ ] **Step 5: 实现入口参数和失败诊断**

```powershell
param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('Preflight','Prepare','SelfTest')]
  [string]$Action,
  [string]$PackageRoot = $PSScriptRoot,
  [string]$CampaignId = ('campaign-' + [guid]::NewGuid().ToString('N')),
  [string]$ValidationId = ([guid]::NewGuid().ToString('N'))
)

Import-Module "$PSScriptRoot\Phase0.Package.psm1" -Force
try {
  switch ($Action) {
    'Preflight' { Invoke-Phase0Preflight -PackageRoot $PackageRoot -CampaignId $CampaignId }
    'Prepare' { Invoke-Phase0Prepare -PackageRoot $PackageRoot -CampaignId $CampaignId }
    'SelfTest' { Invoke-Phase0SelfTest -PackageRoot $PackageRoot -CampaignId $CampaignId }
  }
  exit 0
} catch {
  Write-Phase0Failure -PackageRoot $PackageRoot -CampaignId $CampaignId -ValidationId $ValidationId -Action $Action -ErrorRecord $_
  Write-Error $_
  exit 1
}
```

- [ ] **Step 6: 在可用平台运行测试**

Run: `.venv/bin/python -m pytest tests/test_powershell_contract.py -v`
Expected: 静态契约通过。
Windows Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/phase0/Start-Phase0Validation.ps1 -Action Preflight -PackageRoot "$env:TEMP\umi-phase0-fixture" -CampaignId campaign-preflight-ci-001`
Expected: fixture 完整时 exit 0；篡改时 exit 1。

- [ ] **Step 7: 提交 Task 4**

```bash
git add scripts/phase0 tests/test_powershell_contract.py
git commit -m "feat: add offline Phase 0 package preflight"
```

---

### Task 5: 实现计划任务生命周期与 OCR 双运行编排

**Files:**
- Create: `scripts/phase0/Phase0.Scheduler.psm1`
- Modify: `scripts/phase0/Start-Phase0Validation.ps1`
- Modify: `tests/test_powershell_contract.py`
- Modify: `scripts/run-windows-validation.ps1`

**Interfaces:**
- Consumes: Prepare 生成的 `run-context.json`、Umi Python、插件配置、六类样本清单。
- Produces: `Invoke-InteractiveValidation`、`Install-Phase0ScheduledTask`、`Collect-Phase0ScheduledTask`、`Remove-Phase0ScheduledTask`；入口动作 `RunInteractive|InstallScheduledTask|CollectScheduledTask|RemoveScheduledTask`。

- [ ] **Step 1: 写调度器契约失败测试**

在 `tests/test_powershell_contract.py` 增加：

```python
def test_scheduler_uses_unique_name_and_requires_explicit_cleanup():
    text = (ROOT / "scripts/phase0/Phase0.Scheduler.psm1").read_text(encoding="utf-8")
    assert "UmiOcrPhase0-$ValidationId" in text
    assert "Get-Credential" in text
    assert "-Password $PlainPassword" in text
    assert "Remove-Phase0ScheduledTask" in text
    assert "[switch]$ConfirmCleanup" in text
    assert "Unregister-ScheduledTask" in text
    assert "-Confirm:$false" in text
    assert "$ConfirmCleanup" in text


def test_entrypoint_never_logs_password_or_full_environment():
    text = ENTRY.read_text(encoding="utf-8").lower()
    assert "write-output $plainpassword" not in text
    assert "get-childitem env:" not in text
    assert "convertfrom-securestring" not in text
```

- [ ] **Step 2: 运行测试并确认模块不存在**

Run: `.venv/bin/python -m pytest tests/test_powershell_contract.py -v`
Expected: FAIL，包含 `Phase0.Scheduler.psm1` 不存在。

- [ ] **Step 3: 实现计划任务定义与凭据边界**

```powershell
function Install-Phase0ScheduledTask {
  param(
    [Parameter(Mandatory=$true)][string]$ValidationId,
    [Parameter(Mandatory=$true)][string]$CommandPath,
    [Parameter(Mandatory=$true)][string]$ArgumentFile,
    [System.Management.Automation.PSCredential]$Credential
  )
  $TaskName = "UmiOcrPhase0-$ValidationId"
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "Scheduled task already exists: $TaskName"
  }
  if ($null -eq $Credential) { $Credential = Get-Credential -Message 'Phase 0 scheduled-task account' }
  $Action = New-ScheduledTaskAction -Execute $CommandPath -Argument "-File `"$ArgumentFile`""
  $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 6) -StartWhenAvailable
  $PlainPassword = $Credential.GetNetworkCredential().Password
  try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Settings $Settings `
      -User $Credential.UserName -Password $PlainPassword -RunLevel Highest | Out-Null
  } finally {
    $PlainPassword = $null
  }
  Start-ScheduledTask -TaskName $TaskName
  return $TaskName
}
```

不得把 Credential、明文密码或整个命令行参数写入状态文件。任务参数写入 ACL 受限的 JSON 文件，命令行只传该文件路径。

- [ ] **Step 4: 实现收集和显式清理**

`Collect-Phase0ScheduledTask` 每 5 秒轮询任务，最长 6 小时；记录开始/结束 UTC、`LastTaskResult`、Session ID、任务 XML SHA-256、标准输出和错误日志的清理摘要。非零 `LastTaskResult` 转入 `SCHEDULED_OCR_FAILED`。
`Remove-Phase0ScheduledTask` 的签名固定为：

```powershell
function Remove-Phase0ScheduledTask {
  param([string]$ValidationId, [switch]$ConfirmCleanup)
  if (-not $ConfirmCleanup) { throw 'ConfirmCleanup is required' }
  $TaskName = "UmiOcrPhase0-$ValidationId"
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
```

- [ ] **Step 5: 扩展入口和现有 OCR 脚本**

入口 `ValidateSet` 增加 `RunInteractive`、`InstallScheduledTask`、`CollectScheduledTask`、`RemoveScheduledTask`。
`run-windows-validation.ps1` 增加必填 `-ExecutionMode Interactive|Scheduled`，把模式写入 manifest 安全环境摘要；两个模式必须生成不同 validation ID 和目录。

- [ ] **Step 6: 运行聚焦测试和 Windows DryRun**

Run: `.venv/bin/python -m pytest tests/test_powershell_contract.py tests/test_cli.py -v`
Expected: 0 failed。
Windows DryRun: 调用 `New-Phase0TaskDefinition` 生成定义但不注册，断言任务名、6 小时限制、无登录运行配置和参数文件路径正确。

- [ ] **Step 7: 提交 Task 5**

```bash
git add scripts/phase0 scripts/run-windows-validation.ps1 tests/test_powershell_contract.py tests/test_cli.py
git commit -m "feat: orchestrate interactive and scheduled OCR validation"
```

---

### Task 6: 添加现场模板、管理员手册和 E10 恢复路径

**Files:**
- Create: `templates/samples.json`
- Create: `templates/global-options.json`
- Create: `templates/local-options.json`
- Create: `docs/validation/offline-package-runbook.md`
- Create: `tests/test_offline_docs.py`
- Modify: `scripts/phase0/Start-Phase0Validation.ps1`

**Interfaces:**
- Consumes: Task 3–5 的 CLI 和 PowerShell 动作。
- Produces: 可复制的六类样本模板、无秘密配置模板、逐步命令和 `ResumeE10|BuildFinalReport` 入口动作。

- [ ] **Step 1: 写文档和模板完整性失败测试**

```python
# tests/test_offline_docs.py
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_sample_template_contains_each_category_once_and_no_real_paths():
    value = json.loads((ROOT / "templates/samples.json").read_text(encoding="utf-8"))
    categories = [item["category"] for item in value["samples"]]
    assert categories == [
        "simplified_chinese_image",
        "mixed_chinese_english_image",
        "scanned_pdf_rotated_blank",
        "native_text_pdf",
        "corrupt_pdf",
        "encrypted_pdf",
    ]
    assert all(item["path"].startswith("C:\\Phase0Samples\\") for item in value["samples"])


def test_runbook_keeps_e10_as_a_hard_gate():
    text = (ROOT / "docs/validation/offline-package-runbook.md").read_text(encoding="utf-8")
    assert "OCR_READY_E10_PENDING" in text
    assert "不是完整 Phase 0 通过" in text
    assert "ResumeE10" in text
    assert "BuildFinalReport" in text
```

- [ ] **Step 2: 运行测试并确认模板不存在**

Run: `.venv/bin/python -m pytest tests/test_offline_docs.py -v`
Expected: FAIL，包含 `FileNotFoundError`。

- [ ] **Step 3: 创建固定模板**

`templates/samples.json` 使用以下路径：

```json
{
  "samples": [
    {"category":"simplified_chinese_image","path":"C:\\Phase0Samples\\zh.png"},
    {"category":"mixed_chinese_english_image","path":"C:\\Phase0Samples\\mixed.png"},
    {"category":"scanned_pdf_rotated_blank","path":"C:\\Phase0Samples\\scan-100.pdf"},
    {"category":"native_text_pdf","path":"C:\\Phase0Samples\\native.pdf"},
    {"category":"corrupt_pdf","path":"C:\\Phase0Samples\\corrupt.pdf"},
    {"category":"encrypted_pdf","path":"C:\\Phase0Samples\\encrypted.pdf"}
  ]
}
```

`templates/global-options.json` 固定为官方 Rapid v2.1.5 `Api.__init__` 所需字段：

```json
{"numThread": 4}
```

`templates/local-options.json` 固定为官方 Rapid v2.1.5 `Api.start` 所需字段：

```json
{"language": "简体中文", "angle": true, "maxSideLen": 2048}
```

这些值来自官方包内 `win7_x64_RapidOCR-json/rapidocr_config.py` 与 `models/configs.txt`。模板禁止密码、Token、Cookie 和 OA 地址；管理员可在复制后的工作目录调整线程数、方向分类和边长，但不得修改 Release 原模板。

- [ ] **Step 4: 编写逐步操作手册**

手册必须给出实际命令，顺序固定：

```powershell
.\Start-Phase0Validation.ps1 -Action Preflight -CampaignId $campaignId
.\Start-Phase0Validation.ps1 -Action Prepare -CampaignId $campaignId
.\Start-Phase0Validation.ps1 -Action SelfTest -CampaignId $campaignId
.\Start-Phase0Validation.ps1 -Action RunInteractive -CampaignId $campaignId -ValidationId $interactiveId
.\Start-Phase0Validation.ps1 -Action InstallScheduledTask -CampaignId $campaignId -ValidationId $scheduledId
.\Start-Phase0Validation.ps1 -Action CollectScheduledTask -CampaignId $campaignId -ValidationId $scheduledId
.\Start-Phase0Validation.ps1 -Action ExportEvidence -CampaignId $campaignId -InteractiveId $interactiveId -ScheduledId $scheduledId
```

并明确：

- E10 未准备时停在 `OCR_READY_E10_PENDING`；
- `BuildFinalReport` 此时预期 exit 1；
- E10 准备后把官方文档和证据放入受控目录，再执行 `ResumeE10` 和 `BuildFinalReport`；
- 不得把工作目录、证据 ZIP 或样本上传 GitHub；
- 临时计划任务只在审核证据后显式清理。

- [ ] **Step 5: 增加 ResumeE10 与 BuildFinalReport 动作**

`ResumeE10` 调用便携 Python 对 E10 JSON 运行 `E10Evidence.from_dict()`，成功后转入 `E10_READY`；`BuildFinalReport` 调用现有：

```powershell
& "$PackageRoot\runtime\python\python.exe" -m umi_web_spike.cli build-report `
  --results-dir $ScheduledResultsDir --e10 $E10EvidencePath --output $FinalReportPath
exit $LASTEXITCODE
```

缺少 E10 时不得捕获并改写非零退出码。

- [ ] **Step 6: 运行文档和全量测试**

Run: `.venv/bin/python -m pytest tests/test_offline_docs.py tests/test_powershell_contract.py -v`
Expected: 0 failed。
Run: `.venv/bin/python -m pytest -q`
Expected: 0 failed。

- [ ] **Step 7: 提交 Task 6**

```bash
git add templates docs/validation scripts/phase0/Start-Phase0Validation.ps1 tests/test_offline_docs.py
git commit -m "docs: add offline validation operator workflow"
```

---

### Task 7: 构建便携运行时和完整离线 ZIP

**Files:**
- Create: `scripts/build-offline-package.ps1`
- Create: `tests/test_offline_package.py`
- Modify: `src/umi_web_spike/package_integrity.py`

**Interfaces:**
- Consumes: `packaging/offline-package.lock.json`、缓存目录或锁文件 URL、源码/测试/脚本/模板/文档。
- Produces: `dist/umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip`、同名 `.sha256`、`dist/sbom.json`、`dist/THIRD_PARTY_NOTICES.txt`。

- [ ] **Step 1: 写构建结果和篡改失败测试**

```python
# tests/test_offline_package.py
import json
import os
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def test_builder_is_bound_to_repository_supply_lock():
    text = (ROOT / "scripts/build-offline-package.ps1").read_text(encoding="utf-8")
    lock = json.loads((ROOT / "packaging/offline-package.lock.json").read_text(encoding="utf-8"))
    assert "offline-package.lock.json" in text
    assert "Get-FileHash" in text
    assert "Length" in text
    assert lock["archive_name"] in text


def _real_archive():
    value = os.environ.get("BUILT_OFFLINE_PACKAGE")
    if not value:
        pytest.skip("real archive assertion runs in the Windows build job")
    return Path(value)


def test_built_archive_has_required_layout():
    archive = _real_archive()
    with zipfile.ZipFile(archive) as value:
        names = set(value.namelist())
    required = {
        "umi-ocr-phase0/Start-Phase0Validation.ps1",
        "umi-ocr-phase0/Phase0.Package.psm1",
        "umi-ocr-phase0/Phase0.Scheduler.psm1",
        "umi-ocr-phase0/SHA256SUMS.txt",
        "umi-ocr-phase0/manifest.json",
        "umi-ocr-phase0/sbom.json",
        "umi-ocr-phase0/vendor/Umi-OCR_Rapid_v2.1.5.7z.exe",
        "umi-ocr-phase0/runtime/python/python.exe",
        "umi-ocr-phase0/toolkit/src/umi_web_spike/cli.py",
        "umi-ocr-phase0/templates/samples.json",
    }
    assert required <= names


def test_package_manifest_excludes_work_and_sensitive_files():
    with zipfile.ZipFile(_real_archive()) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("umi-ocr-phase0/manifest.json"))
    lowered = "\n".join(names).lower()
    assert "work/" not in lowered
    assert ".env" not in lowered
    assert "e10.json" not in lowered
    assert all("sha256" in item for item in manifest["files"])
```

普通测试始终运行构建器/lock 静态契约；两个真实 ZIP 测试在 `BUILT_OFFLINE_PACKAGE` 未设置时明确 skip。Windows 完整构建 job 生成真实成品后设置该变量并再次运行本文件，此时不允许 skip。

- [ ] **Step 2: 运行测试并确认构建器不存在**

Run: `.venv/bin/python -m pytest tests/test_offline_package.py -v`
Expected: FAIL，因为 `scripts/build-offline-package.ps1` 尚不存在。

- [ ] **Step 3: 实现下载缓存与严格验证**

构建器参数固定为：

```powershell
param(
  [string]$RepositoryRoot = (Resolve-Path "$PSScriptRoot\..").Path,
  [string]$LockPath = "$RepositoryRoot\packaging\offline-package.lock.json",
  [string]$CacheDir = "$RepositoryRoot\downloads",
  [string]$OutputDir = "$RepositoryRoot\dist",
  [switch]$OfflineCacheOnly
)
```

`Get-LockedAsset` 先检查缓存文件并校验大小/SHA；缓存缺失且指定 `OfflineCacheOnly` 时失败；仅构建阶段允许按锁文件 URL 下载到 `.partial`，校验通过后原子改名。任何摘要错误删除 `.partial` 并返回非零。

- [ ] **Step 4: 构建独立 CPython 运行时**

1. 解压 `python-3.12.10-embed-amd64.zip` 到 `runtime/python`；
2. 创建 `runtime/python/Lib/site-packages`；
3. 使用构建机 Python 执行：

```powershell
python -m pip download --only-binary=:all: --platform win_amd64 --python-version 312 `
  --implementation cp --abi cp312 --dest $Wheelhouse `
  -r "$RepositoryRoot\packaging\requirements-offline.lock"
```

4. 对下载的 9 个 wheel 逐一匹配 lock 名称、大小和 SHA；
5. 离线安装：

```powershell
python -m pip install --no-index --find-links $Wheelhouse --target $SitePackages `
  -r "$RepositoryRoot\packaging\requirements-offline.lock"
```

6. 把 `python312._pth` 写成：

```text
python312.zip
.
Lib
Lib\site-packages
..\..\toolkit\src
import site
```

7. 使用成品运行时执行 `python.exe -m pytest toolkit/tests -q`；失败则停止打包。

- [ ] **Step 5: 组装许可、SBOM、manifest 和 ZIP**

构建器按 File Map 复制文件，并把 `scripts/phase0/Start-Phase0Validation.ps1`、`Phase0.Package.psm1`、`Phase0.Scheduler.psm1` 三个现场入口文件复制到 Release 根目录；源码副本仍保留在 `toolkit/scripts/phase0`。`manifest.json` 格式固定为：

```json
{
  "schema_version": "1.0",
  "tool_version": "0.2.0",
  "umi_version": "2.1.5",
  "engine": "RapidOCR",
  "files": [
    {"path":"vendor/Umi-OCR_Rapid_v2.1.5.7z.exe","size":103369422,"sha256":"659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722"}
  ]
}
```

实际 `files` 必须列出除 `manifest.json` 与 `SHA256SUMS.txt` 外的全部文件。然后对包含 `manifest.json` 的全部文件生成 `SHA256SUMS.txt`。ZIP 完成后使用 `$ZipDigest = (Get-FileHash -Algorithm SHA256 $ZipPath).Hash.ToLowerInvariant()`，在 `dist/umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip.sha256` 写入 `"$ZipDigest  umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip"` 和结尾换行。

许可证：复制 Umi MIT；从 Python embeddable 的 `LICENSE.txt` 复制 Python 许可；从每个 `.dist-info` 收集 `LICENSE*`/`COPYING*`，缺失许可文件时构建失败。SBOM 至少列出组件名、版本、来源 URL、SHA-256 和许可文件相对路径。

- [ ] **Step 6: 在 Windows 运行真实构建和成品断言**

Real Run: `powershell -File scripts/build-offline-package.ps1`
Expected: 下载并校验 103369422 字节 Umi 资产、11133606 字节 Python 资产和 9 个 wheels；便携运行时全套 pytest 通过；生成 ZIP、SHA-256、SBOM 和许可声明。
Run: `$env:BUILT_OFFLINE_PACKAGE = (Resolve-Path 'dist/umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip'); python -m pytest tests/test_offline_package.py -v -rs`
Expected: 3 passed，0 skipped。

- [ ] **Step 7: 提交 Task 7**

```bash
git add scripts/build-offline-package.ps1 src/umi_web_spike/package_integrity.py tests/test_offline_package.py
git commit -m "feat: build complete offline validation package"
```

---

### Task 8: 添加跨平台测试与 Windows 完整包 CI

**Files:**
- Create: `.github/workflows/test.yml`
- Create: `.github/workflows/build-offline-package.yml`

**Interfaces:**
- Consumes: 全部源码、测试和构建器。
- Produces: 每次 PR 的三平台测试；每次手动构建的 Windows 完整离线包 Artifact。

- [ ] **Step 1: 写 workflow 静态失败测试**

在 `tests/test_offline_docs.py` 增加：

```python
def test_workflows_pin_official_actions_and_keep_release_draft():
    test = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    build = (ROOT / ".github/workflows/build-offline-package.yml").read_text(encoding="utf-8")
    checkout = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
    setup = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
    upload = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    assert checkout in test and checkout in build
    assert setup in test and setup in build
    assert upload in build
    assert "ubuntu-latest" in test
    assert "macos-latest" in test
    assert "windows-latest" in test
```

- [ ] **Step 2: 运行测试并确认 workflow 不存在**

Run: `.venv/bin/python -m pytest tests/test_offline_docs.py -v`
Expected: FAIL，包含 `.github/workflows/test.yml` 不存在。

- [ ] **Step 3: 实现 test.yml**

Workflow 必须：

```yaml
name: test
on:
  pull_request:
  push:
    branches: [main, codex/umi-ocr-web-phase0]
permissions:
  contents: read
jobs:
  python:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: '3.12.10'
          cache: pip
      - run: python -m pip install -e ".[test]"
      - run: python -m pytest -q
      - name: Python 3.8 grammar
        run: python -c "import ast,pathlib; files=list(pathlib.Path('src').rglob('*.py'))+list(pathlib.Path('tests').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8'), filename=str(p), feature_version=(3,8)) for p in files]"
```

Windows 增加 PowerShell parser check 和 fixture DryRun；其他平台只运行 Python 契约测试。

- [ ] **Step 4: 实现 build-offline-package.yml**

Workflow 仅 `workflow_dispatch` 和标签 `offline-v*` 触发，运行 `windows-latest`，先跑全套测试，再执行真实 `scripts/build-offline-package.ps1`。上传 Artifact：ZIP、`.sha256`、`sbom.json`、`THIRD_PARTY_NOTICES.txt`、Release README。保留期 14 天。不得上传 `downloads/` 缓存或现场 `work/`。

- [ ] **Step 5: 本地 YAML/契约验证**

Run: `.venv/bin/python -m pytest tests/test_offline_docs.py tests/test_powershell_contract.py -v`
Expected: 0 failed。
Run: `git diff --check`
Expected: 无输出。

- [ ] **Step 6: 提交 Task 8**

```bash
git add .github/workflows/test.yml .github/workflows/build-offline-package.yml tests/test_offline_docs.py
git commit -m "ci: test and build offline validation package"
```

- [ ] **Step 7: 推送并观察 CI**

Run: `git push origin codex/umi-ocr-web-phase0`
Run: `gh run list --repo leileipei/OCR --branch codex/umi-ocr-web-phase0 --limit 3`
Expected: 最新 `test` workflow 的 Linux、macOS、Windows jobs 全部成功。

---

### Task 9: 创建 Draft Release 工作流并执行端到端验收

**Files:**
- Create: `.github/workflows/release-offline-package.yml`
- Create: `docs/validation/README-release.md`
- Modify: `tests/test_offline_docs.py`

**Interfaces:**
- Consumes: Task 7 构建器、Task 8 测试和标签 `offline-v0.2.0`。
- Produces: GitHub Draft Release `offline-v0.2.0`，包含 ZIP、ZIP SHA-256、SBOM、第三方声明和 Release README。

- [ ] **Step 1: 写 Draft Release 安全契约失败测试**

```python
def test_release_workflow_only_creates_draft_with_expected_assets():
    text = (ROOT / ".github/workflows/release-offline-package.yml").read_text(encoding="utf-8")
    assert "offline-v*" in text
    assert "--draft" in text
    assert "umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip" in text
    assert "permissions:" in text and "contents: write" in text
    assert "work/" not in text
```

- [ ] **Step 2: 运行测试并确认 workflow 不存在**

Run: `.venv/bin/python -m pytest tests/test_offline_docs.py -v`
Expected: FAIL，包含 `release-offline-package.yml` 不存在。

- [ ] **Step 3: 实现 release workflow**

工作流只响应 `push.tags: ['offline-v*']`。步骤固定为：checkout（固定 SHA）、setup-python（固定 SHA）、全套 pytest、真实离线包构建、复算 ZIP SHA、执行：

```powershell
gh release create $env:GITHUB_REF_NAME `
  dist/umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip `
  dist/umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip.sha256 `
  dist/sbom.json `
  dist/THIRD_PARTY_NOTICES.txt `
  docs/validation/README-release.md `
  --repo $env:GITHUB_REPOSITORY `
  --title "Umi-OCR Phase 0 Offline Validation Package v0.2.0" `
  --notes-file docs/validation/README-release.md `
  --verify-tag `
  --draft
```

Job 权限仅 `contents: write`，其余权限不授予。任何测试、哈希、SBOM 或许可步骤失败时不调用 `gh release create`。

- [ ] **Step 4: 编写 Release README**

README 必须记录：

- 包含未经修改的官方 Umi-OCR Rapid v2.1.5；
- 官方 Umi SHA-256 和最终 ZIP SHA-256 的验证命令；
- Windows Server x64、PowerShell 5.1+、管理员协作要求；
- 六类脱敏样本不随包提供；
- E10 未包含，完成 OCR 验证后状态为 `OCR_READY_E10_PENDING`；
- Draft Release 不是生产发布或 Phase 0 通过证明。

- [ ] **Step 5: 提交 Task 9**

```bash
git add .github/workflows/release-offline-package.yml docs/validation/README-release.md tests/test_offline_docs.py
git commit -m "ci: publish draft offline validation release"
```

- [ ] **Step 6: 完成前新鲜验证**

Run: `.venv/bin/python -m pytest -q`
Expected on macOS/Linux: 115 passed、2 个明确标记为仅 Windows 完整构建执行的 skipped、0 failed；Windows build job 设置 `BUILT_OFFLINE_PACKAGE` 后为 117 passed、0 skipped、0 failed。
Run: `.venv/bin/python -m compileall -q src tests`
Expected: exit 0。
Run: Python 3.8 grammar command
Expected: exit 0，输出解析文件数量且无 SyntaxError。
Run: `git diff --check origin/main..HEAD`
Expected: 无输出。
Run: secret scan for private keys, GitHub tokens, AWS keys, password fields
Expected: 无真实凭据；模板中的字段名允许，值必须为空或示例域名。

- [ ] **Step 7: 最终代码审查**

使用 `superpowers:requesting-code-review` 审查从本计划开始前基线到当前 HEAD 的完整 diff。修复全部 Critical/Important，重新运行 Step 5。

- [ ] **Step 8: 推送、标记版本并等待 Draft Release**

```bash
git push origin codex/umi-ocr-web-phase0
git tag -a offline-v0.2.0 -m "Umi-OCR Phase 0 offline validation package v0.2.0"
git push origin offline-v0.2.0
RUN_ID=$(gh run list --repo leileipei/OCR --workflow release-offline-package.yml --branch offline-v0.2.0 --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --repo leileipei/OCR --exit-status
gh release view offline-v0.2.0 --repo leileipei/OCR --json isDraft,assets
```

Expected: test、build 和 release workflow 全部成功；`isDraft` 为 `true`，assets 恰好包含 ZIP、ZIP SHA-256、SBOM、第三方声明和 Release README 5 个附件。不得把 Draft Release 改为公开发布。

---

## Completion Status Semantics

代码、CI 和 Draft Release 全部完成后，只能声明：

```text
OFFLINE_VALIDATION_PACKAGE_READY
WINDOWS_REAL_VALIDATION_PENDING
E10_VALIDATION_PENDING
PHASE_0_NOT_PASSED
```

只有公司 Windows Server 上的普通会话、无登录计划任务、真实 RapidOCR、100 页脱敏样本和后续 E10 三项测试全部生成一致证据后，才允许正式报告输出 `PHASE_0_PASSED`。
