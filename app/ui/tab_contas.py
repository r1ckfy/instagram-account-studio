from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
                               QLineEdit, QListWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import DATA_DIR
from ..db import STATUSES, export_profiles
from ..logs import log, success
from .common import (CYAN, GREEN, MUTED, RED, STATUS_COLORS, YELLOW, button, confirm, error,
                     group, info, label, row, warn)

EXPORT_FILTERS = {"CSV (*.csv)": ".csv", "JSON (*.json)": ".json", "Texto (*.txt)": ".txt"}

COLUMNS = ["ID", "Nome", "Usuário", "E-mail", "Senha", "Criado em", "Status", "Atualizado", "Observações"]


class StatusDialog(QDialog):
    def __init__(self, parent, current: str):
        super().__init__(parent)
        self.setWindowTitle("Alterar status")
        form = QFormLayout(self)
        self.status = QComboBox()
        for k, v in STATUSES.items():
            self.status.addItem(v, k)
        self.status.setCurrentIndex(self.status.findData(current))
        self.note = QLineEdit(placeholderText="Motivo / observação")
        form.addRow("Novo status", self.status)
        form.addRow("Observação", self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


def _card(title: str, color: str) -> tuple[QFrame, object]:
    f = QFrame(objectName="card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 10, 14, 10)
    value = label("0")
    value.setStyleSheet(f"color: {color}; font-size: 20pt; font-weight: 700;")
    lay.addWidget(label(title.upper(), "muted"))
    lay.addWidget(value)
    return f, value


class ContasTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.k_total = _card("Perfis no painel", CYAN)
        self.k_ativas = _card("Ativas (confirmadas)", GREEN)
        self.k_pend = _card("Pendentes / preparados", YELLOW)
        self.k_fail = _card("Falhas / bloqueadas", RED)
        self.k_last = _card("Última conta confirmada", MUTED)
        self.k_last[1].setStyleSheet(f"color: {GREEN}; font-size: 10pt; font-weight: 600;")
        self.k_last[1].setWordWrap(True)
        for f, _v in (self.k_total, self.k_ativas, self.k_pend, self.k_fail):
            cards.addWidget(f, 1)
        cards.addWidget(self.k_last[0], 2)

        self.search = QLineEdit(placeholderText="Pesquisar por nome, usuário ou e-mail…")
        self.search.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.addItem("Todos os status", None)
        for k, v in STATUSES.items():
            self.status_filter.addItem(v, k)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        tools = row(self.search, self.status_filter,
                    button("＋ CONTA EXISTENTE", "primary", self.add_existing,
                           "Registrar manualmente uma conta que você já criou"),
                    button("✎ Editar", None, self.edit), button("⇄ Alterar status", None, self.change_status),
                    button("🌐 Abrir em NAVEGADOR", None, self.open_in_signup),
                    button("⤓ Exportar", None, self.export,
                           "Exporta os registros selecionados (ou todos os listados) em CSV, JSON ou TXT, sem senhas"),
                    button("✖ Excluir", "danger", self.delete))
        tools.setStretch(0, 1)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._show_history)
        self.table.doubleClicked.connect(self.edit)

        box_hist, hist = group("HISTÓRICO")
        self.history = QListWidget(wordWrap=True)
        hist.addWidget(self.history)
        box_hist.setMaximumWidth(380)

        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        body.addWidget(box_hist)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        lay.setSpacing(10)
        lay.addLayout(cards)
        lay.addLayout(tools)
        lay.addWidget(label("“Preparado” = dados prontos, conta ainda não criada. "
                            "Somente “Ativa (confirmada)” indica uma conta que você criou e confirmou.",
                            "muted", wrap=True))
        lay.addLayout(body, 1)
        main.profiles_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        rows = self.db.list_profiles(self.search.text(), self.status_filter.currentData())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            values = [p["id"], p["full_name"], f"@{p['username']}", p["email"] or "—",
                      "••••••••" if p["has_password"] else "—", p["created_at"][:16],
                      STATUSES[p["status"]], p["updated_at"][:16], p["notes"].replace("\n", " ")]
            for c, v in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, v)
                if c == 0:
                    item.setData(Qt.UserRole, p["id"])
                if c == 6:
                    item.setForeground(QColor(STATUS_COLORS[p["status"]]))
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(8, max(160, self.table.columnWidth(8)))

        s = self.db.stats()
        self.k_total[1].setText(str(s["total"]))
        self.k_ativas[1].setText(str(s["ativas"]))
        self.k_pend[1].setText(str(s["pendentes"]))
        self.k_fail[1].setText(str(s["falhas"]))
        self.k_last[1].setText(s["ultima_ativa"])
        self._show_history()

    def _selected(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self.table.item(r, 0).data(Qt.UserRole) for r in rows]

    def _one(self) -> int | None:
        ids = self._selected()
        if len(ids) != 1:
            warn(self, "Seleção", "Selecione exatamente um registro na tabela.")
            return None
        return ids[0]

    def _show_history(self):
        self.history.clear()
        ids = self._selected()
        if len(ids) != 1:
            self.history.addItem("Selecione um registro para ver o histórico.")
            return
        for h in self.db.history(ids[0]):
            old = STATUSES.get(h["old_status"], "—") if h["old_status"] else "—"
            self.history.addItem(f"{h['changed_at']}\n  {old} → {STATUSES[h['new_status']]}"
                                 + (f"\n  {h['note']}" if h["note"] else ""))

    def add_existing(self):
        self.main.perfil.new_existing()
        self.main.goto(self.main.perfil)

    def edit(self, *_):
        pid = self._one()
        if pid is not None:
            self.main.perfil.load_profile(pid)
            self.main.goto(self.main.perfil)

    def open_in_signup(self):
        pid = self._one()
        if pid is not None:
            self.main.navegador.select(pid)
            self.main.goto(self.main.navegador)

    def change_status(self):
        pid = self._one()
        if pid is None:
            return
        p = self.db.get_profile(pid)
        dlg = StatusDialog(self, p["status"])
        if not dlg.exec():
            return
        new = dlg.status.currentData()
        if new == p["status"]:
            return
        if new == "ativa" and not confirm(self, "Confirmar conta ativa",
                                          "Confirme que a conta existe e que você consegue acessá-la."):
            return
        self.db.set_status(pid, new, dlg.note.text().strip() or "Alterado na aba CONTAS")
        (success if new == "ativa" else log.info)("Status de @%s: %s → %s.", p["username"],
                                                   STATUSES[p["status"]], STATUSES[new])
        self.main.profiles_changed.emit()

    def export(self):
        ids = set(self._selected())
        rows = [r for r in self.db.list_profiles(self.search.text(), self.status_filter.currentData())
                if not ids or r["id"] in ids]
        if not rows:
            return warn(self, "Exportar", "Nenhum registro para exportar com o filtro atual.")
        default = DATA_DIR / f"contas_{datetime.now():%Y%m%d_%H%M}.csv"
        path, chosen = QFileDialog.getSaveFileName(self, "Exportar contas", str(default),
                                                   ";;".join(EXPORT_FILTERS))
        if not path:
            return
        path = Path(path)
        if path.suffix.lower() not in EXPORT_FILTERS.values():
            path = path.with_name(path.name + EXPORT_FILTERS.get(chosen, ".csv"))
        try:
            n = export_profiles(rows, path)
        except (OSError, ValueError) as e:
            log.error("Falha ao exportar contas: %s", e)
            return error(self, "Exportar", f"Não foi possível exportar:\n{e}")
        scope = "selecionado(s)" if ids else "listado(s)"
        success("%d registro(s) %s exportado(s) para %s (sem senhas).", n, scope, path.name)
        info(self, "Exportar", f"{n} registro(s) {scope} exportado(s) para:\n{path}\n\n"
                               "As senhas não entram na exportação: ficam só no banco cifrado e nos backups.")

    def delete(self):
        ids = self._selected()
        if not ids:
            return warn(self, "Seleção", "Selecione um ou mais registros.")
        if not confirm(self, "Excluir registros",
                       f"Excluir {len(ids)} registro(s) e o histórico deles? Isso não pode ser desfeito.\n"
                       "(Apenas do banco local; nada é alterado no Instagram.)"):
            return
        for pid in ids:
            self.db.delete_profile(pid)
        log.warning("%d registro(s) excluído(s) do banco local.", len(ids))
        self.main.profiles_changed.emit()
