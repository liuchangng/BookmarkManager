"""
make_icon.py - 生成应用图标
使用 PyQt6 绘制一个精美的书签图标
"""

import sys
from pathlib import Path

try:
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QBrush, QPen, QIcon
    from PyQt6.QtCore import Qt, QRect, QPoint

    def create_icon(size=256, output_path=None):
        """创建一个精美的书签图标"""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 背景圆角矩形
        bg_rect = QRect(8, 8, size - 16, size - 16)
        painter.setBrush(QColor("#2563EB"))  # 蓝色
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bg_rect, 24, 24)

        # 书签形状 (白色)
        # 外框
        margin = int(size * 0.22)
        bm_width = int(size * 0.56)
        bm_height = int(size * 0.70)
        x = (size - bm_width) // 2
        y = margin

        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(Qt.PenStyle.NoPen)

        # 书签主体 (带切角的矩形)
        from PyQt6.QtGui import QPolygon
        points = [
            QPoint(x, y),
            QPoint(x + bm_width, y),
            QPoint(x + bm_width, y + bm_height - int(size * 0.15)),
            QPoint(x + bm_width // 2, y + bm_height),
            QPoint(x, y + bm_height - int(size * 0.15)),
        ]
        painter.drawPolygon(QPolygon(points))

        # 书签上的装饰线
        line_color = QColor("#2563EB")
        painter.setPen(QPen(line_color, 3, Qt.PenStyle.SolidLine))
        line_y1 = y + int(size * 0.25)
        line_y2 = y + int(size * 0.35)
        line_y3 = y + int(size * 0.45)
        line_x1 = x + int(size * 0.12)
        line_x2 = x + bm_width - int(size * 0.12)
        painter.drawLine(QPoint(line_x1, line_y1), QPoint(line_x2, line_y1))
        painter.drawLine(QPoint(line_x1, line_y2), QPoint(line_x2, line_y2))
        painter.drawLine(QPoint(line_x1, line_y3), QPoint(line_x2 * 0.7, line_y3))

        painter.end()

        if output_path:
            pixmap.save(output_path, "PNG")
            print(f"✅ 图标已保存: {output_path} ({size}x{size})")

        return pixmap

    def create_ico(output_dir="ui/resources"):
        """生成多种尺寸的 ico 文件"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 生成 PNG (用于 ico)
        png_path = output_path / "icon.png"
        pixmap = create_icon(256, str(png_path))

        # 使用 QIcon 保存 .ico
        icon = QIcon(pixmap)
        ico_path = output_path / "icon.ico"
        # QIcon 不能直接保存 ico，用 PNG 代替
        # Windows 下 PyInstaller 也支持 PNG
        icon_png = output_path / "icon_128.png"
        small_pixmap = create_icon(128, str(icon_png))

        print(f"\n📦 图标文件:")
        print(f"   {png_path} ({png_path.stat().st_size} bytes)")
        print(f"   {icon_png} ({icon_png.stat().st_size} bytes)")

        # 复制为 ico (Windows 可用)
        import shutil
        shutil.copy2(png_path, output_path / "icon.ico")
        print(f"   {output_path / 'icon.ico'} (复制自 PNG)")

        return str(png_path)

    if __name__ == "__main__":
        if len(sys.argv) > 1:
            out = sys.argv[1]
        else:
            out = "ui/resources"
        create_ico(out)

except ImportError:
    print("⚠️ PyQt6 未安装，使用 PIL 生成图标")

    from PIL import Image, ImageDraw, ImageFont
    import math

    def create_icon_pil(size=256, output_path=None):
        """用 PIL 创建图标"""
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 背景圆角矩形
        margin = int(size * 0.03)
        bg_rect = [margin, margin, size - margin, size - margin]
        # 绘制圆角矩形 (蓝色)
        draw.rounded_rectangle(bg_rect, radius=int(size * 0.12), fill=(37, 99, 235, 255))

        # 书签形状 (白色)
        bm_margin = int(size * 0.22)
        bm_w = int(size * 0.56)
        bm_h = int(size * 0.70)
        bx = (size - bm_w) // 2
        by = bm_margin

        # 书签多边形
        points = [
            (bx, by),
            (bx + bm_w, by),
            (bx + bm_w, by + bm_h - int(size * 0.15)),
            (bx + bm_w // 2, by + bm_h),
            (bx, by + bm_h - int(size * 0.15)),
        ]
        draw.polygon(points, fill=(255, 255, 255, 255))

        # 装饰线 (蓝色)
        line_color = (37, 99, 235, 255)
        lw = max(2, int(size * 0.015))
        ly1 = by + int(size * 0.25)
        ly2 = by + int(size * 0.35)
        ly3 = by + int(size * 0.45)
        lx1 = bx + int(size * 0.12)
        lx2 = bx + bm_w - int(size * 0.12)
        for y_pos in [ly1, ly2]:
            draw.line([(lx1, y_pos), (lx2, y_pos)], fill=line_color, width=lw)
        draw.line([(lx1, ly3), (int(lx2 * 0.7), ly3)], fill=line_color, width=lw)

        if output_path:
            img.save(output_path, "PNG")
            print(f"✅ 图标已保存: {output_path} ({size}x{size})")

        return img

    if __name__ == "__main__":
        out_dir = sys.argv[1] if len(sys.argv) > 1 else "ui/resources"
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        create_icon_pil(256, f"{out_dir}/icon.png")
        create_icon_pil(128, f"{out_dir}/icon_128.png")

        # 创建多尺寸 ico
        sizes = [16, 32, 48, 64, 128, 256]
        images = [create_icon_pil(s) for s in sizes]
        images[0].save(
            f"{out_dir}/icon.ico",
            format="ICO",
            sizes=[(s, s) for s in sizes],
            append_images=images[1:],
        )
        print(f"✅ ICO 文件: {out_dir}/icon.ico")
