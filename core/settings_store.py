# settings_store.py — Settings.json 文件存取
"""用户级偏好持久化服务（Settings.json，结构为「分组 → 键值」字典）。

仅负责文件 IO（原子写 + 只读回退），不含任何设置业务逻辑。
不兼容旧版 Settings.ini，首次启动直接按默认值重建。
"""

import json
import os
import sys

from core.log import logger

_FILE_NAME = "Settings.json"


class SettingsStore:
    """设置存取服务（JSON）。"""

    def __init__(self):
        self.settings_path = self._resolve_settings_path()

    @staticmethod
    def _resolve_settings_path() -> str:
        """解析 Settings.json 路径：程序根目录可写时放根目录，否则回退用户数据目录。"""
        root = os.path.dirname(os.path.abspath(sys.argv[0]))
        if os.access(root, os.W_OK):
            return os.path.join(root, _FILE_NAME)
        fallback_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ustxPlayer"
        )
        try:
            os.makedirs(fallback_dir, exist_ok=True)
        except OSError:
            pass
        return os.path.join(fallback_dir, _FILE_NAME)

    def load(self) -> dict:
        """读取设置；文件不存在或格式异常时返回空配置。"""
        if not os.path.exists(self.settings_path):
            return {}
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning(f"设置文件格式异常，按空配置处理: {self.settings_path}")
            return {}
        except Exception as e:
            logger.exception(f"读取设置文件失败，按空配置处理: {e}")
            return {}

    def save(self, config: dict):
        """把配置写入 Settings.json（临时文件 + 原子替换，避免写一半损坏配置）。"""
        tmp_path = self.settings_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.settings_path)