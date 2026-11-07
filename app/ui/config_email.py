"""CONFIGURAÇÕES → GERADOR DE E-MAILS e ENCAMINHAMENTO (Cloudflare + caixa IMAP de destino)."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QLineEdit, QSpinBox, QVBoxLayout,
                               QWidget)

from .. import email_infra, fichas
from .. import generator as gen
from ..logs import log, success
from .common import (GREEN, MUTED, RED, YELLOW, button, confirm, group, info, label, row, run_async,
                     set_color, warn)
from .dialogs import email_settings

SAVED = "•••••• (salva — deixe vazio para manter)"


class EmailSettings(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db
        cfg = email_settings(self.db)

        # ---------------- painel de e-mails
        box_p, fp = group("GERADOR DE E-MAILS", QFormLayout())
        self.panel_url = QLineEdit(cfg["panel_url"])
        self.api_base = QLineEdit(self.db.get_setting("panel_api_base"),
                                  placeholderText="vazio = painel sem API (use importação TXT/CSV)")
        self.auth = QComboBox()
        for k, v in email_infra.PANEL_AUTH.items():
            self.auth.addItem(v, k)
        self.auth.setCurrentIndex(max(0, self.auth.findData(self.db.get_setting("panel_auth", "nenhuma"))))
        self.credential = QLineEdit(echoMode=QLineEdit.Password)
        self.domain = QLineEdit(cfg["domain"])
        self.timeout = QSpinBox(minimum=3, maximum=60, value=cfg["timeout"], suffix=" s")
        self.panel_status = label("", wrap=True)
        fp.addRow("URL do painel", row(self.panel_url, button("Abrir", None, self.open_panel)))
        fp.addRow("URL base da API", self.api_base)
        fp.addRow("Autenticação", self.auth)
        fp.addRow("Credencial", self.credential)
        fp.addRow("Domínio padrão", self.domain)
        fp.addRow("Tempo limite", self.timeout)
        fp.addRow("Status", self.panel_status)
        fp.addRow(label("Criação/listagem de aliases pela API: " +
                        ("disponível." if email_infra.PANEL_CAN_CREATE else
                         "indisponível até a documentação da API do painel ser fornecida. "
                         "A credencial é cifrada com DPAPI e nunca vai para os logs."), "muted", wrap=True))
        self.test_btn = button("⚡ TESTAR API", "primary", self.test_api)
        fp.addRow(row(self.test_btn, button("💾 SALVAR CONFIGURAÇÃO", "success", self.save_panel),
                      button("⟳ SINCRONIZAR ENDEREÇOS", None, self.sync),
                      button("DESCONECTAR", "danger", self.disconnect)))

        # ---------------- encaminhamento
        box_f, ff = group("ENCAMINHAMENTO (CLOUDFLARE EMAIL ROUTING → CAIXA IMAP)", QFormLayout())
        self.dest = QComboBox()
        self.cf_zone = QLineEdit(cfg["cf_zone"], placeholderText="Zone ID do domínio na Cloudflare")
        self.cf_token = QLineEdit(echoMode=QLineEdit.Password)
        self.cf_status = label("", wrap=True)
        ff.addRow("Caixa IMAP de destino", self.dest)
        ff.addRow("Zone ID", self.cf_zone)
        ff.addRow("Token da API", self.cf_token)
        ff.addRow("", self.cf_status)
        ff.addRow(label("Opcional e somente leitura: com um token de permissão “Email Routing Rules: Read” o "
                        "app consulta se cada endereço tem regra de encaminhamento. O app não cria nem altera "
                        "regras. A caixa de destino é a conta da aba IMAP que recebe o encaminhamento (ex.: Gmail).",
                        "muted", wrap=True))
        self.cf_btn = button("Testar Cloudflare", None, self.test_cf)
        ff.addRow(row(button("💾 Salvar encaminhamento", "success", self.save_forwarding), self.cf_btn, None))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(box_p)
        lay.addWidget(box_f)
        self._load_status()

    def showEvent(self, event):
        self.refresh_dest()
        super().showEvent(event)

    def refresh_dest(self):
        current = self.db.get_setting("email_dest_imap")
        self.dest.clear()
        self.dest.addItem("— nenhuma —", "")
        for a in self.db.list_imap():
            self.dest.addItem(f"{a['name']} ({a['email']})", str(a["id"]))
        self.dest.setCurrentIndex(max(0, self.dest.findData(current)))

    def _load_status(self):
        has_cred = bool(self.db.get_secret("panel_credential"))
        self.credential.setPlaceholderText(SAVED if has_cred else "token ou chave da API (se houver)")
        st = self.db.get_setting("panel_status", "Não testado.")
        self.panel_status.setText(st)
        set_color(self.panel_status, GREEN if st.startswith("✓") else RED if st.startswith("✖") else YELLOW)
        has_cf = bool(self.db.get_secret("cf_token"))
        self.cf_token.setPlaceholderText(SAVED if has_cf else "token Cloudflare (somente leitura)")
        st = self.db.get_setting("cf_status", "Não configurado.")
        self.cf_status.setText(st)
        set_color(self.cf_status, GREEN if st.startswith("✓") else RED if st.startswith("✖") else MUTED)
        self.refresh_dest()

    # ------------------------------------------------------------ painel
    def open_panel(self):
        QDesktopServices.openUrl(QUrl(self.panel_url.text().strip()))

    def save_panel(self):
        domain = self.domain.text().strip().lstrip("@").lower()
        if domain and not gen._DOMAIN_RE.match(domain):
            return warn(self, "Domínio", "Informe um domínio válido, ex.: inboxnexo.online.")
        api = self.api_base.text().strip()
        if api and not api.startswith(("https://", "http://")):
            return warn(self, "URL da API", "A URL da API deve começar com https://")
        for key, value in (("panel_url", self.panel_url.text().strip()), ("panel_api_base", api),
                           ("panel_auth", self.auth.currentData()), ("email_domain", domain),
                           ("email_timeout", self.timeout.value())):
            self.db.set_setting(key, value)
        if self.credential.text():
            self.db.set_secret("panel_credential", self.credential.text())
            self.credential.clear()
        self.db.add_activity("integracao", "Configuração do gerador de e-mails salva.")
        success("Configuração do gerador de e-mails salva.")
        self._load_status()

    def _panel_args(self):
        cred = self.credential.text() or self.db.get_secret("panel_credential")
        return self.api_base.text().strip(), self.auth.currentData(), cred, self.timeout.value()

    def _set_panel_status(self, text: str):
        self.db.set_setting("panel_status", f"{text} ({datetime.now():%d/%m %H:%M})")
        self._load_status()

    def test_api(self):
        args = self._panel_args()
        self.test_btn.setEnabled(False)
        self.main.set_busy("Testando API do painel")

        def done(msg):
            self.test_btn.setEnabled(True)
            self.main.set_busy("")
            self._set_panel_status(f"✓ {msg}")
            self.db.add_activity("integracao", f"Teste da API do painel: {msg}")
            success("API do painel: %s", msg)

        def failed(exc):
            self.test_btn.setEnabled(True)
            self.main.set_busy("")
            prefix = "⚠" if isinstance(exc, email_infra.ApiUnavailable) else "✖"
            self._set_panel_status(f"{prefix} {exc}")
            self.db.add_activity("integracao", f"Teste da API do painel: {exc}")
            (log.warning if prefix == "⚠" else log.error)("API do painel: %s", exc)

        run_async(lambda: email_infra.panel_test(*args), done, failed)

    def sync(self):
        try:
            addresses = email_infra.panel_list_addresses({"api_base": self.api_base.text().strip()})
        except email_infra.ApiUnavailable as e:
            if not confirm(self, "Sincronizar endereços",
                           f"Sincronização pela API indisponível.\n\n{e}\n\n"
                           "Importar endereços de um arquivo TXT ou CSV agora?"):
                return
            return self.import_addresses()
        new, old = self.db.add_addresses(addresses, "api")
        success("Sincronização: %d novo(s), %d já existente(s).", new, old)

    def import_addresses(self, path: Path | None = None, quiet: bool = False) -> tuple[int, int, int] | None:
        if path is None:
            chosen, _ = QFileDialog.getOpenFileName(self, "Importar endereços", str(Path.home()),
                                                    "TXT ou CSV (*.txt *.csv);;Todos os arquivos (*)")
            if not chosen:
                return None
            path = Path(chosen)
        try:
            valid, invalid = email_infra.parse_address_file(fichas.read_text(path))
        except (fichas.TxtError, OSError) as e:
            log.error("Importação de endereços falhou: %s", e)
            return warn(self, "Importar endereços", str(e))
        new, old = self.db.add_addresses(valid, f"arquivo: {path.name}")
        msg = f"{path.name}: {new} endereço(s) novo(s), {old} já existente(s), {len(invalid)} inválido(s)."
        self.db.add_activity("importacao", "Endereços — " + msg)
        for bad in invalid:
            self.db.add_activity("validacao", f"{path.name}: endereço inválido ignorado: {bad}")
        success("Endereços importados — %s", msg)
        self.main.profiles_changed.emit()
        if not quiet:
            info(self, "Importar endereços", msg + "\n\nOs endereços ficam disponíveis em ASSOCIAR E-MAIL.")
        return new, old, len(invalid)

    def disconnect(self):
        if confirm(self, "Desconectar", "Apagar a credencial salva da API do painel?"):
            self.db.delete_setting("panel_credential")
            self._set_panel_status("Desconectado: credencial removida.")
            self.db.add_activity("integracao", "API do painel desconectada (credencial removida).")
            log.info("API do painel desconectada.")

    # ------------------------------------------------------------ encaminhamento
    def save_forwarding(self):
        self.db.set_setting("email_dest_imap", self.dest.currentData() or "")
        self.db.set_setting("cf_zone", self.cf_zone.text().strip())
        if self.cf_token.text():
            self.db.set_secret("cf_token", self.cf_token.text())
            self.cf_token.clear()
        self.db.add_activity("integracao", "Configuração de encaminhamento salva.")
        success("Configuração de encaminhamento salva.")
        self._load_status()

    def test_cf(self):
        token = self.cf_token.text() or self.db.get_secret("cf_token")
        zone = self.cf_zone.text().strip()
        if not token or not zone:
            return warn(self, "Cloudflare", "Informe o Zone ID e o token (ou salve-os antes).")
        self.cf_btn.setEnabled(False)
        timeout = self.timeout.value()

        def finish(text: str, ok: bool):
            self.cf_btn.setEnabled(True)
            self.db.set_setting("cf_status", f"{'✓' if ok else '✖'} {text} ({datetime.now():%d/%m %H:%M})")
            self.db.add_activity("integracao", f"Cloudflare: {text}")
            (success if ok else log.error)("Cloudflare: %s", text)
            self._load_status()

        run_async(lambda: email_infra.cf_test(token, zone, timeout),
                  lambda msg: finish(msg, True), lambda exc: finish(str(exc), False))
