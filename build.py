"""
build.py - 一键打包脚本
功能: 安装依赖 → 生成图标 → 运行 PyInstaller → 输出可执行文件
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
OUTPUT_NAME = "BookmarkManager"

# ──────────────────────────────────────────────
#  颜色输出
# ──────────────────────────────────────────────

class C:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"

def info(msg): print(f"{C.BLUE}ℹ️  {msg}{C.END}")
def ok(msg): print(f"{C.GREEN}✅ {msg}{C.END}")
def warn(msg): print(f"{C.YELLOW}⚠️  {msg}{C.END}")
def err(msg): print(f"{C.RED}❌ {msg}{C.END}")
def step(msg): print(f"\n{C.BOLD}{'─'*60}\n  {msg}\n{'─'*60}{C.END}")

# ──────────────────────────────────────────────
#  步骤
# ──────────────────────────────────────────────

def step1_check_environment():
    """检查 Python 版本"""
    step("步骤 1: 检查环境")
    ver = sys.version_info
    info(f"Python: {ver.major}.{ver.minor}.{ver.micro}")

    if ver < (3, 10):
        err(f"需要 Python 3.10+，当前 {ver.major}.{ver.minor}")
        sys.exit(1)

    # 检查 PyInstaller
    try:
        import PyInstaller
        ok(f"PyInstaller: {PyInstaller.__version__}")
    except ImportError:
        warn("PyInstaller 未安装，正在安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        ok("PyInstaller 安装完成")

def step2_install_deps():
    """使用 uv 安装依赖"""
    step("步骤 2: 安装依赖")
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        info("使用 uv 同步依赖 (生产 + 构建)...")
        subprocess.run(["uv", "sync", "--group", "build"], cwd=str(PROJECT_ROOT), check=True)
        ok("依赖安装完成")
    else:
        warn(f"未找到 pyproject.toml: {pyproject}")
        # 降级: 尝试 requirements.txt
        req = PROJECT_ROOT / "requirements.txt"
        if req.exists():
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)], check=True)
            ok("依赖安装完成 (fallback pip)")

def step3_generate_icon():
    """生成图标"""
    step("步骤 3: 生成图标")
    icon_script = PROJECT_ROOT / "make_icon.py"
    icon_dir = PROJECT_ROOT / "ui" / "resources"

    if not icon_dir.exists():
        icon_dir.mkdir(parents=True, exist_ok=True)

    # 检查是否已有图标
    ico_path = icon_dir / "icon.ico"
    png_path = icon_dir / "icon.png"

    if ico_path.exists() and png_path.exists():
        ok(f"图标已存在: {ico_path}")
        return

    # 运行生成脚本
    try:
        subprocess.run([sys.executable, str(icon_script), str(icon_dir)], check=True)
        ok("图标生成完成")
    except subprocess.CalledProcessError:
        warn("图标生成失败，使用默认图标继续")
        # 创建一个简单的占位图标
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (256, 256), (37, 99, 235, 255))
            draw = ImageDraw.Draw(img)
            draw.text((80, 100), "BM", fill="white")
            img.save(png_path, "PNG")
            img.save(ico_path, "ICO")
            ok("占位图标已创建")
        except ImportError:
            err("无法创建图标，请安装 Pillow")

def step4_clean():
    """清理旧的构建产物"""
    step("步骤 4: 清理旧构建")
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            shutil.rmtree(d)
            info(f"已删除: {d}")

    # 删除 spec 生成的文件
    for p in PROJECT_ROOT.glob("*.spec"):
        if p.name != "build.spec":
            p.unlink()
            info(f"已删除: {p}")

    ok("清理完成")

def step5_build():
    """运行 PyInstaller"""
    step("步骤 5: 编译打包")
    spec = PROJECT_ROOT / "build.spec"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec),
    ]

    info("开始编译 (这可能需要几分钟)...")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        err("PyInstaller 编译失败")
        sys.exit(1)

    ok("编译完成")

def step6_verify():
    """验证输出"""
    step("步骤 6: 验证输出")

    exe_path = DIST_DIR / OUTPUT_NAME
    if sys.platform == "win32":
        exe_path = exe_path.with_suffix(".exe")

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        ok(f"可执行文件: {exe_path}")
        ok(f"文件大小: {size_mb:.1f} MB")
    else:
        # 检查 dist 目录
        if DIST_DIR.exists():
            files = list(DIST_DIR.iterdir())
            info(f"dist 目录内容: {[f.name for f in files]}")
        err(f"未找到输出文件: {exe_path}")
        return False

    return True

def step7_create_portable():
    """创建便携版目录结构"""
    step("步骤 7: 创建便携版目录")

    portable_dir = PROJECT_ROOT / "BookmarkManager_Portable"
    if portable_dir.exists():
        shutil.rmtree(portable_dir)

    portable_dir.mkdir()

    # 复制可执行文件
    exe_src = DIST_DIR / OUTPUT_NAME
    if sys.platform == "win32":
        exe_src = exe_src.with_suffix(".exe")
    shutil.copy2(exe_src, portable_dir / exe_src.name)

    # 创建目录结构
    (portable_dir / "data" / "backups").mkdir(parents=True)
    (portable_dir / "data" / "cache").mkdir(parents=True)
    (portable_dir / "data" / "exports").mkdir(parents=True)
    (portable_dir / "data" / "logs").mkdir(parents=True)

    # 复制配置
    shutil.copy2(PROJECT_ROOT / "config.yaml", portable_dir / "config.yaml")

    # 复制说明
    readme = portable_dir / "README.txt"
    readme.write_text(
        "🔖 收藏夹管理工具 - 便携版\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "使用方法:\n"
        "1. 双击 BookmarkManager 启动程序\n"
        "2. 选择浏览器 → 点击「开始导出并解析」\n"
        "3. 等待自动分类完成\n"
        "4. 审核确认 → 生成 HTML → 导入浏览器\n\n"
        "数据目录:\n"
        "  data/backups  - 原书签备份\n"
        "  data/cache    - 分类缓存\n"
        "  data/exports  - 导出的 HTML\n"
        "  data/logs     - 运行日志\n\n"
        "更多帮助请查看完整文档。\n",
        encoding="utf-8",
    )

    ok(f"便携版目录: {portable_dir}")

    # 统计
    total_size = sum(f.stat().st_size for f in portable_dir.rglob("*") if f.is_file())
    info(f"总大小: {total_size / (1024*1024):.1f} MB")

def step8_create_zip():
    """打包为 zip"""
    step("步骤 8: 打包 ZIP")

    import zipfile

    portable_dir = PROJECT_ROOT / "BookmarkManager_Portable"
    zip_path = PROJECT_ROOT / "BookmarkManager_v1.0.zip"

    if not portable_dir.exists():
        warn("便携版目录不存在，跳过")
        return

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in portable_dir.rglob("*"):
            if f.is_file():
                arcname = f.relative_to(PROJECT_ROOT)
                zf.write(f, arcname)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    ok(f"ZIP 文件: {zip_path} ({size_mb:.1f} MB)")

# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

def main():
    print(f"\n{C.BOLD}{C.BLUE}")
    print("╔════════════════════════════════════════════╗")
    print("║   🔖 收藏夹管理工具 - 打包脚本 v1.0       ║")
    print("╚════════════════════════════════════════════╝")
    print(f"{C.END}\n")

    start = __import__("time").time()

    step1_check_environment()
    step2_install_deps()
    step3_generate_icon()
    step4_clean()
    step5_build()

    if step6_verify():
        step7_create_portable()
        step8_create_zip()

        elapsed = __import__("time").time() - start
        print(f"\n{C.GREEN}{C.BOLD}{'═'*60}")
        print(f"  🎉 打包完成! 耗时: {elapsed:.0f}秒")
        print(f"{'═'*60}{C.END}\n")

        print("输出文件:")
        zip_path = PROJECT_ROOT / "BookmarkManager_v1.0.zip"
        if zip_path.exists():
            print(f"  📦 {zip_path} (便携版ZIP)")
        portable = PROJECT_ROOT / "BookmarkManager_Portable"
        if portable.exists():
            print(f"  📁 {portable} (便携版目录)")
        exe = DIST_DIR / OUTPUT_NAME
        if sys.platform == "win32":
            exe = exe.with_suffix(".exe")
        if exe.exists():
            print(f"  ⚙️  {exe} (可执行文件)")
    else:
        err("打包失败，请检查错误信息")

if __name__ == "__main__":
    main()
