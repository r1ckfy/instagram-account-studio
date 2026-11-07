"""Aba PROXY — DIAGNÓSTICO DE REDE: cadastro e testes manuais de conectividade, sem vínculo com perfis."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QLineEdit, QSizePolicy, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import DATA_DIR, browser as browser_config, proxy_check
from ..proxy_browser import DiagnosticSession
from ..db import DuplicateError
from ..fichas import TxtError, read_text
from ..logs import log, success
from .common import (GREEN, MUTED, RED, YELLOW, button, confirm, error, group, info, label, row,
                     run_async, set_color, warn)

STATUS_COLORS = {"nao_testado": MUTED, "conectado": GREEN, "instavel": YELLOW, "desconectado": RED}
COLUMNS = ["Nome", "Protocolo", "Host:porta", "Tipo", "Status", "IP observado", "Latência", "Última verificação"]


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    # ocupa o espaço que sobrar, sem empurrar o formulário para fora da tela em 1366×768
    t.setMinimumHeight(90)
    t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
    return t


class ProxyTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db
        self.pid: int | None = None
        self.rows: list[dict] = []
        self.busy = False
        self.direct_ip = ""
        self.session = DiagnosticSession()
        self.session_pid = None
        self.shutting_down = False
        self.session_was_active = False

        # ---------------- lista
        box_list, lst = group("CONEXÕES CADASTRADAS")
        lst.addLayout(row(button("＋ ADICIONAR PROXY", "primary", self.new),
                          button("⤒ Importar", None, self.import_file, "JSON exportado ou TXT host:porta"),
                          button("⤓ Exportar (sem senhas)", None, self.export), None,
                          button("⟳ TESTAR TODOS", None, self.test_all)))
        self.table = _table(COLUMNS)
        self.table.itemSelectionChanged.connect(self._select)
        lst.addWidget(self.table)

        # ---------------- formulário
        box_form, form = group("CONEXÃO", QFormLayout())
        self.name = QLineEdit(placeholderText="ex.: Provedor X — São Paulo")
        self.protocol = QComboBox()
        for k, v in proxy_check.PROTOCOLS.items():
            self.protocol.addItem(v, k)
        self.host = QLineEdit(placeholderText="host ou endpoint do provedor (sem http://)")
        self.port = QSpinBox(minimum=1, maximum=65535, value=8080)
        self.user = QLineEdit(placeholderText="opcional")
        self.password = QLineEdit(echoMode=QLineEdit.Password, placeholderText="opcional (cifrada com DPAPI)")
        self.service = QComboBox()
        for k, v in proxy_check.SERVICES.items():
            self.service.addItem(v, k)
        self.notes = QLineEdit()
        for text, w in (("Nome", self.name), ("Protocolo", self.protocol), ("Host / endpoint", self.host),
                        ("Porta", self.port), ("Usuário", self.user), ("Senha", self.password),
                        ("Tipo de serviço", self.service), ("Observações", self.notes)):
            form.addRow(text, w)
        self.protocol.setToolTip("HTTP: proxy comum (túnel CONNECT para sites HTTPS). HTTPS: conexão TLS até o "
                                 "próprio proxy. SOCKS5: o DNS é resolvido pelo proxy.")
        form.addRow(row(button("💾 SALVAR", "success", self.save), None, button("✖ REMOVER", "danger", self.remove)))

        # ---------------- diagnóstico
        box_diag, dg = group("DIAGNÓSTICO", QGridLayout())
        dg.setColumnStretch(1, 1)
        self.d = {k: label("—", wrap=True) for k in ("status", "ip", "geo", "latency", "protocol", "auth",
                                                     "checked", "direct", "detail")}
        for k in self.d.values():
            k.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.d["status"].setStyleSheet("font-size: 14pt; font-weight: 700;")
        for r, (text, key) in enumerate((("Status", "status"), ("IP público observado", "ip"),
                                         ("País / cidade (aprox.)", "geo"), ("Latência", "latency"),
                                         ("Protocolo", "protocol"), ("Autenticação", "auth"),
                                         ("Última verificação", "checked"), ("IP sem proxy", "direct"),
                                         ("Detalhes", "detail"))):
            dg.addWidget(label(text, "muted"), r, 0, Qt.AlignTop)
            dg.addWidget(self.d[key], r, 1)
        self.timeout = QSpinBox(minimum=3, maximum=60, value=int(self.db.get_setting("proxy_timeout", "10")),
                                suffix=" s")
        self.timeout.valueChanged.connect(lambda v: self.db.set_setting("proxy_timeout", v))
        self.test_btn = button("⚡ TESTAR CONEXÃO", "primary", self.test_selected)
        dg.addLayout(row(self.test_btn, label("Tempo limite"), self.timeout, None), 9, 0, 1, 2)
        self.proxy_selector = QComboBox()
        self.proxy_selector.currentIndexChanged.connect(self._choose_proxy)
        self.browser_choice = QComboBox()
        self.browser_choice.addItem("Microsoft Edge", "edge")
        self.browser_choice.addItem("Google Chrome", "chrome")
        self.browser_choice.addItem("Chromium configurado", "chromium")
        self.chromium_btn = button("Escolher Chromium…", None, self.choose_chromium)
        self.open_btn = button("ABRIR NAVEGADOR DE TESTE", "primary", self.open_browser)
        self.verify_btn = button("VERIFICAR IP", None, self.verify_browser)
        self.close_btn = button("FECHAR NAVEGADOR", None, self.close_browser)
        self.session_label = label("Sessão do navegador: inativa", wrap=True)
        dg.addLayout(row(label("SELECIONAR PROXY"), self.proxy_selector, self.browser_choice), 10, 0, 1, 2)
        dg.addWidget(self.open_btn, 11, 0, 1, 2)
        dg.addLayout(row(self.verify_btn, self.close_btn), 12, 0, 1, 2)
        dg.addWidget(self.session_label, 13, 0, 1, 2)
        dg.addWidget(self.chromium_btn, 15, 0, 1, 2)
        self.session_timer = QTimer(self)
        self.session_timer.timeout.connect(self._session_state)
        self.session_timer.start(1000)
        dg.addWidget(label(f"Cada teste faz {proxy_check.SAMPLES} requisições a {proxy_check.IP_SERVICE} pelo "
                           "proxy. País/cidade vêm de base de geolocalização e são aproximados. O app não altera "
                           "o proxy do Windows. O navegador de teste usa uma sessão isolada.", "muted", wrap=True), 14, 0, 1, 2)

        box_hist, hist = group("HISTÓRICO DE TESTES E ERROS")
        self.history = _table(["Data", "Status", "IP", "Latência", "Autenticação", "Detalhes"])
        hist.addWidget(self.history)

        left = QVBoxLayout()
        left.addWidget(box_list, 1)
        left.addWidget(box_form)
        right = QVBoxLayout()
        right.addWidget(box_diag)
        right.addWidget(box_hist, 1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        lay.setSpacing(12)
        lay.addLayout(left, 3)
        lay.addLayout(right, 2)
        self.refresh()
        self.new()

    # ------------------------------------------------------------ lista
    def refresh(self):
        self.rows = self.db.list_proxies()
        self.proxy_selector.blockSignals(True)
        self.proxy_selector.clear()
        for item in self.rows:
            self.proxy_selector.addItem(item['name'], item['id'])
        self.proxy_selector.setCurrentIndex(self.proxy_selector.findData(self.pid))
        self.proxy_selector.blockSignals(False)
        self.table.setRowCount(len(self.rows))
        for r, p in enumerate(self.rows):
            values = (p["name"], proxy_check.PROTOCOLS[p["protocol"]], f"{p['host']}:{p['port']}",
                      "Rotativo" if p["service"] == "rotativo" else "Fixo", proxy_check.STATUSES[p["status"]],
                      p["last_ip"] or "—", f"{p['last_latency_ms']} ms" if p["last_latency_ms"] is not None else "—",
                      (p["checked_at"] or "—")[:16])
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c == 4:
                    item.setForeground(QColor(STATUS_COLORS[p["status"]]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        if self.pid is not None:
            idx = next((i for i, p in enumerate(self.rows) if p["id"] == self.pid), None)
            if idx is not None:
                self.table.selectRow(idx)
        self._show_diag()

    def _select(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows):
            return
        p = self.rows[r]
        self.pid = p["id"]
        self.proxy_selector.blockSignals(True)
        self.proxy_selector.setCurrentIndex(self.proxy_selector.findData(self.pid))
        self.proxy_selector.blockSignals(False)
        self.name.setText(p["name"])
        self.protocol.setCurrentIndex(self.protocol.findData(p["protocol"]))
        self.host.setText(p["host"])
        self.port.setValue(p["port"])
        self.user.setText(p["username"])
        self.password.clear()
        self.password.setPlaceholderText("•••••• (salva — deixe vazio para manter)" if p["has_password"]
                                         else "opcional (cifrada com DPAPI)")
        self.service.setCurrentIndex(self.service.findData(p["service"]))
        self.notes.setText(p["notes"])
        self._show_diag()

    def _choose_proxy(self, index):
        pid = self.proxy_selector.itemData(index)
        for row_index, proxy in enumerate(self.rows):
            if proxy['id'] == pid:
                self.table.selectRow(row_index)
                break

    def _show_diag(self):
        p = next((x for x in self.rows if x["id"] == self.pid), None)
        self.test_btn.setEnabled(p is not None and not self.busy)
        self._session_state()
        self.d["direct"].setText(self.direct_ip or "— (obtido no primeiro teste)")
        if p is None:
            for k in ("status", "ip", "geo", "latency", "protocol", "auth", "checked", "detail"):
                self.d[k].setText("—")
            set_color(self.d["status"], MUTED)
            self.history.setRowCount(0)
            return
        hist = self.db.proxy_history(p["id"])
        last = hist[0] if hist else {}
        self.d["status"].setText(proxy_check.STATUSES[p["status"]])
        self.d["status"].setStyleSheet(f"font-size: 14pt; font-weight: 700; color: {STATUS_COLORS[p['status']]};")
        self.d["ip"].setText(p["last_ip"] or "—")
        self.d["geo"].setText(p["last_geo"] or "—")
        self.d["latency"].setText(f"{p['last_latency_ms']} ms (média)" if p["last_latency_ms"] is not None else "—")
        self.d["protocol"].setText(proxy_check.PROTOCOLS[p["protocol"]])
        self.d["auth"].setText(p["auth_status"] or "—")
        set_color(self.d["auth"], RED if p["auth_status"] == "Recusada" else GREEN if p["auth_status"] == "OK"
                  else MUTED)
        self.d["checked"].setText(p["checked_at"] or "nunca")
        self.d["detail"].setText(last.get("detail", "—"))
        self.history.setRowCount(len(hist))
        for r, h in enumerate(hist):
            for c, v in enumerate((h["created_at"][:16], proxy_check.STATUSES[h["status"]], h["ip"] or "—",
                                   f"{h['latency_ms']} ms" if h["latency_ms"] is not None else "—",
                                   h["auth_status"], h["detail"])):
                item = QTableWidgetItem(v)
                if c == 1:
                    item.setForeground(QColor(STATUS_COLORS[h["status"]]))
                self.history.setItem(r, c, item)
        self.history.resizeColumnsToContents()

    # ------------------------------------------------------------ cadastro
    def new(self):
        self.pid = None
        self.proxy_selector.setCurrentIndex(-1)
        self.table.clearSelection()
        for w in (self.name, self.host, self.user, self.password, self.notes):
            w.clear()
        self.protocol.setCurrentIndex(0)
        self.service.setCurrentIndex(0)
        self.port.setValue(8080)
        self.password.setPlaceholderText("opcional (cifrada com DPAPI)")
        self._show_diag()
        self.name.setFocus()

    def _cfg(self) -> dict:
        return {"id": self.pid, "name": self.name.text().strip(), "protocol": self.protocol.currentData(),
                "host": self.host.text().strip(), "port": self.port.value(), "username": self.user.text().strip(),
                "service": self.service.currentData(), "notes": self.notes.text().strip()}

    def save(self) -> int | None:
        cfg = self._cfg()
        if err := proxy_check.validate(cfg):
            return warn(self, "Revise a conexão", err)
        try:
            self.pid = self.db.save_proxy(cfg, self.password.text() or None)
        except DuplicateError as e:
            return warn(self, "Nome duplicado", str(e))
        success("Proxy '%s' salvo (%s %s:%s).", cfg["name"], proxy_check.PROTOCOLS[cfg["protocol"]],
                cfg["host"], cfg["port"])
        self.password.clear()
        self.refresh()
        return self.pid

    def remove(self):
        if self.pid is None:
            return
        name = self.name.text()
        if confirm(self, "Remover conexão", f"Remover '{name}' e o histórico de testes dela?"):
            self.db.delete_proxy(self.pid)
            log.warning("Proxy '%s' removido.", name)
            self.new()
            self.refresh()

    # ------------------------------------------------------------ testes
    def _set_busy(self, on: bool, text: str = ""):
        self.busy = on
        self.main.set_busy(text if on else "")
        self._show_diag()

    def _job(self, items: list[tuple[int, dict, str]], timeout: int, known_direct: str):
        """Roda na thread de trabalho: IP direto (uma vez) + diagnóstico de cada conexão."""
        direct = known_direct
        if not direct:
            try:
                direct = proxy_check.direct_ip(timeout)
            except Exception:
                direct = ""
        return direct, [(pid, proxy_check.diagnose(cfg, pw, timeout, direct=direct)) for pid, cfg, pw in items]

    def _run(self, items: list[tuple[int, dict, str]]):
        if self.busy or not items:
            return
        names = ", ".join(cfg["name"] for _p, cfg, _pw in items)
        log.info("Testando proxy: %s.", names)
        self._set_busy(True, "Testando proxy")
        timeout, known = self.timeout.value(), self.direct_ip

        def done(out):
            self.direct_ip, results = out
            for pid, res in results:
                self.db.record_proxy_test(pid, res)
                name = next(cfg["name"] for p, cfg, _pw in items if p == pid)
                text = (f"Proxy '{name}': {proxy_check.STATUSES[res['status']]} — IP {res['ip'] or '—'}, "
                        f"{res['latency']['avg'] if res['latency'] else '—'} ms, amostras {res['samples']}, "
                        f"autenticação {res['auth']}. {res['detail']}")
                {"conectado": success, "instavel": log.warning}.get(res["status"], log.error)(text)
            self._set_busy(False)
            self.refresh()

        def failed(exc):
            self._set_busy(False)
            log.error("Teste de proxy interrompido: %s", exc)
            error(self, "Teste de proxy", f"O teste não pôde ser concluído:\n{exc}")

        run_async(lambda: self._job(items, timeout, known), done, failed)

    def test_selected(self):
        if self.pid is None:
            return
        p = self.db.get_proxy(self.pid)
        self._run([(p["id"], p, self.db.get_proxy_password(p["id"]))])

    def test_all(self):
        rows = self.db.list_proxies()
        if not rows:
            return warn(self, "Testar todos", "Nenhuma conexão cadastrada.")
        self._run([(p["id"], p, self.db.get_proxy_password(p["id"])) for p in rows])

    def _session_state(self):
        active = self.session.driver is not None
        self.open_btn.setEnabled(self.pid is not None and not self.busy and not active)
        self.verify_btn.setEnabled(active and not self.busy)
        self.close_btn.setEnabled(active and not self.busy)
        self.browser_choice.setEnabled(not self.busy and not active)
        self.chromium_btn.setEnabled(not self.busy and not active)
        self.proxy_selector.setEnabled(not self.busy)
        if self.session_was_active and not active and not self.busy:
            self.session_label.setText(self.session_label.text() + "\nSessão encerrada; conexões fechadas.")
        self.session_was_active = active

    def choose_chromium(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Executável do Chromium", browser_config.chromium_path(self.db), "Executáveis (*.exe)")
        if path:
            self.db.set_setting(browser_config.CHROMIUM_SETTING, path)
            self.browser_choice.setCurrentIndex(self.browser_choice.findData("chromium"))

    def _browser_job(self, opening):
        if self.busy or (opening and self.pid is None):
            return
        pid = self.pid if opening else self.session_pid
        cfg = self.db.get_proxy(pid) if opening else None
        password = self.db.get_proxy_password(pid) if opening else None
        browser, timeout = self.browser_choice.currentData(), self.timeout.value()
        chromium_exe = browser_config.chromium_path(self.db)
        if opening and browser == "chromium" and (not chromium_exe or not Path(chromium_exe).is_file()):
            return warn(self, "Chromium", "Use Escolher Chromium para indicar o executável.")
        previous_ip = self.db.get_setting(f"proxy_browser_ip:{pid}", cfg.get("last_ip") or "") if cfg else ""
        self._set_busy(True, "Verificando navegador pelo proxy")
        self._session_state()
        self.session_label.setText("Conectando e verificando o IP pelo navegador…")

        def work():
            result = (self.session.open(cfg, password, browser, timeout,
                                        chromium_exe=chromium_exe, previous_ip=previous_ip)
                      if opening else self.session.verify())
            if self.shutting_down:
                self.session.close()
            return result

        def done(result):
            self.session_pid = pid
            self.direct_ip = result['direct']
            if any(p['id'] == pid for p in self.db.list_proxies()):
                self.db.record_proxy_test(pid, result)
                if result['ip'] and result['ip'] != result['direct']:
                    self.db.set_setting(f"proxy_browser_ip:{pid}", result['ip'])
            self._set_busy(False)
            self.refresh()
            self.session_label.setText(f"Navegador / proxy #{pid}: {result['ip']} | direto: {result['direct']} | "
                                       f"{result['latency']['avg']} ms | {self.session.cfg['protocol'].upper()} | "
                                       f"{result['auth']} | {result['detail']}")
            self._session_state()

        def failed(exc):
            self.direct_ip = self.session.direct
            result = self.session.last_result
            if result and result.get('status') == 'desconectado' and any(p['id'] == pid for p in self.db.list_proxies()):
                self.db.record_proxy_test(pid, result)
            self._set_busy(False)
            self.refresh()
            self.session_label.setText(str(exc))
            self._session_state()
            log.error("Diagnóstico do navegador: %s", exc)

        run_async(work, done, failed)

    def open_browser(self):
        self._browser_job(True)

    def verify_browser(self):
        self._browser_job(False)

    def close_browser(self):
        if self.busy:
            return
        self._set_busy(True, "Fechando navegador de teste")
        def done(_):
            self._set_busy(False)
            self._session_state()
        run_async(self.session.close, done, lambda exc: done(None))

    def shutdown(self):
        self.shutting_down = True
        self.session_timer.stop()
        self.session.close()

    # ------------------------------------------------------------ importar/exportar
    def export(self):
        rows = self.db.list_proxies()
        if not rows:
            return warn(self, "Exportar", "Nenhuma conexão cadastrada.")
        path, _ = QFileDialog.getSaveFileName(self, "Exportar conexões (sem senhas)",
                                              str(DATA_DIR / f"proxies_{datetime.now():%Y%m%d_%H%M}.json"),
                                              "JSON (*.json)")
        if not path:
            return
        n = proxy_check.export_configs(rows, Path(path))
        success("%d conexão(ões) de proxy exportada(s) sem senhas para %s.", n, Path(path).name)
        info(self, "Exportar", f"{n} conexão(ões) exportada(s) para:\n{path}\n\nSenhas não são exportadas.")

    def import_file(self, path: Path | None = None, quiet: bool = False) -> tuple[int, int, list[str]] | None:
        if path is None:
            chosen, _ = QFileDialog.getOpenFileName(self, "Importar conexões", str(Path.home()),
                                                    "JSON ou TXT (*.json *.txt);;Todos os arquivos (*)")
            if not chosen:
                return None
            path = Path(chosen)
        try:
            rows, warnings = proxy_check.parse_import(read_text(path))
        except (TxtError, ValueError, OSError) as e:
            log.error("Importação de proxies falhou: %s", e)
            return error(self, "Importar", str(e))
        added, skipped = 0, 0
        for r in rows:
            try:
                self.db.save_proxy(r)
                added += 1
            except DuplicateError:
                skipped += 1
        msg = f"{path.name}: {added} conexão(ões) importada(s), {skipped} já existente(s), {len(warnings)} aviso(s)."
        (success if added else log.warning)("Proxies — %s", msg)
        for w in warnings:
            log.warning("Importação de proxies: %s", w)
        self.refresh()
        if not quiet:
            info(self, "Importar", msg + ("\n\n" + "\n".join(warnings[:15]) if warnings else ""))
        return added, skipped, warnings

