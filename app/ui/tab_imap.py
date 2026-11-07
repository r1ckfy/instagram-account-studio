from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout,
                               QLineEdit, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from .. import generator as gen
from .. import imap_client
from ..db import DuplicateError
from ..logs import log, success
from .common import (CYAN, GREEN, RED, YELLOW, button, confirm, group, label, row, run_async,
                     set_color, warn)


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    return t


class ImapTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db
        self.aid: int | None = None
        self.messages: list[dict] = []
        self.visible: list[dict] = []
        self._fetched = None
        self.busy = False

        # ---------------- contas
        box_acc, acc = group("CAIXAS DE E-MAIL")
        self.accounts = _table(["Nome", "E-mail", "Servidor", "Porta", "Segurança"])
        self.accounts.itemSelectionChanged.connect(self._select_account)
        self.accounts.setMaximumHeight(120)
        acc.addWidget(self.accounts)

        box_form, form = group("CONEXÃO", QFormLayout())
        self.preset = QComboBox()
        self.preset.addItems(imap_client.PRESETS)
        self.preset.currentTextChanged.connect(self._apply_preset)
        self.name = QLineEdit(placeholderText="ex.: Hostinger principal")
        self.email = QLineEdit(placeholderText="endereço que você já possui")
        self.host = QLineEdit(placeholderText="imap.seudominio.com")
        self.port = QSpinBox(minimum=1, maximum=65535, value=993)
        self.sec = QComboBox()
        self.sec.addItem("SSL/TLS (porta 993)", "ssl")
        self.sec.addItem("STARTTLS (porta 143)", "starttls")
        self.user = QLineEdit(placeholderText="normalmente o próprio e-mail")
        self.password = QLineEdit(echoMode=QLineEdit.Password,
                                  placeholderText="senha ou senha de app (cifrada com DPAPI)")
        for text, w in (("Modelo", self.preset), ("Nome da conexão", self.name), ("E-mail", self.email),
                        ("Servidor IMAP", self.host), ("Porta", self.port), ("Segurança", self.sec),
                        ("Usuário", self.user), ("Senha", self.password)):
            form.addRow(text, w)
        form.addRow(label("Gmail/Yahoo: use uma senha de app (exige verificação em 2 etapas). "
                          "Login OAuth2 não é suportado nesta versão. Este app não cria e-mails.",
                          "muted", wrap=True))
        self.conn_status = label("", wrap=True)
        form.addRow(self.conn_status)
        self.test_btn = button("⚡ Testar conexão", "primary", self.test)
        form.addRow(row(button("Novo", None, self.new), button("💾 Salvar", "success", self.save),
                        self.test_btn, None, button("Remover", "danger", self.remove)))

        # ---------------- mensagens
        box_msg, msg = group("MENSAGENS RECENTES (SOMENTE LEITURA)")
        self.folder = QLineEdit("INBOX")
        self.folder.setMaximumWidth(140)
        self.limit = QSpinBox(minimum=5, maximum=200, value=30)
        self.filter = QLineEdit(placeholderText="Filtrar por remetente ou assunto…")
        self.filter.textChanged.connect(self._render_messages)
        self.fetch_btn = button("⟳ BUSCAR MENSAGENS", "primary", self.fetch)
        msg.addLayout(row(label("Pasta"), self.folder, label("Qtd."), self.limit, self.filter, self.fetch_btn))
        self.msg_table = _table(["Data", "Remetente", "Assunto"])
        self.msg_table.itemSelectionChanged.connect(self._open_message)
        self.body = QTextBrowser()
        self.body.setOpenLinks(False)
        self.body.setPlaceholderText("Selecione uma mensagem para ler. Anexos não são baixados; "
                                     "nada é marcado como lido ou apagado no servidor.")
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.msg_table)
        split.addWidget(self.body)
        split.setSizes([260, 200])
        msg.addWidget(split, 1)

        left = QVBoxLayout()
        left.addWidget(box_acc)
        left.addWidget(box_form)
        left.addStretch(1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        lay.setSpacing(12)
        lay.addLayout(left, 2)
        lay.addWidget(box_msg, 3)
        self.refresh()
        self.new()

    # ------------------------------------------------------------ contas
    def refresh(self):
        self.rows = self.db.list_imap()
        self.accounts.setRowCount(len(self.rows))
        for r, a in enumerate(self.rows):
            for c, v in enumerate((a["name"], a["email"], a["host"], str(a["port"]),
                                   "SSL/TLS" if a["security"] == "ssl" else "STARTTLS")):
                self.accounts.setItem(r, c, QTableWidgetItem(v))
        self.accounts.resizeColumnsToContents()
        self.main.update_header()

    def _apply_preset(self, name: str):
        host, port, sec = imap_client.PRESETS[name]
        if host:
            self.host.setText(host)
            self.port.setValue(port)
            self.sec.setCurrentIndex(self.sec.findData(sec))

    def _select_account(self):
        r = self.accounts.currentRow()
        if r < 0 or r >= len(self.rows):
            return
        a = self.rows[r]
        self.aid = a["id"]
        self.name.setText(a["name"])
        self.email.setText(a["email"])
        self.host.setText(a["host"])
        self.port.setValue(a["port"])
        self.sec.setCurrentIndex(self.sec.findData(a["security"]))
        self.user.setText(a["username"])
        self.password.clear()
        self.password.setPlaceholderText("•••••• (deixe vazio para manter a senha salva)")
        self.conn_status.setText("")

    def new(self):
        self.aid = None
        self.accounts.clearSelection()
        for w in (self.name, self.email, self.host, self.user, self.password):
            w.clear()
        self.preset.setCurrentIndex(0)
        self.port.setValue(993)
        self.sec.setCurrentIndex(0)
        self.password.setPlaceholderText("senha ou senha de app (cifrada com DPAPI)")
        self.conn_status.setText("")

    def _cfg(self) -> dict:
        return {"id": self.aid, "name": self.name.text().strip(), "email": self.email.text().strip(),
                "host": self.host.text().strip(), "port": self.port.value(),
                "security": self.sec.currentData(),
                "username": self.user.text().strip() or self.email.text().strip()}

    def _validate(self, c: dict) -> str | None:
        if not c["name"]:
            return "Informe um nome para a conexão."
        if gen.validate_email(c["email"]):
            return "Informe um e-mail válido."
        if not gen._DOMAIN_RE.match(c["host"]):
            return "Informe o servidor IMAP (ex.: imap.hostinger.com)."
        return None

    def save(self):
        c = self._cfg()
        if err := self._validate(c):
            return warn(self, "Revise a conexão", err)
        pw = self.password.text()
        if self.aid is None and not pw:
            return warn(self, "Senha", "Informe a senha (ou senha de app) da caixa de e-mail.")
        try:
            self.aid = self.db.save_imap(c, pw or None)
        except DuplicateError as e:
            return warn(self, "Nome duplicado", str(e))
        success("Conexão IMAP '%s' salva.", c["name"])
        self.password.clear()
        self.password.setPlaceholderText("•••••• (deixe vazio para manter a senha salva)")
        aid = self.aid
        self.refresh()
        self.accounts.selectRow(next(i for i, a in enumerate(self.rows) if a["id"] == aid))

    def remove(self):
        if self.aid is None:
            return
        name = self.name.text()
        if confirm(self, "Remover conexão", f"Remover a conexão '{name}' deste aplicativo?\n"
                                            "(Nada é apagado no servidor de e-mail.)"):
            self.db.delete_imap(self.aid)
            log.warning("Conexão IMAP '%s' removida.", name)
            self.new()
            self.refresh()

    def _credentials(self) -> tuple[dict, str] | None:
        c = self._cfg()
        if err := self._validate(c):
            warn(self, "Revise a conexão", err)
            return None
        pw = self.password.text() or (self.db.get_imap_password(self.aid) if self.aid else "")
        if not pw:
            warn(self, "Senha", "Informe a senha para testar a conexão.")
            return None
        return c, pw

    def _busy(self, on: bool, text: str = ""):
        self.busy = on
        self.test_btn.setEnabled(not on)
        self.fetch_btn.setEnabled(not on)
        self.main.set_busy(text if on else "")

    def test(self):
        creds = self._credentials()
        if not creds or self.busy:
            return
        c, pw = creds
        self.conn_status.setText("Conectando…")
        set_color(self.conn_status, YELLOW)
        self._busy(True, "Testando IMAP")
        log.info("Testando conexão IMAP '%s' (%s:%s).", c["name"], c["host"], c["port"])

        def done(msg):
            self._busy(False)
            self.conn_status.setText(f"✓ {msg}")
            set_color(self.conn_status, GREEN)
            success("IMAP '%s': %s", c["name"], msg)

        def failed(exc):
            self._busy(False)
            msg = imap_client.friendly_error(exc)
            self.conn_status.setText(f"✖ {msg}")
            set_color(self.conn_status, RED)
            log.error("IMAP '%s': %s", c["name"], msg)

        run_async(lambda: imap_client.test_connection(c, pw), done, failed)

    # ------------------------------------------------------------ mensagens
    def fetch(self):
        creds = self._credentials()
        if not creds or self.busy:
            return
        c, pw = creds
        folder, limit = self.folder.text().strip() or "INBOX", self.limit.value()
        self._busy(True, "Buscando e-mails")
        self.body.clear()
        log.info("Buscando %d mensagens recentes de '%s' (%s).", limit, c["name"], folder)

        def done(msgs):
            self._busy(False)
            self.messages = msgs
            self._fetched = (c, pw, folder)
            self._render_messages()
            success("%d mensagens carregadas de '%s'.", len(msgs), c["name"])

        def failed(exc):
            self._busy(False)
            msg = imap_client.friendly_error(exc)
            log.error("Falha ao buscar mensagens de '%s': %s", c["name"], msg)
            warn(self, "IMAP", msg)

        run_async(lambda: imap_client.fetch_recent(c, pw, limit, folder), done, failed)

    def _render_messages(self):
        q = self.filter.text().strip().lower()
        self.visible = [m for m in self.messages
                        if not q or q in m["from"].lower() or q in m["subject"].lower()]
        self.msg_table.setRowCount(len(self.visible))
        for r, m in enumerate(self.visible):
            for col, v in enumerate((m["date"], m["from"], m["subject"])):
                item = QTableWidgetItem(v)
                if "instagram" in m["from"].lower():
                    item.setForeground(QColor(CYAN))
                self.msg_table.setItem(r, col, item)
        self.msg_table.resizeColumnToContents(0)
        self.msg_table.setColumnWidth(1, 240)

    def _open_message(self):
        r = self.msg_table.currentRow()
        if r < 0 or r >= len(self.visible) or self.busy:
            return
        m = self.visible[r]
        c, pw, folder = self._fetched
        self.body.setPlainText("Carregando mensagem…")
        self._busy(True, "Lendo e-mail")

        def done(text):
            self._busy(False)
            self.body.setPlainText(f"De: {m['from']}\nAssunto: {m['subject']}\nData: {m['date']}\n\n{text}")

        def failed(exc):
            self._busy(False)
            self.body.setPlainText(f"Não foi possível abrir a mensagem: {imap_client.friendly_error(exc)}")

        run_async(lambda: imap_client.fetch_body(c, pw, m["uid"], folder), done, failed)

