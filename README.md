# 🔖 收藏夹管理工具 (BookmarkManager)

> 智能分类你的浏览器收藏夹，让 1000+ 书签井井有条

---

## ✨ 功能亮点

- **📂 手动导入书签文件** 直接选择浏览器导出的 HTML/JSON 文件解析，无需关闭浏览器（核心功能）
- **🚀 一键导出** Chrome/Edge 书签，毫秒级时间戳命名
- **🔍 URL 体检分流** 零成本识别本地/内网与失效链接，失效/本地自动进系统桶（📁 本地/内网、⚠️ 失效链接），不干扰规则引擎
- **🤖 全 AI 自动分类** URL 体检（本地/失效分流）→ AI 自动生成两级分类（DeepSeek），无需维护任何分类/关键词配置
- **📝 本地摘要** 网页摘要提取（description/H1/高频句，零网络）喂给 AI，大幅降低 token 成本
- **🌐 三重抓取引擎** Scrapling + requests + Firecrawl 兜底
- **📊 可视化审核** 颜色编码 + Excel 导出 + 内置对话框 + 失效链接筛选/一键删除
- **📁 两级分类** 一级大类 × 二级小类由 AI 按内容自动生成（一致性命名），标准 Netscape HTML 输出
- **📥 导入向导** 引导式导入 Chrome/Edge，含自动备份，导出可勾选包含失效/本地书签
- **🔒 安全可靠** API Key 加密存储 / 代理支持 / 原书签备份

---

## 📸 界面预览

```
┌─────────────────────────────────────────────────────────┐
│  🔖 收藏夹管理工具 v1.0                     ⚙ 设置 🔒 锁定 │
├─────────────────────────────────────────────────────────┤
│  [①导入解析]→[②URL体检]→[③AI分类]→[④审核]→[⑤⑥]  │
├─────────────────────────────────────────────────────────┤
│  📂 Chrome | Profile: [Default ▼]  🚀 开始导出并解析    │
│  📊 已解析: 1024 条 | 🏷️ 已分类: 901 | ⏳ 待AI: 123    │
├─────────────────────────────────────────────────────────┤
│  ┌─ 书签预览 ─────────────────┐  ┌─ 分类分布 ────────┐  │
│  │ #  Title       Domain     │  │ 💻 开发技术 (45)  │  │
│  │ 1  GitHub      github.com │  │   ├ 代码托管 (20)  │  │
│  │ 2  MDN         mozilla.. │  │   └ 文档教程 (25)  │  │
│  │ 3  淘宝         taobao.. │  │ 🛒 购物消费 (30)  │  │
│  │ ...                      │  │ 📚 学习知识 (80)  │  │
│  └──────────────────────────┘  └───────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  📈 ████████████████░░░░░░░░░░  进度: 分类中...        │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 方式一：下载便携版

1. 下载 `BookmarkManager_v1.0.zip`
2. 解压 → 双击 `BookmarkManager.exe`

### 方式二：源码运行

```bash
uv sync
uv run python main.py
```

### 快速上手（核心流程）

1. 浏览器中导出书签 → 得到 `bookmarks.html`（或 Chrome/Edge 的 `Bookmarks` JSON）
2. 打开本工具，点击 **📂 导入书签文件** 选择该文件
3. 自动解析 → **URL 体检**（本地/失效分流）→ **AI 自动分类**（自动生成一级大类 + 二级小类）→ 审核 → 生成分类后的 HTML
4. 用浏览器的「导入书签」功能把分类后的 HTML 导回浏览器

> 分类全程由 AI 自动生成，无需配置任何分类/关键词。未配置 AI Key 时所有书签保持「待分类」，可人工审核归类。失效链接默认不写入导出 HTML（可在导出对话框中勾选包含），本地/内网书签默认包含。

---

## 📋 系统要求

- Windows 10+ / macOS 12+ / Linux (Ubuntu 20.04+)
- Chrome 90+ 或 Edge 90+
- Python 3.10+（仅源码版需要）
- 网络访问权限（抓取网页 + AI API）

---

## ⚙️ 配置说明

### 代理

设置 → 代理 → 启用 → 填入地址（如 `http://127.0.0.1:7890`）

### AI (DeepSeek)

1. 获取 Key: https://platform.deepseek.com/
2. 设置 → AI → 填入 Key
3. 点「🔑 测试」验证

---

## 📁 项目结构

```
BookmarkManager/
├── main.py                     # 入口
├── config.yaml                 # 配置（分类体系 + 全部参数）
├── build.py                    # 打包脚本
├── build.spec                  # PyInstaller 配置
├── make_icon.py                # 图标生成
├── version_info.txt            # Windows 版本信息
├── pyproject.toml              # Python 项目配置 & 依赖
├── uv.lock                     # 依赖锁定文件 (uv)
├── .python-version             # Python 版本 (uv 管理)
├── zip_exclude.txt             # ZIP 打包排除规则
├── design.md                   # 智能分类设计方案（A3/B3/C1）
├── tasks.md                    # 任务拆解 T1-T6
├── execution-contract.md       # 执行契约（S5 接口签名/验收）
├── STATE.md / progress.md / memory-store.md   # 工作流状态
├── modules/                    # 核心引擎 (18 个模块)
│   ├── config_manager.py       #   配置管理
│   ├── secure_store.py         #   API Key 加密
│   ├── proxy.py                #   代理管理
│   ├── exporter.py             #   导出浏览器书签
│   ├── parser.py               #   解析 HTML/JSON
│   ├── bookmark.py             #   数据结构
│   ├── classifier.py           #   分类器（方案 A 下规则为空，全部交 AI）
│   ├── classify_worker.py      #   后台分类线程
│   ├── cache.py                #   分类缓存
│   ├── link_probe.py           #   URL 体检（本地/失效三态）
│   ├── summarizer.py           #   本地摘要提取（零网络）
│   ├── fetcher.py              #   网页抓取 (3引擎)
│   ├── fetch_worker.py         #   后台抓取线程
│   ├── ai_client.py            #   DeepSeek API（摘要化 prompt）
│   ├── ai_worker.py            #   后台 AI 线程
│   ├── excel_writer.py         #   Excel 审核表
│   ├── html_builder.py         #   HTML 生成器（失效/本地过滤）
│   └── importer.py             #   浏览器导入
├── ui/                         # 界面 (5 个模块)
│   ├── main_window.py          #   主窗口
│   ├── splash.py               #   启动画面
│   ├── dialogs/
│   │   ├── settings_dialog.py  #   设置对话框
│   │   ├── review_dialog.py    #   审核对话框
│   │   └── import_wizard.py    #   导入向导
│   └── resources/
│       └── styles.qss          #   全局样式
├── tests/                      # 测试 (5 个文件, 57 项用例)
│   ├── test_core.py            #   核心链路（解析/分类/HTML）
│   ├── test_probe.py           #   URL 体检（本地判定/三态/缓存/防误判）
│   ├── test_summarizer.py      #   本地摘要 + 二阶段规则
│   ├── test_ai_prompt.py       #   AI prompt 摘要化/解析
│   └── test_export_options.py  #   导出包含选项（失效/本地过滤）
├── docs/                       # 文档
│   ├── USER_MANUAL.md          #   用户手册
│   ├── DEVELOPMENT.md          #   开发文档
│   ├── PACKAGING.md            #   打包说明
│   ├── QUICKSTART.txt          #   快速入门
│   ├── PHASE3.md               #   阶段开发报告
│   ├── PHASE4.md               #   阶段开发报告
│   ├── PHASE5.md               #   阶段开发报告
│   └── PHASE7_8.md             #   阶段开发报告
└── data/                       # 运行时数据（自动创建）
    ├── backups/                #   原书签备份
    ├── cache/                  #   分类缓存
    ├── exports/                #   导出文件
    └── logs/                   #   运行日志
```

---

## 📊 性能数据

| 指标 | 数值 |
|---|---|
| 1000 条书签解析 | < 1 秒 |
| AI 自动分类 | 标题+摘要输入（≤300 字），每条约 ¥0.01-0.04，预算上限可配 |
| URL 体检 1000 条 | 并发探活（HEAD 优先），失败连续 2 次才判失效（防误判） |
| AI 分类单条 | ~1.5 秒 (含网络) |
| AI 单条成本 | ≤¥0.04（T3 摘要化后输入 token 大幅下降） |
| 内存占用 | < 200MB |
| 可执行文件大小 | ~50MB (UPX压缩后) |

---

## 🔧 开发

### 运行测试

```bash
# 全量测试（pytest）
uv run pytest -q tests/

# 或逐文件直接运行（无需 pytest）
PYTHONIOENCODING=utf-8 uv run python tests/test_core.py
PYTHONIOENCODING=utf-8 uv run python tests/test_probe.py
PYTHONIOENCODING=utf-8 uv run python tests/test_summarizer.py
PYTHONIOENCODING=utf-8 uv run python tests/test_ai_prompt.py
PYTHONIOENCODING=utf-8 uv run python tests/test_export_options.py
```

### 打包为 exe

```bash
uv run python build.py
# 输出: BookmarkManager_v1.0.zip (便携版)
```

---

## 📝 更新日志

### v1.0 (2026-07-24)

- ✅ 完整 6 步工作流
- ✅ Chrome/Edge 导出解析
- ✅ 规则分类 (103条规则, 88%覆盖)
- ✅ 网页抓取 (Scrapling + requests + Firecrawl)
- ✅ AI 分类 (DeepSeek)
- ✅ Excel 审核表 + 内置审核对话框
- ✅ HTML 生成 + 导入向导
- ✅ 代理支持 + VPN 模式
- ✅ API Key 加密存储
- ✅ 268+ 测试断言全部通过

### v1.1 (优化)

- ✅ **手动导入书签文件**（HTML/JSON，免关闭浏览器，含自动去重）
- ✅ **二级智能分类**：小类专属关键词（`sub_keywords`），L2 更精确（如 MDN→文档教程、YouTube→在线视频）
- ✅ 域规则匹配子域名（github.com 命中 gist.github.com）
- ✅ 解析器容错：BOM / HTML 实体（`html.unescape`）/ JSON 错误友好提示
- ✅ HTML 生成：跳过空根目录、「其他」保持两级结构（📁 其他/待分类）
- ✅ **T1 URL 体检器**（`link_probe.py`）：本地/内网判定（file/localhost/私网IP/UNC 等）+ 并发探活（HEAD 优先、404 一次即失效、网络错误连续 2 次防误判）+ 7 天缓存；失效/本地自动进系统桶（📁 本地/内网、⚠️ 失效链接），不干扰规则引擎
- ✅ **T2 本地摘要 + 二阶段规则**（`summarizer.py`）：网页摘要提取（description/H1/高频句，≤200 字，零网络）→ 摘要关键词二次归类（`summary_rule`，可配置开关），命中即免 AI 调用
- ✅ **T3 AI prompt 摘要化**：AI 输入改为页面摘要（不再塞 500 字原文，token 大降）；输出回写 `page_summary`；AI 跳过本地/失效/摘要已归类书签
- ✅ **T4 分类体系扩充**：新增「📖 参考工具」「🏠 居家生活」两类 → 14 大类、310+ 规则
- ✅ **T5 UI**：预览表状态列（✅正常/⚠️失效/📁本地/🕐待定）、失效链接筛选 + 一键删除（二次确认）、导出对话框「包含失效链接/包含本地」复选框、分布树系统桶计数
- ✅ 核心链路测试 57 项全部通过（core/probe/summarizer/ai_prompt/export_options）

### v1.2 (方案 A：全 AI 自动分类)

- ✅ **移除分类配置文件**：`categories` 清空、移除 `classify_rules` 与规则相关设置（rule_enabled / rule_confidence_threshold / summary_rule_enabled）
- ✅ **AI 自由生成两级分类**：prompt 空配置分支（一致性命名、禁 emoji），AI 标签直接采用（清洗 emoji、空值兜底）
- ✅ **全程自动化**：规则阶段退化为空操作，所有书签 → 抓取摘要 → AI；分类/AI 缓存版本升级（旧规则标签作废）
- ✅ **UI 适配**：设置页移除规则组、分类预览改「AI 自动生成」；审核/Excel 从已有书签推导分类选项；classifier 不再覆盖本地/失效系统桶
- ✅ 测试 57 项全绿（规则用例改为方案 A 语义 + 新增自由模式用例）

### 计划中 (v1.1)

- [ ] Firefox 支持
- [ ] 自动 JSON 导入（直接修改浏览器文件）
- [ ] 定时自动备份
- [ ] 多语言（英文界面）
- [ ] 自定义分类体系（GUI 编辑）

---

## 📄 License

MIT License

---

## 🙏 致谢

- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - GUI 框架
- [Scrapling](https://github.com/D4Vinci/Scrapling) - 网页抓取
- [DeepSeek](https://deepseek.com/) - AI 分类能力
- [PyInstaller](https://pyinstaller.org/) - 打包工具
- [uv](https://github.com/astral-sh/uv) - Python 包管理器
- [openpyxl](https://openpyxl.readthedocs.io/) - Excel 处理

---

*Made with ❤️ for bookmark hoarders everywhere*
