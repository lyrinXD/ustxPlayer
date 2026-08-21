# core/settings 包 — 设置子域
"""按领域拆分的设置子域，每个类负责自己的属性 + 信号。

由 core/settings_manager.py 的 SettingsManager 组装并对外暴露，
UI 通过 settings.<子域>.<属性> 访问，如 settings.display.show_bpm。
"""

from core.settings.color import ColorSettings
from core.settings.display import DisplaySettings
from core.settings.player import PlayerSettings
from core.settings.project import ProjectSettings
from core.settings.style import StyleSettings
from core.settings.theme import ThemeSettings

__all__ = [
    "ColorSettings",
    "DisplaySettings",
    "PlayerSettings",
    "ProjectSettings",
    "StyleSettings",
    "ThemeSettings",
]