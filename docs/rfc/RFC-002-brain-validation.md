# RFC-002：Project Brain Validation

状态：Draft  
日期：2026-07-12

## 1. 背景

Project Brain 的目标不是单纯生成项目文档，而是让新的 ChatGPT、Codex 或其他 AI 会话能够在缺少历史聊天记录的情况下，快速恢复：

- 项目目标
- 当前阶段
- 当前活跃任务
- 关键决定
- 安全边界
- 下一步工作位置

仅创建 `.brain/current.md` 和 `.brain/decisions.md` 还不够。随着项目持续变化，可能出现：

- `AGENTS.md` 混入大量当前进度，逐渐变成大杂烩
- `.brain/current.md` 长期不更新，内容失效
- `.brain/decisions.md` 复制架构和长期历史
- 同一事实出现在多个文件中并产生冲突
- AI 完成任务后没有更新当前状态
- 新会话无法准确恢复项目上下文

因此需要一套统一的 Project Brain 检查机制。

## 2. 目标

Project Brain Validator 应验证：

1. Brain 文件结构是否完整。
2. 各文件职责是否清晰。
3. 当前状态是否足够新鲜。
4. 是否存在明显重复或冲突。
5. 新会话能否只依赖最小上下文恢复项目状态。
6. 项目变更是否同步更新了需要更新的 Brain 状态。

## 3. 非目标

本 RFC 不负责：

- 判断业务代码是否正确。
- 替代单元测试、集成测试和人工代码审查。
- 将整个仓库内容复制进 `.brain`。
- 强制所有项目使用完全相同的业务文档结构。
- 自动批准高风险行为或业务决策。

## 4. 文件职责

### 4.1 `AGENTS.md`

保存“如何工作”：

- AI 和贡献者工作规则
- 不可破坏的架构边界
- 安全、隐私和测试要求
- 文档同步要求
- 启动阅读顺序

不应保存频繁变化的：

- 当前正在做什么
- 本周进度
- 临时阻塞
- 下一步任务
- 已完成事项流水账

### 4.2 `.brain/current.md`

保存“现在在哪里”：

- 当前阶段
- 当前活跃任务
- 最近确认的事实
- 当前问题和阻塞
- 下一次开始工作的具体位置
- 当前禁止扩大范围的事项
- 完成当前任务需要定向读取的文档或代码

它是可替换的当前快照，不是长期历史。

### 4.3 `.brain/decisions.md`

保存“当前为什么这样做”：

- 当前仍有效的关键决定
- 决定原因
- 对后续工作的约束
- 重新评估条件

不应保存完整架构说明、实现细节或历史流水。

### 4.4 `docs/`

保存详细事实和长期内容：

- 产品需求
- 技术架构
- 实施计划
- 完整决策历史
- 工程经验
- 业务规则

### 4.5 代码与测试

代码与测试是实现状态的权威来源。Project Brain 不应声称代码已完成，除非该事实可以从代码、测试或已合并变更中确认。

## 5. 检查级别

Validator 输出分为三个级别：

- `ERROR`：必须修复，否则检查失败。
- `WARNING`：允许继续，但需要人工确认。
- `INFO`：改进建议，不影响通过。

## 6. 静态检查规则

### 6.1 文件存在性

最低要求：

- `.brain/current.md`
- `.brain/decisions.md`

缺失任一文件：`ERROR`。

`AGENTS.md` 可由项目选择是否启用；项目存在该文件时，应纳入检查。

### 6.2 必要章节

`.brain/current.md` 至少应能够表达：

- 当前阶段
- 当前活跃任务或当前重点
- 当前问题或阻塞
- 下一步或下一次开始位置

缺少“当前阶段”或“下一步”：`ERROR`。  
缺少活跃任务、问题或接手位置：`WARNING`。

`.brain/decisions.md` 中每项决定建议包含：

- 决定
- 原因
- 约束或重新评估条件

只有标题没有内容：`WARNING`。

### 6.3 新鲜度

`.brain/current.md` 应包含可解析的最后更新日期。

建议默认阈值：

- 30 天以内：通过
- 31–60 天：`WARNING`
- 超过 60 天：`ERROR`

项目可以在配置中调整阈值。

时间过期只表示需要确认，不代表文件中的所有内容必然错误。

### 6.4 `AGENTS.md` 职责检查

当 `AGENTS.md` 出现以下类型内容时提示：

- “当前正在开发”
- “最近完成”
- “下一步”
- 带日期的临时任务进度
- 大量具体 TODO

发现少量内容：`INFO`。  
发现明显的当前状态章节或大量临时进度：`WARNING`。

检查器只提示，不应自动移动内容。

### 6.5 重复与冲突检查

第一版采用保守策略：

- 检查 `.brain/current.md` 和 `.brain/decisions.md` 是否包含高度重复段落。
- 检查同一关键词附近是否出现相反状态，例如：
  - `monitor_only` 与“已启用自动发送”
  - “禁止第三方上传”与“默认发送外部模型”
- 检查同一决定是否在多个文件中出现不同结论。

检测到疑似重复：`INFO` 或 `WARNING`。  
检测到明确冲突：`ERROR`。

Validator 不应仅凭语义相似度自动删除或重写文档。

### 6.6 敏感信息检查

Brain 文件不得包含：

- API Key
- Access Token
- 密码
- 私钥
- 未脱敏客户数据
- 真实订单、账号和个人联系方式

发现高置信度秘密：`ERROR`。  
发现疑似客户数据：`WARNING`，交由人工确认。

## 7. 任务同步检查

当 PR 修改以下内容时，应检查是否需要更新 `.brain/current.md`：

- 当前活跃功能
- 实施阶段
- 主要阻塞
- 自动化等级
- 安全边界
- 下一步工作入口

不是每个代码 PR 都必须修改 `.brain/current.md`。

建议规则：

- 纯重构、格式化、依赖升级：通常不要求。
- 改变项目阶段、当前重点或关键风险：应更新。
- 完成 `.brain/current.md` 中明确列出的活跃任务：应更新。

检查器可以输出：

```text
WARNING: This PR appears to complete or change an active Brain task,
but .brain/current.md was not updated.
```

最终由 PR 作者或审查者确认。

## 8. 新会话恢复测试

恢复测试是 Project Brain 的核心质量检查。

### 8.1 输入范围

默认只允许模型读取：

- `AGENTS.md`
- `.brain/current.md`
- `.brain/decisions.md`

项目没有 `AGENTS.md` 时，只读取两个 `.brain` 文件。

### 8.2 标准问题

模型需要回答：

1. 项目解决什么问题？
2. 当前处于什么阶段？
3. 当前活跃任务是什么？
4. 下一次应该从哪里开始？
5. 当前有哪些关键决定和禁止行为？
6. 完成当前任务还需要定向读取哪些文件？
7. 哪些信息无法从当前上下文确认？

### 8.3 评分维度

每项 0–2 分，总分 14 分：

- 项目目标准确性
- 当前阶段准确性
- 活跃任务准确性
- 下一步可执行性
- 关键决定与安全边界准确性
- 定向阅读建议合理性
- 不确定性表达

建议标准：

- 12–14：通过
- 9–11：带警告通过
- 0–8：失败

任何严重安全边界误判直接失败，例如：

- 把 `monitor_only` 误判为已允许自动发送
- 建议提交真实客户数据
- 建议绕过人工审批

### 8.4 模型输出约束

恢复测试模型必须：

- 明确指出信息来源范围
- 不读取其他文件
- 不修改仓库
- 对无法确认的信息明确说明
- 不根据常识补全业务事实

## 9. PR Gate

第一阶段采用非阻断模式：

```text
brain-check
  ├── static structure
  ├── freshness
  ├── role boundaries
  ├── secret scan
  └── recovery prompt generation
```

输出报告，但仅 `ERROR` 阻止合并。

第二阶段在稳定后增加：

- 自动恢复测试
- 上下文评分
- 与主分支的 Brain 差异检查

不建议一开始就让模型评分成为强制阻断条件，避免不稳定判断影响正常开发。

## 10. Bridge 集成

本地 Bridge/Codex 任务建议采用：

```text
任务下发
  → Codex 修改
  → 项目测试
  → brain-check
  → commit / push
  → Draft PR
```

如果 `brain-check` 出现 `ERROR`：

- 不自动创建“可合并”PR
- 可以创建 Draft PR 并在描述中标记失败项
- 不自动修改 Brain 文档来掩盖错误

建议任务结果中包含：

```text
code/tests: passed | failed | not-run
brain-check: passed | warning | failed
brain-updated: yes | no | not-needed
```

## 11. 配置建议

每个项目可选增加：

```yaml
# .brain/config.yml
version: 1
current_max_age_days: 30
required_files:
  - .brain/current.md
  - .brain/decisions.md
recovery_test:
  enabled: true
  blocking: false
```

第一版工具不应要求所有项目立即增加配置文件；无配置时使用默认值。

## 12. 推荐实施顺序

### Phase 1：静态 Validator

实现：

- 文件存在检查
- 必要章节检查
- 更新时间检查
- 基础敏感信息检查
- Markdown/JSON 格式报告

### Phase 2：PR 差异检查

实现：

- 判断 PR 是否涉及当前活跃任务
- 提示是否需要更新 `.brain/current.md`
- 检查 Brain 文件之间的明显冲突

### Phase 3：恢复测试

实现：

- 生成标准恢复 Prompt
- 调用本地或允许的模型
- 输出结构化评分
- 保留人工复核入口

### Phase 4：GitHub Actions 与 Bridge Gate

实现：

- GitHub Actions 检查
- Bridge 在提交前运行检查
- Draft PR 自动附带检查摘要

## 13. 验收标准

RFC 实施完成后，应满足：

1. 新接入项目可通过一条命令检查 Brain 结构。
2. 过期的 `.brain/current.md` 会被提示。
3. `AGENTS.md` 中明显的当前状态内容会被警告。
4. 高置信度秘密不会进入 Brain 文件。
5. 新会话恢复测试能输出结构化结果。
6. 检查失败不会被自动忽略或伪装成成功。
7. Validator 不修改业务代码，也不自动重写项目决策。

## 14. 待决定问题

- 恢复测试使用本地模型还是云端模型。
- 语义重复检测是否默认启用。
- 模型评分何时可以成为阻断条件。
- `.brain/config.yml` 是否需要成为标准文件。
- Bridge 应在提交前失败退出，还是创建带失败标记的 Draft PR。

## 15. 核心原则

```text
Project Brain 定义上下文结构。
业务项目维护自己的上下文。
Validator 检查上下文是否仍然可信。
Git、代码和测试保存真实实现状态。
```
