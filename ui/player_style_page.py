# player_style_page.py — "播放器" 导航页
"""颜色样式（多样式切换） + 显示设置。"""

import os
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics

from qfluentwidgets import (
    LineEdit, ComboBox, ColorPickerButton, PushButton, CheckBox,
    BodyLabel, StrongBodyLabel, HorizontalSeparator,
    InfoBar, InfoBarPosition,
)
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu
from qfluentwidgets.components.widgets.menu import MenuAnimationType

from core.settings_manager import SettingsManager

# 样式对应的四个颜色键
STYLE_COLOR_KEYS = ["bg_color", "note_color", "lyric_color", "pitch_curve_color"]
STYLE_COLOR_LABELS = {
    "bg_color": "背景色:",
    "note_color": "音名色:",
    "lyric_color": "逐字歌词色:",
    "pitch_curve_color": "音高线颜色:",
}


class _FontComboMenu(ComboBoxMenu):
    """字体下拉菜单：创建菜单项时按字体名设置该项字体，实现下拉预览。

    给每个 item setFont() 即可让该项以该字体渲染预览；选中竖条由库
    IndicatorMenuItemDelegate 用 themeColor() 自动绘制，暗色适配与风格一致。
    """

    def _createActionItem(self, action, before=None):
        item = super()._createActionItem(action, before)
        name = action.text()
        if name and name != "自定义...":
            font = QFont(name, 11)
            item.setFont(font)
            # 用预览字体的 metrics 重算宽度，避免字体名较宽时被裁剪
            fm = QFontMetrics(font)
            w = 40 + fm.horizontalAdvance(name)
            if w > item.sizeHint().width():
                item.setSizeHint(QSize(w, item.sizeHint().height()))
        return item

    def exec(self, pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):
        # 子类化后 PySide6 shiboken 会将实例 exec 解析回 C++ QMenu.exec
        # （静态+实例双重方法），导致 aniType 关键字参数不被接受、下拉框无法弹出。
        # 显式重写 exec 转发到 ComboBoxMenu.exec（Python 函数）绕过此问题。
        return ComboBoxMenu.exec(self, pos, ani, aniType)


class _FontComboBox(ComboBox):
    """字体选择下拉框：使用自定义菜单以启用每项字体预览。"""

    def _createComboMenu(self):
        return _FontComboMenu(self)


class PlayerStylePage(QWidget):
    """播放器样式标签页 — 颜色样式 + 全局背景 + 显示设置。"""

    def __init__(self, settings: SettingsManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._s = settings
        self._color_edits: dict = {}  # key → LineEdit
        self._color_pickers: dict = {}  # key → ColorPickerButton
        self._updating_style = False  # 防止循环信号
        self._path_to_family: dict = {}  # 自定义字体路径→family 映射，避免重复 addApplicationFont
        self._setup_ui()
        self._connect_signals()

    # ===================== UI 构建 =====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        # ========== 全局背景 ==========
        layout.addWidget(StrongBodyLabel("/ 全局背景"))
        row_global = QHBoxLayout()
        row_global.setSpacing(8)
        row_global.addWidget(BodyLabel("统一背景色:"))
        self.global_bg_edit = LineEdit()
        self.global_bg_edit.setText(self._s.global_bg_color)
        self.global_bg_edit.setMaximumWidth(100)
        row_global.addWidget(self.global_bg_edit)
        self.global_bg_picker = ColorPickerButton(
            QColor(self._s.global_bg_color), "选择全局背景色", self
        )
        row_global.addWidget(self.global_bg_picker)
        self.global_bg_check = CheckBox("应用到所有样式")
        self.global_bg_check.setChecked(self._s.global_bg_enabled)
        row_global.addWidget(self.global_bg_check)
        row_global.addStretch()
        layout.addLayout(row_global)
        layout.addWidget(HorizontalSeparator())

        # ========== 颜色样式 ==========
        layout.addWidget(StrongBodyLabel("/ 颜色样式"))

        # 样式选择 + 新建按钮
        row_style = QHBoxLayout()
        row_style.setSpacing(8)
        row_style.addWidget(BodyLabel("当前样式:"))
        self.style_combo = ComboBox()
        self._refresh_style_combo()
        row_style.addWidget(self.style_combo)
        self.new_style_btn = PushButton("新建样式")
        row_style.addWidget(self.new_style_btn)
        self.delete_style_btn = PushButton("删除样式")
        row_style.addWidget(self.delete_style_btn)
        row_style.addStretch()
        layout.addLayout(row_style)

        # 当前样式的 4 个颜色编辑区
        for key in STYLE_COLOR_KEYS:
            self._add_color_row(layout, STYLE_COLOR_LABELS[key], key)

        layout.addWidget(HorizontalSeparator())

        # ========== 显示设置 ==========
        layout.addWidget(StrongBodyLabel("/ 显示设置"))

        # 逐字歌词字体（显示设置最上方，控制播放器中央大字）
        self._builtin_fonts = ["等线", "微软雅黑", "黑体", "得意黑"]
        self.word_lyric_font_combo = self._add_font_row(layout, "逐字歌词字体:")
        self.word_lyric_font_combo.setCurrentText(self._s.word_lyric_font_family)

        # 歌词位置
        row_lyric = QHBoxLayout()
        row_lyric.setSpacing(8)
        row_lyric.addWidget(BodyLabel("歌词位置:"))
        self.lyric_pos_combo = ComboBox()
        self.lyric_pos_combo.addItems(["上", "下"])
        self.lyric_pos_combo.setCurrentText(self._s.lyric_pos)
        row_lyric.addWidget(self.lyric_pos_combo)
        row_lyric.addStretch()
        layout.addLayout(row_lyric)

        # 歌词及信息字体（歌词位置下方，控制 LRC 歌词、音名、BPM、时间、版权等）
        self.info_font_combo = self._add_font_row(layout, "歌词及信息字体:")
        self.info_font_combo.setCurrentText(self._s.info_font_family)

        # 歌词及信息颜色（独立于样式，默认白色）
        self._add_color_row(layout, "歌词及信息颜色:", "info_text_color")

        self._add_combo_with_custom(
            layout, "音高间占位符:", "pitch_placeholder",
            ["无", "-", "自定义文字"],
            self._s.pitch_placeholder, "pitch_custom",
        )
        self._add_combo_with_custom(
            layout, "静默时显示:", "silent_display",
            ["R", "♪", "-", "自定义文字", "什么都不显示"],
            self._s.silent_display, "silent_custom",
        )
        self._add_combo_with_custom(
            layout, "结束时显示:", "end_display",
            ["END", "-", "自定义文字", "什么都不显示"],
            self._s.end_display, "end_custom",
        )

        layout.addStretch()

    def _add_color_row(self, parent, label, key):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel(label))
        edit = LineEdit()
        edit.setMaximumWidth(100)
        self._color_edits[key] = edit
        row.addWidget(edit)
        picker = ColorPickerButton(QColor("#ffffff"), f"选择{label}", self)
        self._color_pickers[key] = picker
        row.addWidget(picker)
        row.addStretch()
        parent.addLayout(row)
        return edit, picker

    def _add_font_row(self, parent, label: str) -> ComboBox:
        """添加字体选择行（内置字体 + 自定义...），返回 combo。

        初始 setCurrentText 由调用方在调用后单独设置。
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel(label))
        combo = _FontComboBox()
        combo.addItems(self._builtin_fonts)
        combo.addItem("自定义...")
        row.addWidget(combo)
        row.addStretch()
        parent.addLayout(row)
        return combo

    def _add_combo_with_custom(self, parent, label, attr, options, init_value, custom_attr):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel(label))
        combo = ComboBox()
        combo.addItems(options)
        setattr(self, f"combo_{attr}", combo)
        row.addWidget(combo)
        custom_edit = LineEdit()
        custom_edit.setPlaceholderText("自定义文字...")
        custom_edit.setMaximumWidth(150)
        custom_edit.setVisible(init_value == "自定义文字")
        setattr(self, f"edit_{custom_attr}", custom_edit)
        row.addWidget(custom_edit)
        row.addStretch()
        parent.addLayout(row)

    # ===================== 信号绑定 =====================

    def _connect_signals(self):
        s = self._s

        # ---- 全局背景 ----
        self._bind_global_bg()

        # ---- 样式切换 ----
        self.style_combo.currentIndexChanged.connect(self._on_style_switched)
        self.new_style_btn.clicked.connect(self._on_new_style)
        self.delete_style_btn.clicked.connect(self._on_delete_style)

        # ---- 样式颜色编辑（4 个 key） ----
        for key in STYLE_COLOR_KEYS:
            self._bind_style_color(key)

        # ---- LRC 歌词颜色（独立于样式） ----
        self._bind_simple_color("info_text_color")

        # ---- 显示设置 ----
        self.lyric_pos_combo.currentTextChanged.connect(
            lambda v: setattr(s, "lyric_pos", v)
        )
        # textActivated 仅用户手动选择触发，避免 sync 时 setCurrentText 引发多余写入
        self.word_lyric_font_combo.textActivated.connect(
            lambda t: self._on_font_changed(self.word_lyric_font_combo, "word_lyric_font_family", t)
        )
        self.info_font_combo.textActivated.connect(
            lambda t: self._on_font_changed(self.info_font_combo, "info_font_family", t)
        )

        self._bind_combo_with_custom("pitch_placeholder", "pitch_custom")
        self._bind_combo_with_custom("silent_display", "silent_custom")
        self._bind_combo_with_custom("end_display", "end_custom")

        # 自定义文本编辑
        for attr_name in ("pitch_custom", "silent_custom", "end_custom"):
            edit = getattr(self, f"edit_{attr_name}", None)
            if edit:
                prop_name = f"{attr_name}_text"
                current = getattr(s, prop_name, "")
                edit.setText(current)
                edit.textChanged.connect(
                    lambda v, pn=prop_name: setattr(s, pn, v)
                )

        # ---- Settings 数据变更 → UI 刷新 ----
        # 样式增删由 _on_new_style / _on_delete_style 单独处理，不在 styles_changed 全量刷新颜色字段
        s.active_style_index_changed.connect(self._on_active_style_changed_external)

    def _bind_color_pair(self, edit, picker, setter):
        """通用颜色 Edit+Picker 双向绑定。

        setter(str): 颜色变更时写入数据源。初始化由各调用方自行完成。
        """
        def on_edit(v):
            setter(v)
            picker.blockSignals(True)
            c = QColor(v)
            if c.isValid():
                picker.setColor(c)
            picker.blockSignals(False)

        def on_picker(c):
            h = c.name()
            setter(h)
            edit.blockSignals(True)
            edit.setText(h)
            edit.blockSignals(False)

        edit.textChanged.connect(on_edit)
        picker.colorChanged.connect(on_picker)

    def _bind_global_bg(self):
        """绑定全局背景色编辑器和选择器。"""
        s = self._s
        self._bind_color_pair(
            self.global_bg_edit, self.global_bg_picker,
            lambda v: setattr(s, "global_bg_color", v),
        )
        # qfluentwidgets CheckBox 的 stateChanged 可能不触发，统一用 checkStateChanged
        self.global_bg_check.checkStateChanged.connect(
            lambda st: setattr(s, "global_bg_enabled", st == Qt.CheckState.Checked)
        )

    def _bind_simple_color(self, key: str):
        """绑定非样式颜色（直接读写 settings 属性）。"""
        edit = self._color_edits.get(key)
        picker = self._color_pickers.get(key)
        if not edit or not picker:
            return
        s = self._s
        # 初始化控件值
        init_val = getattr(s, key, "#ffffff")
        edit.setText(init_val)
        picker.setColor(QColor(init_val))
        self._bind_color_pair(
            edit, picker, lambda v, k=key: setattr(s, k, v),
        )

    def _bind_style_color(self, key: str):
        """绑定单个样式颜色：编辑器和选择器变更 → 写入当前激活样式。"""
        edit = self._color_edits[key]
        picker = self._color_pickers[key]
        s = self._s

        def setter(v):
            s.set_style_color(s.active_style_index, key, v)

        self._bind_color_pair(edit, picker, setter)

    def _bind_combo_with_custom(self, attr, custom_attr):
        combo = getattr(self, f"combo_{attr}")
        custom_edit = getattr(self, f"edit_{custom_attr}")

        current_val = getattr(self._s, attr)
        combo.setCurrentText(current_val)

        def on_change(value):
            setattr(self._s, attr, value)
            custom_edit.setVisible(value == "自定义文字")

        combo.currentTextChanged.connect(on_change)
        custom_edit.setVisible(combo.currentText() == "自定义文字")

    # ===================== 字体操作 =====================

    def _on_font_changed(self, combo: ComboBox, attr: str, text: str):
        """字体选择变更。选择"自定义..."时弹出文件对话框加载字体。

        combo/attr 参数化以支持逐字歌词字体与歌词及信息字体两个独立选择器。
        """
        if text == "自定义...":
            combo.blockSignals(True)
            combo.setCurrentText(getattr(self._s, attr))
            combo.blockSignals(False)
            QTimer.singleShot(0, lambda: self._open_font_dialog(combo, attr))
            return
        setattr(self._s, attr, text)
        # 缺失字体会被 Qt 静默回退，此处检测并提示
        if not QFontDatabase.hasFamily(text):
            InfoBar.warning(
                "提示", f"字体「{text}」未在本机安装，将使用回退字体显示",
                orient=Qt.Orientation.Vertical, duration=2500, parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
            )

    def _open_font_dialog(self, combo: ComboBox, attr: str):
        """打开文件对话框选择字体文件（.ttf/.otf）。

        Windows 原生文件对话框打开 C:\\Windows\\Fonts 时文件列表为空
        （该目录是 shell 虚拟文件夹），故用非原生对话框。
        """
        fonts_dir = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'Fonts')
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择字体文件", fonts_dir,
            "字体文件 (*.ttf *.otf);;所有文件 (*.*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not file_path:
            return
        self._load_custom_font(combo, attr, file_path)

    def _apply_custom_font(self, file_path: str) -> Optional[str]:
        """加载字体文件并插入两个选择框，返回首个 family 名（失败返回 None）。

        addApplicationFont 全局生效。通过 _path_to_family 记录路径→family 映射，
        已加载过的路径不重复 addApplicationFont。
        """
        if not file_path or not os.path.isfile(file_path):
            return None
        # 已加载过：直接用记录的 family 插入
        if file_path in self._path_to_family:
            family = self._path_to_family[file_path]
            for c in (self.word_lyric_font_combo, self.info_font_combo):
                if c.findText(family) < 0:
                    c.insertItem(c.count() - 1, family)
            return family
        # 首次加载
        font_id = QFontDatabase.addApplicationFont(file_path)
        if font_id == -1:
            return None
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            return None
        family = families[0]
        self._path_to_family[file_path] = family
        for c in (self.word_lyric_font_combo, self.info_font_combo):
            if c.findText(family) < 0:
                c.insertItem(c.count() - 1, family)  # 在"自定义..."之前
        return family

    def _load_custom_font(self, combo: ComboBox, attr: str, file_path: str):
        """加载自定义字体文件并同步到两个字体选择框，路径记入工程文件。

        路径写入 settings.custom_font_paths，导出 .uplr 时随之保存。
        """
        family = self._apply_custom_font(file_path)
        if family is None:
            InfoBar.error("错误", "无法加载字体文件", orient=Qt.Orientation.Vertical, duration=2000,
                          parent=self.window(), position=InfoBarPosition.TOP_RIGHT)
            return
        combo.setCurrentText(family)
        setattr(self._s, attr, family)
        # 路径记入工程文件（去重）
        if file_path not in self._s.custom_font_paths:
            self._s.custom_font_paths = self._s.custom_font_paths + [file_path]

    def restore_custom_fonts(self):
        """根据 settings.custom_font_paths 重建两个选择框的自定义字体项。

        导入 .uplr 后由 sync_all_from_settings 调用：先清理旧的自定义字体项
        （保留内置字体与"自定义..."），再按路径重新加载并插入。
        """
        builtin = set(self._builtin_fonts) | {"自定义..."}
        # 清理旧的自定义字体项（从后往前删，避免索引错乱）
        for c in (self.word_lyric_font_combo, self.info_font_combo):
            for i in range(c.count() - 1, -1, -1):
                if c.itemText(i) not in builtin:
                    c.removeItem(i)
        # 重新加载当前工程的自定义字体
        for path in self._s.custom_font_paths:
            self._apply_custom_font(path)

    # ===================== 样式操作 =====================

    def _refresh_style_combo(self):
        """刷新样式下拉框的选项列表。"""
        self.style_combo.blockSignals(True)
        self.style_combo.clear()
        for i in range(self._s.style_count):
            self.style_combo.addItem(f"样式{i + 1}")
        self.style_combo.setCurrentIndex(self._s.active_style_index)
        self.style_combo.blockSignals(False)

    def _on_style_switched(self, index: int):
        """用户在 UI 切换样式下拉框。"""
        if index < 0 or index >= self._s.style_count:
            return
        if self._updating_style:
            return
        self._updating_style = True
        try:
            self._s.active_style_index = index
            self._load_style_colors(index)
        finally:
            self._updating_style = False

    def _on_active_style_changed_external(self, index: int):
        """外部（如 import_uplr）修改了 active_style_index。"""
        if self._updating_style:
            return
        self._updating_style = True
        try:
            if self.style_combo.currentIndex() != index:
                self.style_combo.blockSignals(True)
                self.style_combo.setCurrentIndex(index)
                self.style_combo.blockSignals(False)
            self._load_style_colors(index)
        finally:
            self._updating_style = False

    def _on_new_style(self):
        """新建样式（复制样式1颜色，命名为样式N）。"""
        new_idx = self._s.add_style()
        self._refresh_style_combo()
        self._s.active_style_index = new_idx
        self.style_combo.setCurrentIndex(new_idx)
        self._load_style_colors(new_idx)

    def _on_delete_style(self):
        """删除当前选中的样式（前3个默认样式不可删除）。"""
        idx = self._s.active_style_index
        if idx < 3:
            InfoBar.warning(
                "提示", "默认样式不可删除（样式1-3）",
                orient=Qt.Orientation.Vertical, duration=2000, parent=self.window(),
            )
            return
        success = self._s.remove_style(idx)
        if success:
            self._refresh_style_combo()
            self.style_combo.setCurrentIndex(self._s.active_style_index)
            self._load_style_colors(self._s.active_style_index)

    def _load_style_colors(self, index: int):
        """将指定样式的颜色加载到 UI 控件中。"""
        if index < 0 or index >= self._s.style_count:
            return
        style = self._s.styles[index]
        for key in STYLE_COLOR_KEYS:
            color = style.get(key, "#ffffff")
            edit = self._color_edits.get(key)
            picker = self._color_pickers.get(key)
            if edit:
                edit.blockSignals(True)
                edit.setText(color)
                edit.blockSignals(False)
            if picker:
                picker.blockSignals(True)
                c = QColor(color)
                if c.isValid():
                    picker.setColor(c)
                picker.blockSignals(False)

    # ===================== 同步 =====================

    def sync_all_from_settings(self):
        """从 SettingsManager 同步所有 UI 控件。"""
        s = self._s

        # 全局背景
        self.global_bg_edit.blockSignals(True)
        self.global_bg_edit.setText(s.global_bg_color)
        self.global_bg_edit.blockSignals(False)
        self.global_bg_picker.blockSignals(True)
        c = QColor(s.global_bg_color)
        if c.isValid():
            self.global_bg_picker.setColor(c)
        self.global_bg_picker.blockSignals(False)
        # blockSignals 避免 setChecked 反向写回 settings
        self.global_bg_check.blockSignals(True)
        self.global_bg_check.setChecked(s.global_bg_enabled)
        self.global_bg_check.blockSignals(False)

        # LRC 歌词颜色（独立于样式）
        edit_info = self._color_edits.get("info_text_color")
        picker_info = self._color_pickers.get("info_text_color")
        if edit_info and picker_info:
            edit_info.blockSignals(True)
            edit_info.setText(s.info_text_color)
            edit_info.blockSignals(False)
            picker_info.blockSignals(True)
            c = QColor(s.info_text_color)
            if c.isValid():
                picker_info.setColor(c)
            picker_info.blockSignals(False)

        # 样式下拉框 & 颜色
        self._refresh_style_combo()
        self._load_style_colors(s.active_style_index)

        # 显示设置
        self.lyric_pos_combo.setCurrentText(s.lyric_pos)
        # 须在 setCurrentText 之前恢复自定义字体项，否则 family 不在列表无法选中
        self.restore_custom_fonts()
        self.word_lyric_font_combo.setCurrentText(s.word_lyric_font_family)
        self.info_font_combo.setCurrentText(s.info_font_family)

        for attr, custom_attr in [
            ("pitch_placeholder", "pitch_custom"),
            ("silent_display", "silent_custom"),
            ("end_display", "end_custom"),
        ]:
            combo = getattr(self, f"combo_{attr}")
            combo.setCurrentText(getattr(s, attr))
            edit = getattr(self, f"edit_{custom_attr}")
            edit.setText(getattr(s, f"{custom_attr}_text"))
            edit.setVisible(getattr(s, attr) == "自定义文字")
