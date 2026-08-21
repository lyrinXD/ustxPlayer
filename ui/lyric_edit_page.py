# lyric_edit_page.py — "歌词编辑" 导航页
"""批量编辑 + 歌词表格编辑。"""

import re
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeyEvent, QFocusEvent, QMouseEvent, QPainter

from qfluentwidgets import (
    LineEdit, ComboBox,
    BodyLabel,
    InfoBar, InfoBarPosition, PrimaryPushButton, TableWidget,
)
from qfluentwidgets.common.color import autoFallbackThemeColor
from qfluentwidgets.components.widgets.table_view import TableItemDelegate

from core.settings_manager import SettingsManager
from ui.accent_card import AccentHeaderCardWidget, PAGE_MARGIN, PAGE_SPACING


# ===================== 自定义表格（拦截左右键） =====================

class _StyleTableWidget(TableWidget):
    """歌词编辑表格：qfluentwidgets 原生 TableWidget + 样式列指示条。

    选中行在样式列（第 4 列）左侧显示原生强调色指示条（_StyleTableItemDelegate），
    保留 TableWidget 原生 hover/按下/选中动画与 BackgroundRole 颜色；左右方向键
    转发给外部回调切换样式，失焦清选中。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(_StyleTableItemDelegate(self))
        self.delegate.margin = 0  # 去掉每行上下 2px 透明间隙
        # 原生 delegate 自带的悬停 tooltip 在窗口关闭时会留下悬空 C++ 指针
        # （Internal C++ object already deleted），这里禁用。
        tip = self.delegate.tooltipDelegate
        self.removeEventFilter(tip)
        self.viewport().removeEventFilter(tip)
        tip.deleteLater()
        self.setBorderVisible(True)
        self.setBorderRadius(8)
        self.setAlternatingRowColors(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # 选中变化立即同步给 delegate：点左列与直接点样式列的竖线出现时机一致
        self.selectionModel().selectionChanged.connect(self.updateSelectedRows)
        self._style_key_callback = None  # callable(direction: int)

    def set_style_key_callback(self, cb):
        self._style_key_callback = cb

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

    通过包装库的 paint：库在 col0 画指示条前先被抑制，结束后再在样式列
    补画一次；其余 hover/按下/选中背景与文字绘制全部走库原生逻辑。
    """

    INDICATOR_COLUMN = 3

    def paint(self, painter: QPainter, option, index):
        self._suppress_indicator = True
        try:
            super().paint(painter, option, index)
        finally:
            self._suppress_indicator = False
        if (index.row() in self.selectedRows
                and index.column() == self.INDICATOR_COLUMN
                and self.parent().horizontalScrollBar().value() == 0):
            painter.save()
            try:
                self._drawIndicator(painter, option, index)
            finally:
                painter.restore()

    def setSelectedRows(self, indexes):
        """同步选中行，但不清 pressedRow。

        库原版会在选中同步时顺手清掉 pressedRow，导致两条点击路径的
        按下收缩时机不一致；这里保留 pressedRow，统一由松开时清除。
        """
        self.selectedRows.clear()
        for index in indexes:
            self.selectedRows.add(index.row())

    def _drawIndicator(self, painter: QPainter, option, index):
        if getattr(self, "_suppress_indicator", False):
            return
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
        self._table_built_for: Optional[tuple] = None  # (音符引用, 轨道号)，避免重复重建
        self._syncing_styles = False  # 防止同步样式时信号循环
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

        # 规则说明
        rule_row = QHBoxLayout()
        rule_row.setSpacing(8)
        rule_row.addWidget(BodyLabel("静默和结尾时显示始终应用样式1"))
        rule_row.addStretch()
        edit_vbox.addLayout(rule_row)

        # 操作提示
        hint_row = QHBoxLayout()
        hint_row.setSpacing(8)
        hint_row.addWidget(BodyLabel("提示: 选中单元格后，← → 切换样式，↑ ↓ 切换行"))
        hint_row.addStretch()
        edit_vbox.addLayout(hint_row)

        # 表格（自定义子类拦截左右方向键）
        self.table = _StyleTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["序号", "逐字歌词", "音高", "样式"])
        # 所有列等宽拉伸，不随窗口缩放
        header = self.table.horizontalHeader()
        for col in range(4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        # 水平滚动条在需要时显示
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # 设置左右键回调
        self.table.set_style_key_callback(self._on_style_key)
        self.table.setMinimumHeight(280)
        self._apply_table_theme()
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
        self._refresh_table_row(row, new_style)
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
        if self._table_built_for == (notes, selected):
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
                # 序号（当前轨内序号；可选中以支持原生整行选择）
                idx_item = QTableWidgetItem(str(i + 1))
                idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                idx_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(i, 0, idx_item)

                # 逐字歌词（可选中以支持原生整行选择）
                lyric = note.get("lyric", "")
                lyric_item = QTableWidgetItem(lyric)
                lyric_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                lyric_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(i, 1, lyric_item)

                # 音高（可选中以支持原生整行选择）
                note_num = note.get("note_num", 0)
                pitch_name = midi_to_pitch(note_num)
                pitch_item = QTableWidgetItem(pitch_name)
                pitch_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                pitch_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(i, 2, pitch_item)

                # 样式：保留已有样式，新音符默认样式1
                if global_i not in self._note_styles:
                    self._note_styles[global_i] = 0
                self._set_style_cell(i, self._note_styles[global_i])

            self._table_built_for = (notes, selected)
            self._sync_styles_to_settings()
        finally:
            self._building_table = False
            self.table.setUpdatesEnabled(True)
            self.table.currentItemChanged.connect(self._on_selection_changed)

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

    def _set_style_cell(self, row: int, style_index: int):
        """设置样式单元格的文本和颜色。"""
        item = QTableWidgetItem(f"样式{style_index + 1}")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        bg = self._style_bg_color(style_index)
        item.setBackground(bg)
        item.setForeground(self._contrast_foreground(bg))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table.setItem(row, 3, item)

    def _refresh_table_row(self, row: int, style_index: int):
        """刷新单行的样式单元格（方向键切换时）。"""
        self._set_style_cell(row, style_index)

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
        for row in rows:
            global_row = self._global_of(row)
            self._note_styles[global_row] = style_idx
            self._set_style_cell(row, style_idx)
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
        # 主题变更时刷新表格 QSS（网格色、表头色等）
        self._s.theme.theme_mode_changed.connect(self._apply_table_theme)

    def _on_notes_changed(self, notes: list):
        """音符数据更新时重建表格。

        ustx_notes 的 setter 仅清空 settings 层的 _note_styles，本页面的
        _note_styles 须在此处显式清空，否则 _build_table 的"保留已有样式"
        逻辑会让旧行号样式残留并被同步回 settings。
        """
        self._note_styles = {}  # 新音符数据 → 清空所有逐字样式
        self._global_rows = []
        self._table_built_for = None
        self._build_table()
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
        """样式变更时刷新样式下拉框及表格颜色。"""
        self._refresh_style_combo(self.batch_style_combo)
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            si = self._style_for_row(row)
            self._set_style_cell(row, si)
        self.table.setUpdatesEnabled(True)

    def _on_note_styles_changed(self, styles: dict):
        """外部修改了逐音符样式（如删除样式后重映射），刷新表格。"""
        if self._syncing_styles:
            return
        self._note_styles.update(styles)
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            si = self._style_for_row(row)
            self._set_style_cell(row, si)
        self.table.setUpdatesEnabled(True)

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
        """刷新样式下拉框（同步样式列表）。"""
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

    def _apply_table_theme(self):
        """根据当前主题设置表格样式，透明背景与卡片融合，item.setBackground() 直接生效。"""
        from qfluentwidgets import qconfig, Theme
        is_dark = qconfig.theme == Theme.DARK
        grid = "#3d3d3d" if is_dark else "#e0e0e0"
        text = "#e0e0e0" if is_dark else "#333333"
        header_bg = "#353535" if is_dark else "#e8e8e8"
        self.table.setStyleSheet(
            f"QTableWidget {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  color: {text};"
            f"  gridline-color: {grid};"
            f"  outline: none;"
            f"  selection-background-color: transparent;"
            f"  selection-color: {text};"
            f"}}"
            f"QTableWidget::item {{ padding: 4px 8px; height: 30px; }}"
            f"QTableWidget::item:selected {{ background: transparent; }}"
            f"QHeaderView {{ background: transparent; }}"
            f"QHeaderView::section {{"
            f"  background: {header_bg};"
            f"  color: {text};"
            f"  padding: 6px 4px;"
            f"  border: none;"
            f"  border-bottom: 1px solid {grid};"
            f"  font-weight: 600;"
            f"}}"
            f"QHeaderView::section:first {{ border-top-left-radius: 8px; }}"
            f"QHeaderView::section:last {{ border-top-right-radius: 8px; }}"
        )

    def sync_all_from_settings(self):
        """从 Settings 同步所有数据。"""
        self._apply_table_theme()
        self._refresh_track_combo()
        self._refresh_style_combo(self.batch_style_combo)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        if self._s.ustx_notes:
            self._build_table()
