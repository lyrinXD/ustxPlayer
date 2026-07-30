# other_page.py — "其他" 导航页
"""主题与强调色、快捷键、外部工具、关于软件（含协议许可）。"""

import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PySide6.QtGui import QColor

from qfluentwidgets import (
    PushButton, BodyLabel, StrongBodyLabel, HorizontalSeparator,
    ComboBox, ColorPickerButton, HyperlinkButton,
    InfoBar, InfoBarPosition,
)

from core.settings_manager import SettingsManager


class OtherPage(QWidget):
    """其他标签页 — 主题/快捷键/工具/关于软件。"""

    def __init__(self, settings: SettingsManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._s = settings
        self._setup_ui()
        self._connect_signals()

    # ===================== UI 构建 =====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ---- 主题设置 ----
        layout.addWidget(StrongBodyLabel("/ 主题"))

        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        theme_row.addWidget(BodyLabel("应用主题:"))
        self.theme_combo = ComboBox()
        self.theme_combo.addItems(["跟随系统", "亮色", "暗色"])
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        # ---- 强调色设置 ----
        accent_mode_row = QHBoxLayout()
        accent_mode_row.setSpacing(8)
        accent_mode_row.addWidget(BodyLabel("强调色:"))
        self.accent_color_mode_combo = ComboBox()
        self.accent_color_mode_combo.addItems(["跟随系统", "自定义"])
        accent_mode_row.addWidget(self.accent_color_mode_combo)
        accent_mode_row.addStretch()
        layout.addLayout(accent_mode_row)

        accent_custom_row = QHBoxLayout()
        accent_custom_row.setSpacing(8)
        self._accent_custom_label = BodyLabel("自定义颜色:")
        accent_custom_row.addWidget(self._accent_custom_label)
        self.accent_color_picker = ColorPickerButton(
            QColor(self._s.custom_accent_color), "选择强调色", self
        )
        accent_custom_row.addWidget(self.accent_color_picker)
        accent_custom_row.addStretch()
        layout.addLayout(accent_custom_row)

        layout.addWidget(HorizontalSeparator())

        # ---- 快捷键说明 ----
        layout.addWidget(StrongBodyLabel("/ 播放器快捷键"))
        shortcuts_text = BodyLabel(
            "ESC : 退出\n"
            "空格 : 播放/暂停    X : 倍速-0.1    C : 倍速+0.1    Z : 还原1倍\n"
            "↑ ↓ : 系统音量    ← → : 快退/快进10秒"
        )
        shortcuts_text.setWordWrap(True)
        layout.addWidget(shortcuts_text)

        layout.addWidget(HorizontalSeparator())

        # ---- 外部工具 ----
        layout.addWidget(StrongBodyLabel("/ 外部工具"))

        tool_row = QHBoxLayout()
        tool_row.setSpacing(12)

        uf_btn = PushButton("UtaFormatix")
        uf_btn.clicked.connect(lambda: self._open_url("https://utaformatix.tk/"))
        tool_row.addWidget(uf_btn)

        ml_btn = PushButton("163MusicLyrics")
        ml_btn.clicked.connect(lambda: self._open_url("https://github.com/jitwxs/163MusicLyrics/"))
        tool_row.addWidget(ml_btn)

        v2m_btn = PushButton("Vocal2Midi")
        v2m_btn.clicked.connect(lambda: self._open_url("https://www.bilibili.com/video/BV1Ww7C6kEqL/"))
        tool_row.addWidget(v2m_btn)

        sig_btn = PushButton("signal")
        sig_btn.clicked.connect(lambda: self._open_url("https://signalmidi.app/edit"))
        tool_row.addWidget(sig_btn)

        tool_row.addStretch()
        layout.addLayout(tool_row)

        layout.addWidget(HorizontalSeparator())

        # ---- 关于软件（含协议与许可）----
        layout.addWidget(StrongBodyLabel("/ 关于软件"))

        # 衍生项目说明
        derive_label = BodyLabel("本项目（ustxPlayer）是基于 ustPlayer 的衍生项目")
        layout.addWidget(derive_label)

        # 第一行：原项目 + GitHub仓库
        orig_row = QHBoxLayout()
        orig_row.setSpacing(12)
        orig_row.addWidget(BodyLabel("原项目:"))
        orig_row.addWidget(HyperlinkButton(
            "https://space.bilibili.com/661930756",
            "ustPlayer - v26f19 (c) 2026 SYEternal_R && 灰棱HiRenG"
        ))
        orig_row.addWidget(HyperlinkButton(
            "https://github.com/SYEternalR/ustPlayer", "GitHub仓库"
        ))
        orig_row.addStretch()
        layout.addLayout(orig_row)

        # 第二行：本项目 + GitHub仓库
        proj_row = QHBoxLayout()
        proj_row.setSpacing(12)
        proj_row.addWidget(BodyLabel("本项目:"))
        proj_row.addWidget(HyperlinkButton(
            "https://space.bilibili.com/1398756020", "ustxPlayer - v26g30 (c) 2026 SYEternal_R && 灰棱HiRenG && lyrinXD"
        ))
        proj_row.addWidget(HyperlinkButton(
            "https://github.com/lyrinXD/ustxPlayer", "GitHub仓库"
        ))
        proj_row.addStretch()
        layout.addLayout(proj_row)

        # 最后一行：协议说明 + 使用协议（超链接样式，点击用系统默认程序打开）
        lic_row = QHBoxLayout()
        lic_row.setSpacing(12)
        lic_row.addWidget(BodyLabel("本项目沿用原项目的使用协议"))
        lic_row.addWidget(HyperlinkButton(
            QUrl.fromLocalFile(self._s.terms_file_path).toString(), "使用协议"
        ))
        lic_row.addStretch()
        layout.addLayout(lic_row)

        layout.addWidget(HorizontalSeparator())

        # 彩蛋
        easter = BodyLabel("你知道吗：alpha版本在提交至托管时曾被错误地命名为ustPlyaer。orz")
        easter.setWordWrap(True)
        layout.addWidget(easter)

        layout.addStretch()

    # ===================== 信号绑定 =====================

    def _connect_signals(self):
        s = self._s

        # 主题下拉框
        self.theme_combo.setCurrentText(self._theme_combo_text(s.theme_mode))
        self.theme_combo.currentTextChanged.connect(self._on_theme_combo_changed)
        s.theme_mode_changed.connect(self._on_settings_theme_mode_changed)

        # 强调色模式下拉框
        self.accent_color_mode_combo.setCurrentText(
            self._accent_mode_text(s.accent_color_mode)
        )
        self.accent_color_mode_combo.currentTextChanged.connect(
            self._on_accent_color_mode_combo_changed
        )
        s.accent_color_mode_changed.connect(self._on_settings_accent_mode_changed)

        # 自定义颜色选择器
        self.accent_color_picker.colorChanged.connect(self._on_accent_color_pick)
        s.custom_accent_color_changed.connect(self._on_settings_accent_color_changed)

        # 初始时根据模式显示/隐藏自定义颜色选择器
        self._update_accent_custom_visible(s.accent_color_mode)

    # ===================== 业务逻辑 =====================

    def _on_theme_combo_changed(self, text: str):
        """主题下拉框变化 → 更新 settings.theme_mode。"""
        mode = self._theme_combo_mode(text)
        self._s.theme_mode = mode

    def _on_accent_color_mode_combo_changed(self, text: str):
        """强调色模式变化 → 更新 settings。"""
        mode = self._accent_mode_value(text)
        self._s.accent_color_mode = mode
        self._update_accent_custom_visible(mode)

    def _on_accent_color_pick(self, color: QColor):
        """自定义颜色选择 → 更新 settings。"""
        self._s.custom_accent_color = color.name()

    def _update_accent_custom_visible(self, mode: str):
        """自定义模式下显示颜色选择器，跟随系统时隐藏整行。"""
        visible = mode == "custom"
        self._accent_custom_label.setVisible(visible)
        self.accent_color_picker.setVisible(visible)

    def _on_settings_theme_mode_changed(self, v: str):
        """settings 端主题模式变化 → 同步下拉框。"""
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentText(self._theme_combo_text(v))
        self.theme_combo.blockSignals(False)

    def _on_settings_accent_mode_changed(self, v: str):
        """settings 端强调色模式变化 → 同步下拉框。"""
        self.accent_color_mode_combo.blockSignals(True)
        self.accent_color_mode_combo.setCurrentText(self._accent_mode_text(v))
        self.accent_color_mode_combo.blockSignals(False)
        self._update_accent_custom_visible(v)

    def _on_settings_accent_color_changed(self, v: str):
        """settings 端自定义强调色变化 → 同步取色器。"""
        self.accent_color_picker.blockSignals(True)
        self.accent_color_picker.setColor(QColor(v))
        self.accent_color_picker.blockSignals(False)

    # ===================== 辅助方法 =====================

    @staticmethod
    def _theme_combo_text(mode: str) -> str:
        return {"auto": "跟随系统", "light": "亮色", "dark": "暗色"}.get(mode, "跟随系统")

    @staticmethod
    def _theme_combo_mode(text: str) -> str:
        return {"跟随系统": "auto", "亮色": "light", "暗色": "dark"}.get(text, "auto")

    @staticmethod
    def _accent_mode_text(mode: str) -> str:
        return {"auto": "跟随系统", "custom": "自定义"}.get(mode, "跟随系统")

    @staticmethod
    def _accent_mode_value(text: str) -> str:
        return {"跟随系统": "auto", "自定义": "custom"}.get(text, "auto")

    # ===================== 工具方法 =====================

    def _open_url(self, url: str):
        try:
            webbrowser.open_new_tab(url)
        except Exception as e:
            InfoBar.error("ERcode003", f"打开网页失败：{e}", orient=Qt.Orientation.Vertical, duration=3000,
                          parent=self.window(), position=InfoBarPosition.TOP_RIGHT)

    # ===================== 同步 =====================

    def sync_all_from_settings(self):
        """从 settings 同步所有 UI 控件（导入 uplr 或导航切换后调用）。"""
        s = self._s
        self.theme_combo.setCurrentText(self._theme_combo_text(s.theme_mode))
        self.accent_color_mode_combo.setCurrentText(
            self._accent_mode_text(s.accent_color_mode)
        )
        self.accent_color_picker.setColor(QColor(s.custom_accent_color))
        self._update_accent_custom_visible(s.accent_color_mode)