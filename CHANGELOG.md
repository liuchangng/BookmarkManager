# Changelog

本项目的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-07-24

### ✨ 新增

#### 核心功能
- 🚀 一键导出 Chrome/Edge 书签（毫秒级时间戳命名）
- 🔍 智能解析 Netscape HTML + Chrome/Edge JSON 双格式
- 🏷️ 规则分类引擎（103条规则，88%覆盖率，<30ms/1000条）
- 🌐 三重网页抓取引擎（Scrapling → requests → Firecrawl）
- 🤖 DeepSeek AI 分类（JSON 输出解析 + 重试 + 预算控制）
- 📊 Excel 审核表（颜色编码 + 下拉验证 + 3个Sheet）
- 📁 两级文件夹 HTML 生成（Netscape 标准格式）
- 📥 导入向导对话框（浏览器检测 + 步骤指引 + 备份）

#### 基础设施
- ⚙️ YAML 配置系统（12个分类 + 全部参数可配）
- 🔒 API Key 加密存储（Fernet + 机器指纹）
- 🌍 代理管理（HTTP/HTTPS/SOCKS5 + 系统检测 + 绕过规则 + VPN模式）
- 💾 分类缓存（URL归一化 + 自动过期 + 统计）
- 🎨 全局美化样式（蓝主调 + 圆角卡片 + 状态色）
- ⌨️ 快捷键支持（Ctrl+O/E/C/F/A/S）

#### UI 组件
- 主窗口（步骤导航 + 操作面板 + 预览表 + 日志 + 进度条）
- 设置对话框（代理/AI/抓取/分类/高级 5 Tab）
- 审核对话框（逐条/批量/内嵌详情/筛选）
- 导入向导（浏览器选择/步骤指引/备份/打开导入页）

#### 工程化
- PyInstaller 单文件打包（UPX压缩）
- 一键打包脚本（build.py）
- 版本信息（Windows文件属性）
- 图标生成脚本（PyQt6/PIL双方案）
- 完整测试套件（6个测试文件，268+断言）
- 用户手册（466行，含FAQ）

### 📊 数据

- Python 文件: 27 个
- 代码行数: ~10,500 行
- 测试断言: 268+ 个
- 测试覆盖率: 核心路径 100%
- 可执行文件: ~50MB (UPX压缩后)
- 内存占用: <200MB

### 🔧 技术栈

| 组件 | 技术 |
|---|---|
| GUI | PyQt6 |
| 打包 | PyInstaller + UPX |
| 加密 | cryptography (Fernet) |
| 抓取 | Scrapling + requests |
| AI | DeepSeek API |
| Excel | openpyxl |
| 配置 | PyYAML |
| 代理 | urllib3 + 自定义适配器 |
| 进程检测 | psutil |

### ⚠️ 已知限制

- 仅支持 Chrome/Edge（Firefox 将在 v1.1）
- AI 分类需联网 + API Key
- 抓取强反爬站点可能需要 VPN
- 单文件 exe 启动较慢（解压到临时目录）

### 🔜 后续计划 (v1.1)

- [ ] Firefox 支持
- [ ] 自动 JSON 导入（直接修改浏览器文件）
- [ ] 定时自动备份
- [ ] 多语言（英文界面）
- [ ] 自定义分类体系 GUI 编辑器
- [ ] 深色模式

---

[1.0.0]: https://github.com/example/BookmarkManager/releases/tag/v1.0.0
