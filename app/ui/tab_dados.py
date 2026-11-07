"""Aba DADOS: fichas de influenciadoras virtuais importadas por TXT, e-mail associado e histórico."""
import shutil
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGridLayout, QLineEdit,
                               QListWidget, QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import DATA_DIR, RES_DIR, fichas
from ..db import ACTIVITY_KINDS, EMAIL_STATUSES, STATUSES, export_profiles
from ..logs import log, success
from .common import (STATUS_COLORS, button, confirm, error, group, info, label, row, scrollable,
                     set_color, warn)
from .dialogs import EMAIL_COLORS, AssociateEmailDialog, FichaDialog, ImportPreviewDialog, VerifyEmailDialog
from .gerador import GeradorDialog

COLUMNS = ["ID", "Nome", "Usuário", "Idade", "Localização", "E-mail associado", "Status do e-mail",
           "Status do perfil"]
EXAMPLE = RES_DIR / "exemplos" / "fichas_exemplo.txt"


class DadosTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db
        self.gerador_dialog = GeradorDialog(main)
        self.gerador = self.gerador_dialog.widget
        self.rows: list[dict] = []

        # ---------------- painel esquerdo: lista
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addLayout(row(button("⤒ IMPORTAR TXT", "primary", self.import_txt),
                         button("Modelo de TXT", None, self.save_example, "Salvar um arquivo de exemplo"),
                         button("✦ Gerar ficha aleatória", None, self.gerador_dialog.show), None,
                         button("⤓ EXPORTAR", None, self.export)))
        self.search = QLineEdit(placeholderText="Pesquisar por nome ou username…")
        self.search.textChanged.connect(self.refresh)
        self.f_status = QComboBox()
        self.f_status.addItem("Perfil: todos", None)
        for k, v in STATUSES.items():
            self.f_status.addItem(f"Perfil: {v}", k)
        self.f_status.currentIndexChanged.connect(self.refresh)
        self.f_email = QComboBox()
        self.f_email.addItem("E-mail: todos", None)
        for k, v in EMAIL_STATUSES.items():
            self.f_email.addItem(f"E-mail: {v.capitalize()}", k)
        self.f_email.currentIndexChanged.connect(self.refresh)
        tools = row(self.search, self.f_status, self.f_email)
        tools.setStretch(0, 1)
        lv.addLayout(tools)
        self.kpi = label("", "muted")
        lv.addWidget(self.kpi)
        self.signup_btn = button("\U0001f680 INICIAR CADASTRO AGORA", "success", self.start_signup)
        self.signup_btn.setMinimumHeight(48)
        lv.addWidget(self.signup_btn)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.table.doubleClicked.connect(self.edit)
        lv.addWidget(self.table, 1)

        # ---------------- painel direito: ficha
        box, grid = group("FICHA DA PERSONAGEM", QGridLayout())
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(6)
        self.v = {k: label("", wrap=True) for k in ("name", "user", "birth", "loc", "email", "email_st",
                                                    "status", "source", "notes")}
        for k in self.v.values():
            k.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.bio = QPlainTextEdit(readOnly=True)
        self.bio.setFixedHeight(74)
        self.bio.setMinimumHeight(74)
        rows = [("Nome", "name"), ("Username", "user"), ("Nascimento", "birth"), ("Localização", "loc"),
                ("Bio", None), ("E-mail associado", "email"), ("Status do e-mail", "email_st"),
                ("Status do perfil", "status"), ("Origem", "source"), ("Observações", "notes")]
        for r, (text, key) in enumerate(rows):
            grid.addWidget(label(text, "muted"), r, 0, Qt.AlignTop)
            grid.addWidget(self.bio if key is None else self.v[key], r, 1)
        self.actions = [
            button("🌐 SELECIONAR PERSONAGEM", None, self.select_for_signup, "Usar na aba NAVEGADOR"),
            button("✎ EDITAR FICHA", None, self.edit),
            button("✉ ASSOCIAR E-MAIL", "primary", self.associate),
            button("🩺 VERIFICAR E-MAIL", None, self.verify),
            button("✔ APLICAR AO PERFIL", "success", self.apply),
            button("✖ REMOVER", "danger", self.remove),
        ]
        n = len(rows)
        grid.addLayout(row(self.actions[0], self.actions[1]), n, 0, 1, 2)
        grid.addLayout(row(self.actions[2], self.actions[3]), n + 1, 0, 1, 2)
        grid.addLayout(row(self.actions[4], self.actions[5]), n + 2, 0, 1, 2)
        grid.setRowStretch(n + 3, 1)

        # ---------------- painel inferior: histórico
        bottom, bl = group("HISTÓRICO • VALIDAÇÃO • INTEGRAÇÕES • ALTERAÇÕES")
        self.f_kind = QComboBox()
        self.f_kind.addItem("Todos os eventos", None)
        for k, v in ACTIVITY_KINDS.items():
            self.f_kind.addItem(v, k)
        self.f_kind.currentIndexChanged.connect(self.refresh_activity)
        bl.addLayout(row(self.f_kind, None))
        self.activity = QListWidget(wordWrap=True)
        self.activity.setMinimumHeight(50)
        bl.addWidget(self.activity)

        top = QSplitter(Qt.Horizontal)
        top.addWidget(left)
        top.addWidget(scrollable(box))
        top.setStretchFactor(0, 3)
        top.setStretchFactor(1, 2)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(bottom)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([520, 120])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        lay.addWidget(split)
        main.profiles_changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------ lista
    def start_signup(self):
        pid = self.current_id()
        if pid is not None:
            self.main.central.select(pid)
            self.main.goto(self.main.central)
            self.main.central.start()

    def current_id(self) -> int | None:
        r = self.table.currentRow()
        item = self.table.item(r, 0) if r >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def refresh(self):
        keep = self.current_id()
        self.rows = self.db.list_profiles(self.search.text(), self.f_status.currentData(),
                                          self.f_email.currentData())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.rows))
        for r, p in enumerate(self.rows):
            values = [p["id"], p["full_name"], f"@{p['username']}", p["age"] if p["age"] is not None else "",
                      ", ".join(x for x in (p["city"], p["state"]) if x), p["email"] or "—",
                      EMAIL_STATUSES[p["email_status"]], STATUSES[p["status"]]]
            for c, v in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, v)
                if c == 0:
                    item.setData(Qt.UserRole, p["id"])
                elif c == 6:
                    item.setForeground(QColor(EMAIL_COLORS[p["email_status"]]))
                elif c == 7:
                    item.setForeground(QColor(STATUS_COLORS[p["status"]]))
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == keep:
                self.table.selectRow(r)
                break
        all_rows = self.db.list_profiles()
        last = self.db.list_activity("importacao", 1)
        self.kpi.setText(
            f"{len(all_rows)} ficha(s) • {sum(p['email_status'] == 'nao_associado' for p in all_rows)} sem e-mail • "
            f"{sum(p['email_status'] == 'encaminhamento' for p in all_rows)} com encaminhamento • "
            f"{sum(p['email_status'] == 'testado' for p in all_rows)} recebimento testado • "
            f"última importação: {last[0]['created_at'][:16] if last else '—'}")
        self.show_selected()
        self.refresh_activity()

    def refresh_activity(self):
        self.activity.clear()
        for a in self.db.list_activity(self.f_kind.currentData(), 200):
            self.activity.addItem(f"[{a['created_at'][5:16]}] {ACTIVITY_KINDS[a['kind']].upper()}: {a['message']}")

    def show_selected(self):
        pid = self.current_id()
        for b in self.actions:
            b.setEnabled(pid is not None)
        if pid is None:
            for w in self.v.values():
                w.setText("")
            self.bio.setPlainText("")
            self.v["name"].setText("Selecione uma personagem na lista ou importe um TXT.")
            return
        p = self.db.get_profile(pid)
        born = (f"{date.fromisoformat(p['birthdate']):%d/%m/%Y} ({p['age']} anos)" if p["birthdate"]
                else f"— (idade informada: {p['age']})" if p["age"] is not None else "—")
        self.v["name"].setText(p["full_name"])
        self.v["user"].setText(f"@{p['username']}")
        self.v["birth"].setText(born)
        self.v["loc"].setText(", ".join(x for x in (p["city"], p["state"]) if x) or "—")
        self.bio.setPlainText(p["bio"])
        addr = self.db.get_address(p["email"]) if p["email"] else None
        dest = f"  →  destino: {addr['destination']}" if addr and addr["destination"] else ""
        self.v["email"].setText((p["email"] or "—") + dest)
        self.v["email_st"].setText(EMAIL_STATUSES[p["email_status"]]
                                   + (f"  ({addr['last_result'][:120]})" if addr and addr["last_result"] else ""))
        set_color(self.v["email_st"], EMAIL_COLORS[p["email_status"]], bold=True)
        self.v["status"].setText(STATUSES[p["status"]])
        set_color(self.v["status"], STATUS_COLORS[p["status"]], bold=True)
        self.v["source"].setText(p["source"] or "manual")
        notes = " ".join(p["notes"].split())
        self.v["notes"].setText((notes[:90] + "…" if len(notes) > 90 else notes) or "—")
        self.v["notes"].setToolTip(p["notes"])

    # ------------------------------------------------------------ importação
    def import_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar fichas (TXT)", str(Path.home()),
                                              "Texto (*.txt);;Todos os arquivos (*)")
        if path:
            self.import_path(Path(path))

    def import_path(self, path: Path, preview=True) -> dict | None:
        """Lê, valida, mostra a prévia e grava. `preview=False` importa tudo que é importável (testes)."""
        try:
            items = fichas.classify(fichas.parse_file(path), self.db)
        except (fichas.TxtError, OSError) as e:
            log.error("Importação de %s falhou: %s", path.name, e)
            self.db.add_activity("validacao", f"{path.name}: {e}")
            self.refresh_activity()
            return error(self, "Importar TXT", str(e))
        if preview:
            dlg = ImportPreviewDialog(self, items, path.name)
            if not dlg.exec():
                log.info("Importação de %s cancelada.", path.name)
                return None
            chosen = dlg.selected()
        else:
            chosen = [f for f in items if f["result"] in ("valido", "aviso")]
        ids, skipped = self.db.import_fichas(chosen, f"TXT: {path.name}")
        invalid = [f for f in items if f["result"] == "invalido"]
        report = {"importadas": len(ids), "ignoradas": len(items) - len(ids) - len(invalid),
                  "invalidas": len(invalid)}
        for f in invalid:
            self.db.add_activity("validacao", f"{path.name} linha {f['line']}: " + " ".join(f["errors"]))
        for f in items:
            if f["result"] == "duplicado":
                self.db.add_activity("validacao", f"{path.name} linha {f['line']}: {f['duplicate']}")
        for msg in skipped:
            self.db.add_activity("validacao", f"{path.name}: {msg}")
        self.db.add_activity("importacao", f"{path.name}: {report['importadas']} importada(s), "
                                           f"{report['ignoradas']} ignorada(s), {report['invalidas']} inválida(s).")
        (success if ids else log.warning)("Importação de %s: %d importada(s), %d ignorada(s), %d inválida(s).",
                                          path.name, *report.values())
        self.main.profiles_changed.emit()
        if preview:
            info(self, "Relatório da importação",
                 f"Arquivo: {path.name}\n\n✅ Importadas: {report['importadas']}\n"
                 f"⏭ Ignoradas (não selecionadas ou duplicadas): {report['ignoradas']}\n"
                 f"❌ Inválidas: {report['invalidas']}\n\nDetalhes no histórico abaixo da lista.")
        return report

    def save_example(self):
        dest, _ = QFileDialog.getSaveFileName(self, "Salvar modelo de TXT", str(Path.home() / "fichas_exemplo.txt"),
                                              "Texto (*.txt)")
        if dest:
            shutil.copyfile(EXAMPLE, dest)
            success("Modelo de TXT salvo em %s.", dest)

    def export(self):
        if not self.rows:
            return warn(self, "Exportar", "Nenhuma ficha listada para exportar.")
        default = DATA_DIR / f"fichas_{datetime.now():%Y%m%d_%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar fichas", str(default),
                                              "CSV (*.csv);;JSON (*.json);;Texto (*.txt)")
        if not path:
            return
        try:
            n = export_profiles(self.rows, Path(path))
        except (OSError, ValueError) as e:
            return error(self, "Exportar", str(e))
        success("%d ficha(s) exportada(s) para %s (sem senhas).", n, Path(path).name)
        info(self, "Exportar", f"{n} ficha(s) exportada(s) para:\n{path}\n\nSenhas não são exportadas.")

    # ------------------------------------------------------------ ações da ficha
    def _profile(self) -> dict | None:
        pid = self.current_id()
        return self.db.get_profile(pid) if pid is not None else None

    def select_for_signup(self):
        if p := self._profile():
            self.main.navegador.select(p["id"])
            self.main.goto(self.main.navegador)

    def edit(self, *_):
        p = self._profile()
        if p and FichaDialog(self, self.db, p).exec():
            self.main.profiles_changed.emit()

    def associate(self):
        p = self._profile()
        if p and AssociateEmailDialog(self, self.db, p).exec():
            self.main.profiles_changed.emit()

    def verify(self):
        p = self._profile()
        if not p:
            return
        if not p["email"]:
            return warn(self, "Verificar e-mail", "Esta personagem não tem e-mail associado. Use ASSOCIAR E-MAIL.")
        VerifyEmailDialog(self, self.main, p["email"]).exec()
        self.main.profiles_changed.emit()

    def apply(self):
        p = self._profile()
        if not p:
            return
        self.main.perfil.load_profile(p["id"])
        if not p["birthdate"]:
            t = QDate.currentDate()
            self.main.perfil.birth.setDate(t.addYears(-(p["age"] or 18)))
            warn(self, "Data de nascimento",
                 f"A ficha informa só a idade ({p['age']}). Confirme a data de nascimento no PERFIL antes de salvar.")
        self.main.goto(self.main.perfil)

    def remove(self):
        p = self._profile()
        if p and confirm(self, "Remover ficha", f"Remover @{p['username']} e o histórico dela do banco local?"):
            self.db.delete_profile(p["id"])
            self.db.add_activity("alteracao", f"Ficha @{p['username']} removida.")
            log.warning("Ficha @%s removida.", p["username"])
            self.main.profiles_changed.emit()

