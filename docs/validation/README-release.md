# Umi-OCR Phase 0 离线验证包 v0.2.0

本 Draft Release 用于公司 Windows Server 上的 Phase 0 现场验证。ZIP 内包含未经修改的官方 **Umi-OCR Rapid v2.1.5** 自解压包，以及固定版本的便携 Python、自动化验证工具、依赖许可和完整性清单。

## 使用边界

- 运行环境为 Windows Server x64，要求 PowerShell 5.1 或更高版本，并由服务器管理员协作完成解压、会话和计划任务操作。
- 六类脱敏样本不随包提供。现场需另行准备简体中文图片、中英混排图片、含旋转页与空白页的 100 页扫描 PDF、原生文本 PDF、损坏 PDF 和加密 PDF。
- 泛微 E10 集成未包含在本包中。OCR 普通会话与无登录计划任务验证完成后，状态只能是 `OCR_READY_E10_PENDING`。
- Draft Release 不是生产发布，也不是 Phase 0 通过证明。只有真实 Windows Server、真实 RapidOCR、100 页脱敏样本和后续 E10 三项验证生成一致证据后，才可判断是否通过 Phase 0。

## 验证最终 ZIP SHA-256

下载 ZIP 及同名 `.sha256` 文件后，在两者所在目录运行：

```powershell
$Archive = '.\umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip'
$Sidecar = '.\umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip.sha256'
$Expected = ((Get-Content -LiteralPath $Sidecar -Raw).Trim() -split '  ', 2)[0]
$Actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -cne $Expected) { throw 'ZIP SHA-256 mismatch' }
Write-Host "ZIP SHA-256 verified: $Actual"
```

必须同时保留 `.sha256` 文件作为本次构建的最终 ZIP SHA-256 记录；不要从 Release 页面文字或文件名推断摘要。

## 验证官方 Umi-OCR Rapid 文件

本包锁定的官方文件及摘要为：

```text
Umi-OCR_Rapid_v2.1.5.7z.exe
SHA-256: 659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722
```

先验证 ZIP，再解压并核对其中未经修改的官方自解压包：

```powershell
$ExpectedUmi = '659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722'
Expand-Archive -LiteralPath '.\umi-ocr-phase0-offline-rapid-v2.1.5-tool-v0.2.0.zip' -DestinationPath '.\verified-package'
$Umi = '.\verified-package\umi-ocr-phase0\vendor\Umi-OCR_Rapid_v2.1.5.7z.exe'
$ActualUmi = (Get-FileHash -LiteralPath $Umi -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualUmi -cne $ExpectedUmi) { throw 'Official Umi-OCR SHA-256 mismatch' }
Write-Host "Official Umi-OCR SHA-256 verified: $ActualUmi"
```

摘要全部通过后，按包内 `README-现场验证.md` 执行现场流程。样本、工作目录和证据文件必须留在公司受控环境中，不得提交到 GitHub。

## 当前状态语义

发布此 Draft Release 只允许声明：

```text
OFFLINE_VALIDATION_PACKAGE_READY
WINDOWS_REAL_VALIDATION_PENDING
E10_VALIDATION_PENDING
PHASE_0_NOT_PASSED
```
