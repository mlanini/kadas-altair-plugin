"""Shared styling helpers for Altair dock widgets.

The theme avoids Qt version specific APIs so it can be applied in both
Qt5-based and Qt6-based KADAS/QGIS runtimes.
"""

from qgis.PyQt.QtCore import Qt


THEME_STYLESHEET = """
QWidget#AltairRoot {
    background-color: #f3efe4;
    color: #24313d;
}

QWidget#AltairRoot QLabel {
    color: #24313d;
    background: transparent;
}

QWidget#AltairRoot QLabel[altairRole="title"] {
    color: #102a43;
    font-size: 16px;
    font-weight: 700;
    padding: 4px 2px 0px 2px;
}

QWidget#AltairRoot QLabel[altairRole="subtitle"] {
    color: #52606d;
    font-size: 11px;
    padding-bottom: 4px;
}

QWidget#AltairRoot QLabel[altairRole="meta"] {
    color: #6b7c93;
    font-size: 10px;
}

QWidget#AltairRoot QLabel[altairRole="panel"] {
    background-color: #fffdf7;
    border: 1px dashed #c7bca8;
    border-radius: 10px;
    color: #52606d;
    padding: 10px;
}

QWidget#AltairRoot QLabel[altairRole="status"] {
    border: 1px solid #d8cfbf;
    border-radius: 9px;
    background-color: #f9f6ee;
    color: #334e68;
    font-size: 10px;
    font-weight: 600;
    padding: 6px 10px;
}

QWidget#AltairRoot QLabel[altairRole="status"][altairState="info"] {
    background-color: #e7f1fb;
    border-color: #8eb4d8;
    color: #0f4c75;
}

QWidget#AltairRoot QLabel[altairRole="status"][altairState="success"] {
    background-color: #e7f6ef;
    border-color: #7fb68d;
    color: #1f6f50;
}

QWidget#AltairRoot QLabel[altairRole="status"][altairState="warning"] {
    background-color: #fff2dd;
    border-color: #d8a15d;
    color: #8a5a10;
}

QWidget#AltairRoot QLabel[altairRole="status"][altairState="error"] {
    background-color: #fdebea;
    border-color: #d58d88;
    color: #9b2c2c;
}

QWidget#AltairRoot QGroupBox {
    color: #24313d;
    font-weight: 700;
    border: 1px solid #d8cfbf;
    border-radius: 12px;
    background-color: #fbf8f1;
    margin-top: 12px;
    padding: 14px 10px 10px 10px;
}

QWidget#AltairRoot QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #102a43;
    background-color: #fbf8f1;
}

QWidget#AltairRoot QLineEdit,
QWidget#AltairRoot QComboBox,
QWidget#AltairRoot QDateEdit,
QWidget#AltairRoot QSpinBox,
QWidget#AltairRoot QDoubleSpinBox,
QWidget#AltairRoot QTextEdit,
QWidget#AltairRoot QTreeWidget,
QWidget#AltairRoot QTableWidget {
    background-color: #fffdf8;
    border: 1px solid #cfc4b3;
    border-radius: 8px;
    padding: 5px 7px;
    selection-background-color: #d7e6f4;
    selection-color: #102a43;
    gridline-color: #e1d7c8;
}

QWidget#AltairRoot QComboBox::drop-down {
    border: 0;
    width: 20px;
}

QWidget#AltairRoot QTableWidget,
QWidget#AltairRoot QTreeWidget {
    alternate-background-color: #f5f1e8;
}

QWidget#AltairRoot QHeaderView::section {
    background-color: #e6dece;
    color: #24313d;
    border: 0;
    border-right: 1px solid #d1c6b6;
    border-bottom: 1px solid #d1c6b6;
    padding: 6px 8px;
    font-weight: 700;
}

QWidget#AltairRoot QPushButton {
    background-color: #ebe3d4;
    color: #24313d;
    border: 1px solid #c7bca8;
    border-radius: 9px;
    padding: 7px 12px;
    font-weight: 600;
}

QWidget#AltairRoot QPushButton:hover {
    background-color: #e0d6c6;
}

QWidget#AltairRoot QPushButton:pressed {
    background-color: #d5c9b7;
}

QWidget#AltairRoot QPushButton:disabled {
    background-color: #efe8dc;
    color: #9aa5b1;
    border-color: #ddd6c9;
}

QWidget#AltairRoot QPushButton[altairVariant="primary"] {
    background-color: #0f5f7a;
    color: #f8fbfd;
    border-color: #0b4d63;
}

QWidget#AltairRoot QPushButton[altairVariant="primary"]:hover {
    background-color: #0d556d;
}

QWidget#AltairRoot QPushButton[altairVariant="accent"] {
    background-color: #1d7a63;
    color: #f8fbfd;
    border-color: #17604e;
}

QWidget#AltairRoot QPushButton[altairVariant="accent"]:hover {
    background-color: #176852;
}

QWidget#AltairRoot QPushButton[altairVariant="ghost"] {
    background-color: #f9f6ee;
    color: #52606d;
}

QWidget#AltairRoot QPushButton[altairState="active"] {
    background-color: #1d7a63;
    color: #f8fbfd;
    border-color: #17604e;
}

QWidget#AltairRoot QTabWidget::pane {
    border: 1px solid #d8cfbf;
    border-radius: 10px;
    background-color: #fffdf8;
    top: -1px;
}

QWidget#AltairRoot QTabBar::tab {
    background-color: #e9e1d3;
    color: #52606d;
    border: 1px solid #d0c5b6;
    border-bottom: 0;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 12px;
    margin-right: 2px;
}

QWidget#AltairRoot QTabBar::tab:selected {
    background-color: #fffdf8;
    color: #102a43;
}

QWidget#AltairRoot QProgressBar {
    border: 1px solid #d1c6b6;
    border-radius: 8px;
    background-color: #fffdf8;
    text-align: center;
}

QWidget#AltairRoot QProgressBar::chunk {
    background-color: #0f5f7a;
    border-radius: 7px;
}

QWidget#AltairRoot QSlider::groove:horizontal {
    border: 0;
    height: 6px;
    background: #d7cdbf;
    border-radius: 3px;
}

QWidget#AltairRoot QSlider::handle:horizontal {
    background: #0f5f7a;
    border: 1px solid #0b4d63;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}

QWidget#AltairRoot QScrollArea {
    border: 0;
    background: transparent;
}

QWidget#AltairRoot QCheckBox {
    spacing: 6px;
}
"""


def _repolish(widget):
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def apply_dock_theme(root_widget):
    root_widget.setObjectName('AltairRoot')
    root_widget.setAttribute(Qt.WA_StyledBackground, True)
    root_widget.setStyleSheet(THEME_STYLESHEET)
    _repolish(root_widget)


def apply_dialog_theme(dialog_widget):
    """Apply the shared Altair theme to top-level dialogs."""
    apply_dock_theme(dialog_widget)


def set_label_role(label, role):
    label.setProperty('altairRole', role)
    _repolish(label)


def set_button_variant(button, variant):
    button.setProperty('altairVariant', variant)
    _repolish(button)


def set_status_state(label, state='neutral'):
    label.setProperty('altairState', state or 'neutral')
    _repolish(label)


def set_widget_state(widget, state='neutral'):
    widget.setProperty('altairState', state or 'neutral')
    _repolish(widget)


def infer_status_state(style_text):
    if not style_text:
        return 'neutral'

    style = str(style_text).lower()
    warning_tokens = ('#ffaa00', '#ffa500', '#ffcc00', 'orange')
    error_tokens = ('#ff0000', '#ff6b6b', '#ff6666', 'red')
    success_tokens = ('#00ffbf', '#00cc66', '#00aa66', 'green')
    info_tokens = ('#88ccff', '#00e5ff', 'blue')

    if any(token in style for token in error_tokens):
        return 'error'
    if any(token in style for token in warning_tokens):
        return 'warning'
    if any(token in style for token in success_tokens):
        return 'success'
    if any(token in style for token in info_tokens):
        return 'info'
    return 'neutral'