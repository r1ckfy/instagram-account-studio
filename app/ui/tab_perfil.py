from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QComboBox, QDateEdit, QFormLayout, QHBoxLayout, QLineEdit,
                               QListWidget, QPlainTextEdit, QVBoxLayout, QWidget)

from .. import generator as gen
from ..db import STATUSES, DuplicateError
from ..logs import log, success
from ..security import password_strength, strong_password
from .common import (GREEN, MUTED, RED, YELLOW, button, confirm, error, group, label, row,
                     set_color, warn)

PROFILE_TYPES = ["Pessoal", "Criador de conteúdo", "Modelo virtual", "Comercial"]


class PerfilTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db
        self.pid: int | None = None

        box, form = group("DADOS DO PERFIL", QFormLayout())
        form.setVerticalSpacing(8)
        self.id_label = label("Novo perfil (ainda não salvo)", "muted")
        self.full_name = QLineEdit(maxLength=64)
        self.username = QLineEdit(maxLength=gen.USERNAME_MAX, placeholderText="sem @")
        self.username.textChanged.connect(self._validate_live)
        self.user_hint = label("", wrap=True)
        self.email = QLineEdit(placeholderText="e-mail existente que você controla")
        self.email.textChanged.connect(self._validate_live)
        self.email_hint = label("", wrap=True)
        self.password = QLineEdit(echoMode=QLineEdit.Password)
        self.password.textChanged.connect(self._validate_live)
        self.pw_hint = label("")
        self.eye = button("👁", "icon", self._toggle_pw, "Mostrar/ocultar senha")
        self.birth = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.birth.setMinimumDate(QDate(1900, 1, 1))
        self.bio = QPlainTextEdit()
        self.bio.setFixedHeight(90)
        self.bio.textChanged.connect(self._validate_live)
        self.bio_hint = label("", "muted")
        self.ptype = QComboBox(editable=True)
        self.ptype.addItems(PROFILE_TYPES)
        self.status = QComboBox()
        for k, v in STATUSES.items():
            self.status.addItem(v, k)
        self.notes = QPlainTextEdit(placeholderText="Observações internas (não são publicadas)")
        self.notes.setFixedHeight(70)

        form.addRow("Registro", self.id_label)
        form.addRow("Nome completo *", self.full_name)
        form.addRow("Nome de usuário *", self.username)
        form.addRow("", self.user_hint)
        form.addRow("E-mail", self.email)
        form.addRow("", self.email_hint)
        form.addRow("Senha", row(self.password, self.eye, button("Gerar forte", None, self._gen_pw)))
        form.addRow("", self.pw_hint)
        form.addRow("Data de nascimento *", self.birth)
        form.addRow("Bio", self.bio)
        form.addRow("", self.bio_hint)
        form.addRow("Tipo de perfil", self.ptype)
        form.addRow("Status", self.status)
        form.addRow("Observações", self.notes)
        form.addRow(label("A senha é cifrada com a proteção de dados do Windows (DPAPI) antes de ir ao banco.",
                          "muted", wrap=True))

        self.delete_btn = button("✖ EXCLUIR", "danger", self.delete)
        box_act, act = group("AÇÕES")
        act.addLayout(row(button("💾 SALVAR", "success", self.save), button("Limpar / novo", None, self.clear)))
        act.addLayout(row(button("Recuperar último", None, self.load_last),
                          button("Duplicar (sem dados sensíveis)", None, self.duplicate)))
        act.addLayout(row(None, self.delete_btn))

        box_hist, hist = group("HISTÓRICO DE STATUS")
        self.history = QListWidget(wordWrap=True)
        hist.addWidget(self.history)

        right = QVBoxLayout()
        right.addWidget(box_act)
        right.addWidget(box_hist, 1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        lay.setSpacing(12)
        lay.addWidget(box, 3)
        lay.addLayout(right, 2)
        self.clear()

    # ------------------------------------------------------------ formulário
    def _toggle_pw(self):
        hidden = self.password.echoMode() == QLineEdit.Password
        self.password.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)

    def _gen_pw(self):
        self.password.setText(strong_password(16))
        self.password.setEchoMode(QLineEdit.Normal)

    def _max_birth(self) -> QDate:
        t = date.today()
        return QDate(t.year - gen.MIN_AGE, t.month, min(t.day, 28) if t.month == 2 else t.day)

    def _validate_live(self):
        u = self.username.text().strip()
        err = gen.validate_username(u) if u else None
        if err:
            self.user_hint.setText(f"✖ {err}")
            set_color(self.user_hint, RED)
        elif u and self.db.username_exists(u, self.pid):
            self.user_hint.setText("✖ Já existe outro perfil com este usuário no banco local.")
            set_color(self.user_hint, RED)
        else:
            self.user_hint.setText("")
        self.user_hint.setVisible(bool(self.user_hint.text()))

        e = self.email.text().strip()
        if not e:
            self.email_hint.setText("⚠ E-mail não configurado. Você precisará de um e-mail existente para o cadastro.")
            set_color(self.email_hint, YELLOW)
        elif gen.validate_email(e):
            self.email_hint.setText("✖ E-mail em formato inválido.")
            set_color(self.email_hint, RED)
        else:
            self.email_hint.setText("✓ Formato válido (a caixa não é verificada aqui — use a aba IMAP).")
            set_color(self.email_hint, MUTED)

        pw = self.password.text()
        if pw:
            score, text = password_strength(pw)
            self.pw_hint.setText(f"Força: {text}")
            set_color(self.pw_hint, GREEN if score >= 4 else YELLOW if score >= 2 else RED)
        else:
            self.pw_hint.setText("Sem senha salva.")
            set_color(self.pw_hint, MUTED)
        n = len(self.bio.toPlainText())
        self.bio_hint.setText(f"{n}/{gen.BIO_MAX} caracteres")
        set_color(self.bio_hint, RED if n > gen.BIO_MAX else MUTED)

    def _data(self) -> dict:
        return {"id": self.pid, "full_name": self.full_name.text(),
                "username": self.username.text().strip().lstrip("@").lower(),
                "email": self.email.text().strip(), "birthdate": self.birth.date().toString("yyyy-MM-dd"),
                "bio": self.bio.toPlainText(), "profile_type": self.ptype.currentText(),
                "notes": self.notes.toPlainText(), "status": self.status.currentData()}

    def _errors(self, d: dict) -> list[str]:
        errs = []
        if not d["full_name"].strip():
            errs.append("Informe o nome completo.")
        if e := gen.validate_username(d["username"]):
            errs.append(e)
        if d["email"] and (e := gen.validate_email(d["email"])):
            errs.append(e)
        if e := gen.validate_birthdate(date.fromisoformat(d["birthdate"])):
            errs.append(e)
        if e := gen.validate_bio(d["bio"]):
            errs.append(e)
        return errs

    def _fill(self, p: dict, password: str = ""):
        self.full_name.setText(p.get("full_name", ""))
        self.username.setText(p.get("username", ""))
        self.email.setText(p.get("email", ""))
        self.password.setText(password)
        self.password.setEchoMode(QLineEdit.Password)
        if p.get("birthdate"):
            self.birth.setDate(QDate.fromString(p["birthdate"], "yyyy-MM-dd"))
        self.bio.setPlainText(p.get("bio", ""))
        self.ptype.setCurrentText(p.get("profile_type") or PROFILE_TYPES[0])
        self.status.setCurrentIndex(max(0, self.status.findData(p.get("status", "preparado"))))
        self.notes.setPlainText(p.get("notes", ""))
        self._validate_live()

    def _set_pid(self, pid: int | None):
        self.pid = pid
        self.id_label.setText(f"Perfil #{pid}" if pid else "Novo perfil (ainda não salvo)")
        set_color(self.id_label, GREEN if pid else MUTED)
        self.delete_btn.setEnabled(pid is not None)
        self.history.clear()
        if pid:
            for h in self.db.history(pid):
                old = STATUSES.get(h["old_status"], "—") if h["old_status"] else "—"
                note = f" — {h['note']}" if h["note"] else ""
                self.history.addItem(f"{h['changed_at']}   {old} → {STATUSES[h['new_status']]}{note}")

    # ------------------------------------------------------------ API para outras abas
    def clear(self):
        self._set_pid(None)
        self.birth.setMaximumDate(self._max_birth())
        self._fill({"birthdate": self._max_birth().addYears(-4).toString("yyyy-MM-dd")})

    def new_existing(self):
        """Para registrar manualmente uma conta que já existe no Instagram."""
        self.clear()
        self.status.setCurrentIndex(self.status.findData("ativa"))
        self.full_name.setFocus()

    def load_generated(self, g: dict):
        self.clear()
        style = gen.BIO_STYLES.get(g.get("bio_style", ""), ("",))[0]
        self._fill({**g, "status": "preparado",
                    "profile_type": "Modelo virtual" if g.get("bio_style") == "modelo_virtual" else
                    ("Pessoal" if style in ("", "Perfil pessoal") else "Criador de conteúdo"),
                    "notes": f"Gerado na aba DADOS • local: {g.get('location', '')}"},
                   g.get("password", ""))

    def load_profile(self, pid: int):
        p = self.db.get_profile(pid)
        self._set_pid(pid)
        self._fill(p, self.db.get_password(pid))
        log.info("Perfil @%s carregado para edição.", p["username"])

    def load_last(self):
        p = self.db.last_profile()
        if not p:
            return warn(self, "Nenhum perfil", "Ainda não há perfis salvos.")
        self.load_profile(p["id"])

    def duplicate(self):
        d = self._data()
        self._set_pid(None)
        self._fill({**d, "full_name": "", "username": "", "email": "", "status": "preparado",
                    "notes": f"Duplicado de @{d['username']}" if d["username"] else d["notes"]})
        self.full_name.setFocus()

    # ------------------------------------------------------------ persistência
    def save(self):
        d = self._data()
        errs = self._errors(d)
        if errs:
            return warn(self, "Revise o formulário", "\n".join(f"• {e}" for e in errs))
        if not d["email"] and not confirm(self, "E-mail não configurado",
                                          "Este perfil está sem e-mail. Salvar mesmo assim?"):
            return
        old_status = self.db.get_profile(self.pid)["status"] if self.pid else None
        if d["status"] == "ativa" and old_status != "ativa" and not confirm(
                self, "Confirmar conta ativa",
                "Marcar como ATIVA significa que a conta foi criada e você confirmou o acesso a ela.\n\nConfirmar?"):
            return
        try:
            pid = self.db.save_profile(d, self.password.text())
        except DuplicateError as e:
            return warn(self, "Usuário duplicado", str(e))
        except Exception as e:
            log.error("Falha ao salvar perfil @%s: %s", d["username"], e)
            return error(self, "Erro ao salvar", f"Não foi possível salvar o perfil.\n\n{e}")
        success("Perfil @%s %s.", d["username"], "atualizado" if self.pid else "salvo")
        self._set_pid(pid)
        self.main.profiles_changed.emit()

    def delete(self):
        if not self.pid:
            return
        user = self.username.text()
        if not confirm(self, "Excluir perfil", f"Excluir @{user} e todo o histórico dele? Isso não pode ser desfeito."):
            return
        self.db.delete_profile(self.pid)
        log.warning("Perfil @%s excluído.", user)
        self.clear()
        self.main.profiles_changed.emit()
