# RFC-008：Local Task Intake and Guided First Run v1

- 状态：Implementation Task / Proposed
- 日期：2026-07-19
- 产品：Project Brain
- 目标版本：完成 PR #17 / Build 7 后的下一独立版本
- 建议分支：`codex/project-brain-local-task-intake-v1`
- 交付方式：新的 Draft PR，不修改或复用已发布 artifact

## 1. 背景

Project Brain 当前已经能够完成：

- macOS App 安装与启动；
- 项目注册；
- Worker 与 MCP 生命周期管理；
- 健康检查与 Diagnostics；
- Task Center 状态展示；
- 菜单栏状态、任务计数与退出。

真实配置完成后，菜单栏显示 `Healthy`，Worker 和 MCP 均为 `running`，但 Task Center 只显示 `No tasks`，App 内没有创建任务的明确入口。如果用户没有连接 ChatGPT/MCP 外部入口，系统不会产生任务，导致产品虽然“健康”，却无法独立完成核心价值闭环。

这不是用户操作问题，而是产品入口缺失。本任务需要让 Project Brain 在不依赖 ChatGPT、Tunnel、Gmail 或 CLI 的情况下，直接通过 macOS App 创建、确认、执行并查看任务。

## 2. 本次目标

实现完整的本地任务入口：

```text
选择项目
→ 描述任务
→ 填写验收标准
→ 生成确定性执行计划
→ 用户确认
→ 创建任务
→ 独立 worktree 执行
→ 验证
→ 展示结果 / Draft PR
```

同时完善首次运行引导，让完成项目配置的用户自然进入“创建第一个任务”，而不是停留在空白 Task Center。

## 3. 前置条件

开始开发前必须满足：

1. PR #17 的 Build 7 阻断修复已经合并，或者任务分支精确绑定经批准的最新 Base SHA。
2. 最终打包 App 与内嵌 Core helper 的版本契约已经修复。
3. 主 checkout 保持在 `main`，不得在主 checkout 中创建任务分支或修改文件。
4. 保留现有项目、任务、SQLite、Keychain、Tunnel 配置和用户未跟踪文件。
5. External ChatGPT acceptance 继续标记为 `Pending`，本地任务验收不得替代它。

若 PR #17 尚未合并，不得把本任务直接追加到 PR #17；应等待其基线确定后创建独立 Draft PR。

## 4. 用户体验

### 4.1 菜单栏入口

在项目选择器下方增加主要操作：

```text
New Task…
Open Task Center
Diagnostics
Quit Project Brain
```

规则：

- `New Task…` 使用当前菜单栏选中的项目作为默认项目；
- 没有项目时禁用，并提供 `Add a project first` 提示；
- readiness 不通过时允许打开表单，但不能提交，必须显示阻断项并提供 `Open Diagnostics`；
- 不得通过菜单项直接绕过计划确认。

### 4.2 Task Center 空状态

当前 `No tasks` 空状态改为：

```text
No tasks yet

Project Brain is ready for a new task.

[ Create Task ]
```

空状态下右侧详情区域不再单独显示无意义的 `Select a task`；可以展示简短的三步说明：

1. Describe the outcome.
2. Review the execution plan.
3. Follow progress and review the result.

### 4.3 首次运行引导

项目 onboarding 成功且系统 readiness 通过后，展示一次性引导：

```text
Your first project is ready

Project Brain works in an isolated Git worktree and keeps your main checkout untouched.

[ Create First Task ]   [ Not now ]
```

要求：

- 可以跳过；
- App 重启后不重复强制展示；
- 用户尚未创建过任务时，Task Center 仍保留创建入口；
- 不把 ChatGPT/Tunnel 连接作为本地任务的前置条件；
- 新增字符串必须使用本地化资源，至少提供 English 与简体中文。

### 4.4 创建任务表单

字段：

1. **Project**
   - 必填；
   - 默认使用当前选中项目；
   - 只允许选择已注册且 readiness 通过的项目。

2. **Task type**
   - `Analyze / Review`：只读分析，不要求产生代码改动，不创建 PR；
   - `Implement change`：允许修改独立 worktree，执行验证，并按项目配置推送分支和创建 Draft PR。

3. **Goal**
   - 必填；
   - 10–8,000 个 Unicode 字符；
   - 作为任务目标文本处理，不得解释为 shell command 或 argv。

4. **Acceptance criteria**
   - 可选但推荐；
   - 最多 8,000 个 Unicode 字符；
   - 支持多行文本或结构化条目；
   - 不接受外部命令、路径授权、环境变量或 SQL。

5. **Delivery**（仅 Implement）
   - `Commit changes`；
   - `Push branch`；
   - `Create Draft PR`；
   - 默认值来自项目 execution profile，用户只能在项目策略允许范围内收紧，不能扩大权限。

主按钮为 `Review Execution Plan`，不能直接显示 `Run` 或绕过 plan。

## 5. 执行计划确认

计划页至少显示：

- 项目名称与规范化仓库路径；
- 精确 default branch 和远端 Base SHA；
- Task type；
- 任务目标摘要；
- execution profile revision 与 SHA-256；
- Codex executable/adapter；
- worktree 根目录；
- verification commands 的可读说明；
- 是否 commit、push、创建 Draft PR；
- 当前 readiness 和所有阻断项。

计划必须返回确定性 `plan_token`。提交时在 RuntimeLock 和数据库事务内重新验证：

- 项目仍存在且路径身份一致；
- project revision/hash 未变化；
- default branch/Base SHA 满足策略；
- plan 未过期且未被使用；
- readiness 仍通过；
- delivery 权限没有扩大；
- 没有重复提交。

计划变化时拒绝提交，并要求用户重新查看计划。

## 6. Core 与数据模型

### 6.1 来源无关入口

本地 App 必须复用来源无关的任务入口和同一任务状态机，不创建 Swift 专属任务存储。

建议内部请求结构：

```json
{
  "schema_version": 1,
  "source": "local_app",
  "project_id": "project-brain",
  "task_type": "analysis",
  "goal": "Review the repository readiness and summarize blockers.",
  "acceptance_criteria": [
    "Do not modify repository files",
    "Return actionable findings"
  ],
  "delivery": {
    "commit": false,
    "push": false,
    "draft_pr": false
  }
}
```

Core 负责生成：

- `task_id`；
- `dedupe_key`；
- `created_at`；
- execution profile snapshot；
- Base SHA；
- plan token 和过期时间。

不得接受来自 Swift/UI 的：

- `command`；
- `argv`；
- `cwd`；
- environment；
- SQL；
- worktree path；
- branch name；
- 任意 executable path；
- GitHub token 或 Tunnel token。

### 6.2 传输边界

本任务不实施 Rust、SMAppService 或完整 Agent 架构重构，但不得继续增加把用户文本放入 argv 的临时实现。

在当前架构下：

- 使用固定 Core command；
- 结构化请求通过 stdin 传递；
- stdin 必须经过严格 JSON Schema 验证；
- stdout 在 `--json` 模式下只能输出一个最终 JSON 文档；
- prompt、说明和进度写入 stderr 或结构化事件流；
- Swift 与 Core 必须进行 capability/contract 检查；
- 最终 `.app` 内嵌 helper 必须参与端到端测试。

后续 RFC-007 Product Runtime v1 可以把同一 application service 方法迁移到 Unix Socket/JSON-RPC，不应重写任务业务逻辑。

### 6.3 Analyze / Review 语义

Analyze 任务：

- Codex 在只读或受控环境中运行；
- 不要求工作区产生修改；
- `Task produced no changes` 不得视为失败；
- 成功条件是得到符合结果 schema 的分析结果和完成状态；
- 不 commit、不 push、不创建 PR；
- 结果持久化并可在 Task Center 查看。

### 6.4 Implement change 语义

Implement 任务继续沿用现有安全模型：

- 每个任务独立 worktree；
- 主仓库不切分支、不修改文件；
- Codex 只在任务 worktree 中运行；
- 接受工作区改动或任务执行期间产生的新提交；
- 运行 verification commands；
- 生成 verification seal；
- 只按项目 snapshot 中的配置 commit/push/Draft PR；
- 终态后按现有安全规则清理 worktree；
- 恢复、重试和失败上限沿用统一状态机。

## 7. Task Center 展示

列表至少显示：

- Task title/goal 摘要；
- Project；
- Source：`App`、`ChatGPT`、其他已支持来源；
- Task type；
- Status；
- 当前 phase；
- 创建时间和更新时间。

详情至少显示：

- 完整目标与验收标准；
- 绑定的项目 revision、Base SHA 和 execution profile hash；
- phase 时间线；
- Codex 执行摘要；
- changed files；
- verification results；
- commit、branch、Draft PR；
- failure/recovery 信息；
- 分析任务的结构化结果。

菜单栏的 Pending/Running/Review/Failed 计数必须在本地任务创建与状态变化后同步刷新，无需重启 App。

## 8. 状态与错误体验

继续使用现有权威任务状态机。UI 不得自行推断成功。

错误必须：

- 显示在当前 sheet 或任务详情内；
- 不被 modal/sheet 遮挡；
- 不直接向普通用户展示 argparse usage、Python traceback 或未脱敏 stderr；
- 提供可执行下一步，例如 `Open Diagnostics`、`Review new plan`、`Retry`；
- 在 Diagnostics/导出包中保留脱敏后的技术证据。

重复点击 Confirm、App 重启、网络中断或 Worker 重启不得创建重复任务。

## 9. 安全要求

- Local App 只是新的 ingress，不增加执行权限。
- 所有项目安全策略来自创建任务时绑定的 execution profile snapshot。
- 用户输入不得成为命令、参数、环境变量、路径或分支名称。
- 不允许通过任务文本关闭 sandbox、验证或审批。
- 不允许写入主 checkout。
- RuntimeLock、项目 claim gate、dedupe、过期和重试限制必须继续生效。
- 日志与 UI 对 token、邮箱、用户目录和凭据进行脱敏。
- Keychain 中的凭据不得写入任务记录、日志或诊断包。

## 10. 非目标

本任务不包括：

- Rust Agent 重写或 Spike；
- SwiftUI 改成 Tauri；
- SMAppService 迁移；
- Codex SDK 默认化；
- Secure MCP Tunnel 外部验收；
- ChatGPT developer-mode 外部验收；
- Apple Developer ID 签名、公证或 Sparkle；
- 多任务并发执行；
- 任意 shell/command 编辑器；
- Gmail legacy 修改；
- 自动合并 PR。

任务执行器仍可保持一次只 claim 一个任务；本任务只要求多个任务可以安全排队和展示。

## 11. 测试要求

### 11.1 Python/Core

至少覆盖：

- Local App 请求 schema 的合法/非法输入；
- command/argv/cwd/environment/SQL/path 等字段拒绝；
- plan token 确定性、过期、单次使用和并发提交；
- execution profile revision/hash 变化后拒绝旧计划；
- readiness 变化后 fail closed；
- Analyze 无代码改动时成功；
- Implement 独立 worktree、验证、commit/push/PR 策略；
- source、task type、结果和证据持久化；
- App 重试与重复点击不会产生重复任务；
- 进程中断后的恢复；
- schema migration 的事务性、幂等和回滚；
- 旧任务和外部来源任务保持兼容。

### 11.2 Swift

至少覆盖：

- 菜单栏 `New Task…`；
- Task Center 空状态 CTA；
- onboarding 后 guided first run；
- 表单字段校验和字符上限；
- Analyze/Implement 条件字段；
- readiness blocker 与 Diagnostics 跳转；
- plan 预览和确认；
- plan stale 后重新确认；
- 双击 Confirm 不重复创建；
- 任务创建后列表、详情和菜单计数刷新；
- App 重启后恢复权威状态；
- 当前 sheet 内错误可见；
- English 与简体中文资源存在；
- UI 不包含 command/argv/cwd/environment 输入。

### 11.3 最终 artifact 端到端

测试对象必须是最终 DMG 中的 `.app` 与其内嵌 helper，而不是源码虚拟环境。

至少完成：

1. 保留已有运行数据库安装升级版本；
2. App 从 `/Applications` 启动；
3. Worker/Core readiness 通过；
4. 不连接 ChatGPT/Tunnel；
5. 从 Task Center 创建 Analyze 任务；
6. 任务进入 Pending/Running 并最终成功；
7. 无文件改动不会报 `Task produced no changes`；
8. 结果在 Task Center 可见；
9. 重启 App 后结果仍存在；
10. 主 checkout、已有项目、任务、Keychain 和用户未跟踪文件均未被修改。

Implement 模式的真实 GitHub Draft PR 验收应使用一次性或明确指定的验收仓库，不得未经授权修改用户生产项目。

## 12. 文档

更新或新增：

- `docs/rfc/RFC-008-local-task-intake-and-guided-first-run-v1.md`；
- Product Shell 使用指南；
- Task Center 状态与结果说明；
- Analyze 与 Implement 的区别；
- 本地任务安全边界；
- 故障恢复与诊断说明；
- 最终 DMG 图形化验收步骤。

README 首页应说明 Project Brain 可以直接从 App 创建任务，ChatGPT 是可选入口之一。

## 13. 交付约束

- 从经批准的精确 Base SHA 创建独立 worktree 和分支；
- 创建新的 Draft PR；
- 不修改或复用旧 artifact；
- 不切换主 checkout；
- 不修改用户未跟踪文件；
- 不修改 PR #10/#11 或其他历史 Draft PR；
- `experiments/gmail-inbox/` 相对精确 Base 必须保持 tracked diff 为零；
- 不合并 PR，不转 Ready，除非用户明确授权；
- External ChatGPT acceptance 保持 `Pending`。

## 14. 完成定义

只有全部满足以下条件才能宣称仓库侧完成：

1. 用户可以完全通过 App 创建本地 Analyze 或 Implement 任务；
2. 本地任务不依赖 ChatGPT、Tunnel、Gmail 或 CLI；
3. 计划在执行前可审核，并由 plan token 和 execution snapshot 绑定；
4. Task Center 能展示实时状态、结果和证据；
5. Analyze 无修改是正常成功，不触发错误重试；
6. Implement 继续使用独立 worktree，不污染主仓库；
7. 最终 App 内嵌 helper 端到端测试通过；
8. Python、SwiftPM、Xcode 和 GitHub Actions 全部通过；
9. 数据迁移、升级、重启恢复和重复提交测试通过；
10. 文档、artifact、manifest 和 SHA-256 完整；
11. 未把 External ChatGPT acceptance 标记为通过；
12. PR 保持 Draft，等待独立审核与用户图形化验收。

## 15. 交付报告模板

完成后必须报告：

```text
Draft PR URL:
Base branch / exact Base SHA:
Head branch / Head SHA:
App version / build:
Core helper version / SHA-256:
Task request schema version:
Database schema version / migration result:
New App entry points:
Analyze end-to-end result:
Implement end-to-end result:
Plan token / snapshot enforcement summary:
Final packaged helper contract test:
Python test count/result:
SwiftPM test count/result:
Xcode test count/result:
GitHub Actions URL/conclusion:
DMG / App ZIP / helper / manifest SHA-256:
Main checkout branch/SHA/status:
User untracked files preservation proof:
Gmail legacy exact-base diff result:
PR #10/#11 status and head:
External ChatGPT acceptance status:
Unfinished items / external blockers:
```
