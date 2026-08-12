"""Apple 风格设计体系(与 MC_LogAnalysis 一致)。"""

# ── Apple 设计体系 ──────────────────────────────────────────────
C_BG     = "#F5F5F7"   # 窗口背景(Apple 标志性浅灰)
C_CARD   = "#FFFFFF"   # 卡片底色
C_PRIME  = "#007AFF"   # 主色调(Apple Blue)
C_PRIME_H= "#0062CC"   # 主色调 hover
C_TEXT   = "#1D1D1F"   # 主文字
C_SUB    = "#86868B"   # 辅助文字
C_BORDER = "#E5E5EA"   # 边框/分割线
C_INPUT_BG = "#F9F9F9" # 输入框底板
C_GREEN  = "#34C759"
C_RED    = "#FF3B30"

FONT_FAMILY = (
    '"Helvetica Neue", "PingFang SC", "Segoe UI", "Microsoft YaHei", sans-serif'
)
FONT_MONO = '"Menlo", "Consolas", "Cascadia Code", "SF Mono", monospace'

GAP_SECTION = 14
GAP_ROW     = 8
GAP_INNER   = 6
CARD_PAD    = 14
RADIUS      = 8


def build_qss(scale: float = 1.0) -> str:
    """按缩放系数生成 Apple 风格 QSS(字号随窗口大小缩放)。"""
    f11 = max(9, round(11 * scale))
    f12 = max(9, round(12 * scale))
    f13 = max(10, round(13 * scale))
    f15 = max(12, round(15 * scale))
    return f"""
/* ─── 全局 ─── */
QWidget {{
    background-color: {C_BG};
    font-family: {FONT_FAMILY};
    font-size: {f13}px;
    color: {C_TEXT};
}}

/* ─── 卡片容器 ─── */
QWidget[card="true"] {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS}px;
}}

/* ─── 标签 ─── */
QLabel[heading="true"] {{
    font-size: {f15}px;
    font-weight: bold;
    color: {C_TEXT};
    padding: 0;
}}
QLabel[subtitle="true"] {{
    font-size: {f12}px;
    color: {C_SUB};
}}

/* ─── 主按钮(实心蓝) ─── */
QPushButton[primary="true"] {{
    background-color: {C_PRIME};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 24px;
    font-weight: bold;
    font-size: {f13}px;
}}
QPushButton[primary="true"]:hover {{
    background-color: {C_PRIME_H};
}}
QPushButton[primary="true"]:pressed {{
    background-color: #0055AA;
}}
QPushButton[primary="true"]:disabled {{
    background-color: #A9C6EA;
    color: #E8F0FB;
}}

/* ─── 次按钮(浅灰底) ─── */
QPushButton[secondary="true"] {{
    background-color: #F0F0F2;
    color: {C_TEXT};
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: {f13}px;
}}
QPushButton[secondary="true"]:hover {{
    background-color: #E4E4E8;
}}
QPushButton[secondary="true"]:pressed {{
    background-color: #D8D8DC;
}}

/* ─── 危险按钮(红) ─── */
QPushButton[danger="true"] {{
    background-color: #F0F0F2;
    color: {C_RED};
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: {f13}px;
}}
QPushButton[danger="true"]:hover {{
    background-color: #FFEBEA;
}}

/* ─── 链接按钮 ─── */
QPushButton[link="true"] {{
    background: transparent;
    color: {C_PRIME};
    border: none;
    padding: 6px 12px;
    font-size: {f13}px;
}}
QPushButton[link="true"]:hover {{
    color: {C_PRIME_H};
    text-decoration: underline;
}}

/* ─── 输入框 ─── */
QLineEdit, QDoubleSpinBox, QSpinBox {{
    background-color: {C_INPUT_BG};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: {f13}px;
    color: {C_TEXT};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border: 1.5px solid {C_PRIME};
    background-color: #FFFFFF;
}}
QTextEdit {{
    background-color: {C_INPUT_BG};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 8px 10px;
    font-size: {f13}px;
    color: {C_TEXT};
}}
QTextEdit:focus {{
    border: 1.5px solid {C_PRIME};
    background-color: #FFFFFF;
}}

/* ─── 进度条 ─── */
QProgressBar {{
    background-color: #E8E8ED;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {C_PRIME};
    border-radius: 4px;
}}

/* ─── 结果/日志文本框 ─── */
QTextEdit#logView {{
    background-color: #FAFAFA;
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 10px;
    font-family: {FONT_MONO};
    font-size: {f12}px;
    color: {C_TEXT};
}}

/* ─── 滚动条 ─── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #D0D0D6;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #B0B0B6;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: #D0D0D6;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ─── 菜单栏 ─── */
QMenuBar {{
    background-color: #FFFFFF;
    border-bottom: 1px solid {C_BORDER};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 6px 14px;
    border-radius: 5px;
}}
QMenuBar::item:selected {{
    background-color: #F0F0F2;
}}
QMenu {{
    background-color: #FFFFFF;
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 6px 0;
}}
QMenu::item {{
    padding: 7px 32px 7px 20px;
}}
QMenu::item:selected {{
    background-color: {C_PRIME};
    color: #FFFFFF;
    border-radius: 4px;
}}

/* ─── 状态栏 ─── */
QStatusBar {{
    background-color: #FFFFFF;
    border-top: 1px solid {C_BORDER};
    font-size: {f12}px;
    color: {C_SUB};
    padding: 2px 12px;
}}

/* ─── 提示框 ─── */
QToolTip {{
    background-color: #FFFFFF;
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: {f12}px;
    color: {C_TEXT};
}}
"""


APPLE_QSS = build_qss()


def card(title_text, layout_or_widget, parent=None):
    """Apple 风格卡片:白色圆角背景 + 可选标题。"""
    from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

    c = QWidget(parent)
    c.setProperty("card", True)
    inner = QVBoxLayout(c)
    inner.setContentsMargins(CARD_PAD, CARD_PAD, CARD_PAD, CARD_PAD)
    inner.setSpacing(GAP_ROW)
    if title_text:
        heading = QLabel(title_text)
        heading.setProperty("heading", True)
        inner.addWidget(heading)
    if hasattr(layout_or_widget, "addWidget"):
        inner.addLayout(layout_or_widget, 1)
    else:
        inner.addWidget(layout_or_widget, 1)
    return c


def hint(text):
    """灰色辅助说明标签。"""
    from PyQt5.QtWidgets import QLabel

    lbl = QLabel(text)
    lbl.setProperty("subtitle", True)
    lbl.setWordWrap(True)
    return lbl
