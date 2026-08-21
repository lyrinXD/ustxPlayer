import weakref

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QGraphicsDropShadowEffect
from qfluentwidgets import SimpleCardWidget, StrongBodyLabel, isDarkTheme
from qfluentwidgets.common.config import qconfig
from qfluentwidgets.common.style_sheet import themeColor


# 导航页统一的页面外边距与卡片间距（所有页面共用，保证跨页观感一致）
PAGE_MARGIN = (24, 20, 24, 20)
PAGE_SPACING = 10


class _AccentBar(QWidget):
    """强调色圆角竖线（参考 qfluentwidgets NavigationIndicator 的绘制参数）。

    3×16px、1.5px 圆角、颜色跟随 themeColor()。
    与导航栏选中项左侧竖线视觉一致。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(3, 16)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, e: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(themeColor())
        painter.drawRoundedRect(QRectF(self.rect()), 1.5, 1.5)


class AccentHeaderCardWidget(SimpleCardWidget):
    """带强调色圆角竖线标题的 SimpleCardWidget。

    - title 不为空：显示紧凑标题行（竖线+文字，无横线）
    - title 为空：纯内容卡片（供无标题场景如 bottom_card/彩蛋/多轨选择）
    - Hover 时边框变强调色半透明（alpha=64）
    - 阴影：原生 QGraphicsDropShadowEffect（blur 16 / offset (0,2) / 浅色 alpha 34，深色 0 不投影）

    阴影支持全局开关（set_global_shadow）与单卡临时开关（set_shadow_enabled，
    视频导出期间用）；导出结束用 restore_global_shadow 回退到全局状态。
    所有实例经弱引用注册，全局开关可广播到已存在的全部卡片。
    """

    # 全局阴影开关 + 存活实例注册表（WeakSet：卡片销毁后自动移除）
    _global_shadow = True
    _instances = weakref.WeakSet()

    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setBorderRadius(8)
        self._title = title

        # 原生投影：画在控件矩形之外，布局无需为阴影留位
        self._shadow_effect = QGraphicsDropShadowEffect(self)
        self._shadow_effect.setBlurRadius(16)
        self._shadow_effect.setOffset(0, 2)
        self._shadow_effect.setColor(self._shadow_color())
        self._shadow_effect.setEnabled(self._global_shadow)
        self.setGraphicsEffect(self._shadow_effect)
        self._instances.add(self)

        main_layout = QVBoxLayout(self)
        # 1px 内缩：给画在矩形边缘的 1px 边框笔触留位（贴边会被裁半像素）
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.setSpacing(0)

        # 标题行（仅 title 不为空时显示）
        if title:
            title_row = QHBoxLayout()
            title_row.setContentsMargins(20, 12, 20, 0)
            title_row.setSpacing(10)

            # 强调色竖线（参考导航栏选中竖线参数）
            self._accent_bar = _AccentBar(self)
            title_row.addWidget(self._accent_bar)

            self._title_label = StrongBodyLabel(title)
            title_row.addWidget(self._title_label)
            title_row.addStretch()
            main_layout.addLayout(title_row)
        else:
            self._accent_bar = None
            self._title_label = None

        # 内容区
        self._view_layout = QVBoxLayout()
        self._view_layout.setContentsMargins(20, 12, 20, 18)
        self._view_layout.setSpacing(8)
        main_layout.addLayout(self._view_layout)

        # 强调色/主题变化时触发重绘（竖线 + Hover 边框 + 阴影颜色）
        qconfig.themeColorChanged.connect(self._on_theme_color_changed)
        qconfig.themeChanged.connect(self._on_theme_changed)

    @staticmethod
    def _shadow_color() -> QColor:
        # 深色主题不投影（深底上黑影只会泛灰）
        return QColor(0, 0, 0, 34) if not isDarkTheme() else QColor(0, 0, 0, 0)

    def _on_theme_changed(self):
        self._shadow_effect.setColor(self._shadow_color())
        self.update()

    def refresh_shadow(self):
        """补一次特效全量重绘（含卡片矩形外的阴影余量）。

        子控件重绘时阴影余量不进脏区，内容变更后调用本方法恢复。
        """
        self._shadow_effect.update()

    @classmethod
    def set_global_shadow(cls, enabled: bool):
        """全局开关阴影，广播到所有已存在的卡片实例。

        由其他页"卡片阴影"开关触发；新建卡片会继承当前全局状态。
        """
        cls._global_shadow = bool(enabled)
        for card in list(cls._instances):
            card.set_shadow_enabled(cls._global_shadow)

    def set_shadow_enabled(self, enabled: bool):
        """单卡临时开关阴影（视频导出期间关掉，避免高频子控件更新触发整卡模糊）。"""
        self._shadow_effect.setEnabled(bool(enabled))
        self._shadow_effect.update()

    def restore_global_shadow(self):
        """导出结束恢复本卡阴影到当前全局状态（而非无条件开）。"""
        self.set_shadow_enabled(self._global_shadow)

    @property
    def viewLayout(self) -> QVBoxLayout:
        return self._view_layout

    def _on_theme_color_changed(self, _color: QColor):
        if self._accent_bar:
            self._accent_bar.update()
        self.update()  # 触发 paintEvent 重绘 Hover 边框

    def _normalBackgroundColor(self):
        # 浅色下用不透明纯白：半透明白叠在灰色页面/云母上会泛灰；
        # 深色下保持半透明白即可。
        return QColor(255, 255, 255) if not isDarkTheme() else QColor(255, 255, 255, 13)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        card_rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        # Hover 时边框变强调色半透明
        painter.setBrush(self.backgroundColor)
        if self.isHover:
            pen_color = QColor(themeColor())
            pen_color.setAlpha(64)  # 25% 透明度
        else:
            pen_color = QColor(0, 0, 0, 48 if isDarkTheme() else 12)
        painter.setPen(pen_color)

        r = self.borderRadius
        painter.drawRoundedRect(card_rect, r, r)
