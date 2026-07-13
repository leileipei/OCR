# Windows OCR 验证样本

执行者必须在本地准备以下脱敏样本，但不得提交到版本库：

- 一张简体中文图片；
- 一张中英混排图片；
- 一份 10 页扫描 PDF，包含旋转页和空白页；
- 一份带原生文本层的 PDF；
- 一份损坏 PDF 和一份加密 PDF，用于失败分类。

所有样本必须为脱敏数据，不得包含姓名、身份证号、合同号或其他真实敏感信息。

## Windows 验证解释器

运行 `scripts/run-windows-validation.ps1` 时必须提供两个独立的 Python 解释器：

- `-TestPythonExe`：项目测试环境的 Python，仅用于运行 pytest；
- `-PythonExe`：可加载真实 Umi-OCR 插件及其依赖的 Python，仅用于运行 OCR 验证命令。

计划任务中应传入绝对路径，例如：

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
  -Image 'C:\validation\samples\mixed.png' `
  -Pdf 'C:\validation\samples\scan.pdf'
```
