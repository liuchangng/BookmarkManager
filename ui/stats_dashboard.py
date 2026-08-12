"""
stats_dashboard.py - 统计仪表盘组件
包含：环形覆盖率图 + 统计数字卡片
"""

import math
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QSizePolicy,
)
from PyQt6.QtCore import Qt, QRect, QRectF
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QFont, QColor, QFontMetrics


class DonutChart(QWidget):
    """环形图组件 - 使用 QPainter 绘制分类覆盖率"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(88, 88)
        self.setMinimumSize(80, 80)
        self.total = 0
        self.classified = 0
        self.deleted = 0

    def set_data(self, total: int, classified: int, deleted: int):
        """设置数据并重绘"""
        self.total = total
        self.classified = classified
        self.deleted = deleted
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 留边
        margin = 2
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        side = min(rect.width(), rect.height())
        cx, cy = rect.center().x(), rect.center().y()
        r = (side - 2) / 2
        pen_width = 14
        inner_r = r - pen_width / 2

        # 定义颜色
        color_classified = QColor("#10B981")   # 绿色 - 已分类
        color_unclassified = QColor("#E2E8F0")  # 浅灰 - 未分类
        color_deleted = QColor("#F87171")       # 红色 - 已删除

        # 计算角度 (-90 度 = 从12点方向开始)
        total_active = self.total
        if total_active == 0:
            # 无数据：画完整的灰色环
            pen = QPen(color_unclassified, pen_width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(QRectF(cx - r + 1, cy - r + 1, 2 * r - 2, 2 * r - 2),
                            90 * 16, 360 * 16)
        else:
            classified_angle = int(360 * self.classified / total_active)
            deleted_angle = int(360 * self.deleted / total_active)

            # 1) 基底：未分类（完整灰环）
            pen = QPen(color_unclassified, pen_width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(QRectF(cx - r + 1, cy - r + 1, 2 * r - 2, 2 * r - 2),
                            90 * 16, 360 * 16)

            # 2) 已分类段（绿色，从12点钟方向顺时针）
            if classified_angle > 0:
                pen = QPen(color_classified, pen_width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawArc(QRectF(cx - r + 1, cy - r + 1, 2 * r - 2, 2 * r - 2),
                                90 * 16, -classified_angle * 16)

            # 3) 已删除段（红色，从12点钟方向逆时针）
            if deleted_angle > 0:
                pen = QPen(color_deleted, pen_width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawArc(QRectF(cx - r + 1, cy - r + 1, 2 * r - 2, 2 * r - 2),
                                90 * 16, deleted_angle * 16)

        # 中心文字：百分比
        pct_text = f"{self.classified / max(self.total, 1) * 100:.0f}%"
        font = QFont()
        font.setPixelSize(16)
        font.setBold(True)
        painter.setFont(font)

        fm = QFontMetrics(font)
        # 颜色：根据覆盖率变化
        if self.total == 0:
            pct_color = QColor("#94A3B8")
        elif self.classified / max(self.total, 1) >= 0.8:
            pct_color = QColor("#059669")
        elif self.classified / max(self.total, 1) >= 0.5:
            pct_color = QColor("#D97706")
        else:
            pct_color = QColor("#DC2626")

        painter.setPen(pct_color)
        painter.drawText(QRectF(cx - r + 6, cy - r + 6, 2 * r - 12, 2 * r - 12),
                         Qt.AlignmentFlag.AlignCenter, pct_text)

        # 小标签：总条数
        font.setPixelSize(9)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor("#94A3B8"))
        subtitle = f"{self.total} 条"
        painter.drawText(QRectF(cx - r + 6, cy + 8, 2 * r - 12, 16),
                         Qt.AlignmentFlag.AlignCenter, subtitle)

        painter.end()


class StatCard(QFrame):
    """单个统计数字卡片"""

    def __init__(self, icon: str, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setMinimumWidth(90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        # 图标 + 数值行
        top_row = QHBoxLayout()
        top_row.setSpacing(4)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"font-size: 14px;")
        top_row.addWidget(icon_lbl)

        self.value_lbl = QLabel("--")
        self.value_lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {color};")
        top_row.addWidget(self.value_lbl)

        self.unit_lbl = QLabel("")
        self.unit_lbl.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {color}; padding-top: 4px;")
        top_row.addWidget(self.unit_lbl)

        top_row.addStretch()
        layout.addLayout(top_row)

        # 标签
        self.label_lbl = QLabel(label)
        self.label_lbl.setStyleSheet("font-size: 11px; font-weight: 500; color: #94A3B8;")
        layout.addWidget(self.label_lbl)

    def set_value(self, value, unit=""):
        self.value_lbl.setText(str(value))
        self.unit_lbl.setText(unit)


class StatsDashboard(QFrame):
    """统计仪表盘 - 包含统计卡片和环形图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statsDashboard")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 左侧：统计卡片行
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(8)

        self.card_total = StatCard("📎", "总书签", "#3B82F6")
        cards_layout.addWidget(self.card_total)

        self.card_classified = StatCard("✅", "已分类", "#10B981")
        cards_layout.addWidget(self.card_classified)

        self.card_fetched = StatCard("📡", "已抓取", "#8B5CF6")
        cards_layout.addWidget(self.card_fetched)

        self.card_ai = StatCard("🤖", "AI处理", "#F59E0B")
        cards_layout.addWidget(self.card_ai)

        cards_layout.addStretch()
        layout.addLayout(cards_layout, 1)

        # 右侧：环形图
        chart_frame = QFrame()
        chart_frame.setObjectName("chartFrame")
        chart_layout = QHBoxLayout(chart_frame)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(4)

        self.donut = DonutChart()
        chart_layout.addWidget(self.donut)

        # 图例
        legend = QVBoxLayout()
        legend.setSpacing(2)
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)

        leg_classified = QLabel("● 已分类")
        leg_classified.setStyleSheet("color: #10B981; font-size: 10px;")
        legend.addWidget(leg_classified)

        leg_deleted = QLabel("● 已删除")
        leg_deleted.setStyleSheet("color: #F87171; font-size: 10px;")
        legend.addWidget(leg_deleted)

        leg_unclassified = QLabel("● 未处理")
        leg_unclassified.setStyleSheet("color: #CBD5E1; font-size: 10px;")
        legend.addWidget(leg_unclassified)

        chart_layout.addLayout(legend)
        layout.addWidget(chart_frame)

        self.setVisible(False)  # 初始隐藏，有数据时显示

    def update_stats(self, total: int, classified: int, fetched: int, ai_count: int, deleted: int):
        """更新所有统计数据"""
        if total == 0:
            self.setVisible(False)
            return

        self.setVisible(True)

        self.card_total.set_value(total)
        self.card_classified.set_value(classified,
                                       f"({classified / max(total, 1) * 100:.0f}%)")
        self.card_fetched.set_value(fetched,
                                    f"({fetched / max(total, 1) * 100:.0f}%)")
        self.card_ai.set_value(ai_count)

        self.donut.set_data(total, classified, deleted)
