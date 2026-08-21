# ustxreader.py — USTX 文件解析器
"""OpenUtau USTX (YAML) 文件解析模块。

提取 USTX 文件中的版本、速度、轨道数和音符信息，
供播放器和主窗口使用。
"""

from typing import List, Dict, Union
import os

import yaml

from core.log import logger


# ===================== 主解析函数 =====================


def get_ustx_info(ustx_path: str) -> Dict[str, Union[str, float, int, List[Dict]]]:
    """解析 USTX 文件（YAML 格式），提取版本、速度、轨道数和音符列表。

    USTX 是 OpenUtau 使用的 YAML 格式文件，包含更丰富的信息。

    Args:
        ustx_path: USTX 文件路径（.ustx 或 .txt）

    Returns:
        dict:
            version (str):   USTX 版本号
            tempo (float):   速度 (BPM)
            tempo_count (int): tempo 标记数量（>1 表示歌内有变速）
            tracks (int):    轨道总数（含音频轨）
            tracks_info (list): 人声轨列表 [{track_no, track_name, note_count}]（仅含音符的轨）
            empty_tracks (list): 空人声轨列表 [{track_no, track_name, note_count:0}]
            wave_part_count (int): wave_parts（音频轨）数量
            notes (list):    音符列表 [{index, position, length, lyric, note_num,
                              track_no, pitch_bend}]

    Raises:
        FileNotFoundError: USTX 文件不存在
    """
    if not os.path.exists(ustx_path):
        raise FileNotFoundError(f"USTX 文件不存在: {ustx_path}")

    with open(ustx_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        # 空文件或非映射（如纯列表/标量）→ 视为无内容，避免 AttributeError
        data = {}

    ustx_version = data.get('ustx_version', 'unknown')
    # BPM：OpenUTAU v0.9+ 把 tempo 存在根级 tempos 列表（UTempo{position,bpm}），
    # 根级 bpm 是 v0.6 前的遗留字段，改 BPM 后不再同步（恒为旧值），必须优先读 tempos。
    tempos = data.get('tempos') or []
    if tempos and isinstance(tempos[0], dict):
        ustx_tempo = float(tempos[0].get('bpm', 120.0))
    else:
        ustx_tempo = float(data.get('bpm', 120.0))
    raw_tracks = data.get('tracks', []) or []
    ustx_tracks = max(1, len(raw_tracks))
    # 音频轨（wave_parts）可能未计入 tracks 列表，用其轨道号补齐总轨道数
    wave_track_nos = {
        int(p.get('track_no', 0) or 0)
        for p in (data.get('wave_parts') or [])
        if isinstance(p, dict)
    }
    if wave_track_nos:
        ustx_tracks = max(ustx_tracks, max(wave_track_nos) + 1)
    # 轨道名映射：track_name 是 OpenUtau 字段，旧文件可能缺失，回退"轨道 N"
    track_names: Dict[int, str] = {}
    for idx, t in enumerate(raw_tracks):
        if isinstance(t, dict):
            track_names[idx] = t.get('track_name') or t.get('name') or f"轨道 {idx + 1}"
        else:
            track_names[idx] = f"轨道 {idx + 1}"

    note_list: List[Dict] = []
    track_note_counts: Dict[int, int] = {}
    note_global_idx = 0

    voice_parts = data.get('voice_parts', [])
    for part in voice_parts:
        part_pos = part.get('position', 0)
        track_no = int(part.get('track_no', 0) or 0)
        notes = part.get('notes', [])

        # 从 voice_part.curves 提取 pitd（pitch deviation）曲线数据
        pitd_xs: List[int] = []
        pitd_ys: List[int] = []
        for curve in part.get('curves', []):
            if isinstance(curve, dict) and curve.get('abbr') == 'pitd':
                pitd_xs = curve.get('xs', [])
                pitd_ys = curve.get('ys', [])
                break

        # 构建 tick→pitch 查找表，并预排序 tick（每个 part 仅排序一次，避免每音符重复排序）
        # 曲线 xs 是 part 内相对坐标（OpenUtau 渲染时 pitchStart 减掉 part.position 再采样），
        # 需叠加 part_pos 转全局 tick，才能与下方转全局的 note_pos 比较。
        tick_pitch = {}
        if len(pitd_xs) != len(pitd_ys):
            logger.warning(f"pitd 曲线 xs/ys 长度不一致: {len(pitd_xs)} vs {len(pitd_ys)}，按短的截断")
        for x, y in zip(pitd_xs, pitd_ys):
            tick_pitch[part_pos + int(x)] = int(y)
        sorted_ticks = sorted(tick_pitch.keys())

        for note in notes:
            note_num = note.get('tone', 0)
            lyric = note.get('lyric', '')
            # OpenUTAU 歌词可带语言前缀（en/、ja/ 等，语言码无法穷举，前缀后必有 /），
            # 前缀只用于选择音源/词典，不应显示；统一按第一个 "/" 截断。
            if '/' in lyric:
                lyric = lyric.split('/', 1)[1]
            duration = note.get('duration', 0)
            note_pos = part_pos + note.get('position', 0)
            note_end = note_pos + duration

            # 从 tick_pitch 提取该音符范围内的 pitch_bend
            # 同时记录每个数据点相对音符开头的 tick 偏移，供渲染器按真实时间映射 x 坐标
            pitch_bend: List[int] = []
            pitch_ticks: List[int] = []
            if sorted_ticks:
                for t in sorted_ticks:
                    if note_pos <= t <= note_end:
                        pitch_bend.append(tick_pitch[t])
                        pitch_ticks.append(t - note_pos)

            note_list.append({
                "index": f"{note_global_idx:04d}",
                "position": note_pos,
                "length": duration,
                "lyric": lyric,
                "note_num": note_num,
                "track_no": track_no,
                "pitch_bend": pitch_bend,
                "pitch_ticks": pitch_ticks,
            })
            note_global_idx += 1
            track_note_counts[track_no] = track_note_counts.get(track_no, 0) + 1

    logger.info(f"USTX 解析完成: {len(note_list)} 个音符, BPM={ustx_tempo}")
    if track_note_counts:
        logger.info("USTX 轨道: " + ", ".join(
            f"{track_names.get(t, '轨道' + str(t + 1))}({c})"
            for t, c in sorted(track_note_counts.items())
        ))
    if note_list:
        logger.info(f"USTX 音符区间: pos={note_list[0]['position']}~{note_list[-1]['position']}, "
                    f"共 {note_list[-1]['position'] + note_list[-1]['length']} ticks")

    # 仅人声轨（有音符的轨道），按轨道号排序
    tracks_info = [
        {
            "track_no": t,
            "track_name": track_names.get(t, f"轨道 {t + 1}"),
            "note_count": track_note_counts[t],
        }
        for t in sorted(track_note_counts)
    ]
    # 空人声轨（无音符），供解析报告展示；排除音频轨（wave_parts 引用的轨道号）
    empty_tracks = [
        {
            "track_no": t,
            "track_name": track_names.get(t, f"轨道 {t + 1}"),
            "note_count": 0,
        }
        for t in sorted(track_names)
        if t not in track_note_counts and t not in wave_track_nos
    ]

    return {
        "version": ustx_version,
        "tempo": ustx_tempo,
        "tempo_count": len(tempos),
        "tempos": tempos,
        "tracks": ustx_tracks,
        "tracks_info": tracks_info,
        "empty_tracks": empty_tracks,
        "wave_part_count": len(data.get('wave_parts') or []),
        "notes": note_list,
    }
