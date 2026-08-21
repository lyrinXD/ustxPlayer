# settings/style.py — 样式系统子域
"""样式系统：styles 列表 + 活动样式 + 逐音符样式 + 基础颜色镜像。

背景/音符/歌词/音高四色是活动样式（styles[active_style_index]）的同步镜像，
build_ustx_info 中作为 fallback；用户可临时代色而不固化到样式。
"""

from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.log import logger

_STYLE_COLOR_DEFAULTS = {
    "bg_color": "#000000",
    "note_color": "#6c6c6c",
    "lyric_color": "#ffffff",
    "pitch_curve_color": "#ffffff",
}


class StyleSettings(QObject):
    """样式系统设置（样式列表 + 活动样式 + 逐音符样式）。"""

    bg_color_changed = Signal(str)
    note_color_changed = Signal(str)
    lyric_color_changed = Signal(str)
    pitch_curve_color_changed = Signal(str)
    active_style_index_changed = Signal(int)
    styles_changed = Signal()  # 样式数据变更（颜色/增删）
    note_styles_changed = Signal(object)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._bg_color = _STYLE_COLOR_DEFAULTS["bg_color"]
        self._note_color = _STYLE_COLOR_DEFAULTS["note_color"]
        self._lyric_color = _STYLE_COLOR_DEFAULTS["lyric_color"]
        self._pitch_curve_color = _STYLE_COLOR_DEFAULTS["pitch_curve_color"]
        self._styles = [
            dict(_STYLE_COLOR_DEFAULTS),
            {"bg_color": "#000000", "note_color": "#f8bbd0", "lyric_color": "#ec407a", "pitch_curve_color": "#f8bbd0"},
            {"bg_color": "#000000", "note_color": "#c5cae9", "lyric_color": "#5c6bc0", "pitch_curve_color": "#c5cae9"},
        ]
        self._active_style_index = 0
        self._note_styles = {}

    # ===================== 基础颜色镜像（随活动样式同步） =====================

    @property
    def bg_color(self) -> str:
        return self._bg_color

    @bg_color.setter
    def bg_color(self, v: str):
        if self._bg_color != v:
            self._bg_color = v
            self.bg_color_changed.emit(v)

    @property
    def note_color(self) -> str:
        return self._note_color

    @note_color.setter
    def note_color(self, v: str):
        if self._note_color != v:
            self._note_color = v
            self.note_color_changed.emit(v)

    @property
    def lyric_color(self) -> str:
        return self._lyric_color

    @lyric_color.setter
    def lyric_color(self, v: str):
        if self._lyric_color != v:
            self._lyric_color = v
            self.lyric_color_changed.emit(v)

    @property
    def pitch_curve_color(self) -> str:
        return self._pitch_curve_color

    @pitch_curve_color.setter
    def pitch_curve_color(self, v: str):
        if self._pitch_curve_color != v:
            self._pitch_curve_color = v
            self.pitch_curve_color_changed.emit(v)

    # ===================== 样式系统 =====================

    def _sync_base_colors(self, style: dict):
        """把样式四色同步到基础颜色镜像（build_ustx_info 的 fallback）。"""
        self._bg_color = style.get("bg_color", _STYLE_COLOR_DEFAULTS["bg_color"])
        self._note_color = style.get("note_color", _STYLE_COLOR_DEFAULTS["note_color"])
        self._lyric_color = style.get("lyric_color", _STYLE_COLOR_DEFAULTS["lyric_color"])
        self._pitch_curve_color = style.get(
            "pitch_curve_color", _STYLE_COLOR_DEFAULTS["pitch_curve_color"])

    @property
    def styles(self) -> list:
        return self._styles

    @property
    def active_style(self) -> dict:
        """返回当前激活样式的 dict。"""
        return self._styles[self._active_style_index] if self._styles else {}

    @property
    def active_style_index(self) -> int:
        return self._active_style_index

    @active_style_index.setter
    def active_style_index(self, v: int):
        if 0 <= v < len(self._styles) and self._active_style_index != v:
            self._active_style_index = v
            self.active_style_index_changed.emit(v)
            self._sync_base_colors(self._styles[v])

    @property
    def style_count(self) -> int:
        return len(self._styles)

    @property
    def note_styles(self) -> dict:
        """逐音符样式映射 {行号: 样式索引}。"""
        return self._note_styles

    @note_styles.setter
    def note_styles(self, v: dict):
        self._note_styles = v
        self.note_styles_changed.emit(v)

    def clear_note_styles(self):
        """清空逐音符样式（无信号，供门面在新音符载入时调用）。"""
        self._note_styles = {}

    def set_style_color(self, style_index: int, key: str, value: str):
        """设置指定样式的某个颜色值。"""
        if 0 <= style_index < len(self._styles):
            if self._styles[style_index].get(key) != value:
                self._styles[style_index][key] = value
                # 如果是当前激活样式，同步基础颜色镜像
                if style_index == self._active_style_index:
                    self._sync_base_colors(self._styles[style_index])
                self.styles_changed.emit()

    def add_style(self):
        """新建样式（复制样式1的颜色），返回新索引。"""
        new_idx = len(self._styles)
        self._styles.append(dict(self._styles[0]))  # 复制样式1
        logger.info(f"样式系统: 新建样式{new_idx + 1}（共{len(self._styles)}个）")
        self.styles_changed.emit()
        return new_idx

    def remove_style(self, index: int) -> bool:
        """删除指定索引的样式。至少保留3个样式（默认样式不可删）。"""
        if len(self._styles) <= 3 or index < 0 or index >= len(self._styles):
            return False
        del self._styles[index]
        logger.info(f"样式系统: 删除样式{index + 1}（剩余{len(self._styles)}个）")
        # 调整 active index
        if self._active_style_index >= len(self._styles):
            self._active_style_index = len(self._styles) - 1
        elif self._active_style_index > index:
            self._active_style_index -= 1
        # 重映射逐音符样式：被删样式→样式1，后面的样式索引前移
        new_styles = {}
        for row, si in self._note_styles.items():
            if si == index:
                new_styles[row] = 0
            elif si > index:
                new_styles[row] = si - 1
            else:
                new_styles[row] = si
        self.note_styles = new_styles  # 走 setter 发射 note_styles_changed
        # 同步基础颜色镜像
        self._sync_base_colors(self._styles[self._active_style_index])
        self.styles_changed.emit()
        self.active_style_index_changed.emit(self._active_style_index)
        return True

    def get_style_name(self, index: int) -> str:
        """获取样式显示名称（样式1, 样式2, ...）。"""
        return f"样式{index + 1}"

    # ===================== .uprj 导入的样式字段应用（顺序敏感） =====================

    def apply_styles_from_project(self, raw_styles):
        """导入阶段2：styles 列表（须先于 active_style_index 应用）。"""
        if isinstance(raw_styles, list) and raw_styles:
            # 补齐每个样式 dict 的缺失键，避免下游硬下标 KeyError
            self._styles = [
                {**_STYLE_COLOR_DEFAULTS, **s}
                if isinstance(s, dict) else dict(_STYLE_COLOR_DEFAULTS)
                for s in raw_styles
            ]
            self.styles_changed.emit()

    def apply_active_index_from_project(self, raw_index):
        """导入阶段3：active_style_index（setter 同步基础颜色镜像）。"""
        if raw_index is None:
            return
        try:
            idx = int(raw_index)
        except (ValueError, TypeError):
            logger.warning(f"active_style_index 值非法，已忽略: {raw_index!r}")
            idx = 0
        # 越界时 clamp 到有效范围，避免下游 self._styles[idx] IndexError
        idx = max(0, min(idx, len(self._styles) - 1)) if self._styles else 0
        self.active_style_index = idx

    def apply_note_styles_from_project(self, raw_note_styles):
        """导入阶段5：note_styles（JSON 键为字符串，转回 int 行号/样式索引）。"""
        if isinstance(raw_note_styles, dict):
            self.note_styles = {int(k): int(v) for k, v in raw_note_styles.items()}
        else:
            self.note_styles = {}