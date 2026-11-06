# lyric_edit_page.py — "歌词编辑" 导航页
"""批量编辑 + 歌词表格编辑。"""

import re
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt, QEvent, QRectF
from PySide6.QtGui import (
    QColor, QKeyEvent, QFocusEvent, QMouseEvent, QPainter,
    QPainterPath, QRegion,
)

from qfluentwidgets import (
    LineEdit, ComboBox,
    BodyLabel,
    InfoBar, InfoBarPosition, PrimaryPushButton, TableWidget,
    isDarkTheme, qconfig,
)
from qfluentwidgets.common.color import autoFallbackThemeColor
from qfluentwidgets.common.style_sheet import setCustomStyleSheet, themeColor
from qfluentwidgets.components.widgets.table_view import TableItemDelegate

from core.settings_manager import SettingsManager
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


class LyricEditPage(QWidget):
    """歌词编辑标签页 — 批量筛选 + 表格逐音符编辑。"""

    def __init__(self, settings: SettingsManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._s = settings
        # 每个音符的样式索引（默认 0 = 样式1）
        self._note_styles: dict[int, int] = {}  # key=音符序号(int), value=样式索引(int)
        # 表行 → 全局音符行号映射（多轨工程只显示所选轨，样式键始终是全局行号）
        self._global_rows: list[int] = []
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

    # ===================== 方向键切换样式 =====================

    def hideEvent(self, event):
        """隐藏页面时清除选中，防止切换主题色后残留高亮。"""
        super().hideEvent(event)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)

    def _on_style_key(self, key: int):
        """← → 方向键回调：切换当前行样式。"""
        item = self.table.currentItem()
        if item is None:
            return
        row = item.row()
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
            self.table.setRowCount(len(filtered))

            for i, global_i in enumerate(filtered):
                note = notes[global_i]
                # 前三列都可选中，配合整行选择行为；文本居中
                self.table.setItem(i, 0, self._make_item(str(i + 1)))
                self.table.setItem(i, 1, self._make_item(note.get("lyric", "")))
                self.table.setItem(
                    i, 2, self._make_item(midi_to_pitch(note.get("note_num", 0))))
                # 样式：保留已有样式，新音符默认样式1
                self._set_style_cell(i, self._note_styles.setdefault(global_i, 0))

            self._table_built_for = (notes, selected)
            self._style_dirty = False
            self._sync_styles_to_settings()
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

    def _set_style_cell(self, row: int, style_index: int):
        """设置样式单元格的文本和颜色；已存在则就地更新，不重建单元格。"""
        text = f"样式{style_index + 1}"
        bg, fg = self._style_paint(style_index)
        item = self.table.item(row, 3)
        if item is None:
            item = self._make_item(text)
            self.table.setItem(row, 3, item)
        else:
            item.setText(text)
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
                    self._set_style_cell(row, style_index)
        finally:
            self.table.setUpdatesEnabled(True)

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
                self._set_style_cell(row, style_idx)
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
        self.track_combo.currentIndexChanged.connect(self._on_track_selected)
        # 选中单元格时用强调色高亮（不依赖 stylesheet）
        self.table.currentItemChanged.connect(self._on_selection_changed)

    def _on_notes_changed(self, notes: list):
        """音符数据更新时重建表格。

        ustx_notes 的 setter 仅清空 settings 层的 _note_styles，本页面的
        _note_styles 须在此处显式清空，否则 _build_table 的"保留已有样式"
        逻辑会让旧行号样式残留并被同步回 settings。
        """
        self._note_styles = {}  # 新音符数据 → 清空所有逐字样式
        self._global_rows = []
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
