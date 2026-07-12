# RFC-002: Project Brain Validation

- Status: Draft
- Date: 2026-07-12
- Owners: Project Brain

## 1. 背景

Project Brain 的目标不是增加更多文档，而是让新 AI、开发者或新的工作会话能够快速恢复：

- 项目为什么存在
- 当前处于什么阶段
- 当前活跃任务是什么
- 哪些决定仍然有效
- 下一步应该从哪里开始
- 哪些行为当前禁止执行

只有 `.brain` 文件存在并不代表上下文可靠。若缺少检查机制，容易出现：

- `.brain/current.md` 长期不更新
- `AGENTS.md` 混入大量当前进度
- `.brain/decisions.md` 复制架构或长期历史
- 同一事实在多个文件中冲突
- Codex 完成代码任务后没有更新项目状态
- 新会话读取 Project Brain 后仍无法继续工作

因此需要一个统一的 Project Brain Validator，检查结构、职责边界、新鲜度和恢复能力。

## 2. 目标

Validator 应当：

1. 在本地、Bridge 和 CI 中使用同一套规则。
2. 优先执行确定性的静态检查。
3. 对语义性问题提供警告，而不是轻易阻断开发。
4. 能验证新会话是否可以恢复项目方向和当前工作位置。
5. 不要求所有项目复制同一套详细文档。
6. 不读取或上传真实客户数据、本地密钥和其他私有材料。

## 3. 非目标

本 RFC 不负责：

- 判断业务代码是否正确
- 替代单元测试、集成测试和代码审查
- 自动修改 `.brain` 内容
- 自动合并 Pull Request
- 把所有项目文档搬进 `.brain`
- 用模型结论替代人工审核

## 4. 文件职责

### `AGENTS.md`

回答“如何工作”。适合保存：

- 开发和 Agent 工作规则
- 不可破坏的架构边界
- 安全、隐私和测试要求
- 文档同步要求
- 启动时的阅读顺序

不适合保存：

- 当前正在做的具体任务
- 今日进度
- 临时阻塞
- 已经失效的下一步

### `.brain/current.md`

回答“现在在哪里”。应当包含：

- 最后更新时间
- 当前阶段
- 当前活跃任务
- 最近确认的事实
- 当前阻塞或风险
- 下一次开始位置
- 当前禁止扩大范围的事项
- 继续工作时需要定向读取的文件

### `.brain/decisions.md`

回答“当前为什么这样做”。只保存：

- 当前仍有效并影响后续工作的关键决定
- 决定、原因、约束
- 必要时的重新评估条件

完整历史继续放在项目既有的长期记忆或架构文档中。

### `docs/`

保存详细事实：

- 产品需求
- 技术架构
- 实施计划
- 长期决策历史
- 工程经验
- API 规范

### 代码、测试和 Git

保存实际实现状态。Project Brain 不应假装替代源码和测试结果。

## 5. 检查级别

Validator 使用三个级别：

### ERROR

表示 Project Brain 无法安全使用，应阻断 PR Gate。

示例：

- `.brain/current.md` 缺失
- `.brain/decisions.md` 缺失
- 必需文件无法解析
- 检测到密钥、Token 或明显的真实客户敏感数据
- `current.md` 没有可识别的更新时间

### WARNING

表示上下文可能退化，但默认不阻断 PR。

示例：

- `current.md` 超过规定时间没有更新
- `AGENTS.md` 出现明显的当前任务或临时 TODO
- `decisions.md` 包含大量实现细节
- 同一段文字在多个 Project Brain 文件中高度重复
- 当前任务没有明确的“下一次开始位置”

### INFO

提供建议，不代表问题。

示例：

- 建议补充定向阅读文件
- 建议将完整历史迁回长期文档
- 本次代码变更没有影响当前状态，因此不要求更新 `.brain/current.md`

## 6. 第一阶段静态检查

第一阶段实现应保持简单、确定和可解释。

### 6.1 结构检查

默认要求：

```text
.brain/
├── current.md
└── decisions.md
```

项目可以通过配置关闭某些规则，但不得静默忽略缺失文件。

### 6.2 基础字段检查

`current.md` 至少应能识别：

- 更新时间
- 当前阶段
- 当前任务或当前重点
- 下一步或下一次开始位置

`decisions.md` 至少应包含一条有效决定，或明确声明当前无额外决定并引用长期文档。

### 6.3 新鲜度检查

默认阈值：

- 14 天：INFO
- 30 天：WARNING
- 90 天：ERROR，可由项目配置调整

新鲜度只表示需要复核，不代表内容一定错误。

### 6.4 职责边界检查

对 `AGENTS.md` 中下列模式发出 WARNING：

- 当前正在开发
- 本周计划
- 今日进度
- 临时 TODO
- 当前阻塞

对 `.brain/decisions.md` 中过多的目录结构、端口、接口字段和逐步操作说明发出 WARNING。

这些检查必须输出命中的文件和行号，不做自动删除。

### 6.5 重复检查

检查以下文件间的高相似段落：

- `AGENTS.md`
- `.brain/current.md`
- `.brain/decisions.md`

默认只提示超过一定长度的近似重复，不对标题、短句和必要边界说明报警。

### 6.6 敏感信息检查

至少检查：

- 常见 Token、API Key 和私钥格式
- `.env` 风格密钥
- 明显的账号密码
- 项目配置中定义的敏感词模式

对于客户聊天、订单和截图等业务敏感数据，项目应提供额外规则。Validator 不应把扫描内容发送到外部模型。

## 7. 变更感知检查

Validator 应根据 Git diff 决定是否提醒更新 Project Brain。

### 默认规则

出现以下变更时，提示检查 `.brain/current.md`：

- 新增或完成重要能力
- 改变当前运行级别
- 修改安全边界
- 修改主要架构路径
- 解决或新增当前阻塞
- 当前活跃任务发生切换

以下变更通常不要求更新：

- 纯格式化
- 拼写修正
- 不影响行为的小型测试维护
- 与当前阶段无关的内部重构

第一阶段可使用文件路径和 PR 标签做规则判断；语义判断后续再引入。

## 8. 新会话恢复测试

恢复测试是 Project Brain 的核心验收，但不应在第一阶段成为不稳定的硬门禁。

### 输入限制

测试会话只允许读取：

- `AGENTS.md`
- `.brain/current.md`
- `.brain/decisions.md`

### 标准问题

1. 项目目标和关键架构边界是什么？
2. 当前处于什么阶段？
3. 当前活跃任务是什么？
4. 下一次应从哪里开始？
5. 当前禁止执行哪些行为？
6. 继续实施前需要定向读取哪些文件？
7. 仅凭这三个文件无法确认什么？

### 评价维度

- 目标恢复
- 当前阶段恢复
- 活跃任务恢复
- 安全边界恢复
- 下一步可执行性
- 不确定性表达
- 是否出现明显臆测

### 输出示例

```json
{
  "status": "warning",
  "score": 88,
  "passed": [
    "goal",
    "stage",
    "safety_boundaries",
    "uncertainty"
  ],
  "missing": [
    "exact_next_start_location"
  ],
  "notes": [
    "current.md should name the first file or command to inspect"
  ]
}
```

模型评分必须视为辅助信号，不得替代静态检查和人工审查。

## 9. PR Gate

建议分三个阶段启用。

### Phase 1：报告模式

- 所有 ERROR、WARNING 和 INFO 都只显示报告
- 不阻断 PR
- 收集误报和漏报

### Phase 2：静态错误门禁

以下情况阻断 PR：

- 必需文件缺失
- 文件解析失败
- 敏感信息命中
- 配置无效

WARNING 不阻断。

### Phase 3：项目自定义门禁

各项目可以提高要求，例如：

- `current.md` 超过 30 天阻断
- 修改自动化等级时必须更新 Project Brain
- 合并前必须完成一次恢复测试

不建议全局强制模型评分达到某个固定分数。

## 10. Bridge 集成

Bridge 中的推荐执行顺序：

```text
接收任务
  → 创建工作分支
  → 本地 Codex 修改
  → 运行项目测试
  → 运行 brain-check
  → 提交并 Push
  → 创建 Draft PR
```

默认行为：

- ERROR：停止提交或 PR 创建，并将完整报告写入任务结果
- WARNING：允许创建 Draft PR，在 PR 描述中加入检查摘要
- INFO：只记录

Bridge 不应自动修复 Project Brain，也不应因为 WARNING 丢弃 Codex 的工作结果。

## 11. CLI 提案

建议工具名：`brain-check`。

```bash
brain-check
brain-check --format text
brain-check --format json
brain-check --diff-base origin/main
brain-check --recovery-prompt
```

建议退出码：

```text
0 = 无 ERROR
1 = 存在 ERROR
2 = 工具或配置执行失败
```

建议输出：

```text
Project Brain Check

PASS  .brain/current.md exists
PASS  .brain/decisions.md exists
WARN  current.md was last updated 37 days ago
WARN  AGENTS.md:42 looks like temporary project status
PASS  no secret patterns detected

Result: 0 errors, 2 warnings
```

## 12. 配置提案

可选配置文件：`.brain/config.yaml`。

```yaml
version: 1
freshness:
  info_days: 14
  warning_days: 30
  error_days: 90

required_files:
  - .brain/current.md
  - .brain/decisions.md

recovery:
  enabled: false

rules:
  agents_status_content: warning
  decision_implementation_detail: warning
  duplicate_content: warning
  secret_scan: error
```

没有配置文件时使用安全默认值。

## 13. 实施顺序

### Milestone 1：最小静态检查器

- 文件存在
- 更新时间解析
- 必需章节
- 基础敏感信息扫描
- 文本和 JSON 输出
- 明确退出码

### Milestone 2：Git diff 与 Bridge 集成

- 变更感知提醒
- Bridge 执行 `brain-check`
- PR 描述附加检查摘要

### Milestone 3：恢复测试

- 生成标准恢复提示词
- 可选本地模型评估
- 结果只作为辅助报告

### Milestone 4：GitHub Actions 模板

- 提供可复制工作流
- 支持项目自定义配置
- 默认只阻断确定性的 ERROR

## 14. 验收标准

RFC 落地后，至少应在一个接入项目中验证：

1. 缺少 `.brain/current.md` 时能返回 ERROR。
2. `current.md` 过期时能返回 WARNING。
3. `AGENTS.md` 出现当前任务时能定位到具体行。
4. 明显密钥写入 `.brain` 时能阻断。
5. 正常项目检查退出码为 0。
6. Bridge 能把检查摘要带入 Draft PR。
7. 新会话恢复测试能指出缺失信息，而不是自行猜测。

首个验证项目建议使用 `kefu-ai`，但 Validator 的实现和规则继续维护在 `Project-Brain` 仓库中。

## 15. 核心原则

```text
Project Brain 定义上下文结构和检查规则；
业务项目维护自己的当前状态和有效决定；
代码、测试与 Git 保存实际实现事实；
检查器发现退化，但不替代人工判断。
```
