# 🔖 收藏夹管理工具 (BookmarkManager)

> 上传书签 → 自动解析 → 抓取 → AI 分类 → 导出标准书签，全程浏览器操作

---

## ✨ 功能亮点

- **📂 上传即处理** 拖拽浏览器导出的 HTML / Chrome JSON 书签文件，自动开始全流程处理，无需任何手动步骤
- **🤖 全 AI 自动分类** 链接体检（本地/失效分流）→ 网页抓取 → 本地摘要 → AI 自动生成两级分类（DeepSeek），无需维护任何分类/关键词配置
- **🔍 URL 体检分流** 零成本识别本地/内网与失效链接，自动进系统桶（📁 本地/内网、⚠️ 失效链接）
- **📝 本地摘要** 网页摘要提取（description/H1/高频句，零网络）喂给 AI，大幅降低 token 成本
- **📊 实时进度** SSE 推送各阶段进度与日志（体检 → 分类 → 抓取 → 摘要 → AI），全程可见
- **📁 两级分类** 一级大类由 AI 从推荐清单（开发技术/工具软件/购物消费等 16 类）选择，二级小类同主题同名；碎片化小类可一键「合并小分类」归入「其他」
- **🖥️ 单页操作** 上传区 → 进度区 → 结果区纵向一页，审核（改分类/删失效）直接在结果表操作
- **🌐 代理配置** 页面内配置代理（抓取国外资源 / AI API 均可走代理），支持一键测试连通性
- **🔒 安全可靠** API Key 加密存储 / 预算上限兜底 / 导出可排除失效与本地书签

---

## 🚀 快速开始

### 一键启动（推荐）

**Windows**：双击 `start.bat`（或命令行运行 `start.bat`）
**Linux / macOS**：运行 `./start.sh`

脚本自动完成：**uv sync（安装/更新依赖）→ 启动 webapp → 打开浏览器**。若服务已在运行则直接打开浏览器，不会重复启动。

> 注：`start.bat` 为纯 ASCII（英文提示），避免中文编码在控制台解析出错；界面中文由应用自身提供。`start.sh` 为 UTF-8。

### 源码运行

```bash
uv sync
uv run python webapp.py
```

启动后自动打开浏览器 `http://127.0.0.1:8989`（可在 `config.yaml` 的 `web` 段修改端口）。

### 核心流程（3 步）

1. **上传书签文件** — 浏览器中「导出书签」得到 `bookmarks.html`（或 Chrome 的 `Bookmarks` JSON），拖入页面
2. **自动处理** — 系统自动完成：URL 体检（本地/失效分流）→ 网页抓取 → 本地摘要 → AI 自动分类，进度与日志实时推送
3. **导出** — 审核结果（改分类 / 一键删失效）→ 下载标准 Netscape HTML → 浏览器「导入书签」导回

> 分类全程由 AI 自动生成，无需配置任何分类/关键词。未配置 AI Key 时所有书签保持「待分类」，可在结果页手动归类。失效链接默认不写入导出 HTML（可在配置中改为包含），本地/内网书签默认包含。

---

## 📋 系统要求

- 现代浏览器（Chrome / Edge / Firefox 均可）
- Python 3.10+
- 网络访问权限（抓取网页 + AI API）

---

## ⚙️ 配置说明

### 页面内设置（⚙️ 按钮）

- **代理**：启用 → 填地址/端口 → 「🔌 测试代理」验证；可勾选「AI 请求也走代理」（访问国外 AI API 时有用）
- **AI (DeepSeek)**：填入 API Key → 「🔑 测试」验证；可配 Base URL / 模型 / 单次预算上限

### config.yaml

| 段 | 说明 |
|---|---|
| `web` | 服务地址/端口/是否自动开浏览器（默认 `127.0.0.1:8989`） |
| `proxy` | 代理设置（enabled / custom / use_for / bypass_domains） |
| `ai` | DeepSeek 配置（model / base_url / max_cost_yuan 预算上限） |
| `fetch` | 抓取引擎（scrapling / timeout / concurrency） |
| `probe` | 探活配置（timeout 10s / max_fail_confirm 3 次，防网络抖动误判失效） |
| `output` | 导出默认值（`export_include_dead: false`、`export_include_local: true`） |
| `categories` | 空数组 — 分类由 AI 自动生成 |

---

## 📁 项目结构

```
BookmarkManager/
├── webapp.py                   # Web 入口 (FastAPI + SSE + 静态服务)
├── start.bat / start.sh        # 一键启动（uv sync + 启动 + 开浏览器）
├── config.yaml                 # 配置（代理/AI/抓取/导出/Web）
├── pyproject.toml / uv.lock    # 依赖 (uv)
├── design.md / tasks.md / execution-contract.md   # 设计文档
├── STATE.md / progress.md / memory-store.md       # 工作流状态
├── modules/                    # 核心引擎（纯 Python，零 GUI 依赖）
│   ├── pipeline.py             #   流水线编排（解析→体检→分类→抓取→摘要→AI）
│   ├── config_manager.py       #   配置管理
│   ├── secure_store.py         #   API Key 加密存储
│   ├── proxy.py                #   代理管理
│   ├── parser.py               #   解析 HTML/JSON 书签
│   ├── bookmark.py             #   数据结构
│   ├── classifier.py           #   分类器（规则为空，全部交 AI）
│   ├── cache.py                #   分类缓存
│   ├── link_probe.py           #   URL 体检（本地/失效三态）
│   ├── summarizer.py           #   本地摘要提取（零网络）
│   ├── fetcher.py              #   网页抓取 (3 引擎兜底)
│   ├── ai_client.py            #   DeepSeek API（摘要化 prompt）
│   └── html_builder.py         #   HTML 生成器（失效/本地过滤）
├── web/static/                 # 单页前端（原生 JS，零构建）
│   ├── index.html              #   页面结构（上传/进度/结果/设置）
│   ├── style.css               #   Indigo 设计系统
│   └── app.js                  #   逻辑（SSE 进度 / 审核 / 导出 / 设置）
├── tests/                      # 测试 (7 个文件, 78 项用例)
│   ├── test_core.py            #   核心链路（解析/分类/HTML）
│   ├── test_probe.py           #   URL 体检
│   ├── test_summarizer.py      #   本地摘要 + 二阶段规则
│   ├── test_ai_prompt.py       #   AI prompt 摘要化/解析
│   ├── test_export_options.py  #   导出包含选项 + 筛选/状态文案
│   ├── test_pipeline.py        #   纯 Python 流水线编排
│   └── test_web.py             #   Web API（TestClient，13 端点）
├── docs/                       # 历史文档
└── data/                       # 运行时数据（自动创建：uploads/exports/cache/logs）
```

---

## 📊 性能数据

| 指标 | 数值 |
|---|---|
| 1000 条书签解析 | < 1 秒 |
| AI 自动分类 | 标题+摘要输入（≤300 字），每条约 ¥0.01-0.04，预算上限可配 |
| URL 体检 1000 条 | 并发探活（HEAD 优先），失败连续 2 次才判失效（防误判） |
| AI 分类单条 | ~1.5 秒 (含网络) |
| 内存占用 | < 200MB |

---

## 🔧 开发

### 运行测试

```bash
# 全量测试（pytest）
uv run pytest -q tests/

# 或逐文件直接运行（无需 pytest）
PYTHONIOENCODING=utf-8 uv run python tests/test_core.py
PYTHONIOENCODING=utf-8 uv run python tests/test_web.py
```

### 运行服务

```bash
uv run python webapp.py
# → http://127.0.0.1:8989
```

---

## 📝 更新日志

### v1.0 (2026-07-24)

- ✅ 完整 6 步工作流（桌面版，已废弃）
- ✅ Chrome/Edge 导出解析 / 规则分类 / 网页抓取 / AI 分类 / Excel 审核 / HTML 生成
- ✅ 268+ 测试断言全部通过

### v1.1 (智能分类优化)

- ✅ 手动导入书签文件（HTML/JSON，自动去重）
- ✅ T1 URL 体检器：本地/内网判定 + 并发探活（HEAD 优先、404 一次即失效、连续 2 次防误判）+ 7 天缓存
- ✅ T2 本地摘要 + 二阶段规则（摘要关键词二次归类，命中即免 AI）
- ✅ T3 AI prompt 摘要化（输入改为摘要，token 大降；摘要回写）
- ✅ T4 分类体系扩充至 14 大类、310+ 规则
- ✅ T5 UI：状态列 / 失效筛选 / 一键删除 / 导出包含选项

### v1.2 (方案 A：全 AI 自动分类)

- ✅ 移除分类配置文件，AI 自由生成两级分类（全程自动化）
- ✅ 分类/AI 缓存版本升级，旧规则标签作废

### v1.3 / v1.4 (UI 美化)

- ✅ 按钮体系统一、四态补全、焦点环（桌面版，已废弃）
- ✅ Indigo 现代科技色板 + WCAG 对比度全达标（桌面版，已废弃）

### v2.0 (Web 化重构)

- ✅ **全新 Web 界面**（FastAPI + 原生 JS 单页），替代 PyQt6 桌面版
- ✅ **操作简化**：上传 → 自动处理（SSE 实时进度）→ 结果 → 导出，全程一页
- ✅ **审核内嵌**：结果页直接改分类 / 一键删失效，不设独立审核步骤
- ✅ **页面内设置**：代理（含测试连通性、AI 走代理）、AI Key / 模型 / 预算上限
- ✅ **纯 Python 流水线**：`modules/pipeline.py` 无 GUI 依赖，桌面 worker 全部移除
- ✅ 测试 78 项全绿（新增 pipeline 8 项 + web API 13 项）

---

## 📄 License

MIT License

---

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [Scrapling](https://github.com/D4Vinci/Scrapling) - 网页抓取
- [DeepSeek](https://deepseek.com/) - AI 分类能力
- [uv](https://github.com/astral-sh/uv) - Python 包管理器

---

*Made with ❤️ for bookmark hoarders everywhere*
