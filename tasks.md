# tasks.md — 任务拆解（S4 产物）

> 来源：design.md（已决策 §12）｜Change ID：`CHANGE-2026-08-11-core`
> 门禁：**DP-2.5 任务批准**后进入契约桥接（S5）
> 纪律：每 task 独立 commit（R4）；先写失败测试再实现（R5）；不得静默扩大范围（R7）

---

## 0. 任务图（依赖关系）

```
T1 URL 体检器 ──┬──► T3 AI prompt 升级（依赖 status 分流）
               ├──► T2 本地摘要+二阶段规则（依赖抓取结果，与 T1 无强依赖）
T2 ──► T3（AI 输入用摘要）──────────► T5 UI
T4 分类体系扩充（纯配置，可并行）──► T5（分布树展示新类）
T5 ──► T6 回归与文档
```

- T1、T2、T4 可并行；T3 依赖 T1（失效/本地跳过 AI）与 T2（摘要字段）；T5 依赖 T1–T4；T6 收口。

---

## T1 URL 体检器（design §6 C1）— 最高价值，先做

### T1.1 本地/内网判定 `is_local_url(url) -> bool`（纯函数）
- REQUIRES：无
- 实现：`modules/link_probe.py`；判定规则：`file://`、`localhost`、`127.*`、`10.*`、`172.16-31.*`、`192.168.*`、`*.local`、UNC `\\`、`chrome://`、`edge://`、`about:`、`javascript:`、`data:`
- 验收：纯函数、无网络；以上每种形态 1 条用例 + 3 条反例（公网域名不被误判）
- commit: `feat(probe): local url detection - [task-1.1] - CHANGE-2026-08-11-core`

### T1.2 死链探活 `check_link(url) -> LinkProbeResult`（含缓存与防误判）
- REQUIRES：T1.1（本地地址不探活，直接 local）
- 实现：HEAD 优先，不支持则 GET(range)；DNS 失败 / HTTP 404/410 / 超时 / SSL 错误 → dead，记录 `probe_error` + `http_status`；**连续两次失败才标 dead**（防瞬时抖动）；超时可配（默认 3s）；并发批处理；探活缓存 `data/cache/probe.json`（复用 FetchCache 思路或独立小缓存）
- 验收：正常/404/域名不存在/超时/SSL 各用例；防误判（一次失败不标 dead）；缓存命中不重复请求；超时参数生效
- commit: `feat(probe): link health check with cache & retry - [task-1.2] - CHANGE-2026-08-11-core`

### T1.3 集成到流水线（状态分流）
- REQUIRES：T1.1、T1.2
- 实现：解析后分类前对书签做体检；写入 `Bookmark.status`（`ok/local/dead/pending`）+ `probe_error` + `http_status`；local/dead 归宿系统桶（**不进 categories 规则引擎**）：`📁 本地/内网`、`⚠️ 失效链接`；`_chain_fetch` 跳过 local/dead；`Bookmark` 数据类增量字段（design §8）
- 验收：手动导入 100 条混合样例 → 三态分布正确；失效/本地书签不触发抓取；统计日志输出三态数量
- commit: `feat(probe): status routing into pipeline - [task-1.3] - CHANGE-2026-08-11-core`

### T1.4 测试
- 新增 `tests/test_probe.py`（pytest + standalone 双模式，≥ 8 用例）：is_local_url 判定表 / 探活三态 / 缓存命中 / 防误判 / 流水线集成
- 验收：全绿；`tests/test_core.py` 13 项不回归
- commit: `test(probe): link probe suite - [task-1.4] - CHANGE-2026-08-11-core`

---

## T2 本地摘要 + 二阶段规则（design §5 B3）

### T2.1 本地摘要提取 `extract_summary(result) -> str`
- REQUIRES：无（消费 FetchResult）
- 实现：`modules/summarizer.py`；优先级 meta description → og:description → H1/H2 → 高频句首句；去噪（脚本/导航）；≤200 字；纯函数、无网络
- 验收：给定构造 FetchResult → 摘要非空且 ≤200 字；description 缺失时回退 H1/H2 路径
- commit: `feat(summarize): local summary extractor - [task-2.1] - CHANGE-2026-08-11-core`

### T2.2 classifier text 维度二阶段规则
- REQUIRES：T2.1
- 实现：keyword 规则匹配文本扩展为 `title + url + page_summary`（增量，向后兼容）；摘要命中标记 `classify_method="summary_rule"`、置信度 0.7；低于 `rule_confidence_threshold` 不落地；分类缓存版本号升级重建
- 验收：仅靠摘要关键词能归类（title/url 无关键词）；旧缓存失效重建；置信度阈值过滤生效
- commit: `feat(classify): summary-dimension two-stage rules - [task-2.2] - CHANGE-2026-08-11-core`

### T2.3 配置开关
- 实现：config.yaml + DEFAULT_CONFIG 增加 `classification.summary_rule_enabled: true`
- 验收：开关关闭时二阶段规则不生效；开关可热读（重启生效即可）
- commit: `feat(config): summary_rule_enabled toggle - [task-2.3] - CHANGE-2026-08-11-core`

### T2.4 测试
- 新增 `tests/test_summarizer.py`（≥ 5 用例）：摘要提取 3 路径 / 二阶段命中 / 开关关闭行为 / 置信度过滤
- 验收：全绿，无回归
- commit: `test(summarize): summarizer suite - [task-2.4] - CHANGE-2026-08-11-core`

---

## T3 AI prompt 升级（design §5 B1→B3）

### T3.1 prompt 摘要化 + 输出 summary
- REQUIRES：T2.1
- 实现：`build_classify_prompt` 增加 `摘要: {summary}` 输入（替换 raw text 长文）；输出 JSON 增加 `summary` 字段；`parse_ai_response` 兼容旧格式响应；`MAX_PROMPT_CHARS` 相应下调
- 验收：prompt 含摘要且不含 500 字原文；解析旧/新两种响应均成功
- commit: `feat(ai): summary-based classify prompt - [task-3.1] - CHANGE-2026-08-11-core`

### T3.2 page_summary 回写 + 失效/本地跳过 AI
- REQUIRES：T1.3、T3.1
- 实现：AI 结果的 summary 写入 `Bookmark.page_summary`（`main_window._on_ai_item` / `ai_worker`）；`_chain_ai` 的 `to_classify` 排除 `status in (local, dead)`；AI 缓存版本升级
- 验收：AI 分类后 page_summary 非空；local/dead 书签不出现在 AI 队列
- commit: `feat(ai): persist summary & skip dead/local - [task-3.2] - CHANGE-2026-08-11-core`

### T3.3 测试
- `tests/test_ai_prompt.py`（≥ 4 用例）：prompt 内容断言 / 新旧响应解析 / 跳过逻辑
- 验收：全绿
- commit: `test(ai): ai prompt suite - [task-3.3] - CHANGE-2026-08-11-core`

---

## T4 分类体系扩充（design §4 A3 + 决策#4）— 纯配置

### T4.1 config.yaml + DEFAULT_CONFIG 新增两类
- REQUIRES：无
- 实现：
  - `📖 参考工具`：sub_categories `[字典/翻译, 单位/换算, 天气/日历, 计算/工具]`；sub_keywords 如 `[dict, dictionary, translate, translator, converter, unitconverter, weather, calendar, calculator, timetool]`
  - `🏠 居家生活`：sub_categories `[装修/家居, 食谱/美食, 宠物/园艺]`；sub_keywords 如 `[装修, 家居, 宜家, ikea, 食谱, 下厨房, 宠物, 养花, 园艺]`
- 验收：`Classifier(config.yaml)` 加载后规则数增加且两类可命中；`get_category_list` 输出包含新类
- commit: `feat(config): reference & home categories - [task-4.1] - CHANGE-2026-08-11-core`

### T4.2 测试
- 追加 `tests/test_core.py`：新类命中样例（dict.com→参考工具/字典翻译；ikea→居家生活/装修家居）
- 验收：全绿
- commit: `test(config): new category cases - [task-4.2] - CHANGE-2026-08-11-core`

---

## T5 UI（design §9）

### T5.1 表格「状态」列
- REQUIRES：T1.3
- 实现：主表格新增「状态」列：✅正常 / ⚠️失效（含 http 状态码 tooltip）/ 📁本地 / 🕐待定；沿用现有配色体系
- 验收：导入混合样例后状态列正确显示
- commit: `feat(ui): status column - [task-5.1] - CHANGE-2026-08-11-core`

### T5.2 审核筛选 + 一键删除失效
- REQUIRES：T5.1
- 实现：`review_dialog` 新增筛选「⚠️ 失效链接」「📁 本地/内网」；「一键删除全部失效」按钮（二次确认，R9 confirm_delete）
- 验收：筛选正确；一键删除后计数与表格同步
- commit: `feat(ui): dead-link filter & bulk delete - [task-5.2] - CHANGE-2026-08-11-core`

### T5.3 导出复选框 + html_builder 过滤
- REQUIRES：T1.3
- 实现：`_generate_html` 保存对话框前加选项「包含失效链接」（默认不勾）、「包含本地/内网」（默认勾）；`BookmarkHTMLBuilder` 按 status 过滤；系统桶仍输出（本地/内网文件夹）
- 验收：默认导出不含 dead 含 local；勾选后 dead 也导出；`validate_html` 通过
- commit: `feat(export): include-dead/local option - [task-5.3] - CHANGE-2026-08-11-core`

### T5.4 分布树系统桶
- REQUIRES：T5.1
- 实现：分类分布树固定显示 `⚠️ 失效链接 (N)`、`📁 本地/内网 (N)` 计数
- 验收：混合样例后分布树计数与表格一致
- commit: `feat(ui): system bucket counts in dist tree - [task-5.4] - CHANGE-2026-08-11-core`

---

## T6 回归与文档（收口）

### T6.1 全量回归
- 运行：`uv run python tests/test_core.py` + `uv run pytest -q tests/` 全部测试文件
- 验收：全绿（预计 ≥ 35 用例）；无回归
- commit: `test: full regression - [task-6.1] - CHANGE-2026-08-11-core`

### T6.2 文档同步
- 更新：README（新功能点/更新日志）、progress.md、STATE.md、memory-store.md（新决策与踩坑）
- 验收：文档与实现一致
- commit: `docs: sync README & memory - [task-6.2] - CHANGE-2026-08-11-core`

---

## 范围栅栏（Out of Scope）
- ❌ PARA 项目/领域自动归档（design §1.4）
- ❌ Firefox 书签支持（另开 change）
- ❌ 自动 JSON 写回浏览器（另开 change）
- ❌ 标签自动生成（A4 二期）
- ❌ DMOZ 其余补类（⚽ 体育等，二期按需）

## 完成定义（DoD）
1. 每个 task 有独立 commit（R4）
2. 对应测试文件全绿（R5，含先 RED 后 GREEN）
3. T6.2 后 STATE.md → `reviewing` 待 DP-4 审查
