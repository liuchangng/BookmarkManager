"""
splash.py - 启动画面
程序启动时显示 2 秒的品牌画面
"""

import sys
from PyQt6.QtWidgets import QSplashScreen, QLabel, QApplication
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QColor, QFont, QPainter, QLinearGradient

class SplashScreen(QSplashScreen):
    """自定义启动画面"""

    def __init__(self):
        # 创建 480x320 的启动图
        pixmap = QPixmap(480, 320)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 渐变背景
        gradient = QLinearGradient(0, 0, 480, 320)
        gradient.setColorAt(0, QColor("#1E3A5F"))
        gradient.setColorAt(0.5, QColor("#2563EB"))
        gradient.setColorAt(1, QColor("#3B82F6"))
        painter.fillRect(0, 0, 480, 320, gradient)

        # 图标区域 (白色书签)
        icon_x, icon_y = 200, 50
        icon_w, icon_h = 80, 100
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QPolygon
        points = [
            QPoint(icon_x, icon_y),
            QPoint(icon_x + icon_w, icon_y),
            QPoint(icon_x + icon_w, icon_y + icon_h - 20),
            QPoint(icon_x + icon_w // 2, icon_y + icon_h),
            QPoint(icon_x, icon_y + icon_h - 20),
        ]
        painter.drawPolygon(QPolygon(points))

        # 装饰线
        painter.setPen(QColor("#FFFFFF"))
        for i, y_off in enumerate([25, 40, 55]):
            lw = 40 - i * 10
            painter.drawLine(
                icon_x + 15, icon_y + y_off,
                icon_x + 15 + lw, icon_y + y_off
            )

        # 文字
        painter.setPen(QColor("#FFFFFF"))
        font = QFont("Microsoft YaHei", 22, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(0, 185, 480, 40, Qt.AlignmentFlag.AlignCenter, "🔖 收藏夹管理工具")

        font2 = QFont("Microsoft YaHei", 11)
        painter.setFont(font2)
        painter.setPen(QColor("#DBEAFE"))
        painter.drawText(0, 225, 480, 30, Qt.AlignmentFlag.AlignCenter, "智能分类 · 井井有条")

        # 版本
        font3 = QFont("Microsoft YaHei", 9)
        painter.setFont(font3)
        painter.setPen(QColor("#93C5FD"))
        painter.drawText(0, 280, 480, 25, Qt.AlignmentFlag.AlignCenter, "v1.0.0 | Loading...")

        painter.end()

        super().__init__(pixmap)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

    def fade_out(self, callback):
        """淡出动画后回调"""
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(500)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade_anim.finished.connect(callback)
        self.fade_anim.start()


# ──────────────────────────────────────────────
#  集成到 main.py 的方式:
#
#  if __name__ == "__main__":
#      app = QApplication(sys.argv)
#
#      # 显示启动画面
#      splash = SplashScreen()
#      splash.show()
#      app.processEvents()
#
#      # 初始化（耗时操作放这里）
#      config = ConfigManager(...)
#      secure = SecureStore(...)
#      proxy = ProxyManager(...)
#
#      # 创建主窗口
#      window = MainWindow(config, secure, proxy)
#
#      # 2秒后淡出启动画面并显示主窗口
#      def show_main():
#          splash.close()
#          window.show()
#
#      QTimer.singleShot(2000, lambda: splash.fade_out(show_main))
#      sys.exit(app.exec())
# ──────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    splash = SplashScreen()
    splash.show()
    QTimer.singleShot(3000, splash.close)
    QTimer.singleShot(3500, app.quit)
    sys.exit(app.exec())
