# Memory Store

## L2 跨会话关键决策
- **核心功能定位**：手动导入书签文件 → 解析 → 两级分类（L1 大类 / L2 小类）→ 生成分类 HTML。浏览器自动导出是辅助路径，不因它复杂化主流程。
- **sub_categories 兼容性**：`sub_categories` 被 excel_writer / ai_client / settings_dialog / review_dialog 以字符串列表消费，**不可改为 dict**。小类关键词改用新增的 `sub_keywords: {小类名: [关键词]}` 映射，纯增量、向后兼容。
- **显式规则优先级**：规则按 priority 升序排序、首条命中即停 → 数值越小越先匹配。显式 `classify_rules` 默认 priority=0（人工覆盖语义）。

## L2 跨会话关键决策（2026-08-11 补充）
- **智能分类设计已归档 design.md**：A3 混合分类体系（领域类 + 常用直达 + 系统级固定桶「失效链接/本地内网」）+ B3 本地摘要二阶段规则（AI 兜底）+ C1 URL 体检状态分流。
- 系统级桶（失效/本地）**不进 categories 配置**，由 URL 体检器产出，避免污染规则引擎。
- 落地顺序：URL 体检器 → 本地摘要+text 维度规则 → AI prompt 摘要化 → 分类体系扩充 → UI。
- Bookmark.page_summary 字段已存在但从未写入，设计激活它。
- 待用户确认：失效/本地书签导出默认排除？DMOZ 补类（居家/参考工具/体育）是否首期？→ 已定（design.md §12）：失效默认排除、本地默认导出、首期补「参考工具」「居家生活」两类。

## L2 跨会话关键决策（2026-08-12 方案 A）
- **方案 A（已选）**：移除分类配置（categories 清空 + 删除 rule/classify_rules 键），分类全程由 AI 自动生成。T2 二阶段规则的「命中免 AI」不再生效（无规则可命中），但**摘要提取保留**并继续喂给 AI（省 token）。
- AI 自由生成 prompt 铁律：一致性命名（同主题同名，禁同义反复）+ 禁 emoji（parse 侧用正则二次清洗 `[\U0001F300-\U0001FAFF\u2600-\u27BF]`）+ 空值兜底（l1→📁 其他, l2→未分类）。
- 系统桶（本地/失效）是状态判定不是分类配置，永远保留；`Classifier.classify` 已加固跳过 local/dead（防规则阶段覆盖，即使误传也安全）。
- 缓存版本：改分类语义必须同时 bump CACHE_VERSION + AI_CACHE_VERSION（旧规则标签作废），否则 cache.fill_bookmarks 会把旧标签灌回。

## L2 跨会话关键决策（2026-08-12 UI 美化）
- **UI 纪律（R9 落地）**：QSS 是唯一样式来源，控件一律 objectName + QSS 四态（hover/pressed/focus/disabled），禁内联 setStyleSheet（`import_hint` 已 objectName 化，动态变色除外）。
- **按钮语言**：主操作 primaryBtn / 次要 secondaryBtn / 危险 dangerBtn / 图标 iconBtn / 大开关 bigToggle；QDialogButtonBox 用 `.button(Ok).setObjectName("primaryBtn")` 区分主次。
- **双主题必须同步**：styles.qss 与 styles_dark.qss 改任何规则都要镜像（暗色禁用态色板：bg #0F172A/#1E293B、fg #475569/#64748B、border #1E293B/#334155）。
- **验证手法**：`QT_QPA_PLATFORM=offscreen` 构造 MainWindow+对话框即可捕获 QSS 解析警告与构造错误，无需真启动窗口。

## L3 踩坑
- 配置关键词禁用单字母（如 "x" 会命中任意 URL），短词如 "line" 会误伤 "online"，需谨慎。
- 测试内联 runner 在 Windows GBK 控制台不能 print emoji，需 ASCII。
- FILETIME(1601起) → Unix 秒：(ft - 11644473600000000) // 1000000。
- **T1 探活测试**：本地 HTTP 服务器跑在 127.0.0.1 会被 is_local_url 判为本地而不探测——probe_urls 增加 `is_local` 注入参数作为测试缝；网络失败用例用 `.invalid` TLD（RFC 6761 保留，解析器本地 NXDOMAIN，无外部流量）。
- **探活缓存同秒 Bug**：checked_at 与 now 同秒时 `0 < delta <= max_age` 为 False 导致缓存永远不命中，需用 `0 <= delta`。
- **T2 阈值交互（重要）**：summary_rule 置信度 0.7 < 默认 rule_confidence_threshold 0.8 → 二阶段默认不落地、交给 AI（决策 #3 字面语义）；降阈值到 ≤0.7 才零成本落地。这是产品权衡：默认保守（AI 兜底），要省钱用户在设置里调阈值。
- **T2 实现细节**：fetch_results 混合存 FetchResult 对象（finished_ok）与 dict（item_done），摘要器必须双兼容；分类缓存 CACHE_VERSION 1→2 触发旧缓存重建；AI 跳过条件需含 classify_method=='summary_rule'（否则落地也被 AI 覆盖，B3 失效）。
- **T3 AI 摘要化**：AI 输入从 500 字原文 → ≤300 字页面摘要（省 token）；输出 JSON 增加 summary 字段回写 Bookmark.page_summary；AIResult 需加 summary 字段并进 to_dict（AIWorker 经 to_dict 下发，漏了就丢）。缓存版本 AI_CACHE_VERSION 1→2。
- **T4 分类体系扩充**：新增「参考工具」「居家生活」两类（14 大类，310+ 规则）。⚠️ 跨类关键词冲突由 priority 决定（数值小者先匹配）——`xiachufang` 原本在生活健康/美食外卖（priority 92），新类居家生活/食谱美食 priority 132，若两处都留则新类不可达；**同词只能留一处**，已把 xiachufang 移入新类。⚠️ 手改 YAML 时 sub_keywords 各条目必须单独成行（`sub_keywords:` 与首个条目同行或两条目同行为非法 YAML，ScannerError）。
- **T5 UI**：状态列文案抽为模块级 `_status_text(bm, fetched)` 便于单测（映射 ok→✅正常/dead→⚠️失效/local→📁本地/其他→🕐待定，抓取加 ·已抓）。导出过滤在 `BookmarkHTMLBuilder.build()` 内做（`include_dead=False/include_local=True`），先于 user_deleted 过滤之后；stats 新增 excluded_dead/excluded_local。⚠️ 测试 helper `_mk` 默认 status="ok"——测 pending 兜底时必须显式传 `"pending"`。
- **方案 A 落地**：config_manager.DEFAULT_CONFIG 与 config.yaml 必须同步改（`_deep_merge` 以 override 为准，只改一处会导致旧 categories 残留）；settings_dialog.save 里删掉了 rule 键写入，否则会复活死配置；`Classifier.classify` 直接调用会覆盖 local/dead（真实流水线靠 classify_worker 过滤），已加 status 跳过加固——测试/脚本直接调 classify 也安全。
