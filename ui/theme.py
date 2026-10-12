"""Colour palettes and the application style sheet."""
from __future__ import annotations

PALETTES = {
    "dark": {
        "bg": "#0e0f14",
        "surface": "#16171e",
        "surface2": "#1e2029",
        "surface3": "#262834",
        "border": "#2a2c38",
        "text": "#eceef5",
        "muted": "#8a8fa3",
        "accent": "#7c5cff",
        "accent_hover": "#937aff",
        "accent_soft": "#2a2350",
        "on_accent": "#ffffff",
        "success": "#22c55e",
        "error": "#f43f5e",
        "warning": "#f59e0b",
        "canvas": "#0a0b0f",
    },
    "light": {
        "bg": "#f3f4f8",
        "surface": "#ffffff",
        "surface2": "#f1f2f7",
        "surface3": "#e7e9f0",
        "border": "#e2e4ec",
        "text": "#15161c",
        "muted": "#6b6f82",
        "accent": "#6d4aff",
        "accent_hover": "#8467ff",
        "accent_soft": "#ece7ff",
        "on_accent": "#ffffff",
        "success": "#16a34a",
        "error": "#e11d48",
        "warning": "#d97706",
        "canvas": "#e9ebf1",
    },
}

ICON_FONT = "Segoe MDL2 Assets"

# Segoe MDL2 / Fluent icon code points
ICONS = {
    "folder": "",
    "open": "",
    "add": "",
    "refresh": "",
    "clear": "",
    "prev": "",
    "next": "",
    "down": "",
    "up": "",
    "play": "",
    "stop": "",
    "moon": "",
    "sun": "",
    "photo": "",
    "compare": "",
    "check": "",
    "rot_left": "",
    "rot_right": "",
    "mirror": "",
    "error": "",
    "dot": "",
}


def stylesheet(p: dict) -> str:
    return f"""
* {{
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 10pt;
    color: {p['text']};
    outline: none;
}}
QMainWindow, QDialog, #root {{ background: {p['bg']}; }}
QToolTip {{
    background: {p['surface3']}; color: {p['text']};
    border: 1px solid {p['border']}; border-radius: 6px; padding: 5px 8px;
}}

/* header */
#header {{ background: {p['bg']}; }}
#appTitle {{ font-size: 15pt; font-weight: 600; }}
#appSubtitle {{ color: {p['muted']}; }}
#logo {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p['accent']}, stop:1 #22d3ee);
    border-radius: 10px; color: white; font-size: 14pt; font-weight: 700;
}}

/* cards */
#card {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; }}
#cardTitle {{ font-weight: 600; font-size: 10.5pt; }}
#cardHeader {{ background: transparent; }}
#muted, QLabel[muted="true"] {{ color: {p['muted']}; }}
#hint {{ color: {p['muted']}; font-size: 9pt; }}
#sidebar, #sidebarInner {{ background: transparent; }}

/* inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px;
    padding: 6px 10px; selection-background-color: {p['accent']};
}}
QLineEdit:focus, QComboBox:focus, QComboBox:on, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {p['accent']}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px;
    padding: 4px; selection-background-color: {p['accent_soft']}; selection-color: {p['text']};
}}

/* buttons */
QPushButton, QToolButton {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px;
    padding: 6px 12px;
}}
QPushButton:hover, QToolButton:hover {{ background: {p['surface3']}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {p['border']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {p['muted']}; }}
QPushButton:checked, QToolButton:checked {{
    background: {p['accent_soft']}; border-color: {p['accent']}; color: {p['text']};
}}
#iconButton {{
    font-family: {ICON_FONT}; font-size: 11pt; padding: 6px; min-width: 20px;
}}
#ghost {{ background: transparent; border: none; padding: 4px 6px; }}
#ghost:hover {{ background: {p['surface3']}; }}
#iconGhost {{
    font-family: {ICON_FONT}; font-size: 11pt; background: transparent; border: none;
    padding: 6px; border-radius: 8px;
}}
#iconGhost:hover {{ background: {p['surface3']}; }}
#iconGhost:checked {{ background: {p['accent_soft']}; color: {p['accent_hover']}; }}
#primary {{
    background: {p['accent']}; color: {p['on_accent']}; border: none; border-radius: 10px;
    padding: 10px 26px; font-weight: 600; font-size: 10.5pt;
}}
#primary:hover {{ background: {p['accent_hover']}; }}
#primary:disabled {{ background: {p['surface3']}; color: {p['muted']}; }}
#danger {{
    background: transparent; color: {p['error']}; border: 1px solid {p['error']};
    border-radius: 10px; padding: 9px 18px; font-weight: 600;
}}
#danger:hover {{ background: {p['error']}; color: white; }}

/* segmented control */
#segment {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 9px; }}
#segment QPushButton {{
    background: transparent; border: none; border-radius: 7px; padding: 5px 10px; margin: 2px;
    color: {p['muted']};
}}
#segment QPushButton:hover {{ color: {p['text']}; }}
#segment QPushButton:checked {{ background: {p['accent']}; color: {p['on_accent']}; }}

/* sliders */
QSlider::groove:horizontal {{ height: 4px; background: {p['surface3']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: white; border: 2px solid {p['accent']};
    width: 12px; height: 12px; margin: -6px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ border-color: {p['accent_hover']}; }}
#sliderValue {{ color: {p['muted']}; }}
#sliderValue[changed="true"] {{ color: {p['accent_hover']}; font-weight: 600; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {p['border']}; background: {p['surface2']};
}}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}

/* preview */
#previewFrame {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; }}
#fileName {{ font-weight: 600; }}

/* lists / tabs */
QListWidget, QPlainTextEdit {{
    background: transparent; border: none; padding: 2px;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 8px; }}
QListWidget::item:hover {{ background: {p['surface2']}; }}
QListWidget::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
QPlainTextEdit {{ font-family: "Cascadia Mono", Consolas; font-size: 9pt; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {p['muted']}; padding: 8px 14px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {p['text']}; border-bottom-color: {p['accent']}; }}
QTabBar::tab:hover {{ color: {p['text']}; }}

QProgressBar {{
    background: {p['surface3']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
}}
QProgressBar::chunk {{
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent']}, stop:1 #22d3ee);
}}
#footer {{ background: {p['surface']}; border-top: 1px solid {p['border']}; }}
#status {{ color: {p['muted']}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['surface3']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['surface3']}; border-radius: 3px; min-width: 30px; }}
QSplitter::handle {{ background: transparent; }}
QMenu {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['accent_soft']}; }}
"""
