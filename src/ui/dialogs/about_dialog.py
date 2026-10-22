# === 文件路径: src/ui/dialogs/about_dialog.py ===
"""关于对话框：版本信息 + 面向用户的更新日志（非开发术语）。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout,
)

from src import config

# 更新日志：面向最终用户的中文描述，按版本倒序排列。
# 新增版本时在最前面追加一节即可。
CHANGELOG: list[tuple[str, list[str]]] = [
    ("2.0", [
        "全新界面：四周面板可自由拖动、浮动成独立窗口、合并为标签页，重启后自动还原布局",
        "新增暗色 / 亮色主题，菜单里随时切换",
        "扫描更聚焦：只索引图片、视频、音频、文档、压缩包等常用类型",
        "文件被移走或删除后标记为「失联」，支持一键清理失效记录",
        "自动识别照片拍摄时间与相机、视频时长与分辨率、音频时长、PDF 页数，在详情面板展示",
        "自动标签规则：按扩展名或所在目录自动打标签，规则可随时启停、一键重建",
        "组合搜索：多组标签「且 / 或」条件自由组合筛选",
        "启动密码保护：打开软件需输入主密码，连续输错 5 次锁定 60 秒",
        "加密保险库：敏感文件加密存放，预览只解密到内存，可随时导出明文或移除",
        "修改主密码即时生效，加密文件无需重新加密",
        "加密备份：一键导出加密的数据库备份文件，可凭备份密码恢复",
        "归集功能：把文件按「类型 / 年份」收拢到一个目录（优先硬链接，不占额外空间），跨盘自动改为复制，支持链接修复",
        "导出 CSV 报表：当前筛选结果一键导出，Excel 可直接打开",
        "设置中心：可更改数据保存目录（自动迁移、失败自动回滚）、清理缩略图缓存、整理数据库",
    ]),
    ("1.0", [
        "初始版本：目录扫描、文件搜索、MD5 去重、手动标签、缩略图预览",
    ]),
]


def _build_html() -> str:
    parts = [
        f"<h2 style='margin-bottom:2px'>FileMaster {config.APP_VERSION}</h2>",
        "<p style='margin-top:0'>本地索引式文件管家：扫描索引 / 标签检索 / 去重清理 / 媒体预览 / 加密保护。</p>",
        "<hr>",
        "<h3>更新日志</h3>",
    ]
    for version, entries in CHANGELOG:
        parts.append(f"<h4 style='margin-bottom:4px'>版本 {version}</h4>")
        parts.append("<ul>")
        for entry in entries:
            parts.append(f"<li>{entry}</li>")
        parts.append("</ul>")
    return "".join(parts)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于 FileMaster")
        self.setMinimumSize(520, 560)

        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(_build_html())
        layout.addWidget(browser, 1)

        row = QHBoxLayout()
        row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        layout.addLayout(row)
