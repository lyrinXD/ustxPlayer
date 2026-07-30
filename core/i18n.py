# i18n.py — qfluentwidgets 内部英文文案的中文翻译
"""通过自定义 QTranslator 覆写 translate()，把 qfluentwidgets 用 self.tr() 包裹的
英文文案翻译成中文（导航按钮 tooltip、颜色选择对话框等）。

qfluentwidgets 未随包附带 .qm 翻译文件，此处用 Python 端覆写 translate() 的方式
按 sourceText 精确匹配返回中文。

未命中时返回原文 src：PySide6 + Qt 6 下空字符串会被当作"已翻译为空"直接使用，
导致 QFileDialog 等标准对话框按钮文字消失，故不能返回空串。
"""

import re

from PySide6.QtCore import QTranslator


class ChineseTranslator(QTranslator):
    """按 sourceText 精确匹配的简易中译器。

    命中 _DICT 返回中文翻译；未命中返回原文 src，确保未翻译文案始终可见。
    QFileDialog 等标准对话框的源文本常带 Qt 助记符 &（如 "&Look in:"），
    查找时会先去掉单 &（保留 && 表示真实 &）再匹配字典。
    """

    _DICT = {
        # 导航面板（navigation_panel.py）
        "Open Navigation": "展开导航",
        "Close Navigation": "收起导航",
        "Back": "返回",
        # 颜色对话框（color_dialog.py）
        "OK": "确定",
        "Cancel": "取消",
        "Edit Color": "编辑颜色",
        "Red": "红",
        "Green": "绿",
        "Blue": "蓝",
        "Opacity": "不透明度",
        # 自定义颜色设置卡（custom_color_setting_card.py）
        "Default color": "默认颜色",
        "Custom color": "自定义颜色",
        "Choose color": "选择颜色",
        # QPlatformTheme / QFileDialog 标准对话框文案兜底
        "Open": "打开",
        "Save": "保存",
        "Look in:": "查找范围：",
        "Look in": "查找范围",
        "File name:": "文件名：",
        "File name": "文件名",
        "Files of type:": "文件类型：",
        "Files of type": "文件类型",
        "Create New Folder": "新建文件夹",
        "List View": "列表视图",
        "Detail View": "详情视图",
        "My Computer": "此电脑",
        "Computer": "此电脑",
        "Desktop": "桌面",
    }

    def translate(self, context, sourceText, disambiguation=None, n=-1):  # noqa: D401
        # PySide6 不同版本可能传入 bytes 或 str，统一转 str
        if isinstance(sourceText, (bytes, bytearray)):
            src = bytes(sourceText).decode("utf-8", "replace")
        else:
            src = str(sourceText)
        result = self._DICT.get(src)
        if result is None:
            # 源文本可能带 Qt 助记符 &（如 "&Look in:"），去掉单 & 后再查一次
            stripped = re.sub(r"&(?!&)", "", src)
            if stripped != src:
                result = self._DICT.get(stripped)
        if result is not None:
            return result
        # 未命中返回原文，避免空字符串导致按钮文字消失
        return src
