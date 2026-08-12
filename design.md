# design.md — 书签智能分类优化设计（S3 产物）

> 状态：**待评审**（评审通过 → DP-2 → 进入任务拆解）
> 关联：GO.md 核心目标 = 手动导入书签文件 → 解析 → **两级文件夹分类（1级大类 / 2级小类）** → 收藏落在底部
> 本文档归档 2026-08-11 的设计讨论结论：分类体系 / 摘要归类链路 / 失效与本地地址处理

---

## 1. 背景与目标

### 1.1 项目核心链路（现状已可用）
```
手动导入/浏览器导出 → 解析(parser) → 规则分类(classifier) → 网页抓取(fetcher) → AI补充(ai_client) → 审核(review) → 生成两级HTML(html_builder) → 浏览器导入
```

### 1.2 本次设计要解决的问题
1. **打不开的页面（死链/404/超时）与本地地址（file://、localhost、内网 IP）没有明确归宿**，与真·未知书签混在「其他/待分类」，无法筛选、无法批量清理。
2. **「提取摘要 → 生成两级分类」链路不完整**：目前抓取正文是原始 `text[:500]`，没有真正的摘要步骤；长尾书签全部压给 AI，成本高。
3. **分类体系**可借鉴经典案例（DMOZ / PARA / GTD / 中文门户）优化，但需保持 config.yaml 数据驱动，不硬编码。

### 1.3 设计目标
- 每个书签必须有明确归宿：**领域类 / 失效链接 / 本地内网 / 待分类** 四选一。
- 长尾书签**零成本归类**：本地摘要 + 二阶段规则命中，AI 只做兜底。
- 失效 / 本地判定**纯本地、零网络成本、可解释**。
- 分类体系仍是配置文件驱动，新增系统桶不破坏现有 `categories` 结构。

### 1.4 非目标（Scope Fence）
- ❌ 不做 PARA「项目/领域」自动归档（需要用户当前项目上下文，无法自动推断）。
- ❌ 不改变既有的导出 / 导入 / 审核 / HTML 生成主流程顺序。
- ❌ 不做浏览器端插件。

---

## 2. 现状盘点（已存在能力，设计复用不重复造）

| 能力 | 位置 | 说明 |
|---|---|---|
| 规则分类 | `modules/classifier.py` | config.yaml 驱动，300 条规则（含 sub_keywords 小类规则）；keyword 规则已匹配 `title+url` |
| 三引擎抓取 | `modules/fetcher.py` | Scrapling → requests → Firecrawl 兜底；提取 title/description/keywords/text；带缓存 |
| AI 两级分类 | `modules/ai_client.py` | DeepSeek，prompt 含描述/关键词/正文；JSON 输出 l1/l2/confidence/reason；缓存 + 成本上限 |
| 跳过清单 | `fetcher._should_skip` | 已跳过 file://、chrome://、pdf、媒体、youtube/twitter/facebook 等反爬站 |
| 未命中归宿 | `classifier.classify` | → `其他/待分类`，方法 `unmatched` |
| 两级输出 | `modules/html_builder.py` | L1 大类 → L2 小类 → 书签；「其他」保持两级结构 |
| 摘要字段 | `modules/bookmark.py` | `page_summary` 字段已定义但**从未写入**（本次设计激活它） |

---

## 3. 参考案例调研（2026-08-11 检索）

| 案例 | 出处 | 核心思路 | 对本项目的借鉴 |
|---|---|---|---|
| **DMOZ / ODP** | Open Directory Project（2017 关停，数据仍在） | 15+1 顶层类：Adult/Arts/Business/Computers/Games/Health/Home/News/Recreation/Reference/Regional/Science/Shopping/Society/Sports/World | 领域型大类标杆；现有 12 大类可对照补缺口（如 Home 居家、Reference 工具参考、Sports 体育） |
| **PARA** | Forte Labs (fortelabs.com) | Projects / Areas / Resources / Archives，按「可行动性」组织 | 书签栏「常用直达」思想；顶层不做过细领域分类 |
| **GTD** | Getting Things Done 论坛 | 按任务/上下文组织文件夹 | 同上：按用途而非内容 |
| **奔跑的奶酪** | runningcheese.com（5000 书签实践） | 文件夹分大类（资源/工具…）+ 标签做细粒度描述 | A4 方案来源：1 级大类 + 标签（HTML `TAGS=` 已支持） |
| **Marqly / Raindrop** | Chrome 商店 / 工具评测 | AI 分析网页内容自动归类 | 印证「抓取+AI 归类」路线，但本项目强调**本地优先、AI 兜底** |
| **中文门户分类** | hao123 / 2345 导航 | 常用站直达 + 生活场景大类 | 补充中文用户直觉类目（游戏、生活、新闻、购物已有） |

结论：**领域型（DMOZ/门户）适合做自动分类的骨架；行动型（PARA）只借鉴「常用直达」；标签是备选增强**。

---

## 4. 方案 A：分类体系设计

### A1 领域型（DMOZ / 中文门户风格）
- 12 大类对照 DMOZ 补缺口：新增 `🏠 居家生活`、`📖 参考工具`、`⚽ 体育` 等候选。
- 优点：直觉、好维护；缺点：与「此刻要用它做什么」脱节。
- 改动：仅 config.yaml `categories` + `sub_keywords` 扩充（纯配置，无代码改动）。

### A2 行动型（PARA / GTD）
- `项目 / 领域 / 资源 / 归档` + 书签栏常用直达。
- 优点：生产力导向；缺点：**自动分类不可行**（需用户当前项目上下文），故仅借鉴「常用直达」。

### A3 混合型 ⭐推荐
```
书签栏（直达常用站，不分类）
  └─ 领域大类 × N（现有 12 类，config 驱动）
        └─ 小类 × M（sub_keywords 精确归类）
  ├─ ⚠️ 失效链接        ← 系统级桶（URL 体检判定，不参与规则/AI）
  └─ 📁 本地/内网       ← 系统级桶（URL 体检判定，不参与规则/AI）
其他书签（同构）
```
- 系统级桶**不在 categories 里**，由 URL 体检器产出，避免污染规则引擎。
- 优点：直觉 + 效率兼顾，直接承载「打不开/本地归其他」的诉求。

### A4 标签混合（奔跑的奶酪）
- 文件夹只做 1 级大类，细节用标签；`TAGS=` 属性已支持。
- 优点：一条书签可属多类；缺点：标签自动生成难，作为**二期增强**，不做首期。

### A 决策
首期按 **A3**；若用户需要多归属，二期叠加 A4 标签。

---

## 5. 方案 B：摘要 → 二级归类链路

### B1 单步优化（现状小改）
- 抓取后直接把 title/description/keywords/text[:800] 给 AI，一次输出 JSON。
- 改 prompt：强制输出 `{summary, l1, l2, confidence, reason}`，`summary` 回写 `Bookmark.page_summary`。
- 优：改动最小；劣：长尾全部走 AI，费 token。

### B2 两步（摘要 → 分类）
- 抓取 → 生成摘要（本地或 LLM）→ LLM 只读摘要分类。
- 优：分类更稳省 token；劣：多一次调用 / 本地摘要质量有限。

### B3 本地摘要 + 二阶段规则 ⭐推荐
```
URL 体检(C) → 抓取成功 ?
  ├─ 否 → ⚠️ 失效链接（带原因），结束
  ├─ 是 → 本地摘要提取器 extract_summary(result)
  │        （meta description → og:description → H1/H2 → 高频句首句，≤200字）
  ├─ 一阶段：现有规则匹配 title+url（已存在）
  ├─ 二阶段：摘要+标题 再喂规则一次（keyword 规则增加 text 维度）
  │        命中 → 归类（方法标记 summary_rule）
  └─ 仍未命中 → AI 兜底（prompt 只喂摘要，省 token）→ 回写 page_summary
```
- 优：**性价比最高**——多数长尾书签靠摘要关键词即可归对类；AI 只兜底；复用现有规则引擎。
- 改动点：
  1. 新增 `modules/summarizer.py`（本地摘要提取，无依赖或仅 re）。
  2. `classifier` 的 keyword 规则匹配文本扩展为 `title + url + page_summary`（增量，兼容旧缓存）。
  3. `build_classify_prompt` 增加 `summary` 字段与输出字段。

### B4 完全离线
- 不调 AI：本地摘要 + 规则 + 域名库。
- 优：零成本零隐私风险；劣：覆盖率有上限。作为**无 AI Key 时的降级路径**天然存在（现状 AI 缺失即跳过）。

### B 决策
首期按 **B3**；B1 的 prompt 输出 summary 并入 B3 第 3 步。

---

## 6. 方案 C：打不开 / 本地地址处理

### C1 状态分流 ⭐推荐
分类前先做 **URL 体检**（纯本地、零网络成本、批量并行）：

| 判定 | 规则 | 归宿 |
|---|---|---|
| 本地/内网 | `file://`、`localhost`、`127.*`、`10.*`、`172.16-31.*`、`192.168.*`、`*.local`、UNC `\\`、`chrome://`、`edge://`、`about:`、`javascript:`、`data:` | `📁 本地/内网`（不抓取） |
| 明显死链 | 域名不存在（DNS 失败）、HTTP 404/410、连接超时、SSL 错误（探活确认） | `⚠️ 失效链接`（存 error + HTTP 状态码） |
| 抓取成功但规则/AI 均未命中 | — | `其他/待分类` |
| 正常归类 | — | 领域类 |

- 新增 `Bookmark.status`：`ok / local / dead / pending` + `probe_error` + `http_status`。
- 探活结果单独缓存（`data/cache/probe.json`），避免重复探测同一 URL。
- 审核界面新增「⚠️ 失效链接」「📁 本地/内网」筛选，失效可一键删除。

### C2 三步判定
- HEAD 探活（并发、短超时 3s）→ 有内容才抓正文 → 摘要归类。
- 优：快；劣：部分站点不支持 HEAD（回退 GET range）。

### C3 防误判
- 连续两次失败才标失效（防瞬时网络抖动），重试退避。
- 探活与抓取共享结果：抓取本身失败即视为探活失败，不额外请求。

### C 决策
首期按 **C1**，C3 的「二次确认」并入探活实现；C2 作为可选项（HEAD 探活优于直接 GET）。

---

## 7. 推荐组合与落地顺序

**A3（混合分类体系）+ B3（本地摘要二阶段规则，AI 兜底）+ C1（URL 体检状态分流）**

```
落地顺序（每步可独立交付、独立测试）:
  Step 1  URL 体检器（modules/link_probe.py）—— 本地/内网、死链 三态分流 + 探活缓存
  Step 2  本地摘要提取（modules/summarizer.py）+ classifier text 维度二阶段规则
  Step 3  AI prompt 升级：摘要字段输出 + page_summary 回写 + 失效书签跳过 AI
  Step 4  分类体系按 DMOZ/门户扩充 categories + sub_keywords（纯配置）
  Step 5  UI：表格「状态」列 + 审核筛选「失效/本地」+ 一键删除失效
```

优先级：Step 1 价值最高（直接实现「打不开归其他/未知」）；Step 2 次之；Step 3-5 为增强。

---

## 8. 数据模型变更

```python
# modules/bookmark.py（增量字段）
@dataclass
class Bookmark:
    ...
    page_summary: str = ""      # 激活：本地摘要/AI 摘要回写（现状未使用）
    status: str = "pending"     # ok / local / dead / pending（URL 体检结果）
    probe_error: str = ""       # 死链原因（DNS / HTTP 404 / 超时 / SSL）
    http_status: int = 0        # 探活/抓取 HTTP 状态码
```

- `Bookmark.tags` 已存在（A4 二期用）。
- 分类缓存（`data/cache/classify*.json`）：规则签名含 text 维度变化 → 升级缓存版本号使旧缓存失效重建。

---

## 9. UI 影响（R9 四态强制）

| 界面 | 变更 | 四态 |
|---|---|---|
| 主表格 | 新增「状态」列（✅正常 / ⚠️失效 / 📁本地 / 🕐待定） | — |
| 审核对话框 | 新增筛选「失效链接」「本地/内网」；失效一键删除；loading/empty/error 提示 | 必做 |
| 生成 HTML | 失效/本地书签**默认不导出**（可配置保留），避免把死链导回浏览器 | loading/empty |
| 分类结果页 | 分类分布树显示四个固定桶计数 | — |

- 反 Slop：延续现有 QSS 设计令牌，不新增配色体系。

---

## 10. 验收标准（可测项）

1. `file://`、`localhost`、`127.0.0.1`、`192.168.x`、`*.local`、`chrome://` → `status=local`，不触发抓取。
2. 404 / 域名不存在 / 超时 URL → `status=dead`，带 `probe_error` 与 `http_status`，归宿「失效链接」。
3. 正常 URL 且摘要关键词命中 → 规则二阶段归类成功（`classify_method=summary_rule`），**不消耗 AI**。
4. 正常 URL 摘要未命中 → 进入 AI 兜底，`page_summary` 回写成功。
5. 重复运行：探活/AI 命中缓存，二次运行无网络请求。
6. HTML 导出默认不含失效/本地书签；`validate_html` 通过。
7. 全量回归：`tests/test_core.py` 现有 13 项不回归；新增 probe/summarizer/二阶段测试 ≥ 8 项。

---

## 11. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| 死链误判（瞬时失败） | 连续两次失败才标 dead；探活短超时可配置 | 仅删 `status=dead` 判定逻辑，不影响其他 |
| 摘要关键词误归类 | 二阶段规则沿用置信度阈值（`rule_confidence_threshold`），低置信不落地 | 关闭 text 维度开关（config `classification.summary_rule_enabled`） |
| AI 成本上升 | B3 已把 AI 输入从 800 字原文降为 200 字摘要；成本上限已有 | 恢复单步 prompt |
| 缓存版本不匹配 | 版本号升级自动重建 | 手动清缓存按钮已有 |
| 导出把死链带回浏览器 | 默认排除失效/本地，可配置保留 | 配置项一键恢复 |

---

## 12. 待确认问题（已决策 2026-08-11）

| # | 问题 | 决策 | 理由 / 备注 |
|---|---|---|---|
| 1 | 失效链接导出默认行为 | **默认排除**（不导出、不进浏览器）；导出对话框提供复选框「包含失效链接」，默认不勾选 | 死链导回浏览器毫无意义；失效书签仍在审核列表可一键删除，不丢数据 |
| 2 | 本地/内网是否参与导出 | **默认导出**，归入独立「📁 本地/内网」文件夹；同样受导出复选框控制（默认含、失效不含） | 内网系统/本地文件常是用户要保留的，与死链性质不同 |
| 3 | 摘要二阶段规则开关 | `classification.summary_rule_enabled: true`（默认开）；命中标记 `classify_method=summary_rule`；置信度沿用 keyword 规则 0.7，低于 `rule_confidence_threshold` 不落地；缓存版本号升级重建 | 可随时关闭，回退安全 |
| 4 | DMOZ 补类是否首期 | 首期加入 **2 个**：「📖 参考工具」（字典/翻译/换算/天气/计算器）、「🏠 居家生活」（装修/家居/食谱/宠物）；⚽ 体育等其余**二期按需** | 参考工具类书签多且常落「其他」；体育与视频/新闻边界模糊 |
