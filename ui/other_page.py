# other_page.py — "其他" 导航页
"""主题与强调色、快捷键、外部工具、关于项目（含协议许可）。"""

import os
import time
import webbrowser
import datetime
import threading
import urllib.request
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PySide6.QtGui import QColor, QPainter, QPen, QFontMetrics

from qfluentwidgets import (
    PushButton, BodyLabel, SwitchButton,
    ComboBox, ColorPickerButton, HyperlinkButton,
    InfoBar, InfoBarPosition, isDarkTheme,
)
from qfluentwidgets.common.config import qconfig

from core.app_icons import apply_icon, icon_files
from core.settings_manager import SettingsManager
from core.renderer_core import APP_VERSION
from ui.accent_card import AccentHeaderCardWidget, PAGE_MARGIN, PAGE_SPACING


# 远端版本号：与本地根目录 VERSION 文件同构（单一真相源）
_UPDATE_URL = "https://raw.githubusercontent.com/lyrinXD/ustxPlayer/main/VERSION"


def _fetch_latest_version(timeout: float = 8.0) -> Optional[str]:
    """请求远端 VERSION，返回版本字符串；网络失败返回 None。"""
    try:
        req = urllib.request.Request(
            _UPDATE_URL, headers={"User-Agent": "ustxPlayer/update-check"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return resp.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return None


class _KeyCap(QWidget):
    """键帽样式：自绘圆角底 + 中性色细描边，随深浅色切换自动重绘。

    paintEvent 每次读取最新 isDarkTheme()，颜色为中性色（不掺强调色），
    监听 themeChanged 触发 update()，切主题即时生效且不会被全局 QSS 覆盖。
    """

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        fm = QFontMetrics(self.font())
        self.setFixedSize(fm.horizontalAdvance(text) + 16, fm.height() + 8)
        qconfig.themeChanged.connect(self.update)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        if isDarkTheme():
            fill, border, fg = QColor(255, 255, 255, 28), QColor(255, 255, 255, 60), QColor(255, 255, 255)
        else:
            fill, border, fg = QColor(0, 0, 0, 12), QColor(0, 0, 0, 45), QColor(31, 31, 31)
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)
        painter.setPen(fg)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class OtherPage(QWidget):
    """其他标签页 — 主题/快捷键/工具/关于项目。"""

    _update_result = Signal(object)  # (latest, auto)

    def __init__(self, settings: SettingsManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._s = settings
        self._checking = False
        self._setup_ui()
        self._connect_signals()

    # ===================== UI 构建 =====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGIN)
        layout.setSpacing(PAGE_SPACING)

        # ---- 主题卡片 ----
        theme_card = AccentHeaderCardWidget("主题")
        theme_vbox = QVBoxLayout()
        theme_vbox.setSpacing(8)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        theme_row.addWidget(BodyLabel("应用主题:"))
        self.theme_combo = ComboBox()
        self.theme_combo.addItems(["跟随系统", "亮色", "暗色"])
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        theme_vbox.addLayout(theme_row)

        # ---- 强调色设置 ----
        accent_mode_row = QHBoxLayout()
        accent_mode_row.setSpacing(8)
        accent_mode_row.addWidget(BodyLabel("强调色:"))
        self.accent_color_mode_combo = ComboBox()
        self.accent_color_mode_combo.addItems(["跟随系统", "自定义"])
        accent_mode_row.addWidget(self.accent_color_mode_combo)
        accent_mode_row.addStretch()
        theme_vbox.addLayout(accent_mode_row)

        accent_custom_row = QHBoxLayout()
        accent_custom_row.setSpacing(8)
        self._accent_custom_label = BodyLabel("自定义颜色:")
        accent_custom_row.addWidget(self._accent_custom_label)
        self.accent_color_picker = ColorPickerButton(
            QColor(self._s.theme.custom_accent_color), "强调色", self
        )
        accent_custom_row.addWidget(self.accent_color_picker)
        accent_custom_row.addStretch()
        theme_vbox.addLayout(accent_custom_row)

        card_shadow_row = QHBoxLayout()
        card_shadow_row.setSpacing(8)
        card_shadow_row.addWidget(BodyLabel("卡片阴影"))
        self.sw_card_shadow = SwitchButton()
        self.sw_card_shadow.setChecked(self._s.theme.card_shadow_enabled)
        card_shadow_row.addWidget(self.sw_card_shadow)
        card_shadow_row.addStretch()
        theme_vbox.addLayout(card_shadow_row)
        theme_card.viewLayout.addLayout(theme_vbox)
        layout.addWidget(theme_card)

        # ---- 快捷键卡片 ----
        shortcut_card = AccentHeaderCardWidget("播放器快捷键")
        shortcut_vbox = QVBoxLayout()
        shortcut_vbox.setSpacing(8)

        def _shortcut_row(*groups):
            """一行内放入若干「键帽 + 说明」组，组间留较大间距。"""
            row = QHBoxLayout()
            row.setSpacing(8)
            for i, (keys, desc) in enumerate(groups):
                if i:
                    row.addSpacing(18)
                for k in keys:
                    row.addWidget(_KeyCap(k))
                row.addWidget(BodyLabel(desc))
            row.addStretch()
            shortcut_vbox.addLayout(row)

        _shortcut_row((["ESC"], "退出"))
        _shortcut_row(
            (["空格"], "播放/暂停"),
            (["X"], "倍速-0.1"),
            (["C"], "倍速+0.1"),
            (["Z"], "还原1倍"),
        )
        _shortcut_row(
            (["↑", "↓"], "系统音量"),
            (["←", "→"], "快退/快进10秒"),
        )
        shortcut_card.viewLayout.addLayout(shortcut_vbox)
        layout.addWidget(shortcut_card)

        # ---- 外部工具卡片 ----
        tool_card = AccentHeaderCardWidget("外部工具")
        tool_vbox = QVBoxLayout()
        tool_vbox.setSpacing(8)

        tool_row = QHBoxLayout()
        tool_row.setSpacing(12)

        switch_btn = PushButton("uPl-project-switch")
        switch_btn.setToolTip("工程格式转换工具")
        switch_btn.clicked.connect(lambda: self._open_url("https://github.com/rinflow05/uPl-project-switch"))
        tool_row.addWidget(switch_btn)

        uf_btn = PushButton("UtaFormatix")
        uf_btn.setToolTip("多格式工程转换（在线）")
        uf_btn.clicked.connect(lambda: self._open_url("https://utaformatix.tk/"))
        tool_row.addWidget(uf_btn)

        sig_btn = PushButton("LibreSVIP")
        sig_btn.setToolTip("多格式工程转换（需安装，功能更丰富）")
        sig_btn.clicked.connect(lambda: self._open_url("https://github.com/SoulMelody/LibreSVIP/releases"))
        tool_row.addWidget(sig_btn)

        ml_btn = PushButton("163MusicLyrics")
        ml_btn.setToolTip("获取不同格式的歌词")
        ml_btn.clicked.connect(lambda: self._open_url("https://github.com/jitwxs/163MusicLyrics/"))
        tool_row.addWidget(ml_btn)

        v2m_btn = PushButton("Vocal2Midi")
        v2m_btn.setToolTip("音频转 USTX 工程")
        v2m_btn.clicked.connect(lambda: self._open_url("https://www.bilibili.com/video/BV1Ww7C6kEqL/"))
        tool_row.addWidget(v2m_btn)

        tool_row.addStretch()
        tool_vbox.addLayout(tool_row)

        tool_card.viewLayout.addLayout(tool_vbox)
        layout.addWidget(tool_card)

        # ---- 检查更新卡片 ----
        update_card = AccentHeaderCardWidget("检查更新")
        update_vbox = QVBoxLayout()
        update_vbox.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self.btn_check_update = PushButton("检查更新")
        row1.addWidget(self.btn_check_update)
        row1.addWidget(BodyLabel(f"当前版本 v{APP_VERSION}"))
        row1.addStretch()
        update_vbox.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(BodyLabel("自动检测更新（每7天）"))
        self.sw_auto_check = SwitchButton()
        self.sw_auto_check.setChecked(self._s.theme.auto_check_enabled)
        row2.addWidget(self.sw_auto_check)
        row2.addStretch()
        update_vbox.addLayout(row2)

        update_card.viewLayout.addLayout(update_vbox)
        layout.addWidget(update_card)

        # ---- 关于项目卡片（含协议与许可）----
        about_card = AccentHeaderCardWidget("关于项目")
        about_vbox = QVBoxLayout()
        about_vbox.setSpacing(8)

        # 衍生项目说明
        derive_label = BodyLabel("本项目（ustxPlayer）是基于 ustPlayer 的衍生项目")
        about_vbox.addWidget(derive_label)

        # 第一行：原项目 + GitHub仓库
        orig_row = QHBoxLayout()
        orig_row.setSpacing(12)
        orig_row.addWidget(BodyLabel("原项目:"))
        orig_row.addWidget(HyperlinkButton(
            "https://github.com/ustPlayerDevelop-OperateTeam",
            "ustPlayer - 1.0.0 (v26f19) by ustPlayerDevelop-OperateTeam"
        ))
        orig_row.addWidget(HyperlinkButton(
            "https://github.com/ustPlayerDevelop-OperateTeam/ustPlayer", "GitHub仓库"
        ))
        orig_row.addStretch()
        about_vbox.addLayout(orig_row)

        # 第二行：本项目 + GitHub仓库
        proj_row = QHBoxLayout()
        proj_row.setSpacing(12)
        proj_row.addWidget(BodyLabel("本项目:"))
        proj_row.addWidget(HyperlinkButton(
            "https://space.bilibili.com/1398756020", f"ustxPlayer - {APP_VERSION} by lyrinXD"
        ))
        proj_row.addWidget(HyperlinkButton(
            "https://github.com/lyrinXD/ustxPlayer", "GitHub仓库"
        ))
        proj_row.addStretch()
        about_vbox.addLayout(proj_row)

        # 最后一行：协议说明 + 开源协议（超链接样式，点击用系统默认程序打开）
        lic_row = QHBoxLayout()
        lic_row.setSpacing(12)
        lic_row.addWidget(BodyLabel("本项目与原项目现均遵循 GPLv3 开源协议"))
        lic_row.addWidget(HyperlinkButton(
            QUrl.fromLocalFile(self._s.terms_file_path).toString(), "开源协议"
        ))
        lic_row.addStretch()
        about_vbox.addLayout(lic_row)
        about_card.viewLayout.addLayout(about_vbox)
        layout.addWidget(about_card)

        # ---- 彩蛋卡片（无标题）----
        self._setup_easter_egg(layout)

        layout.addStretch()

    def _setup_easter_egg(self, layout: QVBoxLayout):
        """你知道吗彩蛋：连点 5 下（间隔 ≤1.5s）循环切换应用图标。"""
        self.easter_card = AccentHeaderCardWidget(parent=self)
        easter = BodyLabel("你知道吗：alpha版本在提交至托管时曾被错误地命名为ustPlyaer。orz")
        easter.setWordWrap(True)
        self.easter_card.viewLayout.addWidget(easter)
        layout.addWidget(self.easter_card)
        self.easter_card.clicked.connect(self._on_easter_card_clicked)
        self._easter_clicks = 0
        self._easter_last_click = 0.0
        icons = icon_files()
        saved = self._s.theme.current_icon
        self._icon_index = 0
        for i, p in enumerate(icons):
            if os.path.basename(p) == saved:
                self._icon_index = i
                break

    def _on_easter_card_clicked(self):
        """连点计数：间隔 ≤1.5s 内累计 5 下触发图标循环。"""
        now = time.monotonic()
        if now - self._easter_last_click <= 1.5:
            self._easter_clicks += 1
        else:
            self._easter_clicks = 1
        self._easter_last_click = now
        if self._easter_clicks >= 5:
            self._easter_clicks = 0
            self._cycle_app_icon()

    def _cycle_app_icon(self):
        icons = icon_files()
        if len(icons) < 2:
            return
        self._icon_index = (self._icon_index + 1) % len(icons)
        apply_icon(self.window(), icons[self._icon_index])
        self._s.theme.current_icon = os.path.basename(icons[self._icon_index])
        self._s.write_settings()
        InfoBar.info(
            "彩蛋",
            f"图标已切换：{os.path.basename(icons[self._icon_index])}",
            orient=Qt.Orientation.Vertical, duration=3000,
            parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
        )

    # ===================== 信号绑定 =====================

    def _connect_signals(self):
        s = self._s

        # 主题下拉框
        self.theme_combo.setCurrentText(self._theme_combo_text(s.theme.theme_mode))
        self.theme_combo.currentTextChanged.connect(self._on_theme_combo_changed)
        s.theme.theme_mode_changed.connect(self._on_settings_theme_mode_changed)

        # 强调色模式下拉框
        self.accent_color_mode_combo.setCurrentText(
            self._accent_mode_text(s.theme.accent_color_mode)
        )
        self.accent_color_mode_combo.currentTextChanged.connect(
            self._on_accent_color_mode_combo_changed
        )
        s.theme.accent_color_mode_changed.connect(self._on_settings_accent_mode_changed)

        # 自定义颜色选择器
        self.accent_color_picker.colorChanged.connect(self._on_accent_color_pick)
        s.theme.custom_accent_color_changed.connect(self._on_settings_accent_color_changed)

        # 卡片阴影开关
        self.sw_card_shadow.checkedChanged.connect(self._on_card_shadow_toggled)

        # 检查更新
        self.btn_check_update.clicked.connect(self._on_check_update_clicked)
        self.sw_auto_check.checkedChanged.connect(self._on_auto_check_toggled)
        self._update_result.connect(self._on_update_result)

        # 初始时根据模式显示/隐藏自定义颜色选择器
        self._update_accent_custom_visible(s.theme.accent_color_mode)

    # ===================== 业务逻辑 =====================

    def _on_theme_combo_changed(self, text: str):
        """主题下拉框变化 → 更新 settings.theme_mode。"""
        mode = self._theme_combo_mode(text)
        self._s.theme.theme_mode = mode

    def _on_accent_color_mode_combo_changed(self, text: str):
        """强调色模式变化 → 更新 settings。"""
        mode = self._accent_mode_value(text)
        self._s.theme.accent_color_mode = mode
        self._update_accent_custom_visible(mode)

    def _on_accent_color_pick(self, color: QColor):
        """自定义颜色选择 → 更新 settings。"""
        self._s.theme.custom_accent_color = color.name()

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

    # ===================== 检查更新 =====================

    def _on_auto_check_toggled(self, checked: bool):
        self._s.theme.auto_check_enabled = checked
        self._s.write_settings()

    def _on_card_shadow_toggled(self, checked: bool):
        """卡片阴影开关：写设置并持久化；实际广播由 main 连接 settings 信号完成。"""
        self._s.theme.card_shadow_enabled = checked
        self._s.write_settings()

    def _on_check_update_clicked(self):
        self.check_update(auto=False)

    def check_update(self, auto: bool = False):
        """auto=True 受开关与 7 天间隔限制，失败静默。"""
        if auto and not self._s.theme.auto_check_enabled:
            return
        if auto:
            last = self._s.theme.last_update_check_date
            if last:
                try:
                    last_date = datetime.date.fromisoformat(last)
                    if (datetime.date.today() - last_date).days < 7:
                        return
                except ValueError:
                    pass
        if self._checking:
            return
        self._checking = True
        threading.Thread(target=self._check_update_worker, args=(auto,), daemon=True).start()

    def _check_update_worker(self, auto: bool):
        try:
            latest = _fetch_latest_version()
            self._update_result.emit((latest, auto))
        finally:
            self._checking = False

    def _on_update_result(self, data: tuple):
        latest, auto = data
        # 手动无论成败都写时间，防 7 天内自动检测紧接着打扰；自动成功才写
        if not auto or latest is not None:
            self._s.theme.last_update_check_date = datetime.date.today().isoformat()
            self._s.write_settings()

        if latest is None:
            if not auto:
                InfoBar.error(
                    "检查更新失败", "无法连接更新服务器（网络不可用或 GitHub 访问受限）",
                    orient=Qt.Orientation.Vertical, duration=4000,
                    parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
                )
            return

        if latest != APP_VERSION:
            InfoBar.success(
                "发现新版本", f"ustxPlayer v{latest} 已发布，请前往 GitHub 仓库更新",
                orient=Qt.Orientation.Vertical, duration=10000,
                parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
            )
        elif not auto:
            InfoBar.info(
                "检查更新", f"已是最新版本 v{APP_VERSION}",
                orient=Qt.Orientation.Vertical, duration=4000,
                parent=self.window(), position=InfoBarPosition.TOP_RIGHT,
            )

    # ===================== 同步 =====================

    def sync_all_from_settings(self):
        """从 settings 同步所有 UI 控件（导入 uprj 或导航切换后调用）。"""
        s = self._s
        self.theme_combo.setCurrentText(self._theme_combo_text(s.theme.theme_mode))
        self.accent_color_mode_combo.setCurrentText(
            self._accent_mode_text(s.theme.accent_color_mode)
        )
        self.accent_color_picker.setColor(QColor(s.theme.custom_accent_color))
        self._update_accent_custom_visible(s.theme.accent_color_mode)
