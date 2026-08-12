# Progress

## CHANGE: 核心链路智能化优化 (2026-08-11)

### 已完成
- [x] UI 新增「📂 导入书签文件」入口（HTML/JSON，免关闭浏览器，自动去重）→ 接入既有分类流水线
- [x] parser.py：BOM 容错、html.unescape 实体解码、JSON 错误友好提示、空文件夹名防护
- [x] classifier.py：`sub_keywords` 小类专属关键词规则（L2 更精确）、域规则匹配子域名、显式规则默认最高优先级
- [x] html_builder.py：跳过空根目录、「其他」按 L2 二级分组输出
- [x] config.yaml + DEFAULT_CONFIG：为 11 个大类补充 sub_keywords（+197 条小类规则，共 300 条规则）
- [x] tests/test_core.py：13 项测试全部通过（standalone 与 pytest 双模式）
- [x] **design.md 已归档**：分类体系(A3混合) / 摘要归类链路(B3本地摘要+二阶段规则) / 失效与本地地址处理(C1状态分流)，含落地顺序与验收标准
- [x] **design.md §12 四项决策已定**：①失效链接默认排除导出（复选框可选包含）②本地/内网默认导出（独立文件夹）③`summary_rule_enabled: true` ④首期补「📖 参考工具」「🏠 居家生活」两类
- [x] **tasks.md 已拆解**：T1 URL体检器 → T2 本地摘要+二阶段规则 → T3 AI prompt 升级 → T4 分类体系扩充 → T5 UI → T6 回归收口（每 task 含验收/commit 规范）
- [x] **execution-contract.md 已生成（S5）**：link_probe.py/summarizer.py 接口签名、Bookmark 增量字段、classifier/ai_client/html_builder/main_window 修改点、逐 task REQUIRES/PRODUCES/验收/commit 表、Anti-Slop 铁律、Scope Fence、DP-3 门禁标记

### T1 URL 体检器（已完成 ✅）
- [x] T1.1 `modules/link_probe.py` `is_local_url`：本地协议/UNC/盘符/localhost/.local/IP 回环·私网·链路本地（ipaddress 标准库）
- [x] T1.2 `LinkProbeResult/LinkProbeCache/probe_urls`：HEAD→GET 兜底、404/410 一次即 dead、网络错误连续 max_fail_confirm=2 次才 dead、缓存 7 天过期重探、并发 8、`is_local` 注入测试缝
- [x] T1.3 `Bookmark` 新增 status/probe_error/http_status；`ProbeWorker` 接入 `_on_worker_success`（解析后分类前）；系统桶分流（📁 本地/内网、⚠️ 失效链接，不进规则引擎）；classify_worker 过滤 local/dead；`_chain_fetch` 跳过 local/dead；体检失败降级不阻塞
- [x] T1.4 `tests/test_probe.py` 11 项全绿（standalone + pytest）

### T2 本地摘要 + 二阶段规则（已完成 ✅）
- [x] T2.1 `modules/summarizer.py`：`extract_summary`（description → 正文高频句，≤200 字，零网络，兼容 FetchResult 对象与 dict）+ `summarize_bookmarks`
- [x] T2.2 classifier：keyword 规则匹配文本含 page_summary（增量兼容）；`classify_with_summary` 二阶段（仅 keyword 规则、跳过标题/URL 已命中、置信度 0.7 ≥ rule_confidence_threshold 才落地，方法标记 summary_rule）；`_resolve_method` 区分 rule/summary_rule；CACHE_VERSION 1→2 触发重建
- [x] T2.3 `classification.summary_rule_enabled: true`（config.yaml + DEFAULT_CONFIG）
- [x] T2.4 `tests/test_summarizer.py` 12 项全绿
- [x] 流水线：`_on_fetch_success` → `_apply_summary_rules()`（摘要提取→二阶段）→ `_chain_ai`（summary_rule 跳过，AI 只兜底）

### T6 回归收口（已完成 ✅）
- [x] T6.1 全量回归：`uv run pytest -q tests/` → 57 passed（15 core + 11 probe + 12 summarizer + 10 ai_prompt + 9 export_options）
- [x] T6.2 README 同步：功能亮点（四级智能分类/URL 体检/本地摘要/14 大类/失效删除）、项目结构（18 模块，补 classify_worker/link_probe/summarizer；tests 5 文件 57 项；删不存在的 run_all_tests.py）、测试命令（pytest + 逐文件 runner）、性能表（300+ 规则）、v1.1 更新日志（T1-T5 全量）；docs/process 文档（design/tasks/execution-contract/STATE/progress/memory）入结构树

### T5 UI（已完成 ✅）
- [x] T5.1 状态列：`_populate_table` 第 7 列显示探活三态（✅正常/⚠️失效/📁本地/🕐待定，抓取过加 ·已抓），逻辑抽为模块级 `_status_text` 可测
- [x] T5.2 失效筛选 + 一键删除：筛选下拉新增「失效链接」；标题行新增「🗑️ 删除失效」按钮（dangerBtn，无失效时禁用），二次确认后批量标记 user_deleted，刷新表格/分布树/统计
- [x] T5.3 导出复选框：`_generate_html` 保存前弹「导出选项」对话框（包含失效链接 默认关 / 包含本地/内网 默认开，默认值来自 config output.export_include_dead/local）；`BookmarkHTMLBuilder`/`build_and_save` 新增 `include_dead=False, include_local=True` 过滤 + stats 记录 excluded_dead/excluded_local；生成日志报告排除数
- [x] T5.4 分布树系统桶：`_on_probe_success` 增加 `_update_dist_tree`，📁 本地/内网、⚠️ 失效链接 进入分布树计数
- [x] T5.5 `tests/test_export_options.py` 9 项全绿（默认过滤/两个 flag/stats/已删除优先/build_and_save 转发/配置默认一致/失效筛选逻辑/状态列文案）

### T4 分类体系扩充（已完成 ✅）
- [x] T4.1 config.yaml + DEFAULT_CONFIG 新增「📖 参考工具」（字典/翻译、单位/换算、天气/日历、计算/工具）与「🏠 居家生活」（装修/家居、食谱/美食、宠物/园艺）两类及 sub_keywords（14 大类、310+ 规则）
- [x] 冲突修正：`xiachufang`（下厨房域名）从旧类 生活健康/美食/外卖 移入 居家生活/食谱/美食（避免优先级 92<132 导致新类不可达）；修复 T4 编辑引入的 YAML 行粘连（ScannerError）
- [x] T4.2 `tests/test_core.py` 新增 2 项：新类 sub_keywords 命中（dict/ikea/weather/xiachufang → 正确 L1/L2）+ get_category_list 含新类（修复测试 `_mk` 参数顺序）；修复测试 `_mk` 参数顺序（url/title 颠倒导致 KeyError）

### T3 AI prompt 摘要化（已完成 ✅）
- [x] T3.1 `ai_client.py`：`build_classify_prompt` 输入改「页面摘要」（summary ≤300 字，不再塞 500 字原文）；输出 JSON 增加 summary 字段；`extract_summary_from_response`（容错提取，兼容旧格式）；`MAX_PROMPT_CHARS` 3000→2000
- [x] T3.2 `AIResult.summary` 字段 + to_dict/缓存回填；main_window：`_chain_ai` 跳过 local/dead；bookmark_info 用 page_summary 替代 text；`_on_ai_item` AI summary 回写 `page_summary`；AICache 版本 1→2；quick_classify 同步摘要化
- [x] T3.3 `tests/test_ai_prompt.py` 10 项全绿

### 验证
- `uv run pytest -q tests/` → 57 passed（15 core + 11 probe + 12 summarizer + 10 ai_prompt + 9 export_options）
- 端到端冒烟：prompt 含「页面摘要」且不含原文；AI 返回 summary → page_summary 回写成功；新类命中验证（dict→参考工具/字典翻译、ikea→居家生活/装修家居、weather→参考工具/天气日历、xiachufang→居家生活/食谱美食）
- 无 git 仓库（`git status` fatal），无法按 R4 逐 task commit；改动均在工作区

### CHANGE-2026-08-12-ai-auto（方案 A：全 AI 自动分类，已完成 ✅）
- [x] 移除分类配置文件：config.yaml + DEFAULT_CONFIG `categories: []`，删除 classify_rules 与 rule_enabled/rule_confidence_threshold/summary_rule_enabled
- [x] ai_client：`build_classify_prompt` 空配置分支（AI 自由生成两级分类，一致性命名/禁 emoji）；`parse_ai_response` 空分类直接采用 AI 标签（去 emoji、空值兜底）；AI_CACHE_VERSION 2→3
- [x] cache.py：CACHE_VERSION 2→3（旧规则标签作废）；classify_worker 无规则提示「AI 自动分类模式」
- [x] classifier.classify 加固：跳过 status local/dead（系统桶不被规则阶段覆盖）
- [x] UI 适配：settings 移除规则组/AI 文案/分类预览空态；review_dialog/excel_writer 空分类时从已有书签推导分类选项；Excel L1 校验空选项跳过
- [x] 测试改造：test_core 规则用例→方案 A 语义（0 规则/全 unmatched/空分类列表），test_summarizer 真实配置无规则，test_ai_prompt 新增自由 prompt/标签直通 2 项——57 项全绿
- [x] 端到端冒烟：无规则 → 全部待分类 → AI 生成标签（💻 去 emoji）→ HTML 验证通过；系统桶保持

### CHANGE-2026-08-12-ui-polish（UI 样式美化与布局优化，已完成 ✅）
- [x] 按钮体系统一：import_wizard open/copy → secondaryBtn；review_dialog 批量按钮 → primary/secondary + QDialogButtonBox OK/Cancel 分主次；settings test_key → secondaryBtn、show_key → iconBtn（新增 QSS）
- [x] 按钮微交互：移除全局 pressed padding 跳动（浅/暗双主题），新增 QPushButton:focus 焦点环
- [x] 四态补全（浅/暗同步）：secondary/danger/bigToggle/ComboBox/SpinBox/CheckBox/Radio/Tab/ToolButton 的 disabled；QScrollBar::corner
- [x] 布局：import_hint → objectName hintText（QSS 统一），主窗口最小尺寸 900×600 → 1024×640
- [x] 验证：QSS 双主题解析无警告、MainWindow+Settings/Review/ImportWizard 三对话框 offscreen 构建 OK、pytest 57 passed

### 全部完成
- T1 体检分流 → T2 摘要二阶段 → T3 AI 摘要化 → T4 分类扩充 → T5 UI → T6 回归收口，57 项测试全绿，README 与实现一致
