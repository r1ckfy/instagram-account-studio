import getpass

from PySide6.QtCore import QThreadPool, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from .. import APP_NAME, VERSION
from ..logs import log
from .common import CYAN, GREEN, MUTED, YELLOW, label, scrollable, set_color
from .tab_config import ConfigTab
from .tab_central import CentralTab
from .tab_contas import ContasTab
from .tab_dados import DadosTab
from .tab_imap import ImapTab
from .tab_logs import LogsTab
from .tab_navegador import NavegadorTab
from .tab_perfil import PerfilTab
from .tab_proxy import ProxyTab


class MainWindow(QMainWindow):
    profiles_changed = Signal()

    def __init__(self, db, log_handler):
        super().__init__()
        self.db = db
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setMinimumSize(1100, 640)

        # ---------------- cabeçalho
        header = QFrame(objectName="header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 18, 10)
        h.setSpacing(10)
        logo = label("◈")
        logo.setStyleSheet(f"color: {CYAN}; font-size: 20pt;")
        title = label(APP_NAME.upper())
        title.setStyleSheet("font-size: 14pt; font-weight: 800; letter-spacing: 2px;")
        self.chip_status = label("", "chip")
        self.chip_browser = label("", "chip")
        self.chip_counts = label("", "chip")
        for w in (logo, title, label(f"v{VERSION}", "chip")):
            h.addWidget(w)
        h.addStretch(1)
        for w in (label(f"👤 {getpass.getuser()}", "chip"), self.chip_status, self.chip_browser,
                  self.chip_counts):
            h.addWidget(w)
        self.set_busy("")
        self.set_demo_state("AGUARDANDO")

        # ---------------- abas
        self.tabs = QTabWidget(documentMode=True)
        self.dados = DadosTab(self)
        self.perfil = PerfilTab(self)
        self.navegador = NavegadorTab(self)
        self.imap = ImapTab(self)
        self.proxy = ProxyTab(self)
        self.central = CentralTab(self)
        self.contas = ContasTab(self)
        self.logs = LogsTab(self, log_handler)
        self.config = ConfigTab(self)
        self._pages = {}
        for w, text in ((self.central, "CENTRAL DE CADASTROS"), (self.dados, "✦  DADOS"), (self.perfil, "◉  PERFIL"),
                        (self.navegador, "🌐  NAVEGADOR"), (self.imap, "✉  IMAP"), (self.proxy, "⇄  PROXY"),
                        (self.contas, "☰  CONTAS"), (self.logs, "▤  LOGS"),
                        (self.config, "⚙  CONFIGURAÇÕES")):
            page = scrollable(w)
            self._pages[w] = page
            self.tabs.addTab(page, text)

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(header)
        v.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.profiles_changed.connect(self.update_header)
        self.update_header()
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1440, int(avail.width() * 0.94)), min(900, int(avail.height() * 0.92)))

    # ------------------------------------------------------------ API comum
    def goto(self, tab: QWidget):
        self.tabs.setCurrentWidget(self._pages[tab])

    def update_header(self):
        s = self.db.stats()
        self.chip_counts.setText(f"Perfis {s['total']}  •  Preparados {s['preparados']}  •  Ativas {s['ativas']}")

    def set_busy(self, text: str):
        self.chip_status.setText(f"◌ {text}…" if text else "● PRONTO")
        set_color(self.chip_status, YELLOW if text else GREEN, bold=True)

    def set_demo_state(self, state: str, active: bool = False):
        self.chip_browser.setText(f"🌐 Navegador demo: {'conectado' if active else 'inativo'}"
                                  + (f" ({state.lower()})" if active else ""))
        set_color(self.chip_browser, CYAN if active else MUTED)

    def reload_all(self):
        self.perfil.clear()
        self.dados.refresh()
        self.imap.refresh()
        self.profiles_changed.emit()

    def closeEvent(self, event):
        if self.proxy.busy or self.central.busy or self.navegador.dolphin_busy:
            self.proxy.shutting_down = True
            self.central.batch_stop.set()
            event.ignore()
            self.set_busy("Encerrando diagnóstico de proxy")
            QTimer.singleShot(500, self.close)
            return
        self.central.shutdown()
        self.proxy.shutdown()
        self.navegador.shutdown()
        if not QThreadPool.globalInstance().waitForDone(8000):
            log.warning("Tarefas em segundo plano ainda ativas no encerramento.")
        log.info("Aplicativo encerrado.")
        super().closeEvent(event)
