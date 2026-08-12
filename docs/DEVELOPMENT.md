# 🔧 开发文档

## 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                      UI Layer (PyQt6)                       │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ MainWindow │  │ SettingsDlg  │  │  ReviewDialog      │    │
│  │ (6步流程)   │  │ (5 Tab)     │  │  (审核/删除/修改)   │    │
│  └─────┬──────┘  └──────┬───────┘  └─────────┬──────────┘    │
│        │                │                      │              │
│  ┌─────┴────────────────┴──────────────────────┴──────────┐    │
│  │              Workers (后台线程)                        │    │
│  │  ExportWorker | ClassifyWorker | FetchWorker | AIWorker │    │
│  └─────┬──────────────────────────────────────────────────┘    │
└────────┼──────────────────────────────────────────────────────┘
         │
┌────────┼──────────────────────────────────────────────────────┐
│        ▼              Engine Layer (modules/)                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐    │
│  │ Exporter │→ │ Parser   │→ │Classifier │→ │  Fetcher   │    │
│  │ (导出)    │  │ (解析)    │  │ (规则)    │  │  (抓取)    │    │
│  └──────────┘  └──────────┘  └────┬─────┘  └─────┬──────┘    │
│                                   │               │           │
│  ┌──────────┐  ┌──────────┐  ┌────▼─────┐  ┌─────▼──────┐    │
│  │HTMLBuilder│  │ExcelWriter│ │AI Client │  │ Cache      │    │
│  │(生成HTML) │  │(审核表)   │ │(DeepSeek)│  │(缓存管理)  │    │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘    │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────────┐      │
│  │Importer  │  │SecureStore│ │  ConfigManager           │      │
│  │(浏览器导入)│  │(加密存储) │ │  (YAML 配置)             │      │
│  └──────────┘  └──────────┘  └──────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

## 数据流

```
Browser Bookmarks
       │
       ▼
  Exporter (JSON → Netscape HTML)
       │
       ▼
  Parser (HTML/JSON → List[Bookmark])
       │
       ▼
  Classifier (规则匹配 → category_l1/l2)
       │
       ▼ (未覆盖的)
  Fetcher (URL → 网页内容)
       │
       ▼
  AI Client (内容 → 智能分类)
       │
       ▼
  Review Dialog / Excel (用户审核)
       │
       ▼
  HTML Builder (审核后 → Netscape HTML)
       │
       ▼
  Importer (引导用户导入浏览器)
```

## 模块依赖关系

```
main.py
  ├── modules/__init__.py
  │     ├── config_manager.py  (无依赖)
  │     ├── secure_store.py    (依赖 cryptography)
  │     ├── proxy.py           (依赖 urllib3/requests)
  │     ├── exporter.py        (依赖 psutil)
  │     ├── parser.py          (无外部依赖)
  │     ├── bookmark.py        (dataclass)
  │     ├── classifier.py      (依赖 config.yaml)
  │     ├── cache.py           (无外部依赖)
  │     ├── fetcher.py         (依赖 scrapling/requests)
  │     ├── fetch_worker.py    (依赖 fetcher)
  │     ├── ai_client.py       (依赖 requests)
  │     ├── ai_worker.py       (依赖 ai_client)
  │     ├── excel_writer.py    (依赖 openpyxl)
  │     ├── html_builder.py    (无外部依赖)
  │     └── importer.py        (依赖 psutil)
  └── ui/
        ├── main_window.py     (依赖所有 modules)
        └── dialogs/
              ├── settings_dialog.py
              ├── review_dialog.py
              └── import_wizard.py
```

## 关键设计决策

### 1. 为什么用 Netscape HTML 而非直接操作 JSON？

- **通用性**：HTML 格式可被所有浏览器导入
- **安全**：不直接修改浏览器文件，避免损坏风险
- **可逆**：导入失败不影响原书签

### 2. 为什么规则 + AI 混合？

- 规则快且免费（88% 覆盖）
- AI 处理长尾（12%），但每条 ~¥0.04
- 缓存避免重复调用同一 URL

### 3. 为什么用 PyQt6 而非 Web 技术？

- 桌面应用，无需跨平台 Web 适配
- 直接操作文件系统/进程
- 打包为单文件 exe

### 4. 配置为什么用 YAML？

- 人类可读可编辑
- 支持注释
- 分类体系天然适合层级结构

## 扩展指南

### 添加新分类规则

编辑 `config.yaml` 的 `categories` 段：

```yaml
categories:
  - name: "🎨 设计创意"
    sub_categories:
      - "设计工具"
      - "灵感素材"
      - "配色方案"
    rules:
      domain:
        - "dribbble.com"
        - "behance.net"
        - "figma.com"
      keyword:
        - "design"
        - "ui/ux"
        - "mockup"
```

### 添加新的抓取引擎

在 `modules/fetcher.py` 中：

```python
def _fetch_with_new_engine(self, url: str) -> FetchResult:
    # 你的实现
    pass

# 在 fetch() 方法中加入调用链
```

### 添加新的 AI 提供商

在 `modules/ai_client.py` 中修改：

```python
# 当前: DeepSeek API
# 扩展: 支持 OpenAI/Claude/Qwen 等
def __init__(self, api_key, provider="deepseek"):
    self.provider = provider
    if provider == "openai":
        self.api_url = "https://api.openai.com/v1/chat/completions"
    elif provider == "deepseek":
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
```

## 测试策略

```
Phase 1: 配置/加密/代理/UI骨架  → 19 断言
Phase 2: 导出/解析              → 29 断言
Phase 3: 规则分类/缓存           → 40 断言
Phase 4: 网页抓取/重试           → 60 断言
Phase 5: AI分类/Excel/审核       → 60 断言
Phase 6: HTML生成/导入           → 60 断言
                                 ───────
总计:                            268+ 断言
```

### 运行测试

```bash
# 单个 Phase
python tests/test_phase1.py

# 全量
for f in tests/test_phase*.py; do
  echo "=== $f ==="
  python "$f"
done

# 带覆盖率
uv add --dev coverage         # 或: uv sync --group dev
uv run coverage run --source=modules main.py
uv run coverage report -m
```

## 打包流程

```bash
# 开发环境
python build.py

# CI/CD (GitHub Actions)
# .github/workflows/build.yml
- uses: actions/setup-python@v4
- run: pip install uv
- run: uv sync --group build
- run: uv run pyinstaller build.spec --clean
- uses: actions/upload-artifact@v3
  with:
    path: dist/
```

## 性能优化建议

| 瓶颈 | 优化方案 |
|---|---|
| 大文件解析慢 | 流式解析 + 增量处理 |
| AI 调用慢 | 并发请求 + 结果缓存 |
| 表格卡顿 | 虚拟滚动 (QTableView + Model) |
| 启动慢 (exe) | 延迟加载非核心模块 |
| 内存占用高 | 及时释放抓取结果 |

## 代码规范

- Python 3.10+ 语法（使用 `list[T]` 等内置泛型）
- 每个模块 ≤ 800 行（超过则拆分）
- 函数 ≤ 50 行
- 类型注解全覆盖
- 日志用 `logging` 模块，不用 `print`
- 异常必须捕获并记录

## 贡献流程

1. Fork 仓库
2. 创建分支 `feature/xxx`
3. 编写代码 + 测试
4. 确保全部测试通过
5. 提交 PR + 描述变更

---

*最后更新: 2026-07-24*
