# GO.md — 统一入口（一个命令吃所有）

> **BDMA 思想：一个入口文件，吃掉所有路由。**
> 你只需 `@GO.md`（或 Agent 已自动加载）＋ 一句自然语言，路由器根据 `STATE.md` 与意图自动判断阶段、自动推进、自动门禁。
> **没有快捷短语，没有记忆命令——状态机本身就是你的进度条。**

---

## 用法（唯一一种）

```
@GO.md 我要给项目加一个暗黑模式
```

- **Agent 已配置自动加载（R13）** → 直接说需求即可，本文件在会话开始已被注入，**无需手打 `@GO.md`**。
- **自动加载未生效** → 手打 `@GO.md` 兜底。
- **不需要任何额外命令/短语**：继续、看进度、修 bug、归档——统统是自然语言，GO.md 按「状态 + 意图」解析。

> 为什么没有快捷短语表？因为一个文件 + 状态机已经能吃掉所有路由（参考 BDMA「one command eats all」）。
> 维护一堆魔法短语反而让 Agent 走捷径、绕过门禁。状态机 + 意图识别就够了。

---

## 核心纪律：严格推进的契约链（Design by Contract）

> 笔记 3.XX.12（齐码.SKILL 借鉴）：**每个步骤的输入，必须是上一步骤的产物。**
> 这是「契约式设计」搬到 AI 工作流——先定义"做什么、谁对谁负责"，再到不留一丝歧义，最后才动手。

流水线**线性 · 可拓展 · 不可跳步**。每一步只做三件事：

```
REQUIRES（上游产物） → 做本步 → PRODUCES（下游唯一输入） + 门禁 STOP（等用户批准）
```

- **REQUIRES 缺失 → 拒绝进入该步**（`scripts/state-guard.mjs` 硬拦截）。
- **门禁 STOP 未获批准 → 禁止越过**（DP-x 标记是推进的唯一钥匙）。
- **PRODUCES 是下一步的 REQUIRES** —— 环环相扣，无孤儿工件、无静默跳过。

### 步骤登记表（Step Registry）—— 可拓展

编号即顺序。**要加一步**：在序列插入 + 补 `state-guard.mjs` 的 `TRANSITIONS` 转移 + 补 `GATE_BY_STATE` 工件门禁。

| # | 步骤 | 状态 | 提示词 | REQUIRES（上游产物） | PRODUCES | 门禁 |
|---|---|---|---|---|---|---|
| **S1** | 想法/变更 | `exploring` | `0-change` | —（新变更）| `STATE.md` + `CHANGE-<id>/` + 规模通道判定 | — |
| **S2** | 需求澄清 | `specifying` | `1-requirement` | `STATE.md`(exploring) | `proposal.md` + `ADR.md` | **DP-1** |
| **S3** | 设计/UI | `designing` | `2-design` → `2a-ui-design` | `proposal.md`(DP-1) | `design.md` + `design-tokens.md` + `UI-DESIGN.md` | **DP-2** |
| **S4** | 任务拆解 | `tasking` | `3-task` | `design.md`(DP-2) | `tasks.md` | **DP-2.5** |
| **S5** | 契约桥接 | `bridging` | `contract-loader` | `proposal.md`+`design.md`+`tasks.md` | `execution-contract.md` | **DP-3** ⭐唯一"写代码"确认 |
| **S6** | 实现 | `approved-for-build`→`executing` | `4-dev` | `execution-contract.md`(DP-3) | 代码 + 每 task commit | 每 task TDD |
| **S7** | 测试 | `testing` | `5-test` | `execution-contract.md`(DP-3) | `TEST.md` | **DP-5** |
| **S8** | 审查 | `reviewing` | `6-review` | `TEST.md` | `REVIEW.md` | **DP-4 前置** |
| **S9** | 集成归档 | `integrating` | `7-integration` | `REVIEW.md` | 集成 + 文档 | **DP-4** |
| **S10** | 部署 | `deploying` | `8-deploy` | 测试绿 + git 干净 + review 过 | `DEPLOY.md` | **DP-8** |
| **S11** | 收口 | `closing` | `7-integration` | `DEPLOY.md` | summary / learnings + 记忆 | → `archived` |

> **八步骨架** = S1→S2→S3→S4→S5→S6→S7→S8（想法→需求→设计→任务→契约→实现→测试→审查）。
> S9 / S10 / S11 与调试分支是**可拓展扩展步**——加步只需改登记表 + `state-guard` 两处。

### 可用工具（按阶段）

本流程内置以下工具 Skill，在对应阶段可用（Agent 自动发现 `skills/` 目录，无需额外配置）：

| 工具 | 适用步骤 | 用途 |
|---|---|---|
| `grill-me` | S2（需求澄清）| 严格一问一答澄清需求，禁止跳过 |
| `design-system-picker` | S3（设计）| 匹配设计系统/组件库，避免自由发挥 |
| `agnes-media-generator` | S3（设计）/ S6（实现）/ S10（部署）| 通过 Agnes AI API 生成图片（文生图/图生图）和视频（文生视频/图生视频）|
| `sdd-engine` | S6（实现）| 子代理驱动开发，每 task 独立子代理+双阶段审查 |
| `ui-anti-slop` | S6/S8 | 扫描 AI Slop 模式（Inter/Roboto/紫色/8px）|
| `git-enforcer` | S6/S8/S9 | 提交前规则检查，禁止不合规 commit |
| `ecc-memory` | S11（收口）| 跨会话记忆持久化 |
| `deploy-runner` | S10（部署）| 可审计部署（dry-run → 真实部署）|
| `doc-writer` | S9/S11 | 文档生成 |
| `code-understander` | S6/S8 | 代码理解/分析 |

### 调试分支（正常路由，不是快捷方式）

意图含 `修 / fix / 调试 / bug` 且当前处于 `executing` / `testing` → 路由 `bug-investigator`（状态 `debugging`）：

1. 必须复现（看得到才算）
2. 提假设：**"我怀疑是 X，因为 Y"**（禁止"随便试试"）
3. 验证假设（日志 / 断点 / 测试）
4. 修复 + 回归测试
5. commit（含 bug-id）
6. 回 `executing` / `testing`

---

## 自动路由逻辑（意图 + STATE）

读 `STATE.md`（无 → 视为新变更，进 S1）：

```
├── exploring            → S1 (0-change) → S2
├── specifying           → S2 (1-requirement) → 澄清门 DP-1
├── designing            → S3 (2-design → 2a-ui-design) → DP-2
├── tasking              → S4 (3-task) → DP-2.5
├── bridging             → S5 (contract-loader) → DP-3
├── approved-for-build   → S6 (4-dev，DP-3 后开始写代码)
├── executing            → S6 (4-dev，SDD 子代理并行)
├── testing              → S7 (5-test) → DP-5
├── debugging            → bug-investigator（从 executing/testing 进入）
├── reviewing            → S8 (6-review) → DP-4
├── integrating          → S9 (7-integration) → DP-4
├── deploying            → S10 (8-deploy) → DP-8
└── closing              → S11 (7-integration) → archived
```

意图含 `修 / fix / 调试 / bug` 且处于 `executing` / `testing` → 路由 `debugging` 分支。

---

## 启动消费顺序（AGENTS 式）

Agent 读完本文件后，**严格按此顺序**加载（存在才读，缺失跳过）：

1. `RULES.md` —— 14 条硬规则（护栏，不是建议）
2. `SYSTEM.md` —— 精简版全局约束
3. `STATE.md` —— 当前状态机位置 → `progress.md` —— 已完成 task
4. `CONTEXT-glossary.md` + `ADR.md` —— 术语表 / 不可逆决策
5. `memory-store.md` —— 跨会话记忆
6. **按当前步的 `REQUIRES` 加载上游工件**（proposal / design / tasks / contract …）
7. `spec-resources/prompts/<当前步>.md` —— 执行本步

> 顺序即契约：**先懂规则 → 再懂状态 → 再懂上下文 → 最后才动手。**

---

## UI/UX 硬约束（来自笔记 3.XX.12 借鉴）

设计 / 实现阶段必须满足（R9 + 笔记 A.4 / C.7）：

- **四态强制**：每个页面 / 组件必须处理 `loading / empty / error / forbidden`，缺一则审查打回。
- **no orphan + no missing 双铁律**：实现 = 设计——不许多出契约外元素（orphan），不许漏掉契约要求（missing）。
- **设计令牌即契约**：`design-tokens.md`（DTCG 风格）是唯一视觉真相源，值只从令牌取，绝不自由发挥。
- **反 Slop**：禁 Inter / 紫色 / 8px 三件套；`scripts/ui-validate.mjs` 自动扫描阻断。

---

## 反模式清单（"绝不"列表）

- ❌ 跳过阶段 / 跳门禁（R2）
- ❌ 无 DP-3 批准就写实现代码
- ❌ 没有 contract 就动手
- ❌ 静默扩大 Scope（R7）
- ❌ 多个 task 混一个 commit（R4）
- ❌ 产出 AI Slop UI / 缺四态
- ❌ 用"我手动验证了"代替 `TEST.md` 证据（R5）
- ❌ 清空上下文不写 `progress.md`（R1 + R10）
- ❌ 跳过 grill-me 写 `proposal.md`（R11）
- ❌ closing 不产文档（R12）
- ❌ 部署无回滚方案 / 不写 `DEPLOY.md`（R14）
- ❌ 调试"随便试试"不提假设

---

## 强制门禁 STOP 链（不可越过）

```
DP-1 需求批准 → DP-2 设计批准 → DP-2.5 任务批准
   → DP-3 写代码批准（唯一一次）
   → DP-5 测试放行 → DP-4 审查/集成批准 → DP-8 部署批准
```

任一门禁未获明确批准（确认 / OK / approve）→ **停在当前步，不许越过。**

---

## 内容级过期回退

不是看时间戳，而是比较内容——上游产物变了，回退到对应步重做：

| 变化 | 回退到 |
|---|---|
| `proposal.md` 范围变了 | `specifying` (S2) |
| `specs/` 已批准需求改了 | `bridging` (S5) |
| `design.md` 架构约束变了 | `bridging` (S5) |
| `tasks.md` 批次变了 | `bridging` (S5) |
| `execution-contract.md` 不再匹配 intent | `bridging` (S5) |
