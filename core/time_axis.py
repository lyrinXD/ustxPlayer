"""OpenUTAU tempos 分段的 tick↔秒换算。"""

from typing import List, Tuple


class TimeAxis:
    """按 OpenUTAU 根级 `tempos`（[{position, bpm}]）分段换算 tick 与秒。

    单一 tempo 时与旧公式 `tick_per_second = bpm * 480 / 60` 完全一致；
    多段 tempo 时每段独立速率：tick→秒按段累加，秒→tick 按段逆查。
    节拍基准固定 480 tick/拍（与 USTX 一致）。
    段表：[(tick_start, tick_end_or_None, sec_at_start, ticks_per_sec)]，
    末段 tick_end=None 表示延伸到曲末之后（防 seek 上限越界）。
    """

    def __init__(self, tempos, default_bpm: float = 120.0):
        self._segments: List[Tuple[int, int, float, float]] = self._build(tempos, default_bpm)

    @staticmethod
    def _build(tempos, default_bpm: float = 120.0):
        pts = []
        for t in tempos or []:
            if not isinstance(t, dict):
                continue
            try:
                pos = int(t.get("position", 0))
                bpm = float(t.get("bpm", 120.0))
            except (TypeError, ValueError):
                continue
            if bpm > 0:
                pts.append((pos, bpm))
        if not pts:
            pts = [(0, default_bpm if default_bpm > 0 else 120.0)]
        pts.sort(key=lambda p: p[0])
        if pts[0][0] != 0:
            # 首个标记不在 0 时，按该 BPM 从 0 起算，避免曲首出现负偏移
            pts.insert(0, (0, pts[0][1]))
        segments = []
        sec = 0.0
        for i, (pos, bpm) in enumerate(pts):
            tick_end = pts[i + 1][0] if i + 1 < len(pts) else None
            tps = bpm * 480 / 60
            segments.append((pos, tick_end, sec, tps))
            if tick_end is not None:
                sec += (tick_end - pos) / tps
        return segments

    def tick_to_seconds(self, tick) -> float:
        if tick <= 0:
            return 0.0
        for pos, end, sec0, tps in self._segments:
            if end is None or tick < end:
                return sec0 + (tick - pos) / tps
        last = self._segments[-1]
        return last[2] + (tick - last[0]) / last[3]

    def seconds_to_tick(self, seconds) -> float:
        if seconds <= 0:
            return 0.0
        for pos, end, sec0, tps in self._segments:
            if end is None:
                return pos + (seconds - sec0) * tps
            seg_sec = (end - pos) / tps
            if seconds < sec0 + seg_sec:
                return pos + (seconds - sec0) * tps
        last = self._segments[-1]
        return last[0] + (seconds - last[2]) * last[3]

    def bpm_at_tick(self, tick) -> float:
        """返回 tick 处生效的 BPM（变速段内取当前段，tick=0 取首段）。"""
        if tick < 0:
            tick = 0
        for pos, end, _sec0, tps in self._segments:
            if end is None or tick < end:
                return tps / 8.0  # tps = bpm * 480 / 60 = bpm * 8
        last = self._segments[-1]
        return last[3] / 8.0
