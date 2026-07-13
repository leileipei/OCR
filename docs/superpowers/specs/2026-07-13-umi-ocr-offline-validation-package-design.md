# Umi-OCR Phase 0 离线现场验证包设计

## 1. 背景与目标

公司计划把 Umi-OCR 改造成基于浏览器的多人 OCR 系统。正式 Web 开发必须先通过 Phase 0，证明真实 OCR 插件、PDF 流程、Windows 无交互运行和 e-cology 10 官方 SSO 边界可用。

当前公司 Windows Server 与泛微测试环境仍在准备中。本设计先交付一个可由公司 Windows/OA 管理员与开发方协作执行的完整离线验证包。管理员负责准备服务器、脱敏样本和后续 E10 测试环境；开发方提供命令、审核证据和诊断问题。

本轮只验证 OCR 侧就绪度。跳过 E10 时必须明确输出 `OCR_READY_E10_PENDING`，完整 Phase 0 报告仍为停止状态。

## 2. 已确认决策

- 执行模式：管理员准备环境并执行，开发方提供命令与结果审核。
- E10：暂时跳过，等待独立测试环境准备完成。
- Windows Server：尚未准备完成。
- 交付：仓库保存源码，同时生成完整离线 ZIP。
- OCR 引擎：RapidOCR。
- Umi-OCR 版本：Windows Rapid v2.1.5。
- 发布：通过 GitHub Draft Release 分发，不把大型二进制提交进 Git 历史。
- 打包方式：官方原包封装。离线 ZIP 内保留未修改的官方自解压包，不重新打包其内部内容。

官方 Windows Rapid v2.1.5 包为 `Umi-OCR_Rapid_v2.1.5.7z.exe`，官方发布页公布的 SHA-256 为：

```text
659c55896c32a5e019dc7bde1713d0e5c73186a2c653bed84c4480fa1795b722
```

来源：<https://github.com/hiroi-sora/Umi-OCR/releases/tag/v2.1.5>

Umi-OCR 主项目使用 MIT License。离线包必须保留其版权与许可文本，并汇总捆绑组件的第三方许可：<https://github.com/hiroi-sora/Umi-OCR/blob/main/LICENSE>

## 3. 范围

### 3.1 本轮包含

- 可重复的本地 Windows 构建脚本；
- GitHub Actions 测试、离线包构建和 Draft Release 工作流；
- 官方 Umi-OCR Rapid v2.1.5 原始自解压包；
- 独立于 Umi-OCR Python 3.8 的便携测试运行时；
- Phase 0 探针源码及锁定的离线依赖；
- PowerShell 分阶段现场向导；
- 六类脱敏样本清单模板；
- 普通 PowerShell 与无登录用户计划任务两种 OCR 验证；
- 本机完整证据、脱敏审核包和 OCR 独立就绪报告；
- SHA-256 文件清单、许可证目录和简化 SBOM；
- 最终 ZIP 及其 SHA-256。

### 3.2 本轮不包含

- e-cology 10 真实联调和 E10 正式证据；
- Vue、FastAPI、PostgreSQL、多人任务队列或正式 Web 功能；
- 在尚未准备好的公司服务器上执行真实验收；
- 自定义 EXE/MSI 安装器、代码签名或自动升级；
- 把 OCR 独立就绪误写成完整 Phase 0 通过。

## 4. Release 成品

成品名称：

```text
umi-ocr-phase0-offline-rapid-v2.1.5-<tool-version>.zip
```

建议目录：

```text
umi-ocr-phase0/
├── README-现场验证.md
├── Start-Phase0Validation.ps1
├── SHA256SUMS.txt
├── manifest.json
├── sbom.json
├── licenses/
│   ├── Umi-OCR-MIT.txt
│   ├── Python.txt
│   └── THIRD_PARTY_NOTICES.txt
├── vendor/
│   └── Umi-OCR_Rapid_v2.1.5.7z.exe
├── runtime/
│   └── python/                 # 独立便携测试运行时
├── toolkit/
│   ├── src/
│   ├── tests/
│   ├── scripts/
│   └── pyproject.toml
├── templates/
│   ├── samples.json
│   ├── global-options.json
│   └── local-options.json
└── work/                       # 首次运行后创建，不进入 Release
```

官方 Umi-OCR 自解压包必须保持字节不变。构建过程先验证固定 SHA-256，再复制到 Release 目录。内部运行时、模型或插件由官方原包提供，避免二次修改带来的来源、兼容性和杀毒误报问题。

## 5. 构建与发布架构

### 5.1 单一构建逻辑

本地 Windows 构建与 GitHub Actions 必须调用相同的 PowerShell 构建模块。构建模块负责：

1. 下载或读取缓存中的官方 Rapid v2.1.5 原包；
2. 在复制前验证固定 SHA-256；
3. 准备独立便携测试运行时和锁定依赖；
4. 复制探针源码、测试、脚本、模板和文档；
5. 汇总许可证与第三方声明；
6. 生成简化 SBOM；
7. 为成品目录中的每个文件生成 SHA-256；
8. 创建最终 ZIP；
9. 为 ZIP 本身生成 SHA-256。

构建必须是 fail-closed：下载失败、摘要不符、依赖未锁定、许可证缺失、测试失败或清单无法生成时，不得产生可发布成品。

### 5.2 GitHub Actions

工作流分为三类：

- `test.yml`：Linux、macOS 与 Windows 运行 Python 测试和 Python 3.8 grammar 检查；Windows 额外运行 PowerShell 静态/行为测试；
- `build-offline-package.yml`：在 Windows Runner 构建离线 ZIP，并把 ZIP、SHA-256 和 SBOM 作为 CI Artifact；
- `release-offline-package.yml`：仅由手动触发或版本标签启动，复用已验证构建逻辑并创建 Draft Release。

Release 默认保持 Draft，必须由维护者核对版本、SHA-256、许可证和测试结果后手动发布。

## 6. 现场向导

主入口为：

```powershell
.\Start-Phase0Validation.ps1 -Action <Action>
```

向导提供以下动作：

| Action | 目的 | 主要输出 |
|---|---|---|
| `Preflight` | 检查包完整性、Windows、权限、CPU、磁盘和路径 | `preflight.json` |
| `Prepare` | 校验并解压官方 Rapid 包，创建唯一验证目录 | `run-context.json` |
| `SelfTest` | 用便携测试运行时执行自动化测试 | `self-test.json` |
| `RunInteractive` | 在普通 PowerShell 中运行真实插件和脱敏样本 | OCR/PDF/资源证据 |
| `InstallScheduledTask` | 创建无登录用户运行的临时计划任务 | 任务定义与任务 ID |
| `CollectScheduledTask` | 等待任务结束并收集退出码、日志和资源证据 | 计划任务证据 |
| `ExportEvidence` | 生成不含原始业务内容的审核包 | `review-bundle.zip` |
| `ResumeE10` | 后续写入并验证真实 E10 证据 | `e10.json` |
| `BuildFinalReport` | 汇总全部门槛 | 正式继续/停止报告 |

向导不得静默安装系统级服务、修改 IIS、修改现有计划任务或变更系统 Python。任何创建计划任务的操作必须在输出中显示名称、账号、触发方式和清理命令。

## 7. 状态机与重跑

每次现场验证使用唯一 `validation_id`，目录不可复用：

```text
NEW
  -> PREFLIGHT_PASSED
  -> PREPARED
  -> SELF_TEST_PASSED
  -> INTERACTIVE_OCR_PASSED
  -> SCHEDULED_OCR_PASSED
  -> OCR_READY_E10_PENDING
  -> E10_READY
  -> PHASE_0_PASSED
```

任一步失败进入对应的 `*_FAILED` 状态，并生成诊断。重试创建新的 attempt 子目录，不覆盖旧证据。只有同一 `validation_id` 下经过哈希绑定的证据可以进入下一状态。

`OCR_READY_E10_PENDING` 是 OCR 子阶段成功，不是完整 Phase 0 成功。`BuildFinalReport` 在 E10 缺失时必须返回非零退出码并输出停止结论。

## 8. 计划任务生命周期

临时计划任务名包含验证 ID，例如：

```text
UmiOcrPhase0-<validation_id>
```

创建前必须确认同名任务不存在。任务按“无论用户是否登录都运行”配置，使用管理员明确指定的服务账号或验证账号，不保存到仓库或审核包中的明文密码。

`CollectScheduledTask` 记录：

- 任务 XML 的脱敏摘要与 SHA-256；
- 运行账号标识的脱敏值；
- Session ID、退出码、开始/结束时间；
- stdout/stderr 与清理后的 Windows 事件信息；
- OCR、PDF、进程树资源和 Qt/QML 检测证据。

证据收集完成后，向导默认提示删除临时任务。只有管理员确认后才删除；删除结果写入审计记录。现有生产计划任务不得被修改。

## 9. 样本与 OCR 门槛

正式验证必须包含：

1. 简体中文非空白图片；
2. 中英混排非空白图片；
3. 至少 100 页、包含旋转页和空白页、无原生文本层的扫描 PDF；
4. 带原生文本层的 PDF；
5. 损坏 PDF；
6. 加密 PDF。

原始样本只保存在服务器本机受控目录，不进入 Git、Release 或脱敏审核包。探针记录真实文件 SHA-256、固定预期、实际分类、非空 OCR 文本块、语种字符覆盖、可搜索 PDF 和进程树资源数据。

## 10. 证据分层与脱敏

### 10.1 本机完整证据

本机证据目录使用受限 ACL，仅验证管理员和指定审核人员可读。它可以包含：

- 样本绝对路径；
- OCR 文本校验所需的本地数据；
- 完整异常栈和诊断日志；
- 官方文件与样本的 SHA-256；
- 计划任务原始输出。

本机证据不得自动上传 GitHub。

### 10.2 脱敏审核包

审核包只包含：

- validation ID、工具/Umi-OCR/插件/解释器版本；
- 文件 SHA-256 和不暴露业务语义的样本编号；
- OCR 结果数量、字符类型覆盖和通过/失败值；
- PDF 页数、旋转/空白页统计、可搜索验证；
- CPU、内存、耗时、吞吐和 Worker 建议；
- 计划任务退出码、Session ID 和清理后的日志；
- 阶段状态与报告。

审核包不得包含原始图片、PDF、完整 OCR 文本、真实账号、密码、Cookie、Token、OA 页面内容或系统环境变量全集。导出前必须运行敏感模式扫描；命中后停止导出并列出字段路径。

## 11. 错误处理

- 每个动作先验证前置状态，不满足时不执行后续操作；
- 文件先写入同文件系统临时目录，完成后原子发布；
- 任何已存在的最终证据目录均不覆盖；
- 哈希不一致、目录复用、插件异常、Qt/QML 依赖、桌面会话、页数不足、样本缺失或脱敏失败都返回非零退出码；
- 异常证据记录阶段、异常类型、完整栈、本机安全环境摘要和建议动作；
- 日志清理器不记录密码参数、完整环境变量或命令行中的秘密；
- 现场执行不依赖互联网，任何运行时联网尝试都视为配置错误。

## 12. 测试策略

### 12.1 Python

- Python 3.8 grammar；
- Python 3.12 自动化测试；
- fake-plugin 图片/PDF/资源端到端；
- E10 缺失时 fail-closed；
- 哈希篡改、跨运行证据、错误语种、空 OCR 和伪资源指标；
- 审核包脱敏与敏感字段阻断。

### 12.2 Windows/PowerShell

- 参数、路径空格和退出码传播；
- Preflight、Prepare 和 SelfTest；
- 计划任务创建、状态收集与确认清理；
- 同名任务和重复目录拒绝；
- 无网络环境下解包、自检和 fake-plugin 验证；
- ZIP 或内部文件被修改后的哈希失败；
- Umi-OCR 官方原包 SHA-256 校验；
- 本地构建与 CI Artifact 目录结构一致。

真实 Umi-OCR、真实计划任务、100 页脱敏样本和 E10 环境仍属于公司现场验收，不能用 CI 模拟结果替代。

## 13. 验收标准

代码与包构建阶段完成需满足：

- Linux/macOS Python 自动化测试全部通过；
- Windows CI 自动化测试全部通过；
- 离线 ZIP 在断网环境完成解包、自检和 fake-plugin 验证；
- 官方 Umi-OCR 原包与最终 ZIP 的 SHA-256 可复算；
- 任一受清单保护的文件被修改后验证失败；
- 计划任务失败时能够生成脱敏诊断包；
- Draft Release 包含 ZIP、ZIP SHA-256、SBOM、许可证和安装说明；
- 本地构建和 GitHub Actions 构建使用同一脚本并产生相同目录结构；
- 缺少 E10 证据时正式报告保持停止状态。

现场 Phase 0 只有在服务器、真实插件、100 页样本、计划任务和 E10 三项验证全部通过后才完成。

## 14. 后续顺序

1. 为本设计编写实施计划；
2. 实现测试与离线构建；
3. 发布 Draft Release；
4. 等 Windows Server 就绪后执行 OCR 现场验证；
5. 等 E10 测试环境就绪后补充官方 SSO 证据；
6. 生成正式 Phase 0 报告；
7. 用户批准后再编写 Phase 1 最小业务闭环计划。
