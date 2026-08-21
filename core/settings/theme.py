# settings/theme.py — 应用外观与偏好子域
"""主题/强调色/卡片阴影/图标/更新检测偏好。这些是用户级偏好，
只写入 Settings.json（[ThemeSettings] 分组），不参与 .uprj 工程序列化。"""

from typing import Optional

from PySide6.QtCore import QObject, Signal

_THEME_MODES = {"auto", "light", "dark"}
_ACCENT_MODES = {"auto", "custom"}


class ThemeSettings(QObject):
    """应用外观与用户偏好设置。"""

    theme_mode_changed = Signal(str)
    accent_color_mode_changed = Signal(str)
    custom_accent_color_changed = Signal(str)
    card_shadow_enabled_changed = Signal(bool)
    # 以下为持久化偏好，无监听方，不设 signal
    current_icon_changed = Signal(str)
    last_update_check_date_changed = Signal(str)
    auto_check_enabled_changed = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._theme_mode = "auto"  # auto=跟随系统, light=亮色, dark=暗色
        self._accent_color_mode = "auto"  # auto=跟随系统, custom=自定义
        self._custom_accent_color = "#5a7a50"
        self._card_shadow_enabled = True
        self._current_icon = ""  # 图标文件名（空=默认第一个）
        self._last_update_check_date = ""  # "YYYY-MM-DD"（空=从未）
        self._auto_check_enabled = True  # 启动自动检测更新

    @property
    def theme_mode(self) -> str:
        return self._theme_mode

    @theme_mode.setter
    def theme_mode(self, v: str):
        if self._theme_mode != v:
            self._theme_mode = v
            self.theme_mode_changed.emit(v)

    @property
    def accent_color_mode(self) -> str:
        return self._accent_color_mode

    @accent_color_mode.setter
    def accent_color_mode(self, v: str):
        if self._accent_color_mode != v:
            self._accent_color_mode = v
            self.accent_color_mode_changed.emit(v)

    @property
    def custom_accent_color(self) -> str:
        return self._custom_accent_color

    @custom_accent_color.setter
    def custom_accent_color(self, v: str):
        if self._custom_accent_color != v:
            self._custom_accent_color = v
            self.custom_accent_color_changed.emit(v)

    @property
    def card_shadow_enabled(self) -> bool:
        return self._card_shadow_enabled

    @card_shadow_enabled.setter
    def card_shadow_enabled(self, v: bool):
        if self._card_shadow_enabled != v:
            self._card_shadow_enabled = v
            self.card_shadow_enabled_changed.emit(v)

    @property
    def current_icon(self) -> str:
        return self._current_icon

    @current_icon.setter
    def current_icon(self, v: str):
        if self._current_icon != v:
            self._current_icon = v
            self.current_icon_changed.emit(v)

    @property
    def last_update_check_date(self) -> str:
        return self._last_update_check_date

    @last_update_check_date.setter
    def last_update_check_date(self, v: str):
        if self._last_update_check_date != v:
            self._last_update_check_date = v
            self.last_update_check_date_changed.emit(v)

    @property
    def auto_check_enabled(self) -> bool:
        return self._auto_check_enabled

    @auto_check_enabled.setter
    def auto_check_enabled(self, v: bool):
        if self._auto_check_enabled != v:
            self._auto_check_enabled = v
            self.auto_check_enabled_changed.emit(v)

    # ===================== Settings.json 分组读写 =====================

    def read_from(self, config: dict):
        """从 [ThemeSettings] 分组读取（枚举越界时回退默认）。"""
        cs = config.get("ThemeSettings")
        if not isinstance(cs, dict):
            return
        mode = cs.get("theme_mode", "auto")
        if mode in _THEME_MODES:
            self._theme_mode = mode
        amode = cs.get("accent_color_mode", "auto")
        if amode in _ACCENT_MODES:
            self._accent_color_mode = amode
        self._custom_accent_color = cs.get("custom_accent_color", self._custom_accent_color)
        self._card_shadow_enabled = bool(cs.get("card_shadow_enabled", self._card_shadow_enabled))
        self._current_icon = cs.get("current_icon", self._current_icon)
        self._last_update_check_date = cs.get("last_update_check_date", self._last_update_check_date)
        self._auto_check_enabled = bool(cs.get("auto_check_enabled", self._auto_check_enabled))

    def write_to(self, config: dict):
        """写入 [ThemeSettings] 分组。"""
        config["ThemeSettings"] = {
            "theme_mode": self._theme_mode,
            "accent_color_mode": self._accent_color_mode,
            "custom_accent_color": self._custom_accent_color,
            "card_shadow_enabled": self._card_shadow_enabled,
            "current_icon": self._current_icon,
            "last_update_check_date": self._last_update_check_date,
            "auto_check_enabled": self._auto_check_enabled,
        }