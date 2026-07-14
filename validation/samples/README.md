# Windows OCR 验证样本

执行者必须准备脱敏样本清单 JSON。正式验证固定覆盖六类，不能删减：

- `simplified_chinese_image`：含清晰简体中文且非空白的图片；实际 OCR 文本必须包含 CJK 字符；
- `mixed_chinese_english_image`：含中英混排且非空白的图片；实际 OCR 文本必须同时包含 CJK 字符与拉丁字母；
- `scanned_pdf_rotated_blank`：至少 100 页的纯扫描 PDF，包含旋转页和空白页，源文件不能有文本层；
- `native_text_pdf`：带原生文本层的 PDF；
- `corrupt_pdf`：损坏 PDF，预期无法打开；
- `encrypted_pdf`：需要密码的 PDF，预期识别为加密文件。

所有样本必须为脱敏数据，不得包含姓名、身份证号、合同号或其他真实敏感信息。清单只记录本机绝对路径，不提交真实样本。示例：

```json
{
  "samples": [
    {"category": "simplified_chinese_image", "path": "C:\\validation\\samples\\zh.png"},
    {"category": "mixed_chinese_english_image", "path": "C:\\validation\\samples\\mixed.png"},
    {"category": "scanned_pdf_rotated_blank", "path": "C:\\validation\\samples\\scan-100.pdf"},
    {"category": "native_text_pdf", "path": "C:\\validation\\samples\\native.pdf"},
    {"category": "corrupt_pdf", "path": "C:\\validation\\samples\\corrupt.pdf"},
    {"category": "encrypted_pdf", "path": "C:\\validation\\samples\\encrypted.pdf"}
  ]
}
```

## Windows 验证解释器与单次运行

脚本使用两个独立解释器：`TestPythonExe` 只跑项目 pytest，`PythonExe` 只加载真实 Umi-OCR 插件。每次执行自动生成不可复用的 `ValidationId`，结果原子发布到 `validation\results\runs\<ValidationId>`；目录已存在时验证会拒绝执行。正式门槛 `MinPages` 默认为 100，仅自动化测试允许显式降低。`BusinessConcurrencyLimit` 默认为 5，Worker 建议同时受实测内存、逻辑 CPU 和业务并发上限约束。

```powershell
.\scripts\run-windows-validation.ps1 `
  -ProjectRoot 'C:\umi-web-spike' `
  -UmiDataRoot 'C:\Umi-OCR' `
  -TestPythonExe 'C:\umi-web-spike\.venv\Scripts\python.exe' `
  -PythonExe 'C:\Umi-OCR\runtime\python.exe' `
  -PluginRoot 'C:\Umi-OCR\data\plugins' `
  -PluginName 'ocr_paddle' `
  -GlobalOptions 'C:\validation\global.json' `
  -LocalOptions 'C:\validation\local.json' `
  -SamplesManifest 'C:\validation\samples.json' `
  -BusinessConcurrencyLimit 5
```

E10 证据必须使用同一个 `ValidationId`，并在生成报告前写入该运行目录之外的受控位置。报告会严格核对 schema、运行 ID、UTC 时间、样本 SHA-256、插件/解释器身份和所有门槛；不得复制旧运行证据。

E10 JSON 必须由真实测试结果填写；`official_document_sha256` 是所依据官方文档文件的 SHA-256，三项测试结果和 `ready` 必须都是真布尔值且保持一致：

```json
{
  "schema_version": "1.0",
  "validation_id": "与本次 OCR 运行相同的 ValidationId",
  "recorded_at_utc": "2026-07-13T08:00:00Z",
  "protocol": "oidc",
  "official_document_reference": "E10 官方统一身份接口文档版本号/章节",
  "official_document_path": "C:\\validation\\controlled\\e10-official.pdf",
  "official_document_sha256": "64 位小写十六进制摘要",
  "login_endpoint": "https://oa.example.internal/sso/authorize",
  "verification_endpoint": "https://oa.example.internal/sso/userinfo",
  "external_user_id_field": "user_id",
  "department_id_field": "department_id",
  "test_login_succeeded": true,
  "disabled_account_rejected": true,
  "logout_behavior_verified": true,
  "ready": true
}
```

成功运行的 `manifest.json` 将 `ocr-image.json`、`ocr-pdf.json`、`resources.json` 映射到各自 SHA-256。生成报告时会重新读取 E10 官方文档、六类样本和三个证据 JSON 并计算摘要；路径不存在、内容被替换或摘要不一致都会停止阶段 0。
