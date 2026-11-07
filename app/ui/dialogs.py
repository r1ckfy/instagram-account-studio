"""Diálogos da aba DADOS: prévia de importação, edição de ficha, associação e verificação de e-mail."""
import urllib.parse
from datetime import date, datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                               QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import email_infra, fichas, imap_client
from .. import generator as gen
from ..db import EMAIL_STATUSES, DuplicateError
from ..logs import log, success
from .common import (CYAN, GREEN, MUTED, RED, YELLOW, button, confirm, error, group, label, row,
                     run_async, set_color, warn)

RESULT_COLORS = {"valido": GREEN, "aviso": YELLOW, "duplicado": MUTED, "invalido": RED}
EMAIL_COLORS = {"nao_associado": MUTED, "associado": CYAN, "pendente": YELLOW,
                "encaminhamento": CYAN, "testado": GREEN, "erro": RED}
RECEIPT_TIMEOUT_MIN = 10


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


def email_settings(db) -> dict:
    """Configurações de e-mail usadas pelos diálogos e pela aba CONFIGURAÇÕES."""
    dest_id = db.get_setting("email_dest_imap")
    dest = next((a for a in db.list_imap() if str(a["id"]) == dest_id), None)
    return {"domain": db.get_setting("email_domain", "inboxnexo.online"),
            "panel_url": db.get_setting("panel_url", "https://painel.inboxnexo.online/"),
            "timeout": int(db.get_setting("email_timeout", "10")),
            "cf_zone": db.get_setting("cf_zone"), "cf_token": db.get_secret("cf_token"),
            "dest": dest, "dest_password": db.get_imap_password(dest["id"]) if dest else ""}


# ------------------------------------------------------------- importação
class ImportPreviewDialog(QDialog):
    def __init__(self, parent, items: list[dict], filename: str):
        super().__init__(parent)
        self.items = items
        self.setWindowTitle(f"Prévia da importação — {filename}")
        self.resize(1150, 640)
        counts = {k: sum(f["result"] == k for f in items) for k in fichas.RESULTS}
        summary = label(f"{len(items)} ficha(s) • {counts['valido']} válida(s) • {counts['aviso']} com aviso • "
                        f"{counts['duplicado']} duplicada(s) • {counts['invalido']} inválida(s)", "title")
        self.table = _table(["Importar", "Linha", "Resultado", "Nome", "Usuário", "Nascimento / idade",
                             "Local", "E-mail", "Detalhes"])
        self.table.setRowCount(len(items))
        for r, f in enumerate(items):
            check = QTableWidgetItem()
            importable = f["result"] in ("valido", "aviso")
            default = importable and not any("já associado" in w or "repetido no arquivo" in w
                                             for w in f["warnings"])
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled if importable else Qt.NoItemFlags)
            check.setCheckState(Qt.Checked if default else Qt.Unchecked)
            born = f"{date.fromisoformat(f['birthdate']):%d/%m/%Y}" if f["birthdate"] else ""
            age = f"{born} ({f['age']} anos)" if born else (f"{f['age']} anos" if f["age"] else "")
            details = " ".join(f["errors"] + ([f["duplicate"]] if f["duplicate"] else []) + f["warnings"])
            values = ["", str(f["line"]), fichas.RESULTS[f["result"]], f["full_name"], f"@{f['username']}",
                      age, ", ".join(x for x in (f["city"], f["state"]) if x), f["email"] or "—", details]
            self.table.setItem(r, 0, check)
            for c, v in enumerate(values[1:], start=1):
                item = QTableWidgetItem(v)
                if c == 2:
                    item.setForeground(QColor(RESULT_COLORS[f["result"]]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(8, 320)
        self.table.itemSelectionChanged.connect(self._show)
        self.table.itemChanged.connect(self._count)
        self.detail = QPlainTextEdit(readOnly=True)
        self.detail.setFixedHeight(130)
        self.import_btn = button("", "success", self._accept)
        lay = QVBoxLayout(self)
        lay.addWidget(summary)
        lay.addWidget(label("Duplicadas e inválidas não podem ser importadas. Fichas cujo e-mail já está "
                            "associado a outra personagem vêm desmarcadas.", "muted", wrap=True))
        lay.addWidget(self.table, 1)
        lay.addWidget(self.detail)
        lay.addLayout(row(button("Marcar importáveis", None, lambda: self._set_all(True)),
                          button("Desmarcar todas", None, lambda: self._set_all(False)), None,
                          button("Cancelar", None, self.reject), self.import_btn))
        self._count()

    def _set_all(self, on: bool):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _count(self, *_):
        n = len(self.selected())
        self.import_btn.setText(f"⤒ IMPORTAR SELECIONADAS ({n})")
        self.import_btn.setEnabled(n > 0)

    def _show(self):
        r = self.table.currentRow()
        if r < 0:
            return
        f = self.items[r]
        lines = [f"Linha {f['line']} — {f['full_name']} (@{f['username']})", "", "Bio:", f["bio"] or "(vazia)"]
        if f["notes"]:
            lines += ["", "Observações:", f["notes"]]
        for title, msgs in (("Erros", f["errors"]), ("Duplicidade", [f["duplicate"]] if f["duplicate"] else []),
                            ("Avisos", f["warnings"])):
            if msgs:
                lines += ["", f"{title}:"] + [f"• {m}" for m in msgs]
        self.detail.setPlainText("\n".join(lines))

    def selected(self) -> list[dict]:
        return [self.items[r] for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.Checked]

    def _accept(self):
        if self.selected():
            self.accept()


# ------------------------------------------------------------- edição
class FichaDialog(QDialog):
    def __init__(self, parent, db, profile: dict, *, credentials=False, fixed_birthdate=None):
        super().__init__(parent)
        self.db, self.p = db, profile
        self.fixed_birthdate = fixed_birthdate
        self.setWindowTitle(f"Editar ficha — @{profile['username']}")
        self.resize(560, 560)
        form = QFormLayout()
        self.full_name = QLineEdit(profile["full_name"])
        self.username = QLineEdit(profile["username"])
        born = fixed_birthdate.isoformat() if fixed_birthdate else profile["birthdate"]
        self.birth = QLineEdit(f"{date.fromisoformat(born):%d/%m/%Y}" if born else "",
                               placeholderText="DD/MM/AAAA (ou deixe vazio e informe a idade)")
        self.age = QLineEdit("" if born or profile["age"] is None else str(profile["age"]))
        if fixed_birthdate:
            self.birth.setReadOnly(True)
            self.age.setText(str(gen.age_on(fixed_birthdate, date.today())))
            self.age.setReadOnly(True)
        self.state = QLineEdit(profile["state"])
        self.city = QLineEdit(profile["city"])
        self.bio = QPlainTextEdit(profile["bio"])
        self.bio.setFixedHeight(110)
        self.notes = QPlainTextEdit(profile["notes"])
        self.notes.setFixedHeight(70)
        for text, w in (("Nome *", self.full_name), ("Usuário *", self.username), ("Nascimento", self.birth),
                        ("Idade", self.age), ("Estado", self.state), ("Cidade", self.city),
                        ("Bio", self.bio), ("Observações", self.notes)):
            form.addRow(text, w)
        self.email = self.password = None
        if credentials:
            self.email = QLineEdit(profile["email"])
            self.password = QLineEdit(echoMode=QLineEdit.Password, placeholderText="Em branco mantém a senha")
            form.addRow("E-mail de cadastro", self.email)
            form.addRow("Nova senha", self.password)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        if not credentials:
            lay.addWidget(label("E-mail é alterado em ASSOCIAR E-MAIL.", "muted"))
        lay.addWidget(bb)

    def _save(self):
        birth = self.fixed_birthdate.isoformat() if self.fixed_birthdate else self.birth.text().strip()
        f = fichas.validate({"full_name": self.full_name.text().strip(), "username": self.username.text(),
                             "birthdate": birth, "age": self.age.text().strip(),
                             "state": self.state.text().strip(), "city": self.city.text().strip(),
                             "bio": self.bio.toPlainText().strip("\n"), "notes": self.notes.toPlainText().strip(),
                             "email": self.email.text() if self.email is not None else ""})
        if f["errors"]:
            return warn(self, "Revise a ficha", "\n".join(f"• {e}" for e in f["errors"]))
        try:
            data = {"id": self.p["id"], **{k: f[k] for k in (
                "full_name", "username", "birthdate", "age", "state", "city", "bio", "notes")}}
            if self.email is not None:
                data["email"] = f["email"]
            password = (self.password.text() or None) if self.password is not None else None
            self.db.save_profile(data, password)
        except DuplicateError as e:
            return warn(self, "Usuário duplicado", str(e))
        self.db.add_activity("alteracao", f"Ficha @{f['username']} editada.")
        log.info("Ficha @%s editada.", f["username"])
        self.accept()


# ------------------------------------------------------------- associação
class AssociateEmailDialog(QDialog):
    def __init__(self, parent, db, profile: dict):
        super().__init__(parent)
        self.db, self.p = db, profile
        self.cfg = email_settings(db)
        self.setWindowTitle(f"Associar e-mail — @{profile['username']}")
        self.resize(820, 600)
        current = label(f"Atual: {profile['email'] or '—'}  •  {EMAIL_STATUSES[profile['email_status']]}")
        set_color(current, EMAIL_COLORS[profile["email_status"]], bold=True)

        box_list, lst = group("ENDEREÇOS NO BANCO LOCAL")
        self.search = QLineEdit(placeholderText="Filtrar endereços…")
        self.search.textChanged.connect(self._refresh)
        self.table = _table(["Endereço", "Associado a", "Status", "Origem"])
        self.table.itemSelectionChanged.connect(self._pick)
        lst.addWidget(self.search)
        lst.addWidget(self.table)

        self.address = QLineEdit(f"{profile['username']}@{self.cfg['domain']}" if not profile["email"]
                                 else profile["email"])
        box_new, new = group("ENDEREÇO A ASSOCIAR")
        new.addWidget(self.address)
        new.addWidget(label("Use um endereço que já existe e recebe mensagens (ex.: alias no seu painel ou "
                            "catch-all da Cloudflare). Associar não cria o endereço.", "muted", wrap=True))
        api = label("Criação de alias pela API do painel: " +
                    ("disponível" if email_infra.PANEL_CAN_CREATE else
                     "indisponível — a API do painel não foi documentada. Crie o alias no painel e cole aqui."),
                    wrap=True)
        set_color(api, GREEN if email_infra.PANEL_CAN_CREATE else YELLOW)
        new.addWidget(api)
        new.addLayout(row(button("🌐 Abrir painel de e-mails", None, self._open_panel), None))

        lay = QVBoxLayout(self)
        lay.addWidget(current)
        lay.addWidget(box_list, 1)
        lay.addWidget(box_new)
        lay.addLayout(row(button("Remover associação", "danger", self._clear), None,
                          button("Cancelar", None, self.reject),
                          button("✔ ASSOCIAR", "success", self._associate)))
        self._refresh()

    def _refresh(self):
        self.rows = self.db.list_addresses(self.search.text())
        self.table.setRowCount(len(self.rows))
        for r, a in enumerate(self.rows):
            st = a["status"] or ("associado" if a["owners"] else "nao_associado")
            for c, v in enumerate((a["address"], a["owners"] or "—", EMAIL_STATUSES[st], a["source"])):
                item = QTableWidgetItem(v)
                if c == 2:
                    item.setForeground(QColor(EMAIL_COLORS[st]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def _pick(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.rows):
            self.address.setText(self.rows[r]["address"])

    def _open_panel(self):
        QDesktopServices.openUrl(QUrl(self.cfg["panel_url"]))

    def _associate(self):
        addr = self.address.text().strip().lower()
        if err := gen.validate_email(addr):
            return warn(self, "E-mail", err)
        if addr == (self.p["email"] or "").lower():
            return self.reject()
        owners = self.db.address_owners(addr, self.p["id"])
        if owners and not confirm(self, "Endereço já associado",
                                  f"{addr} já está associado a {', '.join('@' + o for o in owners)}.\n"
                                  "Associar também a esta personagem?"):
            return
        self.db.associate_email(self.p["id"], addr)
        log.info("E-mail %s associado a @%s.", addr, self.p["username"])
        self.accept()

    def _clear(self):
        if self.p["email"] and confirm(self, "Remover associação",
                                       f"Desassociar {self.p['email']} de @{self.p['username']}?"):
            self.db.associate_email(self.p["id"], "")
            log.info("E-mail desassociado de @%s.", self.p["username"])
            self.accept()


# ------------------------------------------------------------- verificação
class VerifyEmailDialog(QDialog):
    def __init__(self, parent, main, address: str):
        super().__init__(parent)
        self.main, self.db, self.addr = main, main.db, address.strip().lower()
        self.setWindowTitle(f"Verificar e-mail — {self.addr}")
        self.resize(820, 640)
        self.status = label("")
        self.dest = label("", "muted", wrap=True)

        box_cfg, cfg = group("CONFIGURAÇÃO (SINTAXE • DNS • ENCAMINHAMENTO • IMAP)")
        self.check_btn = button("🩺 VERIFICAR CONFIGURAÇÃO", "primary", self.verify)
        cfg.addLayout(row(self.check_btn,
                          button("Marcar regra como configurada (manual)", None, self.mark_manual), None))
        self.report = QPlainTextEdit(readOnly=True)
        cfg.addWidget(self.report)

        box_rx, rx = group("TESTE DE RECEBIMENTO")
        self.rx_info = label("", wrap=True)
        self.rx_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.start_btn = button("▶ INICIAR TESTE", "primary", self.start_test)
        self.mail_btn = button("✉ Abrir no meu cliente de e-mail", None, self.open_mailto)
        self.find_btn = button("⟳ VERIFICAR CAIXA", "success", self.check_inbox)
        rx.addWidget(self.rx_info)
        rx.addLayout(row(self.start_btn, self.mail_btn, self.find_btn, None))

        lay = QVBoxLayout(self)
        lay.addLayout(row(label("Status:"), self.status, None))
        lay.addWidget(self.dest)
        lay.addWidget(box_cfg, 1)
        lay.addWidget(box_rx)
        lay.addLayout(row(None, button("Fechar", None, self.accept)))
        self._load()

    def _load(self):
        a = self.db.get_address(self.addr) or {}
        owners = self.db.address_owners(self.addr)
        st = a.get("status") or ("associado" if owners else "nao_associado")
        self.status.setText(EMAIL_STATUSES[st])
        set_color(self.status, EMAIL_COLORS[st], bold=True)
        cfg = email_settings(self.db)
        dest = a.get("destination") or (cfg["dest"]["email"] if cfg["dest"] else "")
        self.dest.setText(f"Caixa de destino: {dest or 'não definida'}"
                          + (f"  •  Última verificação: {a['checked_at']} — {a['last_result']}"
                             if a.get("checked_at") else ""))
        self.token = a.get("test_token")
        self.token_started = a.get("test_started_at")
        if self.token:
            self.rx_info.setText(
                f"Teste em andamento desde {self.token_started}. De um endereço seu, envie um e-mail para "
                f"<b>{self.addr}</b> com o assunto <b>{self.token}</b> e clique em VERIFICAR CAIXA.")
        else:
            self.rx_info.setText("Gera um código; você envia, de um endereço seu, um e-mail com esse código "
                                 "no assunto para este endereço. O app procura a mensagem na caixa de destino "
                                 "(entrada e spam), sem alterá-la.")
        self.mail_btn.setEnabled(bool(self.token))
        self.find_btn.setEnabled(bool(self.token) and cfg["dest"] is not None)
        if cfg["dest"] is None:
            self.find_btn.setToolTip("Defina a caixa IMAP de destino em CONFIGURAÇÕES → ENCAMINHAMENTO.")

    def _busy(self, on: bool, text: str = ""):
        for b in (self.check_btn, self.start_btn, self.find_btn):
            b.setEnabled(not on)
        self.main.set_busy(text if on else "")

    def verify(self):
        cfg = email_settings(self.db)
        self.report.setPlainText("Verificando…")
        self._busy(True, "Verificando e-mail")
        current = (self.db.get_address(self.addr) or {}).get("status", "")

        def done(res):
            self._busy(False)
            status = res["status"]
            if status == "encaminhamento" and current == "testado":
                status = None  # não rebaixa um recebimento já comprovado
            lines = [f"{icon}  {text}" for icon, text in res["checks"]]
            self.report.setPlainText("\n".join(lines))
            summary = "; ".join(t for i, t in res["checks"] if i in (email_infra.FAIL, email_infra.OK))[:500]
            self.db.set_address_check(self.addr, status, summary, res["destination"])
            self.db.add_activity("integracao", f"Verificação de {self.addr}: " +
                                 (EMAIL_STATUSES[status] if status else "status mantido"))
            fails = sum(i == email_infra.FAIL for i, _ in res["checks"])
            (log.warning if fails else success)("Verificação de %s: %d falha(s).", self.addr, fails)
            self._load()

        def failed(exc):
            self._busy(False)
            self.report.setPlainText(f"A verificação não pôde ser concluída: {exc}")
            log.error("Verificação de %s falhou: %s", self.addr, exc)

        run_async(lambda: email_infra.verify_address(
            self.addr, cfg["cf_token"], cfg["cf_zone"], cfg["dest"], cfg["dest_password"], cfg["timeout"]),
            done, failed)

    def mark_manual(self):
        if confirm(self, "Regra de encaminhamento",
                   f"Confirma que existe uma regra ativa na Cloudflare encaminhando {self.addr}?\n"
                   "Isso não comprova o recebimento — use o teste de recebimento."):
            self.db.set_address_check(self.addr, "encaminhamento", "Regra marcada manualmente pelo usuário.")
            self.db.add_activity("integracao", f"{self.addr}: encaminhamento marcado manualmente.")
            log.info("Encaminhamento de %s marcado manualmente.", self.addr)
            self._load()

    def start_test(self):
        if self.token and not confirm(self, "Novo teste", "Já existe um teste em andamento. Gerar um novo código?"):
            return
        self.db.start_receipt_test(self.addr)
        self.db.add_activity("integracao", f"Teste de recebimento iniciado para {self.addr}.")
        log.info("Teste de recebimento iniciado para %s.", self.addr)
        self._load()

    def open_mailto(self):
        q = urllib.parse.urlencode({"subject": self.token,
                                    "body": "Teste de recebimento do Instagram Account Studio."},
                                   quote_via=urllib.parse.quote)
        QDesktopServices.openUrl(QUrl(f"mailto:{self.addr}?{q}"))

    def check_inbox(self):
        cfg = email_settings(self.db)
        if not cfg["dest"] or not self.token:
            return
        token, dest = self.token, cfg["dest"]
        self._busy(True, "Procurando mensagem de teste")

        def done(found):
            self._busy(False)
            if found:
                result = f"Mensagem {token} recebida em {dest['email']} / {found['folder']} ({found['date']})."
                self.db.set_address_check(self.addr, "testado", result, dest["email"])
                self.db.add_activity("integracao", f"{self.addr}: RECEBIMENTO TESTADO. {result}")
                success("Recebimento comprovado para %s.", self.addr)
            else:
                started = datetime.fromisoformat(self.token_started)
                minutes = (datetime.now() - started).total_seconds() / 60
                if minutes >= RECEIPT_TIMEOUT_MIN:
                    result = f"Mensagem {token} não chegou em {RECEIPT_TIMEOUT_MIN} minutos a {dest['email']}."
                    self.db.set_address_check(self.addr, "erro", result, dest["email"])
                    self.db.add_activity("integracao", f"{self.addr}: ERRO DE ENTREGA. {result}")
                    log.error("Recebimento não comprovado para %s.", self.addr)
                else:
                    warn(self, "Ainda não chegou",
                         f"A mensagem {token} ainda não está em {dest['email']} (entrada/spam). "
                         f"Envie-a se ainda não enviou e tente de novo em instantes "
                         f"(prazo: {RECEIPT_TIMEOUT_MIN} min desde o início do teste).")
            self._load()

        def failed(exc):
            self._busy(False)
            msg = imap_client.friendly_error(exc)
            log.error("Busca da mensagem de teste falhou: %s", msg)
            error(self, "IMAP", msg)
            self._load()

        run_async(lambda: imap_client.find_message(dest, cfg["dest_password"], token, self.addr), done, failed)

