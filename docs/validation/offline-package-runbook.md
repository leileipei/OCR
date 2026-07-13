# Umi-OCR Phase 0 离线验证包管理员手册

本文面向在隔离内网 Windows Server 上执行验证的管理员。所有命令都在解压后的包根目录、提升权限的 64 位 PowerShell 中运行；现场执行不需要网络，也不会安装系统服务、修改 IIS 或修改系统 Python。

## 1. 重要边界

- `OCR_READY_E10_PENDING` 只表示 OCR 子阶段就绪，**不是完整 Phase 0 通过**，不得据此开始正式 Web 开发。
- E10 尚未准备时，完整报告必须停止；`BuildFinalReport` 预期 exit 1，并生成“停止”结论报告。
- 工作目录、完整证据、证据 ZIP 和原始样本不得上传 GitHub，也不得放入 Git、GitHub Release 或其他公共制品库。
- 临时计划任务不会自动删除。必须在审核证据后，再用 `-ConfirmCleanup` 显式清理。
- 不要修改发布 ZIP。可把发布包解压为现场工作副本，并仅在该副本中调整配置；保留原 ZIP 及其 SHA-256 供复核。

## 2. 样本与 Rapid 配置

包内 `templates/samples.json` 固定列出六类样本：简体中文图片、中英混排图片、至少 100 页且含旋转页和空白页的无文本层扫描 PDF、原生文本 PDF、损坏 PDF、加密 PDF。把脱敏后的真实文件放入 `C:\Phase0Samples`，文件名与模板一致。原始样本只留在受控服务器本机。

`templates/global-options.json` 和 `templates/local-options.json` 对应官方 Rapid v2.1.5 包内 `win7_x64_RapidOCR-json/rapidocr_config.py` 与 `models/configs.txt`：

- 全局初始化：`numThread = 4`；
- 单次运行：`language = 简体中文`、`angle = true`、`maxSideLen = 2048`。

模板不包含密码、Token、Cookie 或 OA 地址。若现场需要调整线程数、方向分类或最长边，请在解压后的工作副本操作，不要改写发布 ZIP 中的原模板，也不要在配置文件中加入账号或秘密。

## 3. 初始化标识

三个标识只能使用字母、数字、点、下划线和连字符，且 interactive 与 scheduled 标识必须不同：

```powershell
$campaignId = "campaign-20260713-001"
$interactiveId = "interactive-20260713-001"
$scheduledId = "scheduled-20260713-001"
```

后续所有命令必须复用这三个值；不要跨 campaign 混用证据。

## 4. OCR 现场验证

按以下顺序逐条执行。`InstallScheduledTask` 会要求输入明确的非管理员验证账号凭据，并显示临时任务信息。

```powershell
.\Start-Phase0Validation.ps1 -Action Preflight -CampaignId $campaignId
.\Start-Phase0Validation.ps1 -Action Prepare -CampaignId $campaignId
.\Start-Phase0Validation.ps1 -Action SelfTest -CampaignId $campaignId
.\Start-Phase0Validation.ps1 -Action RunInteractive -CampaignId $campaignId -ValidationId $interactiveId
.\Start-Phase0Validation.ps1 -Action InstallScheduledTask -CampaignId $campaignId -ValidationId $scheduledId
.\Start-Phase0Validation.ps1 -Action CollectScheduledTask -CampaignId $campaignId -ValidationId $scheduledId
.\Start-Phase0Validation.ps1 -Action ExportEvidence -CampaignId $campaignId -InteractiveId $interactiveId -ScheduledId $scheduledId
```

`ExportEvidence` 严格校验两个运行属于同一 campaign、使用不同 validation ID 且都通过，然后生成：

- `ocr-readiness.md`：OCR 独立就绪报告；
- `review-bundle.zip`：只含允许列表字段的脱敏审核包；
- campaign 下的 `e10` 与 `reports` 受控目录。

命令会在控制台打印审核包位置。完整 OCR 证据仍留在 `work/campaigns/<campaignId>/attempts`，不得上传。

## 5. E10 未准备时的硬门槛检查

先从 `ExportEvidence` 输出或计划任务安装 attempt 中确认 scheduled OCR 结果目录，并设置受控路径：

```powershell
$campaignRoot = Join-Path (Get-Location) "work\campaigns\$campaignId"
$scheduledResultsDir = Read-Host "粘贴 ExportEvidence 使用的 Scheduled OCR results 绝对路径"
$e10EvidencePath = Join-Path $campaignRoot "e10\e10.json"
$stopReportPath = Join-Path $campaignRoot "reports\final-report-e10-missing.md"
$entryScript = Join-Path (Get-Location) "Start-Phase0Validation.ps1"
```

E10 文件尚不存在时执行以下检查；它必须生成停止报告，并且 `BuildFinalReport` 预期 exit 1：

```powershell
& $entryScript -Action BuildFinalReport -CampaignId $campaignId -ScheduledResultsDir $scheduledResultsDir -E10EvidencePath $e10EvidencePath -FinalReportPath $stopReportPath
if ($LASTEXITCODE -ne 1) { throw "缺少 E10 时 BuildFinalReport 必须返回 exit 1" }
```

不要把失败报告路径复用于最终成功报告；入口拒绝覆盖已有文件。

## 6. E10 准备后的恢复

把泛微官方文档副本和人工核验后的 `e10.json` 放入 `work/campaigns/<campaignId>/e10` 受控目录。`e10.json` 必须满足现有 `E10Evidence` schema，包括：

- `schema_version`、与 `$scheduledId` 相同的 `validation_id`、UTC 记录时间；
- 官方协议类型与官方文档引用；
- 官方文档的绝对本机路径及小写 SHA-256；
- HTTPS 登录/校验端点以及外部用户、部门字段名；
- 登录成功、禁用账号拒绝、退出行为三项 JSON 布尔值；
- `ready` 必须等于三项验证结果的逻辑与。

官方文档路径也必须位于同一 campaign 的 `e10` 受控目录。证据中不得保存密码、Cookie、Token 或 Authorization 值。

```powershell
$finalReportPath = Join-Path $campaignRoot "reports\final-report.md"
.\Start-Phase0Validation.ps1 -Action ResumeE10 -CampaignId $campaignId -E10EvidencePath $e10EvidencePath
.\Start-Phase0Validation.ps1 -Action BuildFinalReport -CampaignId $campaignId -ScheduledResultsDir $scheduledResultsDir -E10EvidencePath $e10EvidencePath -FinalReportPath $finalReportPath
```

`ResumeE10` 使用包内便携 Python 调用 `E10Evidence.from_dict()`，验证官方文档哈希、HTTPS 端点、三项布尔门槛，并强制 E10 validation ID 与 scheduled validation ID 一致。只有随后 `BuildFinalReport` 返回 0，状态才会从 `E10_READY` 转为 `PHASE_0_PASSED`。

## 7. 审核后显式清理

先确认本机完整证据、脱敏审核包和最终报告均已审核并按公司制度留存，再清理临时计划任务：

```powershell
.\Start-Phase0Validation.ps1 -Action RemoveScheduledTask -CampaignId $campaignId -ValidationId $scheduledId -ConfirmCleanup
```

清理动作会核验任务与持久安装记录的绑定，写入清理意图和结果；不要在审核证据前执行，也不要用任务计划程序手工删除来绕过记录。

## 8. 失败处理

- 任一命令非零退出时立即停止，不要继续下一步。
- 重试使用相同 campaign 和对应 validation ID；系统会创建新的单调递增 attempt，不覆盖旧证据。
- 不要手工编辑 `state.json`、attempt 目录或计划任务元数据。
- 发现路径重解析点、证据绑定不一致、哈希不符或敏感字段时，保留当前工作目录供审计并重新准备干净的现场工作副本。
