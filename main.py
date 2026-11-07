import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app import APP_NAME, DATA_DIR, VERSION
from app.db import Database
from app.logs import log, setup_logging, success
from app.ui.common import STYLESHEET
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLESHEET)
    handler = setup_logging(DATA_DIR / "logs")
    log.info("Aplicativo iniciado (versão %s).", VERSION)

    try:
        db = Database(DATA_DIR / "studio.db")
    except Exception as e:
        log.exception("Falha ao abrir o banco de dados.")
        QMessageBox.critical(None, APP_NAME, f"Não foi possível abrir o banco de dados:\n{e}")
        return 1
    success("Banco de dados conectado (%s).", db.path)

    def excepthook(exc_type, exc, tb):
        log.error("Erro inesperado: %s", exc, exc_info=(exc_type, exc, tb))
        QMessageBox.critical(None, "Erro inesperado",
                             f"Ocorreu um erro inesperado:\n{exc}\n\nOs detalhes foram gravados no log.")

    sys.excepthook = excepthook
    window = MainWindow(db, handler)
    window.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
