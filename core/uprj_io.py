# uprj_io.py — .uprj 工程文件导入/导出
""".uprj（v3 自包含 JSON）序列化/反序列化、字段注册表与校验。

数据来源与载体是 SettingsManager 的各子域（project/display/color/player），
本模块只负责记录、默认值、序化与导入时的字段落位，不持有任何设置业务。
"""

import json
import os
import copy

from core.log import logger
from core.settings.style import _STYLE_COLOR_DEFAULTS


class ProjectFileMissingError(Exception):
    """工程文件中引用的文件路径不存在。

    import_uprj 加载配置后校验 lrc/audio/custom_font_paths 路径，
    收集全部缺失项后一次性抛出。此时配置已加载到内存，仅文件不可用，
    调用方捕获后仍应同步 UI 供用户重新选择文件。
    """

    def __init__(self, missing: list[tuple[str, str]]):
        # missing: [(字段标签, 路径), ...]
        self.missing = missing
        lines = "\n".join(f"  - {label}: {path}" for label, path in missing)
        super().__init__(f"以下文件路径不存在:\n{lines}")


# .uprj 导出按"每元素一行"渲染的集合字段：json 的 indent 会把每个小 dict
# 展开成多行，这些字段统一压缩，保持工程文件可读。
_COMPACT_FIELDS = (
    ("ustx_data", "notes"),
    ("ustx_data", "tempos"),
    ("ustx_data", "tracks_info"),
    ("settings", "styles"),
    ("settings", "note_styles"),
)


def _compact_block(value) -> str:
    """把列表/字典渲染成每元素一行、内容内联的 JSON 块（元素缩进 6、收尾 4）。"""
    if isinstance(value, dict):
        items = [
            f"{json.dumps(str(k), ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}"
            for k, v in value.items()
        ]
        open_, close_ = "{", "}"
    else:
        items = [json.dumps(v, ensure_ascii=False, separators=(", ", ": ")) for v in value]
        open_, close_ = "[", "]"
    if not items:
        return open_ + close_
    return open_ + "\n" + ",\n".join("      " + it for it in items) + "\n    " + close_


def _dump_uprj_json(payload: dict) -> str:
    """indent=2 序列化 .uprj，但 _COMPACT_FIELDS 里的列表/字典每元素一行。"""
    # 浅拷贝两个 section：占位符只进副本，不污染内存缓存
    # （ustx_data 可能与 cached_ustx_info 共享）。
    out = dict(payload)
    for section in ("ustx_data", "settings"):
        out[section] = dict(payload.get(section) or {})
    tokens = {}
    for section, key in _COMPACT_FIELDS:
        value = out[section].get(key)
        if isinstance(value, (list, dict)):
            token = f"__{section}_{key}__"
            out[section][key] = token
            tokens[token] = (key, value)
    text = json.dumps(out, ensure_ascii=False, indent=2)
    for token, (key, value) in tokens.items():
        text = text.replace(f'"{key}": "{token}"', f'"{key}": {_compact_block(value)}')
    return text


class UprjProjectIO:
    """.uprj 工程文件序列化服务（v3 自包含）。

    构造时注入 SettingsManager（通过其子域与会话状态读写字段）。
    导入按阶段顺序进行，规避信号副作用清空结构化数据；
    字段默认值的唯一真相源在 _get_project_defaults。
    """

    # 导入时需延后/特殊处理的字段名集合
    _DEFERRED_FIELDS = {"styles", "active_style_index", "note_styles"}

    # ===================== .uprj 工程文件字段注册表 =====================
    # 数据驱动的字段序列化：导出/导入共用单一真相源。
    # 类型约定: str/bool/int/float/json。字段按归属分布在各子域，
    # 通过 _FIELD_OWNER 映射到对应子域对象后统一存取。
    # 注意：
    #   - 主题/强调色等用户级偏好仅写入 Settings.json，不参与 .uprj。
    #   - ustx_notes 由工程文件内嵌的 ustx_data 直接还原，不经过 USTX 解析。
    #   - ustx_path 是会话级源文件路径（仅 .ustx 工作流用），不进出 .uprj。
    #   - 导入顺序敏感字段(styles/active_style_index/note_styles)在 import_uprj 中单独处理。
    PROJECT_SCHEMA = [
        # 基础元信息
        ("project_name", "str"),
        ("song_name", "str"),
        ("song_author", "str"),
        ("ustx_author", "str"),
        # 颜色（与活动样式联动，build_ustx_info 中作为 fallback）
        ("bg_color", "str"),
        ("note_color", "str"),
        ("lyric_color", "str"),
        ("pitch_curve_color", "str"),
        ("info_text_color", "str"),
        # 全局背景
        ("global_bg_color", "str"),
        ("global_bg_enabled", "bool"),
        # 路径与位置
        ("lyric_pos", "str"),
        ("lrc_path", "str"),
        ("audio_path", "str"),
        # 静默/结尾/音高占位显示
        ("silent_display", "str"),
        ("silent_custom_text", "str"),
        ("end_display", "str"),
        ("end_custom_text", "str"),
        ("pitch_placeholder", "str"),
        ("pitch_custom_text", "str"),
        # 字体（逐字歌词字体 / 歌词及信息字体）
        ("word_lyric_font_family", "str"),
        ("info_font_family", "str"),
        # 自定义字体文件路径（打开工程时按路径重新加载恢复）
        ("custom_font_paths", "json"),
        # 布尔显示开关
        ("show_bpm", "bool"),
        ("show_play_time", "bool"),
        ("show_song_name", "bool"),
        ("show_song_author", "bool"),
        ("show_ustx_author", "bool"),
        ("show_copyright", "bool"),
        ("show_phoneme", "bool"),
        ("show_midinote", "bool"),
        ("show_waveform", "bool"),
        ("fullscreen", "bool"),
        ("show_lyric", "bool"),
        ("show_lyric_autohide", "bool"),
        ("lyric_autohide_threshold", "float"),
        ("curve_show", "bool"),
        # 样式系统（结构化数据，导入顺序敏感）
        ("styles", "json"),
        ("active_style_index", "int"),
        ("note_styles", "json"),
        # 多轨工程：当前播放的人声轨（不在 tracks_info 内时回退第一条）
        ("selected_track_no", "int"),
    ]

    def __init__(self, manager):
        self._m = manager

        # PROJECT_SCHEMA 字段 → 所属子域映射（.uprj 序列化定位字段用）
        self._FIELD_OWNER = {}
        for name in ("project_name", "song_name", "song_author", "ustx_author",
                     "audio_path", "selected_track_no"):
            self._FIELD_OWNER[name] = manager.project
        for name in ("bg_color", "note_color", "lyric_color", "pitch_curve_color",
                     "styles", "active_style_index", "note_styles"):
            self._FIELD_OWNER[name] = manager.style
        for name in ("info_text_color", "global_bg_color", "global_bg_enabled"):
            self._FIELD_OWNER[name] = manager.color
        for name in ("lyric_pos", "lrc_path", "silent_display", "silent_custom_text",
                     "end_display", "end_custom_text", "pitch_placeholder",
                     "pitch_custom_text", "word_lyric_font_family", "info_font_family",
                     "custom_font_paths"):
            self._FIELD_OWNER[name] = manager.player
        self._FIELD_OWNER.update({
            "show_bpm": manager.display, "show_play_time": manager.display,
            "show_song_name": manager.display, "show_song_author": manager.display,
            "show_ustx_author": manager.display, "show_copyright": manager.display,
            "show_phoneme": manager.display, "show_midinote": manager.display,
            "show_waveform": manager.display, "fullscreen": manager.display,
            "show_lyric": manager.display, "show_lyric_autohide": manager.display,
            "lyric_autohide_threshold": manager.display, "curve_show": manager.display,
        })

    # ===================== 工程字段默认值与重置 =====================

    def _get_project_defaults(self) -> dict:
        """返回所有 PROJECT_SCHEMA 字段的默认值（每次返回新副本）。

        作为工程字段默认值的单一真相源，__init__ 与 import_uprj 共用。
        styles/custom_font_paths/note_styles 为可变对象，调用方需自行 deepcopy
        （_reset_project_to_defaults 已处理）。
        """
        return {
            # 基础元信息
            "project_name": "",
            "song_name": "",
            "song_author": "",
            "ustx_author": "",
            # 颜色（与活动样式联动，build_ustx_info 中作为 fallback）
            **_STYLE_COLOR_DEFAULTS,
            "info_text_color": "#ffffff",
            # 全局背景
            "global_bg_color": "#00ff00",
            "global_bg_enabled": False,
            # 路径与位置
            "lyric_pos": "上",
            "lrc_path": "",
            "audio_path": "",
            # 静默/结尾/音高占位显示
            "silent_display": "♪",
            "silent_custom_text": "",
            "end_display": "END",
            "end_custom_text": "",
            "pitch_placeholder": "无",
            "pitch_custom_text": "",
            # 字体（逐字歌词字体 / 歌词及信息字体）
            "word_lyric_font_family": "等线",
            "info_font_family": "微软雅黑",
            # 自定义字体文件路径
            "custom_font_paths": [],
            # 布尔显示开关
            "show_bpm": True,
            "show_play_time": True,
            "show_song_name": True,
            "show_song_author": True,
            "show_ustx_author": True,
            "show_copyright": True,
            "show_phoneme": False,
            "show_midinote": False,
            "show_waveform": False,
            "fullscreen": True,
            "show_lyric": True,
            "show_lyric_autohide": True,
            "lyric_autohide_threshold": 3.0,
            "curve_show": False,
            # 样式系统（结构化数据，导入顺序敏感）
            "styles": [
                dict(_STYLE_COLOR_DEFAULTS),
                {"bg_color": "#000000", "note_color": "#f8bbd0", "lyric_color": "#ec407a", "pitch_curve_color": "#f8bbd0"},
                {"bg_color": "#000000", "note_color": "#c5cae9", "lyric_color": "#5c6bc0", "pitch_curve_color": "#c5cae9"},
            ],
            "active_style_index": 0,
            "note_styles": {},
            "selected_track_no": 0,
        }

    def reset_project_to_defaults(self):
        """将所有 PROJECT_SCHEMA 字段重置为默认值。

        直接写各子域 backing field（不经 setter），避免 active_style_index setter 同步
        颜色、note_styles setter 发信号等副作用。同时清空会话状态与解析缓存。
        """
        defaults = self._get_project_defaults()
        for name, _ftype in self.PROJECT_SCHEMA:
            owner = self._FIELD_OWNER[name]
            setattr(owner, f"_{name}", copy.deepcopy(defaults[name]))
        # ustx_path 是会话级源文件路径（不在 PROJECT_SCHEMA），导入工程时同样清空
        self._m.project._ustx_path = ""
        # 派生状态清空
        self._m._ustx_notes = []
        self._m._cached_ustx_info = None
        # 延迟应用状态（import_uprj parse_ustx=False 暂存 note_styles，由 FilePage 恢复）
        self._m._deferred_ustx_parse = None

    # ===================== .uprj 导出/导入 =====================

    def export_uprj(self, output_file: str):
        """导出全部配置到 .uprj 工程文件（JSON 格式，v3 自包含）。

        全量记录所有注册字段（含默认值），内嵌解析后的 ustx_data
        （get_ustx_info 输出），不再保存 USTX 原文。
        三个文件(lrc/audio)为空时同样可导出（作为预设配置）。
        """
        # 全量序列化所有注册字段
        settings_data = {}
        for name, _ftype in self.PROJECT_SCHEMA:
            owner = self._FIELD_OWNER[name]
            settings_data[name] = getattr(owner, name)

        # 工程名为空时兜底为"未命名"（仅写入导出文件）
        if not settings_data["project_name"].strip():
            settings_data["project_name"] = "未命名"

        payload = {
            "format": "ustxPlayer.uprj",
            "version": 3,
            "ustx_data": self._get_export_ustx_data(),
            "settings": settings_data,
        }
        # 原子写入：先写临时文件再替换，避免中途失败损坏已有工程文件
        tmp = output_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_dump_uprj_json(payload))
        os.replace(tmp, output_file)

    def _get_export_ustx_data(self) -> dict:
        """获取导出用的解析数据（JSON 可序列化）。

        优先取内存缓存（内嵌工程 path=""，.ustx 工程需 path 与当前源一致）；
        缓存缺失/过期时兜底同步解析当前 ustx_path；无源文件则返回空数据（预设工程）。
        """
        ustx_path = self._m.project.ustx_path
        cached = self._m._cached_ustx_info or {}
        info = cached.get("info")
        if info and (not ustx_path.strip() or cached.get("path") == ustx_path.strip()):
            return info
        if ustx_path and os.path.isfile(ustx_path):
            try:
                from core.ustxreader import get_ustx_info
                return get_ustx_info(ustx_path)
            except Exception:
                logger.exception(f"导出前解析 ustx 失败: {ustx_path}")
        return {
            "version": "unknown",
            "tempo": 120.0,
            "tempo_count": 0,
            "tempos": [],
            "tracks": 1,
            "tracks_info": [],
            "empty_tracks": [],
            "wave_part_count": 0,
            "notes": [],
        }

    def import_uprj(self, input_file: str, parse_ustx: bool = True):
        """从 .uprj 工程文件导入全部配置（JSON 格式，v3 自包含）。

        工程文件内嵌解析后的 ustx_data（get_ustx_info 输出），导入时只做
        JSON 反序列化，不解析 USTX、不写缓存。

        导入顺序规避信号副作用清空结构化数据：
          0) 重置所有 PROJECT_SCHEMA 字段为默认值，确保旧工程配置不残留；
          1) 普通字段循环赋值，跳过顺序敏感字段；
          2) styles（须在 active_style_index 之前）；
          3) active_style_index（setter 同步基础颜色属性）；
          4) 应用内嵌解析数据（parse_ustx=True 时同步写入 ustx_notes，False 时延迟）；
          5) note_styles 最后赋值（在 ustx_notes 清空之后）；
          6) 校验文件路径，缺失项一次性抛出 ProjectFileMissingError。
        支持 lrc/audio 均为空的预设场景（ustx_data 为空数据）。

        Args:
            parse_ustx: 是否立即写入 ustx_notes。False 时推迟到下一帧，
                        由 FilePage 应用后调用 apply_deferred_uprj_styles() 恢复样式。
        """
        with open(input_file, "r", encoding="utf-8") as f:
            payload = json.load(f)

        # 校验工程文件格式，避免误导入任意 JSON 污染当前配置
        if payload.get("format") != "ustxPlayer.uprj":
            raise ValueError("不是有效的 ustxPlayer 工程文件（format 不匹配）")
        if payload.get("version") != 3:
            raise ValueError("工程格式版本不受支持，请尝试使用格式转换工具")

        data = payload.get("settings", {})
        ustx_data = payload.get("ustx_data", {})
        if not isinstance(ustx_data, dict):
            logger.warning("工程文件 ustx_data 非法，已按空数据处理")
            ustx_data = {}

        # ---- 阶段0: 重置所有工程字段为默认值 ----
        # 先校验格式再重置：格式非法时抛 ValueError，当前配置不受影响
        self.reset_project_to_defaults()

        # ---- 阶段1: 普通字段（跳过顺序敏感字段）----
        for name, ftype in self.PROJECT_SCHEMA:
            if name in self._DEFERRED_FIELDS:
                continue
            if name not in data:
                continue
            raw = data[name]
            owner = self._FIELD_OWNER[name]
            try:
                if ftype == "bool":
                    setattr(owner, name, bool(raw))
                elif ftype == "int":
                    setattr(owner, name, int(raw))
                elif ftype == "float":
                    setattr(owner, name, float(raw))
                else:  # str / json
                    setattr(owner, name, raw)
            except (ValueError, TypeError):
                logger.warning(f"工程文件字段 {name} 值非法，已跳过: {raw!r}")

        # ---- 阶段2/3/5: 顺序敏感的样式系统字段（style 子域） ----
        self._m.style.apply_styles_from_project(data.get("styles"))
        self._m.style.apply_active_index_from_project(data.get("active_style_index"))

        # ---- 阶段4: 应用内嵌解析数据（自包含，不关联任何 USTX 文件）----
        self._m.project._ustx_path = ""  # 不走 setter：值已为空，避免无意义信号
        self._m._cached_ustx_info = {"path": "", "info": ustx_data}

        # 校验播放轨道：保存的 selected_track_no 必须是 tracks_info 内的人声轨，
        # 否则回退第一条人声轨（无音符工程保持 0）。须在 ustx_notes 赋值之前，
        # 保证歌词表按已校验的轨道号建表。
        tracks_info = ustx_data.get("tracks_info") or []
        valid_tracks = {t.get("track_no") for t in tracks_info
                        if isinstance(t, dict) and t.get("track_no") is not None}
        if valid_tracks and self._m.project.selected_track_no not in valid_tracks:
            self._m.project._selected_track_no = min(valid_tracks)

        _notes = ustx_data.get("notes", [])
        if isinstance(_notes, list):
            if parse_ustx:
                # 同步应用（对话框导入等场景）：JSON 反序列化后直接可用
                self._m.ustx_notes = _notes
            else:
                # 延迟应用：置空音符，由 FilePage 在下一帧写入并重建歌词表
                self._m.ustx_notes = []
        else:
            self._m.ustx_notes = []

        # ---- 阶段5: note_styles（必须在 ustx_notes 之后，否则会被清空）----
        self._m.style.apply_note_styles_from_project(data.get("note_styles"))

        # ---- 延迟应用暂存（parse_ustx=False 时保存 note_styles，由 FilePage 恢复）----
        if not parse_ustx:
            ns = data.get("note_styles")
            self._m._deferred_ustx_parse = {
                "note_styles": {int(k): int(v) for k, v in ns.items()} if isinstance(ns, dict) else {},
            }

        # ---- 阶段6: 校验文件路径（lrc/audio/custom_font_paths 非空路径必须存在）----
        # 自包含工程不引用 USTX 文件，仅校验其余外部资源路径；收集全部缺失后一次性抛出
        missing: list[tuple[str, str]] = []
        if self._m.player.lrc_path and not os.path.exists(self._m.player.lrc_path):
            missing.append(("歌词文件", self._m.player.lrc_path))
        if self._m.project.audio_path and not os.path.exists(self._m.project.audio_path):
            missing.append(("音频文件", self._m.project.audio_path))
        for font_path in self._m.player.custom_font_paths:
            if font_path and not os.path.exists(font_path):
                missing.append(("字体文件", font_path))
        if missing:
            raise ProjectFileMissingError(missing)

    def apply_deferred_uprj_styles(self):
        """延迟应用完成后，恢复 UPRJ 工程文件中保存的 note_styles。

        由 FilePage._apply_notes 在设置 ustx_notes 之后调用。
        """
        if self._m._deferred_ustx_parse is None:
            return
        self._m.style.note_styles = self._m._deferred_ustx_parse.get("note_styles", {})
        self._m._deferred_ustx_parse = None