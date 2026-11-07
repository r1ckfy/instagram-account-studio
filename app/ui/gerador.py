"""Gerador aleatório de fichas (fluxo antigo da aba DADOS, agora em um diálogo)."""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import generator as gen
from ..logs import log
from ..security import password_strength, strong_password
from .common import (GREEN, MUTED, RED, YELLOW, CopyField, button, confirm, copy_text,
                     group, label, row, set_color, warn)


class GeradorWidget(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db
        self.current: dict | None = None

        # ---------------- parâmetros
        box_in, form = group("PARÂMETROS", QFormLayout())
        form.setVerticalSpacing(8)
        self.first = QLineEdit(placeholderText="aleatório")
        self.last = QLineEdit(placeholderText="aleatório")
        self.gender = QComboBox()
        for k, v in gen.GENDERS.items():
            self.gender.addItem(v, k)
        self.birthdate = QLineEdit(gen.MODEL_BIRTHDATE.strftime("%d/%m/%Y"), readOnly=True)
        self.uf = QComboBox()
        for uf, (name, *_rest) in sorted(gen.STATES.items(), key=lambda kv: kv[1][0]):
            self.uf.addItem(f"{name} ({uf})", uf)
        self.uf.setCurrentIndex(self.uf.findData("AL"))
        self.city = QLineEdit(placeholderText="capital do estado")
        self.extra = QSpinBox(minimum=0, maximum=4)
        self.digits = QSpinBox(minimum=0, maximum=4)
        self.sep = QComboBox()
        for k, v in (("nenhum", "Nenhum"), ("ponto", "Ponto ( . )"), ("underline", "Underline ( _ )")):
            self.sep.addItem(v, k)
        self.domain = QLineEdit(self.db.get_setting("email_domain") or "gmail.com")
        self.bio_style = QComboBox()
        for k, (name, _t) in gen.BIO_STYLES.items():
            self.bio_style.addItem(name, k)
        self.pw_len = QSpinBox(minimum=12, maximum=64, value=16, suffix=" caracteres")
        for text, w in (("Nome", self.first), ("Sobrenome", self.last), ("Apresentação", self.gender),
                        ("Nascimento", self.birthdate), ("Estado", self.uf), ("Cidade", self.city),
                        ("Letras extras no usuário", self.extra), ("Números no usuário", self.digits),
                        ("Separador", self.sep), ("Domínio do e-mail", self.domain),
                        ("Estilo da bio", self.bio_style), ("Tamanho da senha", self.pw_len)):
            form.addRow(text, w)
        form.addRow(label("Personagens sempre adultos (18+).", "muted"))
        form.addRow(button("⚡ GERAR DADOS", "primary", self.generate_all))

        # ---------------- resultado
        box_out, grid = group("RESULTADO", QGridLayout())
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        self.f_name, self.f_birth = CopyField(), CopyField()
        self.f_user, self.f_email = CopyField(), CopyField()
        self.f_pass, self.f_loc = CopyField(secret=True), CopyField()
        self.f_user.edit.setReadOnly(False)
        self.f_user.edit.textEdited.connect(self._user_edited)
        self.user_status = label("", wrap=True)
        self.pw_status = label("")
        self.bio = QPlainTextEdit()
        self.bio.setFixedHeight(92)
        self.bio.textChanged.connect(self._bio_count)
        self.bio_count = label("0/150", "muted")
        regen = lambda field: button("↻", "icon", lambda: self.regen(field), "Gerar novamente")  # noqa: E731
        lines = [("Nome completo", self.f_name, "name"), ("Nascimento", self.f_birth, None),
                 ("Usuário", self.f_user, "user"), ("", self.user_status, None),
                 ("E-mail sugerido", self.f_email, "email"),
                 ("", label("Sugestão de endereço — não verificamos se existe. Use um e-mail que você controla.",
                            "muted", wrap=True), None),
                 ("Senha", self.f_pass, "pass"), ("", self.pw_status, None),
                 ("Localização", self.f_loc, None)]
        r = 0
        for text, w, field in lines:
            grid.addWidget(label(text), r, 0)
            grid.addWidget(w, r, 1)
            if field:
                grid.addWidget(regen(field), r, 2)
            r += 1
        grid.addWidget(label("Bio"), r, 0)
        grid.addWidget(self.bio, r, 1)
        bio_side = QVBoxLayout()
        bio_side.addWidget(regen("bio"))
        bio_side.addWidget(button("⧉", "icon", lambda: copy_text(self.bio.toPlainText()), "Copiar bio"))
        bio_side.addStretch(1)
        grid.addLayout(bio_side, r, 2)
        grid.addWidget(self.bio_count, r + 1, 1)
        self.apply_btn = button("✔ APLICAR AO PERFIL", "success", self.apply)
        self.copy_all_btn = button("⧉ Copiar tudo (sem senha)", None, self.copy_all)
        grid.addLayout(row(self.copy_all_btn, None, self.apply_btn), r + 2, 0, 1, 3)

        # ---------------- histórico
        box_hist, hist = group("HISTÓRICO DE SUGESTÕES")
        self.history = QListWidget()
        self.history.itemDoubleClicked.connect(self._load_history)
        hist.addWidget(label("Duplo clique para reutilizar (a senha não é guardada no histórico).", "muted", True))
        hist.addWidget(self.history, 1)
        hist.addLayout(row(None, button("Limpar histórico", "danger", self.clear_history)))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        lay.setSpacing(12)
        lay.addWidget(box_in, 3)
        right = QVBoxLayout()
        right.addWidget(box_out)
        right.addWidget(box_hist, 1)
        lay.addLayout(right, 5)
        self._set_enabled(False)
        self.refresh_history()

    # ------------------------------------------------------------ geração
    def _opts(self) -> dict:
        return {"first": self.first.text(), "last": self.last.text(),
                "gender": self.gender.currentData(),
                "uf": self.uf.currentData(), "city": self.city.text(),
                "extra_letters": self.extra.value(), "digits": self.digits.value(),
                "sep": self.sep.currentData(), "domain": self.domain.text(),
                "bio_style": self.bio_style.currentData(), "password_len": self.pw_len.value()}

    def _check_domain(self) -> bool:
        if gen._DOMAIN_RE.match(self.domain.text().strip().lstrip("@")):
            return True
        warn(self, "Domínio inválido", "Informe um domínio de e-mail válido, por exemplo gmail.com.")
        return False

    def generate_all(self):
        if not self._check_domain():
            return
        try:
            password = self.db.get_secret(gen.DEFAULT_PASSWORD_SETTING)
        except OSError:
            return warn(self, "Senha padrão", "Configure novamente a senha padrão nesta conta do Windows.")
        g = gen.generate(self._opts(), birthdate=gen.MODEL_BIRTHDATE, password=password)
        for _ in range(5):  # evita repetir um usuário que já existe no banco local
            if not self.db.username_exists(g["username"]):
                break
            g["username"] = gen.gen_username(g["first"], g["last"], self.extra.value(),
                                             max(self.digits.value(), 2), self.sep.currentData())
            g["email"] = gen.gen_email(g["username"], self.domain.text())
        self.current = g
        self._show()
        self.db.add_generated(g)
        self.refresh_history()
        log.info("Dados gerados para @%s.", g["username"])

    def regen(self, field: str):
        if not self.current:
            return self.generate_all()
        g, o = self.current, self._opts()
        g["username"] = self.f_user.text().strip() or g["username"]
        g["bio"] = self.bio.toPlainText()
        if field == "name":
            g["first"], g["last"] = gen.gen_name(g["gender"], o["first"], o["last"])
            g["full_name"] = f"{g['first']} {g['last']}"
        elif field == "user":
            g["username"] = gen.gen_username(g["first"], g["last"], o["extra_letters"], o["digits"], o["sep"])
            g["email"] = gen.gen_email(g["username"], o["domain"])
        elif field == "email":
            if not self._check_domain():
                return
            g["email"] = gen.gen_email(g["username"], o["domain"])
        elif field == "pass":
            g["password"] = strong_password(o["password_len"])
        elif field == "bio":
            g["bio"] = gen.gen_bio(o["bio_style"], g["first"], g["age"], g["uf"], g["city"], g["gender"])
            g["bio_style"] = o["bio_style"]
        self._show()

    def _show(self):
        g = self.current
        born = date.fromisoformat(g["birthdate"])
        self.f_name.setText(g["full_name"])
        self.f_birth.setText(f"{born:%d/%m/%Y}  ({gen.age_on(born, date.today())} anos)")
        self.f_user.setText(g["username"])
        self.f_email.setText(g["email"])
        self.f_pass.setText(g["password"])
        self.f_loc.setText(g["location"])
        self.bio.setPlainText(g["bio"])
        score, text = password_strength(g["password"])
        self.pw_status.setText(f"Força: {text}")
        set_color(self.pw_status, GREEN if score >= 4 else YELLOW)
        self._check_user()
        self._set_enabled(True)

    def _user_edited(self, text):
        if self.current:
            self.current["username"] = text.strip().lower()
        self._check_user()

    def _check_user(self):
        u = self.f_user.text().strip()
        err = gen.validate_username(u)
        if err:
            self.user_status.setText(f"✖ {err}")
            set_color(self.user_status, RED)
        elif self.db.username_exists(u):
            self.user_status.setText("⚠ Já existe um perfil com este usuário no banco local.")
            set_color(self.user_status, YELLOW)
        else:
            self.user_status.setText("✓ Formato válido e livre no banco local. "
                                     "A disponibilidade no Instagram não é verificada.")
            set_color(self.user_status, MUTED)

    def _bio_count(self):
        n = len(self.bio.toPlainText())
        self.bio_count.setText(f"{n}/{gen.BIO_MAX}")
        set_color(self.bio_count, RED if n > gen.BIO_MAX else MUTED)

    def _set_enabled(self, on: bool):
        self.apply_btn.setEnabled(on)
        self.copy_all_btn.setEnabled(on)

    # ------------------------------------------------------------ ações
    def _collect(self) -> dict:
        g = dict(self.current)
        g["username"] = self.f_user.text().strip()
        g["bio"] = self.bio.toPlainText().strip()
        return g

    def apply(self):
        if not self.current:
            return
        g = self._collect()
        err = gen.validate_username(g["username"]) or gen.validate_bio(g["bio"])
        if err:
            return warn(self, "Revise os dados", err)
        self.main.perfil.load_generated(g)
        self.main.goto(self.main.perfil)
        log.info("Dados de @%s aplicados ao formulário de perfil.", g["username"])
        if isinstance(self.window(), QDialog):
            self.window().accept()

    def copy_all(self):
        g = self._collect()
        copy_text(f"Nome: {g['full_name']}\nUsuário: @{g['username']}\nE-mail sugerido: {g['email']}\n"
                  f"Nascimento: {date.fromisoformat(g['birthdate']):%d/%m/%Y}\n"
                  f"Localização: {g['location']}\nBio:\n{g['bio']}")

    # ------------------------------------------------------------ histórico
    def refresh_history(self):
        self.history.clear()
        for h in self.db.list_generated():
            item = QListWidgetItem(f"{h['full_name']}  •  @{h['username']}  •  {h['created_at'][:16]}")
            item.setData(Qt.UserRole, h)
            self.history.addItem(item)

    def _load_history(self, item):
        h = item.data(Qt.UserRole)
        try:
            password = self.db.get_secret(gen.DEFAULT_PASSWORD_SETTING)
        except OSError:
            return warn(self, "Senha padrão", "Configure novamente a senha padrão nesta conta do Windows.")
        first, _, last = h["full_name"].partition(" ")
        born = gen.MODEL_BIRTHDATE
        uf = self.uf.currentData()
        self.current = {**h, "first": first, "last": last, "gender": self.gender.currentData(),
                        "birthdate": born.isoformat(), "age": gen.age_on(born, date.today()), "uf": uf,
                        "city": self.city.text().strip() or gen.STATES[uf][1],
                        "location": f"{self.city.text().strip() or gen.STATES[uf][1]}, {uf}",
                        "bio_style": self.bio_style.currentData(),
                        "password": password or strong_password(self.pw_len.value())}
        saved_age = gen.age_on(date.fromisoformat(h["birthdate"]), date.fromisoformat(h["created_at"][:10]))
        if h["birthdate"] != born.isoformat() or saved_age != self.current["age"]:
            g = self.current
            g["bio"] = gen.gen_bio(g["bio_style"], first, g["age"], uf, g["city"], g["gender"])
        self._show()

    def clear_history(self):
        if confirm(self, "Limpar histórico", "Apagar todas as sugestões do histórico?"):
            self.db.clear_generated()
            self.refresh_history()
            log.info("Histórico de sugestões limpo.")



class GeradorDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.setWindowTitle("Gerar ficha aleatória")
        self.widget = GeradorWidget(main)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.widget)
        self.resize(1200, 720)
