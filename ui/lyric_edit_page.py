# lyric_edit_page.py — "歌词编辑" 导航页
"""批量编辑 + 歌词表格编辑。"""

import re
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeyEvent, QFocusEvent

from qfluentwidgets import (
    LineEdit, ComboBox,
    BodyLabel, StrongBodyLabel, HorizontalSeparator,
    InfoBar, InfoBarPosition, PrimaryPushButton, themeColor,
)

from core.settings_manager import SettingsManager


# ===================== 自定义表格（拦截左右键） =====================

class _StyleTableWidget(QTableWidget):
    """自定义 QTableWidget，将左右方向键转发给外部回调以切换样式。"""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self._building_table = False  # 防止重复建表
        self._handling_selection = False  # 防止选中回调递归
        self._table_built_for: Optional[list] = None  # 记录已建表的笔记引用，避免重复重建
        self._syncing_styles = False  # 防止同步样式时信号循环
        self._setup_ui()
        self._connect_signals()

    # ===================== UI 构建 =====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        # ========== 批量编辑 ==========
        layout.addWidget(StrongBodyLabel("/ 批量编辑"))

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
        layout.addLayout(row_idx)

        # 按音高筛选
        row_pitch = QHBoxLayout()
        row_pitch.setSpacing(8)
        row_pitch.addWidget(BodyLabel("按音高筛选:"))
        self.filter_pitch_start = LineEdit()
        self.filter_pitch_start.setPlaceholderText("起始音高")
        self.filter_pitch_start.setMaximumWidth(100)
        row_pitch.addWidget(self.filter_pitch_start)
        row_pitch.addWidget(BodyLabel("~"))
        self.filter_pitch_end = LineEdit()
        self.filter_pitch_end.setPlaceholderText("结束音高")
        self.filter_pitch_end.setMaximumWidth(100)
        row_pitch.addWidget(self.filter_pitch_end)
        row_pitch.addStretch()
        layout.addLayout(row_pitch)

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
        layout.addLayout(row_style)

        layout.addWidget(HorizontalSeparator())

        # ========== 歌词编辑 ==========
        layout.addWidget(StrongBodyLabel("/ 歌词编辑"))

        # 规则说明
        rule_row = QHBoxLayout()
        rule_row.setSpacing(8)
        rule_row.addWidget(BodyLabel("静默和结尾时显示始终应用样式1"))
        rule_row.addStretch()
        layout.addLayout(rule_row)

        # 操作提示
        hint_row = QHBoxLayout()
        hint_row.setSpacing(8)
        hint_row.addWidget(BodyLabel("提示: 选中单元格后，← → 切换样式，↑ ↓ 切换行"))
        hint_row.addStretch()
        layout.addLayout(hint_row)

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
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # 设置左右键回调
        self.table.set_style_key_callback(self._on_style_key)
        self._apply_table_theme()
        layout.addWidget(self.table, 1)

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
        current_style = self._note_styles.get(row, 0)
        if key == Qt.Key.Key_Left:
            new_style = (current_style - 1) % self._s.style_count
        else:
            new_style = (current_style + 1) % self._s.style_count
        self._note_styles[row] = new_style
        self._refresh_table_row(row, new_style)
        self.table.setCurrentCell(row, 3)
        self._sync_styles_to_settings()

    # ===================== 表格操作 =====================

    def _build_table(self):
        """根据音符数据重建表格。同批笔记不会重复建表，且保留已有样式。"""
        notes = self._s.ustx_notes
        if self._table_built_for is notes:
            return
        if self._building_table:
            return
        self._building_table = True
        try:
            self.table.currentItemChanged.disconnect(self._on_selection_changed)
        except (TypeError, RuntimeError):
            pass
        try:
            self.table.setUpdatesEnabled(False)
            self.table.setRowCount(len(notes))

            for i, note in enumerate(notes):
                # 序号（不可选中）
                idx_item = QTableWidgetItem(str(i + 1))
                idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                idx_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i, 0, idx_item)

                # 逐字歌词（不可选中）
                lyric = note.get("lyric", "")
                lyric_item = QTableWidgetItem(lyric)
                lyric_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                lyric_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i, 1, lyric_item)

                # 音高（不可选中）
                note_num = note.get("note_num", 0)
                pitch_name = midi_to_pitch(note_num)
                pitch_item = QTableWidgetItem(pitch_name)
                pitch_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                pitch_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i, 2, pitch_item)

                # 样式：保留已有样式，新音符默认样式1
                if i not in self._note_styles:
                    self._note_styles[i] = 0
                self._set_style_cell(i, self._note_styles[i])

            self._table_built_for = notes
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
        if 0 <= style_index < self._s.style_count:
            p = self._s.styles[style_index]
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
        """根据两种筛选条件获取交集行号集合。

        Returns:
            set: 匹配的行号集合
            None: 输入格式非法（已弹错误提示）
        """
        notes = self._s.ustx_notes
        if not notes:
            return set()

        idx_set: Optional[set] = None
        pitch_set: Optional[set] = None

        # 序号筛选
        start_text = self.filter_idx_start.text().strip()
        end_text = self.filter_idx_end.text().strip()
        if start_text or end_text:
            try:
                s = int(start_text) if start_text else 1
                e = int(end_text) if end_text else len(notes)
            except ValueError:
                InfoBar.error("格式错误", "序号筛选请输入整数", orient=Qt.Orientation.Vertical, duration=2000,
                              parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
                return None
            idx_set = set()
            for i in range(max(0, s - 1), min(e, len(notes))):
                idx_set.add(i)

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
            pitch_set = set()
            for i, note in enumerate(notes):
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
            return set(range(len(notes)))

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
            self._note_styles[row] = style_idx
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
        self._s.styles_changed.connect(self._on_styles_changed)
        self._s.note_styles_changed.connect(self._on_note_styles_changed)
        # 选中单元格时用强调色高亮（不依赖 stylesheet）
        self.table.currentItemChanged.connect(self._on_selection_changed)
        # 显式连接主题变更信号，解耦对 switchTo 隐式兜底的依赖
        self._s.theme_mode_changed.connect(self._apply_table_theme)

    def _on_notes_changed(self, notes: list):
        """音符数据更新时重建表格。

        ustx_notes 的 setter 仅清空 settings 层的 _note_styles，本页面的
        _note_styles 须在此处显式清空，否则 _build_table 的"保留已有样式"
        逻辑会让旧行号样式残留并被同步回 settings。
        """
        self._note_styles = {}  # 新音符数据 → 清空所有逐字样式
        self._table_built_for = None
        self._build_table()

    def _on_styles_changed(self):
        """样式变更时刷新样式下拉框及表格颜色。"""
        self._refresh_style_combo(self.batch_style_combo)
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            si = self._note_styles.get(row, 0)
            self._set_style_cell(row, si)
        self.table.setUpdatesEnabled(True)

    def _on_note_styles_changed(self, styles: dict):
        """外部修改了逐音符样式（如删除样式后重映射），刷新表格。"""
        if self._syncing_styles:
            return
        self._note_styles.update(styles)
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            si = self._note_styles.get(row, 0)
            self._set_style_cell(row, si)
        self.table.setUpdatesEnabled(True)

    def _on_selection_changed(self, current, previous):
        """选中单元格变化时：先清旧再设新，非样式列自动跳转。

        点击非样式列时调用 setCurrentCell 跳转到样式列，该调用会二次触发本回调
        并被 _handling_selection 守卫挡回，故跳转后的高亮须在守卫释放之后补做。
        """
        if self._handling_selection:
            return
        self._handling_selection = True
        pending = None
        try:
            if previous is not None:
                self._restore_item_color(previous)
            if current is not None and current.column() != 3:
                # 跳转样式列；二次回调会被守卫挡回，高亮留到守卫之外补做
                self.table.setCurrentCell(current.row(), 3)
                pending = self.table.item(current.row(), 3)
            elif current is not None:
                pending = current
        finally:
            self._handling_selection = False
        if pending is not None:
            self._highlight_item(pending)

    def _restore_item_color(self, item: QTableWidgetItem):
        """恢复单元格的原始颜色。只对样式列恢复样式色，其他列不动。"""
        if item.column() != 3:
            return
        si = self._note_styles.get(item.row(), 0)
        bg = self._style_bg_color(si)
        item.setBackground(bg)
        item.setForeground(self._contrast_foreground(bg))

    def _highlight_item(self, item: QTableWidgetItem):
        """用当前强调色高亮单元格。"""
        ac = QColor(themeColor().name())
        item.setBackground(ac)
        item.setForeground(QColor("#ffffff"))

    def _refresh_style_combo(self, combo: ComboBox):
        """刷新样式下拉框（同步样式列表）。"""
        combo.blockSignals(True)
        combo.clear()
        for i in range(self._s.style_count):
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
            self._s.note_styles = dict(self._note_styles)
        finally:
            self._syncing_styles = False

    def _apply_table_theme(self):
        """根据当前主题设置表格样式，表格背景透明与界面融合。"""
        from qfluentwidgets import qconfig, Theme
        is_dark = qconfig.theme == Theme.DARK
        alt = "#252525" if is_dark else "#f0f0f0"
        text = "#ffffff" if is_dark else "#000000"
        self.table.setStyleSheet(
            f"QTableWidget {{ background: transparent; border: none; color: {text}; gridline-color: {alt}; }}"
            f"QHeaderView::section {{ background: {alt}; color: {text}; padding: 4px; border: none; }}"
        )

    def sync_all_from_settings(self):
        """从 Settings 同步所有数据。"""
        self._apply_table_theme()
        self._refresh_style_combo(self.batch_style_combo)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        if self._s.ustx_notes:
            self._build_table()
