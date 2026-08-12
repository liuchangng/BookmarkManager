# execution-contract.md — 执行契约（S5 产物）

> Change ID：`CHANGE-2026-08-11-core`
> 上游 REQUIRES：design.md（§12 已决策） + tasks.md（T1–T6）
> **门禁：本契约仅在 DP-3 批准后生效**。无 DP-3 批准不得写任何实现代码（R2）。
> 本契约是「唯一写代码确认」：实现必须与本文档接口签名一一对应，no orphan / no missing（R9）。

---

## 1. 依赖关系（与 tasks.md §0 一致）

```
T1 URL体检器 ──┬──► T3 AI prompt 升级（依赖 status 分流）
               ├──► T2 本地摘要+二阶段规则（消费 FetchResult，与 T1 无强依赖）
T2 ──► T3（AI 输入用摘要）────────────► T5 UI
T4 分类体系扩充（纯配置，可与 T1/T2 并行）──► T5（分布树新类）
T5 ──► T6 回归与文档
```

执行建议顺序：**T1.1 → T1.2 → T1.3 → T1.4 → T2.1 → T2.2 → T2.3 → T2.4 → T3.1 → T3.2 → T3.3 → T4.1 → T4.2 → T5.1 → T5.2 → T5.3 → T5.4 → T6.1 → T6.2**

---

## 2. 接口签名（实现必须满足）

### 2.1 新增模块 `modules/link_probe.py`（T1）

```python
# ── 本地/内网判定（纯函数，无网络）──
def is_local_url(url: str) -> bool:
    """file://、localhost、127.*、10.*、172.16-31.*、192.168.*、*.local、
    UNC(\\\\)、chrome://、edge://、about:、javascript:、data: → True"""

# ── 探活结果 ──
@dataclass
class LinkProbeResult:
    url: str
    status: str = "pending"   # "ok" | "local" | "dead" | "pending"
    http_status: int = 0
    error: str = ""           # DNS / HTTP 404 / 超时 / SSL / 本地地址
    checked_at: int = 0
    method: str = ""          # "head" | "get" | "local" | "skip"

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "LinkProbeResult": ...

# ── 探活缓存（data/cache/probe.json，沿用 FetchCache 思路）──
class LinkProbeCache:
    def __init__(self, cache_dir: str = "data/cache/probe"): ...
    def get(self, url: str) -> Optional[dict]: ...
    def set(self, url: str, result: LinkProbeResult): ...
    def save(self): ...
    def stats(self) -> dict: ...   # {total, hits, misses, hit_rate}

# ── 批量探活（并发、短超时、连续两次失败才标 dead）──
def probe_urls(urls: list[str], *, timeout: float = 3.0,
               max_fail_confirm: int = 2, cache: Optional[LinkProbeCache] = None,
               progress_cb: Optional[Callable] = None) -> dict[str, LinkProbeResult]:
    """返回 {url: LinkProbeResult}；本地地址直接 local 不发起请求；
    失败一次不标 dead，连续 max_fail_confirm 次失败才标 dead"""
```

### 2.2 新增模块 `modules/summarizer.py`（T2.1）

```python
def extract_summary(result) -> str:
    """消费 modules.fetcher.FetchResult（或 to_dict() 的 dict）
    优先级：meta description → og:description → H1/H2 文本 → 高频句首句
    去噪（script/style/导航/版权行）；返回 ≤200 字；无网络、纯本地"""

def summarize_bookmarks(fetch_results: dict[str, object]) -> dict[str, str]:
    """批量：{url: summary}；无抓取结果的 URL 返回空字符串（不参与二阶段规则）"""
```

### 2.3 修改 `modules/bookmark.py`（T1.3，增量字段）

```python
@dataclass
class Bookmark:
    # ... 现有字段不变 ...
    page_summary: str = ""      # 激活（T3.2 回写）
    status: str = "pending"     # ok / local / dead / pending（T1.3）
    probe_error: str = ""       # 死链原因
    http_status: int = 0        # 探活/抓取 HTTP 状态码
```

### 2.4 修改 `modules/classifier.py`（T2.2）

```python
# keyword 规则匹配文本（增量，不破坏旧行为）:
#   text = f"{title} {url} {page_summary}"  （page_summary 为空时与现状一致）
# 命中摘要维度的规则 → classify_method="summary_rule"（新值，UI method_map 需登记）
# 置信度沿用 keyword 规则的 0.7；低于 rule_confidence_threshold 不落地
# 分类缓存版本号升级（强制旧缓存重建）
```

### 2.5 修改 `modules/ai_client.py`（T3.1）

```python
def build_classify_prompt(bookmark_info: dict, categories: list[dict]) -> tuple[str, str]:
    """bookmark_info 新增 "summary" 键（≤200 字）；user prompt 中
    「正文摘要」字段替换为「页面摘要: {summary}」；不再塞 text[:500] 原文
    输出 JSON 增加字段: {"l1","l2","confidence","reason","summary"}"""

def parse_ai_response(response_text: str, categories: list[dict]) -> tuple[str, str, float, str]:
    """返回 (l1, l2, confidence, reason)；summary 由调用方单独提取，
    旧格式响应（无 summary）必须兼容解析"""

def extract_summary_from_response(response_text: str) -> str: ...  # 新增，容错提取
```

### 2.6 修改 `ui/main_window.py`（T1.3 / T3.2 / T5）

```python
# T1.3: 解析后分类前调用
#   probes = probe_urls([b.url for b in bookmarks], cache=self.link_probe_cache)
#   回写 b.status / b.probe_error / b.http_status；local/dead 跳过 _chain_fetch
# T3.2: _chain_ai 的 to_classify 排除 status in ("local", "dead")
#       _on_ai_item 成功时 bm.page_summary = summary
# T5.1: _populate_table 新增「状态」列（✅正常/⚠️失效/📁本地/🕐待定）
# T5.3: _generate_html 保存前弹出勾选：
#         「包含失效链接」(默认 False) 「包含本地/内网」(默认 True)
#       传入 BookmarkHTMLBuilder 新参数
```

### 2.7 修改 `modules/html_builder.py`（T5.3）

```python
class BookmarkHTMLBuilder:
    def __init__(self, bookmarks, root_name="书签栏", other_root_name="其他书签",
                 sort_by="title", add_favicon=True, preserve_dates=True,
                 backup_original=True,
                 include_dead: bool = False,    # 新增：默认排除失效
                 include_local: bool = True):   # 新增：默认包含本地/内网
        ...

def build_and_save(bookmarks, output_path, root_name="书签栏", sort_by="title",
                   add_favicon=True, preserve_dates=True,
                   include_dead: bool = False, include_local: bool = True) -> dict:
    ...
```

### 2.8 配置（T2.3 / T4.1 / T5.3 默认值来源）

```yaml
# config.yaml + modules/config_manager.DEFAULT_CONFIG 同步新增：
classification:
  summary_rule_enabled: true        # T2.3
output:
  export_include_dead: false        # T5.3 默认值
  export_include_local: true        # T5.3 默认值
categories:
- name: 📖 参考工具                  # T4.1 新增
  sub_categories: [字典/翻译, 单位/换算, 天气/日历, 计算/工具]
  sub_keywords:
    字典/翻译: [dict, dictionary, translate, translator, 翻译, 词典]
    单位/换算: [converter, convert, 换算, 单位]
    天气/日历: [weather, calendar, 天气, 日历, 农历]
    计算/工具: [calculator, 计算器, timetool]
- name: 🏠 居家生活
  sub_categories: [装修/家居, 食谱/美食, 宠物/园艺]
  sub_keywords:
    装修/家居: [装修, 家居, 宜家, ikea, 家装]
    食谱/美食: [食谱, 下厨房, 菜谱, cooking]
    宠物/园艺: [宠物, 养花, 园艺, 多肉]
```

---

## 3. 逐 task 契约

| Task | REQUIRES | PRODUCES | 验收（DoD） | Commit |
|---|---|---|---|---|
| T1.1 | — | `is_local_url` 纯函数 | 判定表用例全绿（本地 8 类 + 反例 3） | `feat(probe): local url detection - [task-1.1]` |
| T1.2 | T1.1 | `LinkProbeResult/Cache/probe_urls` | 三态用例 + 防误判 + 缓存命中 + 超时生效 | `feat(probe): link health check - [task-1.2]` |
| T1.3 | T1.1+T1.2 | `Bookmark.status/probe_error/http_status` 写入；系统桶分流；fetch 跳过 | 混合样例三态分布正确；local/dead 不触发抓取 | `feat(probe): status routing - [task-1.3]` |
| T1.4 | T1.1-1.3 | `tests/test_probe.py` ≥8 用例 | 全绿 + `test_core.py` 13 项不回归 | `test(probe): suite - [task-1.4]` |
| T2.1 | — | `extract_summary` ≤200 字 | 3 条提取路径用例 | `feat(summarize): extractor - [task-2.1]` |
| T2.2 | T2.1 | keyword 规则 text 维度；`summary_rule` 标记；缓存版本升级 | 仅摘要关键词命中；旧缓存重建；阈值过滤 | `feat(classify): two-stage - [task-2.2]` |
| T2.3 | T2.2 | `summary_rule_enabled` 配置 | 关闭时二阶段不生效 | `feat(config): toggle - [task-2.3]` |
| T2.4 | T2.1-2.3 | `tests/test_summarizer.py` ≥5 用例 | 全绿 | `test(summarize): suite - [task-2.4]` |
| T3.1 | T2.1 | prompt 摘要化 + summary 输出 + 兼容解析 | 新旧响应解析通过；无 500 字原文 | `feat(ai): summary prompt - [task-3.1]` |
| T3.2 | T1.3+T3.1 | `page_summary` 回写；AI 跳过 local/dead | 分类后 summary 非空；跳过生效 | `feat(ai): persist summary - [task-3.2]` |
| T3.3 | T3.1+T3.2 | `tests/test_ai_prompt.py` ≥4 用例 | 全绿 | `test(ai): suite - [task-3.3]` |
| T4.1 | — | config 新增 2 类 | 规则数增加、新类命中、category_list 含新类 | `feat(config): categories - [task-4.1]` |
| T4.2 | T4.1 | `test_core.py` 追加用例 | 新类命中全绿 | `test(config): cases - [task-4.2]` |
| T5.1 | T1.3 | 表格状态列 | 混合样例显示正确 | `feat(ui): status column - [task-5.1]` |
| T5.2 | T5.1 | 筛选 + 一键删除失效（二次确认） | 筛选与计数同步 | `feat(ui): dead filter - [task-5.2]` |
| T5.3 | T1.3 | 导出复选框 + builder 过滤 | 默认含 local 不含 dead；勾选后可含 dead；validate 通过 | `feat(export): include options - [task-5.3]` |
| T5.4 | T5.1 | 分布树系统桶计数 | 计数与表格一致 | `feat(ui): bucket counts - [task-5.4]` |
| T6.1 | 全部 | 全量回归 | 全部测试文件绿（≥35 用例） | `test: regression - [task-6.1]` |
| T6.2 | T6.1 | README/progress/STATE/memory 同步 | 文档与实现一致 | `docs: sync - [task-6.2]` |

---

## 4. Design Constraints（R9 Anti-Slop 铁律，contract-builder 自动抽取）

- ❌ 禁 Inter 字体（沿用现有 QSS 字体栈）
- ❌ 禁紫色系主色（沿用现有主题令牌，不改色板）
- ❌ 禁 8px 圆角 + 阴影卡片三件套堆砌（沿用现有 objectName/QSS 样式）
- ❌ 禁三栏对称布局
- ✅ 新增控件必须有 hover/active/focus/disabled 四态（QSS 补全）
- ✅ 状态色沿用现有语义：`#16A34A`(正常) / `#DC2626`(失效) / `#94A3B8`(待定)
- ✅ 所有新增 UI 文案中文，与现有一致
- ✅ 四态强制：T5 各界面必须处理 loading / empty / error / forbidden

---

## 5. Scope Fence（Out of Scope，禁止触碰）

- ❌ PARA 项目/领域自动归档
- ❌ Firefox 书签支持 / 自动 JSON 写回浏览器（另开 change）
- ❌ 标签自动生成（A4 二期）
- ❌ DMOZ 其余补类（⚽ 体育等）
- ❌ 重构既有 parser/exporter/review_dialog 的非相关逻辑
- ❌ 修改 `data/` 下既有缓存文件格式之外的数据（探活缓存为新增文件）

---

## 6. 纪律速查（执行时对照）

- **R4**：每个 task 独立 commit，message 含 task ID + change ID + 测试状态
- **R5**：TDD——先写失败测试（RED）→ 最小实现（GREEN）→ 重构（REFACTOR）
- **R6**：能查代码/配置的不得问用户
- **R7**：超出 §5 Scope Fence 的改动需重新生成契约
- **R8**：代码注释随项目现有风格；commit 双语（中文摘要 + 英文 type）
- **R13**：契约产物名称/位置固定（本文件），不另建别名

---

## 7. 门禁标记

```
DP-3（写代码批准）：待批准
批准人：________    日期：________
批准后：STATE.md → approved-for-build / executing，按 §1 顺序执行 T1-T6
```

**未获 DP-3 批准前，禁止进入 S6 实现。**
