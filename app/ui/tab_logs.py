import html
import os

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QLineEdit, QPlainTextEdit,
                               QVBoxLayout, QWidget)

from .. import DATA_DIR
from ..logs import QtLogHandler, log, success
from .common import CYAN, GREEN, MUTED, RED, TEXT, YELLOW, button, label, row, set_color

LEVEL_COLORS = {"INFO": TEXT, "SUCESSO": GREEN, "AVISO": YELLOW, "ERRO": RED, "CRITICAL": RED}


class LogsTab(QWidget):
    def __init__(self, main, handler: QtLogHandler):
        super().__init__()
        self.main, self.handler = main, handler

        self.level = QComboBox()
        self.level.addItem("Todos os níveis", None)
        for lv in ("INFO", "SUCESSO", "AVISO", "ERRO"):
            self.level.addItem(lv, lv)
        self.level.currentIndexChanged.connect(self.render)
        self.search = QLineEdit(placeholderText="Pesquisar nas mensagens…")
        self.search.textChanged.connect(self.render)
        self.autoscroll = QCheckBox("Rolagem automática")
        self.autoscroll.setChecked(True)
        self.activity = label("●")
        set_color(self.activity, MUTED)
        self.count = label("", "muted")
        tools = row(self.activity, self.level, self.search, self.autoscroll,
                    button("⤓ Ir ao final", None, self.to_end),
                    button("Exportar…", None, self.export),
                    button("Abrir pasta de logs", None, lambda: os.startfile(DATA_DIR / "logs")),
                    button("Limpar visualização", "danger", self.clear))
        tools.setStretch(2, 1)

        self.view = QPlainTextEdit(readOnly=True)
        font = QFont("Cascadia Mono")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.view.setFont(font)
        self.view.setMaximumBlockCount(5000)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        lay.addLayout(tools)
        lay.addWidget(self.view, 1)
        lay.addLayout(row(self.count, None, label(f"Arquivo com rotação: {DATA_DIR / 'logs' / 'studio.log'}", "muted")))

        self._blink = QTimer(self, singleShot=True, interval=700)
        self._blink.timeout.connect(lambda: set_color(self.activity, MUTED))
        handler.emitter.record.connect(self.on_record)
        self.render()

    def _matches(self, level: str, msg: str) -> bool:
        want = self.level.currentData()
        q = self.search.text().strip().lower()
        return (want is None or level == want) and (not q or q in msg.lower())

    def _line(self, t: str, level: str, msg: str) -> str:
        color = LEVEL_COLORS.get(level, TEXT)
        body = html.escape(msg).replace("\n", "<br>")
        return (f'<span style="color:{MUTED}">[{t}]</span> '
                f'<span style="color:{color};font-weight:700">[{level}]</span> '
                f'<span style="color:{color if level != "INFO" else TEXT}">{body}</span>')

    @Slot(str, str, str)
    def on_record(self, t: str, level: str, msg: str):
        set_color(self.activity, CYAN)
        self._blink.start()
        if self._matches(level, msg):
            self.view.appendHtml(self._line(t, level, msg))
            if self.autoscroll.isChecked():
                self.to_end()
        self._update_count()

    def render(self):
        self.view.clear()
        lines = [self._line(*r) for r in list(self.handler.records) if self._matches(r[1], r[2])]
        if lines:
            self.view.appendHtml("<br>".join(lines))
        self.to_end()
        self._update_count()

    def _update_count(self):
        recs = list(self.handler.records)
        errs = sum(1 for r in recs if r[1] == "ERRO")
        self.count.setText(f"{len(recs)} eventos na sessão • {errs} erro(s)")

    def to_end(self):
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self):
        self.handler.records.clear()
        self.render()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exportar logs", str(DATA_DIR / "logs_exportados.txt"),
                                              "Texto (*.txt)")
        if not path:
            return
        lines = [f"[{t}] [{lv}] {m}" for t, lv, m in list(self.handler.records) if self._matches(lv, m)]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            log.error("Falha ao exportar logs: %s", e)
            return
        success("%d linha(s) de log exportada(s) para %s.", len(lines), path)
