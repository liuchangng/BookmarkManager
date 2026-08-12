# RULES.md — 增强版硬规则（14 条）

> 这些不是建议，是护栏。**违反就拦截并回退。**

---

## R1 · 上下文与 Token 管理

**四信号触发 fresh context**：
- 输入 token > 50k
- AI 开始复读同一段话
- 同一错误重复 ≥ 2 次
- 阶段切换（exploring → specifying → designing → tasking → bridging → approved-for-build → executing → testing → reviewing → integrating → deploying → closing）

**触发后必须**：
1. 写 `progress.md`（当前阶段 + 已完成任务 + 下一步）
2. 写 `STATE.md`（状态快照）
3. 清窗后第一句话：`@progress.md @STATE.md 继续`

**禁止**：不带进度文件就清窗。

---

## R2 · 阶段门禁

**不允许跳过任何阶段**。状态机严格按顺序（12 阶段主链路）：

```
exploring → specifying → designing → tasking → bridging → approved-for-build
   → executing → testing → reviewing → integrating → deploying → closing
```

**强制回退触发条件**：
- proposal 范围变了 → 回 `specifying`
- design 架构约束变了 → 回 `bridging`
- 新行为出现 / 接口重大变更 → 回 `specifying`
- 遇 bug → 强制进 `debugging`（不允许"随便试试"）

**禁止**：用户说"跳过吧这次赶时间"也不行。

---

## R3 · 角色红线

**每个 Skill 只做自己阶段的事**：
- `need-explorer` 不写代码、不写 spec
- `spec-writer` 不实现、不审查
- `contract-builder` 不写新内容、只提取压缩
- `build-executor` 不重新规划、只执行契约
- `code-reviewer` 不改代码、只出报告
- `grill-me`（增强）只追问、不写方案

**禁止**：角色越界。

---

## R4 · 提交纪律（🆕 增强）

**每个 task 完成后必须 commit**，contract 里写"无 commit 不算完成"。

**Commit 规范**（参照 Conventional Commits）：
```
feat(auth): add OAuth2 login flow - [task-1.2] - Spec: proposal-001
fix(ui): correct button alignment on mobile - [task-3.1] - Fixes #42
```

**Commit 必须包含**：
- 关联的 task ID
- 关联的 change ID
- 测试状态（pass/fail）

**禁止**：
- 多个 task 混在一个 commit
- "WIP" / "fix" / "update" 等无意义 message
- 跳过 commit 直接进下一个 task

**强制检查**：`scripts/git-enforcer.mjs` 在每个 task 结束时自动验证。

---

## R5 · 测试铁律

**TDD 不可妥协**：
1. **RED** — 先写失败测试，看到它失败
2. **GREEN** — 写最少代码让测试通过
3. **REFACTOR** — 清理代码，测试保持绿色

**Red Flags**（出现即拦截）：
- 先写实现再补测试 → 删掉重来
- "我手动验证了"当作自动化证据 → 不接受
- 静默扩大 task 范围 → 回退到 contract

**禁止**：声称"完成了"但没有新鲜测试证据。

---

## R6 · 反幻觉

**能查代码就别问用户**：
- 项目结构 → 自己 `ls` / `find`
- 已有 API → 自己读源文件
- 已有设计决策 → 自己读 `CONTEXT.md` / `ADR.md`
- 已有术语 → 自己读 `CONTEXT-glossary.md`

**禁止**：能用工具验证的事拿来问用户。

---

## R7 · 范围栅栏

**contract 里的 Scope Fence 是铁律**：
- "Out of Scope" 里写的东西，禁止碰
- 用户中途加需求 → 走 `contract-builder` 重新生成契约
- 不允许"顺手改一下"

**禁止**：静默扩大变更范围。

---

## R8 · 语言约定

**默认中文**（除非项目代码是英文项目）：
- 工件（proposal/specs/design/tasks）→ 中文
- 代码注释 → 跟随项目现有风格
- commit message → 中文 + 英文摘要
- UI 文案 → 中文

**禁止**：无理由在中英文间反复横跳。

---

## R9 · UI/UX 反 Slop（🆕 增强）

**Design.md 顶部必须包含 Anti-Slop 铁律**：

```markdown
## Anti-Slop 铁律（不可违反）
- ❌ 禁止使用 Inter 字体（太 generic）
- ❌ 禁止紫色渐变（#7C3AED 等紫色系主色）
- ❌ 禁止 8px 圆角 + 阴影的"卡片三件套"堆砌
- ❌ 禁止三栏对称布局（除非内容确实需要）
- ❌ 禁止无 hover/active/focus/disabled 四态的组件
- ❌ 禁止 AI 默认配色（gray-50/100/200 阶梯灰）
- ✅ 必须从 popular-web-designs 的 54 套 token 里选一套色板
- ✅ 字体必须从 design-tokens 里指定的字体栈选
- ✅ 每个组件必须定义 hover/active/focus/disabled 四态
- ✅ 间距必须遵循 8px 基线网格
- ✅ 对比度 ≥ 4.5:1（WCAG AA）
```

**执行方式**：
- `contract-builder` 自动把 Anti-Slop 铁律抽进 `execution-contract.md` 的 Design Constraints 段
- `build-executor` 每写一个组件就对照检查
- `code-reviewer` 增加"审美审查"维度（taste-skill 三维度量化）

**禁止**：产出 AI Slop 风格的 UI。

---

## R10 · 记忆持久化（🆕 增强）

**跨会话记忆协议**：

**每次会话结束前必须保存**：
1. `progress.md` — 当前进度台账
2. `STATE.md` — 状态快照
3. `memory-store.md` — 本次学到的关键决策 / 踩坑 / 上下文
4. `CONTEXT-glossary.md` — 新增术语和定义
5. `ADR.md` — 新增架构决策记录

**新会话开始时必须加载**：
```
@progress.md @STATE.md @memory-store.md @CONTEXT-glossary.md
```

**记忆分级**：
- **L1 会话级**（progress.md）— 当前 change 的进度
- **L2 项目级**（CONTEXT.md + ADR.md）— 跨 change 的架构决策
- **L3 个人级**（memory-store.md）— 跨项目的经验和偏好

**禁止**：不带记忆文件就开新会话。

---

## R11 · 需求拷问（🆕 增强）

**进入 `specifying` 阶段前，必须经过 grill-me / grill-with-docs 拷问**。

**两种模式（二选一，不叠加，追问逻辑重叠）**：

| 模式 | 触发条件 | 产物 |
|---|---|---|
| **grill-me**（轻量）| 无代码库 / 空白项目 / 临时想法 | 仅对话内澄清 |
| **grill-with-docs**（持久化）| **有代码库**（默认）| 对话 + CONTEXT-glossary.md + ADR.md |

**grill-me 规则**（不可跳过）：
1. 一次只问一个问题
2. 每个问题给推荐答案
3. 能从代码/文档查到的事实自己查
4. 决策权始终留给用户
5. 确认理解一致前，不许开始行动

**grill-with-docs 规则**（有代码库时）：
- 同步更新 `CONTEXT-glossary.md`（术语解析，**立即写入，不批量**）
- 同步创建 `ADR.md`（架构决策记录，**仅不可逆决策**）
- 每个重大决策都留纸面痕迹
- 冲突检测：用户用词与 glossary 不一致 → 立即指出

**grill-me 问题库**（spec-resources/references/grill-questions.md）：
- 架构：技术栈选择 / 数据模型 / 接口设计 / 错误处理
- UX：用户角色 / 核心流程 / 边界情况 / 无障碍
- 部署：环境 / 监控 / 回滚 / 数据迁移
- 安全：认证 / 授权 / 数据保护 / 审计

**禁止**：
- 没经过 grill-me / grill-with-docs 就写 proposal
- 同时启用两者（追问逻辑完全重叠，造成指令冲突）
- 可逆决策也写 ADR（ADR 只给不可逆的）
- 术语解析只在会话结束时批量写入（必须**立即**写入）

---

## R12 · 文档输出（🆕 增强）

**change 归档时（closing 阶段），必须产出可发布文档**：

**最低要求**（每次 closing 必产）：
1. `40-Outputs/CHANGE-<id>-summary.md` — 本次变更摘要（给人看的）
2. `40-Outputs/CHANGE-<id>-learnings.md` — 本次踩坑和学到的
3. 更新 `LESSONS.md`（全局失败知识库）

**按需产出**（用户明确要求时）：
- 技术博客草稿
- README 更新
- API 文档
- 用户指南

**100x-learning write 模式**接入：
- 使用 `scripts/doc-export.mjs` 自动生成草稿
- 调用 `spec-resources/references/doc-standards.md` 的格式规范
- 输出到 `40-Outputs/Writing/`

**禁止**：
- 只留一份 contract 就当"文档完成"
- 把 AI 生成的内容直接当终稿（必须人工 review）

---

## R13 · Agent 自动加载 GO.md（🆕 v3.0 增强）

**GO.md 必须自动加载，不依赖用户每次手打 `@GO.md`**。

**各 Agent 实现方式**（由 `setup.mjs` 自动配置，**支持 JoyCode / Opencode / Hermes / Cursor / Freebuff / WorkBuddy**）：

| Agent | 注入文件 | 注入方式 |
|---|---|---|
| **JoyCode**（默认）| `.joycode/rules/spec-superflow.mdc` | `alwaysApply: true` 自动注入（含路由器 + 澄清门禁 + STOP）。**这是修复"直接实现零互动"的核心机制 —— JoyCode 只读 `.joycode/rules/*.mdc`，绝不读 `config.yaml` bootstrap** |
| **Opencode** | `.opencode/opencode.json` + `.opencode/skills/` | `setup.mjs` 创建 `.opencode/opencode.json`，通过 `instructions: ["GO.md", "RULES.md", "SYSTEM.md"]` 自动加载工作流；技能复制到 `.opencode/skills/` 供按需调用 |
| **Cursor** | `.cursor/rules/spec-superflow.mdc` | 同 JoyCode：复用同一份 `rules/spec-superflow.mdc`（`alwaysApply: true`），复制到 `.cursor/rules/` 自动注入工作流 + 澄清门禁 |
| **WorkBuddy** | `.workbuddy/rules/spec-superflow.mdc` | 同 JoyCode/Cursor：复用同一份 `rules/spec-superflow.mdc`（`alwaysApply: true`），复制到 `.workbuddy/rules/` 自动注入工作流 + 澄清门禁；技能复制到 `.workbuddy/skills/` 供按需调用 |
| **Hermes** | `<target>/skills/` + 根 `GO.md` | 同 Opencode：技能复制到 `.hermes/skills/`，框架文件复制到项目根 |
| **Freebuff** | `knowledge.md`（项目根）| `setup.mjs` 写入/合并 `knowledge.md`（Freebuff 会话开始自动加载的纯 markdown 知识文件），含 12 阶段状态机 + 澄清门禁 + STOP 链，并指向 `@GO.md` / `@RULES.md` |

> ⚠️ **已移除的 Agent**：CodeBuddy 在 v4.3.0 不再内置适配（用户范围收窄为 JoyCode/Opencode/Hermes/Cursor/Freebuff/WorkBuddy）。如需支持，可自行把 `skills/` 复制到对应 Agent 的 skills 目录。

**状态文件**：当前状态存于项目根 `STATE.md`（`---` frontmatter 的 `current_state` 字段）。`.spec-superflow.yaml` 仅为历史兼容的回退源。

**强制检查**：
- 会话开始 → Agent 必须**先读 GO.md** → 再读 RULES.md + SYSTEM.md
- JoyCode / Cursor / WorkBuddy：`.{joycode,cursor,workbuddy}/rules/spec-superflow.mdc` 已 `alwaysApply`，无需手打 `@GO.md`
- Opencode：`.opencode/opencode.json` 的 `instructions` 已自动加载 GO.md / RULES.md / SYSTEM.md；若未生效，手动 `@GO.md` 兜底
- Freebuff：`knowledge.md` 已自动加载；指向 `@GO.md` / `@RULES.md`；若未生效，手动 `@GO.md` 兜底
- Hermes：技能自动发现；若未生效，手动 `@GO.md` 兜底
- 用户说"修 bug / fix / 调试"等快捷意图 → GO.md 路由器自动识别并路由

**禁止**：
- 用户没打 `@GO.md` 就直接开干（JoyCode 本就无需手打）
- Agent 跳过 GO.md 路由器直接执行代码修改
- 多个 Agent 配置冲突（同一项目只启用一个 Agent 的自动加载）

---

<!-- R11 的 grill-with-docs 内容已并入上方 R11，避免编号重复 -->

---

## R14 · 部署纪律（🆕 v4.4 增强）

**Phase 8（deploying）的硬约束**——把"部署"从口头承诺变成可审计、可回滚的步骤。

**preflight 不过 → 禁止真实部署**：
- `TEST.md` 全绿（无失败项）
- 工作树干净（所有变更已 commit）
- `REVIEW.md` 无未解决 Critical / Important

**强制要求**：
1. **先 `--dry-run` 预演**，确认步骤无误再真实部署（`scripts/deploy.mjs run --target <t> --dry-run`）。
2. **无回滚方案禁止上生产**——DP-8 门禁强制用户口头确认回滚命令。
3. **每次部署必须写 `DEPLOY.md`**——环境 / 版本 / 步骤 / 健康检查 / 回滚（R12 文档输出延伸）。
4. 生产部署**先备份 / 打 tag**，禁止直接 push main 不回滚。
5. 部署后做**健康检查**（端点 200 + 关键路径可用）才算完成。

**禁止**：
- 跳过 preflight 直接部署
- 无回滚方案上生产
- 部署后不留 DEPLOY.md 记录

---

## 违反处理

| 违反 | 处理 |
|---|---|
| R1-R3（流程纪律）| 回退到正确阶段，重写工件 |
| R4（Git 提交）| 阻止进入下一 task，强制 commit |
| R5（测试铁律）| 删掉裸奔代码，从 RED 重来 |
| R6（反幻觉）| 驳回回答，要求用工具查证 |
| R7（范围栅栏）| 回退到 contract-builder 重做 |
| R8（语言约定）| 重写，不计入进度 |
| R9（UI 反 Slop）| 打回重写，对照 Anti-Slop 清单逐条检查 |
| R10（记忆持久化）| 阻止清窗，强制写入记忆文件 |
| R11（需求拷问）| 阻止进入 specifying，先跑 grill-me / grill-with-docs |
| R12（文档输出）| 阻止 closing，先产出文档 |
| R13（自动加载）| 阻止执行，要求先配置 Agent 自动加载 GO.md |
| R14（部署纪律）| 阻止真实部署，要求先过 preflight + 回滚方案 + 写 DEPLOY.md |

---

> **记住：这些规则存在的意义不是为难你，是让 AI 在关键节点停下来、看一眼、说不。**
> **工具只能帮你守住你真心想守的纪律。**
