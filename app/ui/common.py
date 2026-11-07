"""Tema dark-tech, widgets utilitários e execução assíncrona (QThreadPool)."""
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

BG, PANEL, COMP = "#090D11", "#10152A", "#171D35"
CYAN, GREEN, RED, YELLOW = "#00D9F5", "#00E69A", "#FF4268", "#FFC247"
TEXT, MUTED, BORDER = "#E8ECF5", "#8A93B2", "#232B4A"

STATUS_COLORS = {"preparado": MUTED, "em_cadastro": CYAN, "verificacao": YELLOW,
                 "ativa": GREEN, "bloqueada": RED, "desativada": MUTED, "falhou": RED}

STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-family: "Segoe UI"; font-size: 10pt; }}
QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="title"] {{ color: {CYAN}; font-size: 11pt; font-weight: 700; letter-spacing: 1px; }}
QLabel[role="chip"] {{ background: {COMP}; border: 1px solid {BORDER}; border-radius: 11px; padding: 3px 10px; }}
QFrame#header {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
            margin-top: 16px; padding: 14px 12px 12px 12px; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {CYAN}; letter-spacing: 1px; }}
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox, QDateEdit, QListWidget {{
    background: {COMP}; border: 1px solid #262F55; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {CYAN}; selection-color: {BG}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{ border-color: {CYAN}; }}
QLineEdit:read-only {{ background: #121831; }}
QComboBox QAbstractItemView {{ background: {COMP}; border: 1px solid {BORDER}; selection-background-color: #0E3A4A; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; background: transparent; }}
QPushButton {{ background: {COMP}; border: 1px solid #2A345E; border-radius: 8px; padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ border-color: {CYAN}; }}
QPushButton:pressed {{ background: #0E3A4A; }}
QPushButton:disabled {{ color: #4A5275; border-color: {BORDER}; background: #10152A; }}
QPushButton[variant="primary"] {{ background: {CYAN}; color: #04121A; border: none; }}
QPushButton[variant="primary"]:hover {{ background: #4DE7FA; }}
QPushButton[variant="success"] {{ background: {GREEN}; color: #03140D; border: none; }}
QPushButton[variant="success"]:hover {{ background: #4DF0B8; }}
QPushButton[variant="danger"] {{ background: transparent; color: {RED}; border: 1px solid {RED}; }}
QPushButton[variant="danger"]:hover {{ background: {RED}; color: white; }}
QPushButton[variant="icon"] {{ padding: 4px 8px; min-width: 22px; }}
QPushButton[variant="primary"]:disabled, QPushButton[variant="success"]:disabled,
QPushButton[variant="danger"]:disabled {{ background: #10152A; color: #4A5275; border: 1px solid {BORDER}; }}
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: {PANEL}; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 11px 16px; border: none;
               border-bottom: 2px solid transparent; font-weight: 700; letter-spacing: 1px; }}
QTabBar::tab:selected {{ color: {CYAN}; border-bottom: 2px solid {CYAN}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
QTableWidget {{ background: {PANEL}; alternate-background-color: #131A33; gridline-color: {BORDER};
               border: 1px solid {BORDER}; border-radius: 8px; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: #0E3A4A; color: white; }}
QHeaderView::section {{ background: {COMP}; color: {CYAN}; border: none; border-right: 1px solid {BORDER};
                       padding: 6px; font-weight: 700; }}
QTableCornerButton::section {{ background: {COMP}; border: none; }}
QScrollArea {{ background: transparent; border: none; }}
QSplitter::handle {{ background: {BORDER}; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2A345E; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2A345E; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QToolTip {{ background: {COMP}; color: {TEXT}; border: 1px solid {CYAN}; }}
QMessageBox QLabel {{ min-width: 320px; }}
"""

# Segundos até limpar uma senha copiada (alterado em CONFIGURAÇÕES). 0 = nunca.
clipboard_clear_seconds = 30


def button(text: str, variant: str | None = None, slot=None, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    if variant:
        b.setProperty("variant", variant)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


def set_color(lb: QLabel, color: str, bold: bool = False):
    lb.setStyleSheet(f"color: {color};" + (" font-weight: 700;" if bold else ""))


def group(title: str, layout=None) -> tuple[QGroupBox, object]:
    box = QGroupBox(title)
    lay = layout or QVBoxLayout()
    box.setLayout(lay)
    return box, lay


def row(*widgets, stretch_last: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(8)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    if stretch_last:
        lay.addStretch(1)
    return lay


def scrollable(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    return area


def copy_text(text: str, secret: bool = False):
    cb = QGuiApplication.clipboard()
    cb.setText(text)
    if secret and clipboard_clear_seconds > 0:
        QTimer.singleShot(clipboard_clear_seconds * 1000,
                          lambda: cb.text() == text and cb.clear())


class CopyField(QWidget):
    """Campo somente leitura + botão copiar (e mostrar/ocultar para segredos)."""

    def __init__(self, secret: bool = False, on_copy=None):
        super().__init__()
        self.secret, self.on_copy = secret, on_copy
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.edit, 1)
        if secret:
            self.edit.setEchoMode(QLineEdit.Password)
            self.eye = button("👁", "icon", self.toggle, "Mostrar/ocultar")
            lay.addWidget(self.eye)
        self.copy_btn = button("⧉ Copiar", None, self.copy, "Copiar para a área de transferência")
        lay.addWidget(self.copy_btn)

    def toggle(self):
        hidden = self.edit.echoMode() == QLineEdit.Password
        self.edit.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)

    def setText(self, text: str):
        self.edit.setText(text)
        self.edit.setCursorPosition(0)
        self.copy_btn.setEnabled(bool(text))

    def text(self) -> str:
        return self.edit.text()

    def copy(self):
        if not self.text():
            return
        copy_text(self.text(), self.secret)
        self.copy_btn.setText("✓ Copiado")
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("⧉ Copiar"))
        if self.on_copy:
            self.on_copy()


def info(parent, title: str, text: str):
    QMessageBox.information(parent, title, text)


def warn(parent, title: str, text: str):
    QMessageBox.warning(parent, title, text)


def error(parent, title: str, text: str):
    QMessageBox.critical(parent, title, text)


def confirm(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes


# ------------------------------------------------------------ tarefas em 2º plano
_alive: set = set()


class _Bridge(QObject):
    """Vive na thread da interface: sinais emitidos pelo worker chegam aqui enfileirados."""
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(str)

    def __init__(self, on_done, on_error, on_progress):
        super().__init__()
        self._cbs = (on_done, on_error, on_progress)
        self.done.connect(self._done)
        self.failed.connect(self._failed)
        self.progress.connect(self._progress)

    @Slot(object)
    def _done(self, result):
        _alive.discard(self)
        if self._cbs[0]:
            self._cbs[0](result)

    @Slot(object)
    def _failed(self, exc):
        _alive.discard(self)
        if self._cbs[1]:
            self._cbs[1](exc)

    @Slot(str)
    def _progress(self, text):
        if self._cbs[2]:
            self._cbs[2](text)


class _Task(QRunnable):
    def __init__(self, fn, bridge: _Bridge, with_progress: bool):
        super().__init__()
        self.fn, self.bridge, self.with_progress = fn, bridge, with_progress

    def run(self):
        try:
            result = self.fn(self.bridge.progress.emit) if self.with_progress else self.fn()
        except Exception as e:  # entregue à interface, que decide a mensagem
            self.bridge.failed.emit(e)
        else:
            self.bridge.done.emit(result)


def run_async(fn, on_done=None, on_error=None, on_progress=None):
    """Executa `fn` fora da thread da interface. Callbacks rodam na thread da interface.
    Com `on_progress`, `fn` recebe uma função `progress(str)`."""
    bridge = _Bridge(on_done, on_error, on_progress)
    _alive.add(bridge)
    QThreadPool.globalInstance().start(_Task(fn, bridge, on_progress is not None))
