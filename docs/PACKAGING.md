# 📦 打包清单 - Phase 7

## 交付文件

| 文件 | 用途 |
|---|---|
| `build.py` | 一键打包脚本（安装依赖→生成图标→编译→打包ZIP） |
| `build.spec` | PyInstaller 规格文件（单文件/UPX/隐藏导入/排除） |
| `version_info.txt` | Windows 版本信息（文件属性中显示） |
| `make_icon.py` | 图标生成脚本（PyQt6/PIL 双方案） |
| `requirements.txt` | Python 依赖清单 |

## 打包命令

```bash
# 一键打包（推荐）
python build.py

# 仅编译（不打包ZIP）
pyinstaller build.spec --clean

# 开发模式（不压缩，启动更快）
pyinstaller --onefile --noconsole --debug=all main.py
```

## 输出结构

```
dist/
└── BookmarkManager(.exe)     ← 单文件可执行

BookmarkManager_Portable/      ← 便携版目录
├── BookmarkManager(.exe)     ← 可执行文件
├── config.yaml               ← 配置文件
├── README.txt                ← 快速说明
└── data/
    ├── backups/              ← 书签备份
    ├── cache/                ← 分类缓存
    ├── exports/              ← 导出文件
    └── logs/                 ← 运行日志

BookmarkManager_v1.0.zip       ← 最终交付
```

## 平台适配

| 平台 | 可执行后缀 | 特殊处理 |
|---|---|---|
| Windows | `.exe` | ico图标 + 版本信息 |
| macOS | 无后缀 | icns图标 + 代码签名 |
| Linux | 无后缀 | PNG图标 + AppImage |

## 体积优化

| 策略 | 效果 |
|---|---|
| UPX 压缩 | -40%~50% |
| exclude numpy/pandas | -30MB |
| optimize=2 | -5%~10% |
| 单文件模式 | 无外部依赖 |

## 安全注意事项

- ⚠️ 不要在 exe 中硬编码 API Key
- ✅ API Key 在运行时由用户填入 → 加密存储到本地
- ✅ 网络请求走代理（用户配置）
- ✅ 不收集任何用户数据

---

# 📚 文档清单 - Phase 8

| 文件 | 位置 | 读者 |
|---|---|---|
| README.md | 项目根目录 | 所有用户 |
| USER_MANUAL.md | docs/ | 终端用户 |
| docs/PACKAGING.md | docs/ | 开发者 |
| DEVELOPMENT.md | docs/ | 贡献者 |
| CHANGELOG.md | 项目根目录 | 所有用户 |
| LICENSE | 项目根目录 | 法律 |
