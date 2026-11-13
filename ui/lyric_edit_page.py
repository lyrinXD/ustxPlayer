# lyric_edit_page.py — "歌词编辑" 导航页
"""批量编辑 + 歌词表格编辑。"""

import re
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QApplication, QVBoxLayout, QHBoxLayout, QListWidgetItem, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import (
    Qt, QEvent, QRect, QRectF, QTimer, QPropertyAnimation, QEasingCurve, Property,
)
from PySide6.QtGui import (
    QBrush, QColor, QKeyEvent, QFocusEvent, QMouseEvent, QPainter,
    QPainterPath, QRegion,
)

from qfluentwidgets import (
    LineEdit, ComboBox,
    BodyLabel,
    FluentIcon, HorizontalSeparator, IconWidget, InfoBar, InfoBarPosition,
    ListWidget, PrimaryPushButton, PushButton,
    TableWidget,
    isDarkTheme, qconfig,
)
from qfluentwidgets.common.color import autoFallbackThemeColor
from qfluentwidgets.common.style_sheet import setCustomStyleSheet, themeColor
from qfluentwidgets.components.widgets.table_view import TableItemDelegate

from core.settings_manager import SettingsManager
from core.ustxreader import is_non_sung_lyric, iter_mapped_lyrics, normalize_lyric
from ui.accent_card import AccentHeaderCardWidget, PAGE_MARGIN, PAGE_SPACING

# 表格单元格统一的对齐与选中标志
_ITEM_FLAGS = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
_ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter


# ===================== 表格 =====================

class _TableBorder(QWidget):
    """表格顶层圆角边框；覆盖 viewport 与滚动条槽，透明且鼠标穿透。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("lyricTableBorder")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class _StyleTableWidget(TableWidget):
    """歌词表格：原生 TableWidget + 样式列选中指示条。

    左右方向键交给外部切换样式，失焦清选中；主题和边框由库及 _TableBorder 管理。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._delegate = _StyleTableItemDelegate(self)
        self.setItemDelegate(self._delegate)
        self._delegate.margin = 0  # 去掉每行上下 2px 透明间隙
        # 禁用原生 tooltip：窗口关闭时可能留下悬空 C++ 指针
        tip = self._delegate.tooltipDelegate
        self.removeEventFilter(tip)
        self.viewport().removeEventFilter(tip)
        tip.deleteLater()
        self.setBorderVisible(False)
        self._border = _TableBorder(self)
        self._border.raise_()
        self.viewport().installEventFilter(self)
        self._update_table_style()
        qconfig.themeColorChanged.connect(self._update_table_style)
        qconfig.themeChanged.connect(self._update_table_style)
        self.setAlternatingRowColors(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # 选中变化立即同步给 delegate：点左列与直接点样式列的竖线出现时机一致
        self.selectionModel().selectionChanged.connect(self.updateSelectedRows)
        self._style_key_callback = None  # callable(direction: int)

    def set_style_key_callback(self, cb):
        self._style_key_callback = cb

    def _update_table_style(self, _color=None):
        """合并表头与圆角样式；强调色变化时重建，明暗主题由库自动切换。"""
        accent = themeColor()
        tint = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.08)"

        def qss(line: str) -> str:
            return (
                "QHeaderView { background: transparent; border: none; }"
                "QHeaderView::section {"
                f"  background: {tint};"
                "  color: --ThemeColorPrimary;"
                "  padding: 0 4px;"
                "  border: none;"
                f"  border-bottom: 1px solid {line};"
                "  font-size: 14px;"
                "  font-weight: normal;"
                "}"
                "QHeaderView::section:first { border-top-left-radius: 8px; }"
                "QHeaderView::section:last { border-top-right-radius: 8px; }"
            )

        def border_qss(line: str) -> str:
            return (
                "QWidget#lyricTableBorder {"
                "  background: transparent;"
                f"  border: 1px solid {line};"
                "  border-radius: 8px;"
                "}"
            )

        setCustomStyleSheet(self, qss("#e6e6e6"), qss("#3a3a3a"))
        self._border.setStyleSheet(
            border_qss("#3a3a3a" if isDarkTheme() else "#e6e6e6"))

    def _update_mask(self):
        """裁掉 viewport 两个下角；上角紧接表头，保持直角。"""
        viewport = self.viewport()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return
        # 内收 1px，与边框内沿贴合
        path = QPainterPath()
        path.addRoundedRect(QRectF(viewport.rect()).adjusted(0, 0, -1, -1), 7, 7)
        region = QRegion(path.toFillPolygon().toPolygon())
        region = region.united(QRegion(0, 0, viewport.width(), 8))
        viewport.setMask(region)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._border.setGeometry(self.rect())
        self._border.raise_()
        self._update_mask()

    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type() == QEvent.Type.Resize:
            self._update_mask()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if self._style_key_callback is not None:
                self._style_key_callback(event.key())
            return  # 消费事件，不交给父类
        super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent):
        """失去焦点时清除选中，避免强调色高亮残留（点选表格外部控件时）。"""
        self.clearSelection()
        self.setCurrentCell(-1, -1)
        super().focusOutEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """松开鼠标后清除按下行残留（拖选后弱选中来自库的 pressedRow 未清）。"""
        super().mouseReleaseEvent(event)
        self.delegate.setPressedRow(-1)
        self.viewport().update()


class _StyleTableItemDelegate(TableItemDelegate):
    """把原生指示条从第 0 列移到第 4 列（样式格），x 用 option.rect.x()+4 对齐。

    库的 paint 只在第 0 列调用 _drawIndicator，因此这里让它在首列调用时直接
    返回（抑制），再由 paint 在样式列补画一次；其余 hover/按下/选中背景与
    文字绘制全部走库原生逻辑。
    """

    INDICATOR_COLUMN = 3

    def helpEvent(self, event, view, option, index) -> bool:
        """表格不使用 tooltip，直接截断，避免进入库内会访问失效 QTimer 的 tooltip delegate。"""
        return False

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)
        if (index.row() in self.selectedRows
                and index.column() == self.INDICATOR_COLUMN
                and self.parent().horizontalScrollBar().value() == 0):
            painter.save()
            try:
                self._drawIndicator(painter, option, index)
            finally:
                painter.restore()

    def setSelectedRows(self, indexes):
        """同步选中行；保留 pressedRow，按下动画统一由松开时清除。"""
        self.selectedRows.clear()
        for index in indexes:
            self.selectedRows.add(index.row())

    def _drawIndicator(self, painter: QPainter, option, index):
        if index.column() != self.INDICATOR_COLUMN:
            return  # 库在首列调用，本表格改由 paint 在样式列绘制
        y, h = option.rect.y(), option.rect.height()
        # 按下时收缩（0.35h），松开恢复（0.257h）：两条点击路径一致
        ph = round(0.35 * h if self.pressedRow == index.row() else 0.257 * h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(
            autoFallbackThemeColor(self.lightCheckedColor, self.darkCheckedColor))
        painter.drawRoundedRect(
            option.rect.x() + 4, ph + y, 3, h - 2 * ph, 1.5, 1.5)


# MIDI 音高转换
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_PITCH_RE = re.compile(r'^([A-G])(#?)(\d+)$', re.IGNORECASE)


def midi_to_pitch(note_num: int) -> str:
    """MIDI 编号 → 音高名（如 60 → C4）。"""
    if note_num < 0:
        return "??"
    octave = (note_num // 12) - 1
    name = NOTE_NAMES[note_num % 12]
    return f"{name}{octave}"


def pitch_to_midi(text: str) -> int:
    """音高名 → MIDI 编号（如 C#4 → 61）。无效格式抛出 ValueError。"""
    m = _PITCH_RE.match(text.strip().upper())
    if not m:
        raise ValueError(f"无效的音高格式: {text}（应如 C#4）")
    note_name = m.group(1).upper()
    sharp = m.group(2)  # '#' or ''
    octave = int(m.group(3))
    base_index = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    idx = base_index[note_name] + (1 if sharp else 0)
    # 拒绝非法等音：E#、B#
    if note_name == "E" and sharp:
        raise ValueError(f"无效的音高: {text}（E# 应使用 F）")
    if note_name == "B" and sharp:
        raise ValueError(f"无效的音高: {text}（B# 应使用 C）")
    return (octave + 1) * 12 + idx


class _ChevronIndicator(QWidget):
    """折叠指示器：Fluent 细折线 chevron，展开/收起时绕中心旋转 180°。"""

    _SIZE = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        # 点击穿透到标题行，展开/收起由 eventFilter 统一处理
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._angle = 0.0
        self._dark_mode = isDarkTheme()
        self._icon = FluentIcon.CHEVRON_DOWN_MED.icon()
        self._anim = QPropertyAnimation(self, b"angle", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def getAngle(self) -> float:
        return self._angle

    def setAngle(self, angle: float):
        self._angle = float(angle)
        self.update()

    angle = Property(float, getAngle, setAngle)

    def set_expanded(self, expanded: bool, animated: bool = True):
        target = 180.0 if expanded else 0.0
        self._anim.stop()
        if animated:
            self._anim.setStartValue(self._angle)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.setAngle(target)

    def _sync_icon(self):
        """图标随主题重建：FluentIcon 在创建时按当前主题取色。"""
        dark = isDarkTheme()
        if dark != self._dark_mode:
            self._dark_mode = dark
            self._icon = FluentIcon.CHEVRON_DOWN_MED.icon()

    def paintEvent(self, _event):
        self._sync_icon()
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(0.62)  # 次级文字强度，不抢标题
        painter.translate(self.rect().center())
        painter.rotate(self._angle)
        half = self._SIZE // 2
        self._icon.paint(painter, QRect(-half, -half, self._SIZE, self._SIZE))


class LyricEditPage(QWidget):
    """歌词编辑标签页 — 批量筛选 + 表格逐音符编辑。"""

    def __init__(self, settings: SettingsManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._s = settings
        # 每个音符的样式索引（默认 0 = 样式1）
        self._note_styles: dict[int, int] = {}  # key=音符序号(int), value=样式索引(int)
        # 表行 → 全局音符行号映射（多轨工程只显示所选轨，样式键始终是全局行号）
        self._global_rows: list[int] = []
        self._hidden_globals: set[int] = set()  # 被映射隐藏（含跟随延音）的全局行
        self._building_table = False  # 防止重复建表
        self._handling_selection = False  # 防止选中回调递归
        self._table_built_for: Optional[tuple] = None  # (音符列表引用, 轨道号)，避免重复重建
        self._syncing_styles = False  # 防止同步样式时信号循环
        self._style_colors: list[tuple[QColor, QColor]] = []  # 逐样式缓存的 (背景色, 前景色)
        self._style_dirty = False  # 样式变更时本页不可见，切页时补刷
        self._setup_ui()
        self._connect_signals()

    # ===================== UI 构建 =====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGIN)
        layout.setSpacing(PAGE_SPACING)

        # ========== 播放轨道选择（多轨工程，仅人声轨 >1 时显示） ==========
        # 用无标题卡片包裹，与其他卡片视觉统一
        self.track_card = AccentHeaderCardWidget(parent=self)
        track_row = QHBoxLayout()
        track_row.setSpacing(8)
        track_row.addWidget(BodyLabel("播放轨道:"))
        self.track_combo = ComboBox()
        self.track_combo.setMinimumWidth(180)
        track_row.addWidget(self.track_combo)
        track_row.addStretch()
        self.track_card.viewLayout.addLayout(track_row)
        self.track_card.hide()
        layout.addWidget(self.track_card)

        # ========== 批量编辑卡片 ==========
        batch_card = AccentHeaderCardWidget("批量编辑")
        batch_vbox = QVBoxLayout()
        batch_vbox.setSpacing(8)

        # 按序号筛选
        row_idx = QHBoxLayout()
        row_idx.setSpacing(8)
        row_idx.addWidget(BodyLabel("按序号筛选:"))
        self.filter_idx_start = LineEdit()
        self.filter_idx_start.setPlaceholderText("起始序号")
        self.filter_idx_start.setMaximumWidth(100)
        row_idx.addWidget(self.filter_idx_start)
        row_idx.addWidget(BodyLabel("~"))
        self.filter_idx_end = LineEdit()
        self.filter_idx_end.setPlaceholderText("结束序号")
        self.filter_idx_end.setMaximumWidth(100)
        row_idx.addWidget(self.filter_idx_end)
        row_idx.addStretch()
        batch_vbox.addLayout(row_idx)

        # 按音高筛选
        row_pitch = QHBoxLayout()
        row_pitch.setSpacing(8)
        row_pitch.addWidget(BodyLabel("按音高筛选:"))
        self.filter_pitch_start = LineEdit()
        self.filter_pitch_start.setPlaceholderText("起始音高")
        self.filter_pitch_start.setMaximumWidth(100)
        # 音高名是 C/C#/D 这类拉丁字符，禁用中文输入法组合，聚焦即英文输入
        self.filter_pitch_start.setInputMethodHints(Qt.InputMethodHint.ImhLatinOnly)
        row_pitch.addWidget(self.filter_pitch_start)
        row_pitch.addWidget(BodyLabel("~"))
        self.filter_pitch_end = LineEdit()
        self.filter_pitch_end.setPlaceholderText("结束音高")
        self.filter_pitch_end.setMaximumWidth(100)
        self.filter_pitch_end.setInputMethodHints(Qt.InputMethodHint.ImhLatinOnly)
        row_pitch.addWidget(self.filter_pitch_end)
        row_pitch.addStretch()
        batch_vbox.addLayout(row_pitch)

        # 批量设置样式
        row_style = QHBoxLayout()
        row_style.setSpacing(8)
        row_style.addWidget(BodyLabel("设置选中音符样式:"))
        self.batch_style_combo = ComboBox()
        self._refresh_style_combo(self.batch_style_combo)
        row_style.addWidget(self.batch_style_combo)
        self.batch_apply_btn = PrimaryPushButton("应用")
        row_style.addWidget(self.batch_apply_btn)
        row_style.addStretch()
        batch_vbox.addLayout(row_style)
        batch_card.viewLayout.addLayout(batch_vbox)
        layout.addWidget(batch_card)

        # ========== 歌词编辑卡片 ==========
        edit_card = AccentHeaderCardWidget("歌词编辑")
        edit_vbox = QVBoxLayout()
        edit_vbox.setSpacing(8)

        # 操作提示
        hint_row = QHBoxLayout()
        hint_row.setSpacing(8)
        hint_row.addWidget(BodyLabel("提示: 选中单元格后，← → 切换样式，↑ ↓ 切换行"))
        hint_row.addStretch()
        style_note = BodyLabel("静默和结尾时始终应用样式1")
        style_note.setTextColor("#6b6b6b", "#9e9e9e")
        hint_row.addWidget(style_note)
        edit_vbox.addLayout(hint_row)

        # 外观交给 Fluent TableWidget；子类只扩展样式列选中与方向键行为
        self.table = _StyleTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["序号", "逐字歌词", "音高", "样式"])
        # 四列等宽拉伸
        header = self.table.horizontalHeader()
        header.setFixedHeight(38)  # 略高于 30px 数据行
        for col in range(4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        # 水平滚动条在需要时显示
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # 设置左右键回调
        self.table.set_style_key_callback(self._on_style_key)
        self.table.setMinimumHeight(420)
        edit_vbox.addWidget(self.table, 1)
        edit_card.viewLayout.addLayout(edit_vbox)
        layout.addWidget(edit_card, 1)

        # ========== 音素映射卡片（标题栏右侧折叠） ==========
        self.map_card = AccentHeaderCardWidget("音素映射", self)
        self.map_expanded = False
        self.map_count_label = BodyLabel("未设置")
        self.map_chevron = _ChevronIndicator(self.map_card)
        header_row = self.map_card.headerLayout
        assert header_row is not None  # 本卡固定带标题
        self.map_header = header_row
        header_row.setContentsMargins(20, 12, 20, 12)
        header_row.addWidget(self.map_count_label)
        header_row.addWidget(self.map_chevron)
        self.map_card._title_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.map_count_label.setCursor(Qt.CursorShape.PointingHandCursor)

        self.map_body = QWidget()
        map_vbox = QVBoxLayout(self.map_body)
        map_vbox.setContentsMargins(0, 0, 0, 0)
        map_vbox.setSpacing(10)

        operation_layout = QVBoxLayout()
        operation_layout.setSpacing(6)
        map_row = QHBoxLayout()
        map_row.setSpacing(12)
        source_col = QVBoxLayout()
        source_col.setSpacing(6)
        source_col.addWidget(BodyLabel("原音素"))
        self.map_source_edit = LineEdit()
        self.map_source_edit.setClearButtonEnabled(True)
        source_col.addWidget(self.map_source_edit)
        map_row.addLayout(source_col, 1)

        map_arrow = BodyLabel("→")
        map_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        map_arrow.setFixedSize(28, 33)
        map_row.addWidget(map_arrow, 0, Qt.AlignmentFlag.AlignBottom)

        target_col = QVBoxLayout()
        target_col.setSpacing(6)
        target_col.addWidget(BodyLabel("映射为"))
        self.map_target_edit = LineEdit()
        self.map_target_edit.setClearButtonEnabled(True)
        target_col.addWidget(self.map_target_edit)
        map_row.addLayout(target_col, 1)

        self.map_add_btn = PrimaryPushButton("添加映射")
        self.map_add_btn.setMinimumWidth(96)
        self.map_add_btn.setEnabled(False)
        map_row.addWidget(self.map_add_btn, 0, Qt.AlignmentFlag.AlignBottom)

        # 删除选中规则：用文字按钮，与样式页“新建样式 / 删除样式”保持同一套写法
        self.map_delete_btn = PushButton("删除规则")
        self.map_delete_btn.setMinimumWidth(96)
        self.map_delete_btn.setToolTip("删除列表中选中的规则")
        self.map_delete_btn.setEnabled(False)
        map_row.addWidget(self.map_delete_btn, 0, Qt.AlignmentFlag.AlignBottom)
        operation_layout.addLayout(map_row)

        match_box = QWidget()
        match_box.setFixedHeight(34)
        match_layout = QHBoxLayout(match_box)
        match_layout.setContentsMargins(0, 0, 0, 0)
        match_layout.setSpacing(8)
        match_icon = IconWidget(FluentIcon.SEARCH)
        match_icon.setFixedSize(16, 16)
        match_layout.addWidget(match_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.map_hint_label = BodyLabel("输入原音素后显示匹配结果")
        self.map_hint_label.setWordWrap(True)
        match_layout.addWidget(self.map_hint_label, 1)
        operation_layout.addWidget(match_box)
        map_vbox.addLayout(operation_layout)

        map_vbox.addWidget(HorizontalSeparator())

        self.map_rules_empty = QWidget()
        self.map_rules_empty.setFixedHeight(117)  # 3 行 × 39px，超出滚动
        empty_layout = QVBoxLayout(self.map_rules_empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.addStretch()
        empty_label = BodyLabel("暂无映射规则")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_label)
        empty_layout.addStretch()
        map_vbox.addWidget(self.map_rules_empty)

        self.map_rules_list = ListWidget()
        self.map_rules_list.setFixedHeight(117)  # 3 行 × 39px，超出滚动
        self.map_rules_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.map_rules_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        map_vbox.addWidget(self.map_rules_list)

        self.map_card.viewLayout.addWidget(self.map_body)
        self.map_body.setVisible(False)
        self.map_card.viewLayout.setContentsMargins(20, 0, 20, 0)
        layout.addWidget(self.map_card)

    # ===================== 方向键切换样式 =====================

    def hideEvent(self, event):
        """隐藏页面时清除选中，防止切换主题色后残留高亮。"""
        super().hideEvent(event)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.map_rules_list.clearSelection()
        self.map_rules_list.setCurrentRow(-1)

    def _on_style_key(self, key: int):
        """← → 方向键回调：切换当前行样式。"""
        item = self.table.currentItem()
        if item is None:
            return
        row = item.row()
        if self._row_hidden(row):
            return  # 被映射隐藏的行不参与样式切换
        global_row = self._global_of(row)
        current_style = self._note_styles.get(global_row, 0)
        if key == Qt.Key.Key_Left:
            new_style = (current_style - 1) % self._s.style.style_count
        else:
            new_style = (current_style + 1) % self._s.style.style_count
        self._note_styles[global_row] = new_style
        self._set_style_cell(row, new_style)
        self.table.setCurrentCell(row, 3)
        self._sync_styles_to_settings()

    # ===================== 表格操作 =====================

    def _global_of(self, row: int) -> int:
        """表行号 → 全局音符行号（全轨拍平列表）。"""
        if 0 <= row < len(self._global_rows):
            return self._global_rows[row]
        return row

    def _style_for_row(self, row: int) -> int:
        """取表行的样式索引（按全局行号存储，切轨不丢样式）。"""
        return self._note_styles.get(self._global_of(row), 0)

    def _build_table(self):
        """根据音符数据重建表格：只显示所选轨，样式键保持全局行号。"""
        notes = self._s.ustx_notes
        selected = self._s.project.selected_track_no
        if (self._table_built_for is not None
                and self._table_built_for[0] is notes
                and self._table_built_for[1] == selected):
            return
        if self._building_table:
            return
        filtered = [i for i, n in enumerate(notes) if n.get("track_no", 0) == selected]
        if not filtered and notes:
            # 兜底：选轨与音符数据未对齐时对齐到第一条音符所属轨道
            first_track = notes[0].get("track_no", 0)
            if first_track != selected:
                self._s.project.selected_track_no = first_track
                return  # setter 信号触发 _on_track_changed 重建
        self._building_table = True
        try:
            self.table.currentItemChanged.disconnect(self._on_selection_changed)
        except (TypeError, RuntimeError):
            pass
        try:
            self.table.setUpdatesEnabled(False)
            self._global_rows = filtered
            self._rebuild_hidden_cache()
            self.table.setRowCount(len(filtered))

            for i, global_i in enumerate(filtered):
                note = notes[global_i]
                # 前三列都可选中，配合整行选择行为；文本居中
                self.table.setItem(i, 0, self._make_item(str(i + 1)))
                self._set_lyric_cell(i, note)
                self.table.setItem(
                    i, 2, self._make_item(midi_to_pitch(note.get("note_num", 0))))
                # 样式：保留已有样式，新音符默认样式1
                self._set_style_cell(i, self._note_styles.setdefault(global_i, 0),
                                     hidden=self._row_hidden(i))

            self._table_built_for = (notes, selected)
            self._style_dirty = False
            self._sync_styles_to_settings()
            self._update_map_hint()
        finally:
            self._building_table = False
            self.table.setUpdatesEnabled(True)
            self.table.currentItemChanged.connect(self._on_selection_changed)

    @staticmethod
    def _make_item(text: str) -> QTableWidgetItem:
        """构造只读居中的单元格。"""
        item = QTableWidgetItem(text)
        item.setTextAlignment(_ALIGN_CENTER)
        item.setFlags(_ITEM_FLAGS)
        return item

    @staticmethod
    def _contrast_foreground(bg: QColor) -> QColor:
        """根据背景亮度返回黑或白前景色（保证可读对比度）。"""
        brightness = (bg.red() * 299 + bg.green() * 587 + bg.blue() * 114) / 1000
        return QColor("#000000") if brightness > 128 else QColor("#ffffff")

    def _style_bg_color(self, style_index: int) -> QColor:
        """获取指定样式的歌词色作为单元格背景色标识。"""
        if 0 <= style_index < self._s.style.style_count:
            p = self._s.style.styles[style_index]
            return QColor(p.get("lyric_color", "#ffffff"))
        return QColor("#ffffff")

    def _rebuild_style_colors(self) -> list[tuple[QColor, QColor]]:
        """按样式索引重建 (背景色, 前景色) 列表。"""
        colors = []
        for i in range(self._s.style.style_count):
            bg = self._style_bg_color(i)
            colors.append((bg, self._contrast_foreground(bg)))
        return colors

    def _style_paint(self, style_index: int) -> tuple[QColor, QColor]:
        """取样式对应的 (背景色, 前景色)，按样式索引缓存，避免逐行解析颜色字符串。"""
        if len(self._style_colors) != self._s.style.style_count:
            self._style_colors = self._rebuild_style_colors()
        if 0 <= style_index < len(self._style_colors):
            return self._style_colors[style_index]
        return self._style_colors[0]

    def _set_style_cell(self, row: int, style_index: int, hidden: bool = False):
        """设置样式单元格的文本和颜色；已存在则就地更新，不重建单元格。

        hidden 为映射后不参与播放的行：文本换成“隐藏”，不涂样式色，底色跟随主题。
        """
        text = "隐藏" if hidden else f"样式{style_index + 1}"
        item = self.table.item(row, 3)
        if item is None:
            item = self._make_item(text)
            self.table.setItem(row, 3, item)
        else:
            item.setText(text)
        if hidden:
            item.setBackground(QBrush())
            item.setForeground(QBrush())
        else:
            bg, fg = self._style_paint(style_index)
            item.setBackground(bg)
            item.setForeground(fg)

    def _refresh_style_cells(self, styles: Optional[set[int]] = None):
        """刷新样式列；styles 为 None 时全表刷新，否则只刷用到这些样式索引的行。"""
        if styles is not None and not styles:
            return
        self.table.setUpdatesEnabled(False)
        try:
            for row in range(self.table.rowCount()):
                style_index = self._style_for_row(row)
                if styles is None or style_index in styles:
                    self._set_style_cell(row, style_index, hidden=self._row_hidden(row))
        finally:
            self.table.setUpdatesEnabled(True)

    # ===================== 音素映射 =====================

    @staticmethod
    def _map_target(lyric: str, rules: dict) -> Optional[str]:
        """查映射目标；延音 "+" 不参与映射。"""
        if lyric == "+":
            return None
        return rules.get(lyric)

    def _rebuild_hidden_cache(self):
        """计算被映射隐藏的全局行；隐藏音符后面的延音随之一并隐藏。"""
        notes = self._s.ustx_notes
        visible = {i for i, _ in iter_mapped_lyrics(
            notes, self._global_rows, self._s.project.phoneme_map)}
        self._hidden_globals = set(self._global_rows) - visible

    def _row_hidden(self, row: int) -> bool:
        return self._global_of(row) in self._hidden_globals

    def _set_lyric_cell(self, row: int, note: dict):
        """歌词列：命中映射时显示 `原歌词 → 目标`，否则原样显示。"""
        lyric = note.get("lyric", "")
        target = self._map_target(lyric, self._s.project.phoneme_map)
        text = f"{lyric} → {target}" if target is not None else lyric
        item = self.table.item(row, 1)
        if item is None:
            self.table.setItem(row, 1, self._make_item(text))
        else:
            item.setText(text)

    def _refresh_mapping_cells(self):
        """映射变化后只刷新歌词与样式两列，不重建表格、不重新赋值音符。"""
        notes = self._s.ustx_notes
        self._rebuild_hidden_cache()
        self.table.setUpdatesEnabled(False)
        try:
            for row in range(self.table.rowCount()):
                global_i = self._global_of(row)
                self._set_lyric_cell(row, notes[global_i])
                self._set_style_cell(row, self._style_for_row(row),
                                     hidden=self._row_hidden(row))
        finally:
            self.table.setUpdatesEnabled(True)

    @staticmethod
    def _is_special_source(text: str) -> bool:
        """内置非演唱符号与延音写法不能作为映射来源。"""
        return is_non_sung_lyric(text) or normalize_lyric(text) == "+"

    def _update_map_hint(self):
        """输入来源后即时显示命中情况（当前轨列出序号，其他轨只汇总数量）。"""
        source = self.map_source_edit.text().strip()
        if not source:
            self.map_hint_label.setText("输入原音素后显示匹配结果")
            return
        notes = self._s.ustx_notes
        selected = self._s.project.selected_track_no
        hit_rows = [row + 1 for row, global_i in enumerate(self._global_rows)
                    if notes[global_i].get("lyric", "") == source]
        other = sum(1 for n in notes
                    if n.get("track_no", 0) != selected and n.get("lyric", "") == source)
        if not hit_rows and not other:
            self.map_hint_label.setText("当前工程没有匹配音符")
            return
        parts = []
        if hit_rows:
            shown = "、".join(f"#{r}" for r in hit_rows[:8])
            if len(hit_rows) > 8:
                shown += f" 等 {len(hit_rows)} 个"
            parts.append(f"当前轨命中：{shown}")
        if other:
            parts.append(f"其他轨另有 {other} 个命中")
        self.map_hint_label.setText("；".join(parts))

    def _rebuild_map_rules(self):
        """重建规则列表；空状态独立占位，不作为列表项参与选中。"""
        rules = self._s.project.phoneme_map
        self.map_rules_empty.setVisible(not rules)
        self.map_rules_list.setVisible(bool(rules))
        self.map_rules_list.setUpdatesEnabled(False)
        try:
            self.map_rules_list.clear()
            for source, target in rules.items():
                item = QListWidgetItem(f"{source}  →  {target}")
                item.setData(Qt.ItemDataRole.UserRole, source)
                self.map_rules_list.addItem(item)
        finally:
            self.map_rules_list.setUpdatesEnabled(True)
        # 列表重建后 Qt 会补一个无高亮的 current 行，删除按钮只认选中
        self.map_rules_list.clearSelection()
        self.map_rules_list.setCurrentRow(-1)
        QTimer.singleShot(0, self._reset_map_current)
        self.map_delete_btn.setEnabled(False)
        self.map_count_label.setText(f"{len(rules)} 条规则" if rules else "未设置")
        self.map_card.layout().activate()
        self.map_card.refresh_shadow()

    def _on_map_rule_clicked(self, item: QListWidgetItem):
        """将选中的规则回填到输入区，继续编辑后通过“更新映射”保存。"""
        source = item.data(Qt.ItemDataRole.UserRole)
        target = self._s.project.phoneme_map.get(source)
        if target is None:
            return
        self.map_source_edit.setText(source)
        self.map_target_edit.setText(target)
        self.map_target_edit.setFocus()
        self.map_target_edit.selectAll()

    def _reset_map_current(self):
        """清掉列表重建后补上的 current 行；用户已选中某行时保留。"""
        if self.map_rules_list.selectedItems():
            return
        self.map_rules_list.setCurrentRow(-1)

    def _on_map_selection_changed(self):
        """选中变化时更新“删除规则”的可用状态。"""
        self.map_delete_btn.setEnabled(bool(self.map_rules_list.selectedItems()))

    def _on_delete_selected_map(self):
        items = self.map_rules_list.selectedItems()
        if not items:
            return
        source = items[0].data(Qt.ItemDataRole.UserRole)
        self._on_remove_map(source)

    def eventFilter(self, obj, event):
        """处理映射标题行点击，并在点击规则列表外部时清除选中。"""
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget):
            inside_list = obj is self.map_rules_list or self.map_rules_list.isAncestorOf(obj)
            if not inside_list and obj is not self.map_delete_btn:
                self.map_rules_list.clearSelection()
                self.map_rules_list.setCurrentRow(-1)
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            title_clicked = obj in (self.map_card._title_label, self.map_count_label)
            header_clicked = (obj is self.map_card and
                              self.map_header.geometry().contains(event.position().toPoint()))
            if title_clicked or header_clicked:
                self._toggle_map_body()
                return True
        return super().eventFilter(obj, event)

    def _toggle_map_body(self):
        """展开/收起映射内容；折叠时标题行上下留白保持一致。"""
        self.setUpdatesEnabled(False)
        try:
            self.map_expanded = not self.map_expanded
            self.map_body.setVisible(self.map_expanded)
            self.map_chevron.set_expanded(self.map_expanded)
            header_row = self.map_header
            if self.map_expanded:
                header_row.setContentsMargins(20, 12, 20, 0)
                self.map_card.viewLayout.setContentsMargins(20, 12, 20, 18)
            else:
                header_row.setContentsMargins(20, 12, 20, 12)
                self.map_card.viewLayout.setContentsMargins(20, 0, 20, 0)
            self.map_card.layout().activate()
        finally:
            self.setUpdatesEnabled(True)
        self.map_card.refresh_shadow()

    def _on_map_input_changed(self, *_args):
        source = self.map_source_edit.text().strip()
        target = self.map_target_edit.text().strip()
        self.map_add_btn.setEnabled(bool(source) and bool(target))
        # 来源已存在时按钮语义为更新
        self.map_add_btn.setText(
            "更新映射" if source in self._s.project.phoneme_map else "添加映射")
        self._update_map_hint()

    def _on_add_map(self):
        source = self.map_source_edit.text().strip()
        target = self.map_target_edit.text().strip()
        if not source or not target:
            return
        if self._is_special_source(source):
            InfoBar.warning("无法添加", f"“{source}”是内置特殊符号，不能作为映射来源",
                            orient=Qt.Orientation.Vertical, duration=2000,
                            parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
            return
        rules = dict(self._s.project.phoneme_map)
        rules[source] = target
        self._s.project.phoneme_map = rules
        self.map_source_edit.clear()
        self.map_target_edit.clear()
        self.map_source_edit.setFocus()

    def _on_remove_map(self, source: str):
        rules = dict(self._s.project.phoneme_map)
        if rules.pop(source, None) is None:
            return
        self._s.project.phoneme_map = rules

    def _on_phoneme_map_changed(self, _rules: dict):
        self._rebuild_map_rules()
        self._refresh_mapping_cells()
        self._on_map_input_changed()

    # ===================== 批量筛选 =====================

    def _get_filtered_rows(self) -> set | None:
        """根据两种筛选条件获取交集表行号集合（相对当前所选轨的显示行）。

        Returns:
            set: 匹配的表行号集合
            None: 输入格式非法（已弹错误提示）
        """
        display_rows = self._global_rows
        if not display_rows:
            return set()

        idx_set: Optional[set] = None
        pitch_set: Optional[set] = None

        # 序号筛选（按当前轨显示序号 1..N）
        start_text = self.filter_idx_start.text().strip()
        end_text = self.filter_idx_end.text().strip()
        if start_text or end_text:
            try:
                s = int(start_text) if start_text else 1
                e = int(end_text) if end_text else len(display_rows)
            except ValueError:
                InfoBar.error("格式错误", "序号筛选请输入整数", orient=Qt.Orientation.Vertical, duration=2000,
                              parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
                return None
            idx_set = set(range(max(0, s - 1), min(e, len(display_rows))))

        # 音高筛选
        p_start_text = self.filter_pitch_start.text().strip()
        p_end_text = self.filter_pitch_end.text().strip()
        if p_start_text or p_end_text:
            try:
                if p_start_text:
                    ps = pitch_to_midi(p_start_text)
                else:
                    ps = -999
                if p_end_text:
                    pe = pitch_to_midi(p_end_text)
                else:
                    pe = 999
            except ValueError as e:
                InfoBar.error("格式错误", str(e), orient=Qt.Orientation.Vertical, duration=2000,
                              parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
                return None
            notes = self._s.ustx_notes
            pitch_set = set()
            for i, global_i in enumerate(display_rows):
                note = notes[global_i]
                nn = note.get("note_num", 0)
                if ps <= nn <= pe:
                    pitch_set.add(i)

        # 取交集；若均未填写则返回全部行
        if idx_set is not None and pitch_set is not None:
            return idx_set & pitch_set
        elif idx_set is not None:
            return idx_set
        elif pitch_set is not None:
            return pitch_set
        else:
            return set(range(len(display_rows)))

    def _on_batch_apply(self):
        """应用批量样式设置，完成后清空输入框并重置样式。"""
        rows = self._get_filtered_rows()
        if rows is None:
            return  # 格式非法，错误提示已在 _get_filtered_rows 中弹出
        if not rows:
            InfoBar.warning("提示", "没有匹配的音符", orient=Qt.Orientation.Vertical, duration=1500,
                            parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
            return
        style_idx = self.batch_style_combo.currentIndex()
        self.table.setUpdatesEnabled(False)
        try:
            for row in rows:
                global_row = self._global_of(row)
                self._note_styles[global_row] = style_idx
                self._set_style_cell(row, style_idx, hidden=self._row_hidden(row))
        finally:
            self.table.setUpdatesEnabled(True)
        self._sync_styles_to_settings()
        # 清空输入框并重置样式到样式1
        self.filter_idx_start.clear()
        self.filter_idx_end.clear()
        self.filter_pitch_start.clear()
        self.filter_pitch_end.clear()
        self.batch_style_combo.setCurrentIndex(0)
        InfoBar.success("完成", f"已为 {len(rows)} 个音符设置样式{style_idx + 1}",
                        orient=Qt.Orientation.Vertical, duration=2000, parent=self.window(), position=InfoBarPosition.TOP_RIGHT)

    # ===================== 信号绑定 =====================

    def _connect_signals(self):
        self.batch_apply_btn.clicked.connect(self._on_batch_apply)
        self._s.ustx_notes_changed.connect(self._on_notes_changed)
        self._s.project.selected_track_changed.connect(self._on_track_changed)
        self._s.style.styles_changed.connect(self._on_styles_changed)
        self._s.style.note_styles_changed.connect(self._on_note_styles_changed)
        self._s.project.phoneme_map_changed.connect(self._on_phoneme_map_changed)
        self.track_combo.currentIndexChanged.connect(self._on_track_selected)
        self.map_add_btn.clicked.connect(self._on_add_map)
        self.map_source_edit.textChanged.connect(self._on_map_input_changed)
        self.map_target_edit.textChanged.connect(self._on_map_input_changed)
        self.map_rules_list.itemClicked.connect(self._on_map_rule_clicked)
        self.map_rules_list.itemSelectionChanged.connect(self._on_map_selection_changed)
        self.map_delete_btn.clicked.connect(self._on_delete_selected_map)
        QApplication.instance().installEventFilter(self)
        # 选中单元格时用强调色高亮（不依赖 stylesheet）
        self.table.currentItemChanged.connect(self._on_selection_changed)
        self._rebuild_map_rules()

    def _on_notes_changed(self, notes: list):
        """音符数据更新时重建表格。

        ustx_notes 的 setter 仅清空 settings 层的 _note_styles，本页面的
        _note_styles 须在此处显式清空，否则 _build_table 的"保留已有样式"
        逻辑会让旧行号样式残留并被同步回 settings。
        """
        self._note_styles = {}  # 新音符数据 → 清空所有逐字样式
        self._global_rows = []
        self._hidden_globals = set()
        self._table_built_for = None
        # 本页不在前台时不建表：拖拽导入时建表会阻塞 UI，打断 InfoBar 动画。
        if self.isVisible():
            self._build_table()
        else:
            self.table.setRowCount(0)  # 防止切回本页时残留旧行
        self._refresh_track_combo()

    def _on_track_changed(self, track_no: int):
        """播放轨道切换：只过滤显示，保留各轨样式（不清空）。"""
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self._table_built_for = None
        self._build_table()

    def _on_track_selected(self, index: int):
        """播放轨道下拉切换（多轨工程）。"""
        cached = self._s.cached_ustx_info or {}
        tracks_info = (cached.get("info") or {}).get("tracks_info") or []
        if 0 <= index < len(tracks_info):
            t = tracks_info[index]
            if isinstance(t, dict) and "track_no" in t:
                self._s.project.selected_track_no = t["track_no"]

    def _refresh_track_combo(self):
        """刷新播放轨道下拉：多轨时显示并定位当前轨，单轨/无轨时隐藏。

        同时校正 selected_track_no：当前值不在人声轨列表时回退第一条
        （单轨工程也必须对齐，否则过滤后音符为空）。
        """
        cached = self._s.cached_ustx_info or {}
        tracks_info = (cached.get("info") or {}).get("tracks_info") or []
        tracks_info = [t for t in tracks_info if isinstance(t, dict)]
        if not tracks_info:
            self.track_card.hide()
            return
        if len(tracks_info) == 1:
            only = tracks_info[0].get("track_no")
            if self._s.project.selected_track_no != only:
                self._s.project.selected_track_no = only
            self.track_card.hide()
            return
        current = self._s.project.selected_track_no
        current_idx = 0
        for i, t in enumerate(tracks_info):
            if t.get("track_no") == current:
                current_idx = i
                break
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        for t in tracks_info:
            name = t.get("track_name") or f"轨道 {t.get('track_no', 0) + 1}"
            self.track_combo.addItem(f"{name}（{t.get('note_count', 0)} 音符）")
        self.track_combo.setCurrentIndex(current_idx)
        self.track_combo.blockSignals(False)
        self.track_card.show()
        target = tracks_info[current_idx].get("track_no")
        if current != target:
            self._s.project.selected_track_no = target

    def _on_styles_changed(self):
        """样式数据变更：刷新样式下拉（仅数量变化时）与表格样式列颜色。"""
        old = self._style_colors
        new = self._rebuild_style_colors()
        changed = {i for i in range(min(len(old), len(new)))
                   if old[i][0].name() != new[i][0].name()}
        self._style_colors = new
        # 仅调色时不能重建下拉，否则会把用户在批量编辑里选的样式重置为样式1
        self._refresh_style_combo(self.batch_style_combo)
        if not self.isVisible():
            self._style_dirty = True
            return
        # 样式数量变化说明索引已整体重映射，必须全表刷；否则只刷用到变色样式的行
        if len(old) != len(new):
            self._refresh_style_cells()
        else:
            self._refresh_style_cells(changed)

    def _on_note_styles_changed(self, styles: dict):
        """外部修改了逐音符样式（如删除样式后重映射），刷新表格。"""
        if self._syncing_styles:
            return
        self._note_styles.update(styles)
        if not self.isVisible():
            self._style_dirty = True
            return
        self._refresh_style_cells()

    def _on_selection_changed(self, current, previous):
        """选中单元格变化时：非样式列自动跳转到样式列，保持选中状态一致。

        点击非样式列时调用 setCurrentCell 跳转到样式列，该调用会二次触发本回调
        并被 _handling_selection 守卫挡回。选中态的左侧强调色竖线由
        _StyleTableItemDelegate 根据选中状态自动绘制，无需在此手动覆盖颜色。
        """
        if self._handling_selection:
            return
        if current is None or current.column() == 3:
            return
        self._handling_selection = True
        try:
            self.table.setCurrentCell(current.row(), 3)
        finally:
            self._handling_selection = False

    def _refresh_style_combo(self, combo: ComboBox):
        """刷新样式下拉框（同步样式列表）。

        样式数量没变时直接返回：调色、切页都会走到这里，重建会把用户
        当前选中的样式重置为样式1。
        """
        if combo.count() == self._s.style.style_count:
            return
        combo.blockSignals(True)
        combo.clear()
        for i in range(self._s.style.style_count):
            combo.addItem(f"样式{i + 1}")
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    # ===================== 同步 =====================

    def _sync_styles_to_settings(self):
        """将本地样式同步到 SettingsManager，供播放器使用。"""
        if self._syncing_styles:
            return
        self._syncing_styles = True
        try:
            self._s.style.note_styles = dict(self._note_styles)
        finally:
            self._syncing_styles = False

    def sync_all_from_settings(self):
        """从 Settings 同步所有数据。"""
        self._refresh_track_combo()
        self._refresh_style_combo(self.batch_style_combo)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        if self._s.ustx_notes:
            self._build_table()
        if self._style_dirty:
            self._style_dirty = False
            self._refresh_style_cells()
