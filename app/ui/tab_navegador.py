import threading
from datetime import date

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                               QHBoxLayout, QLineEdit, QListWidget, QRadioButton, QVBoxLayout,
                               QWidget)

from .. import DATA_DIR, INSTAGRAM_SIGNUP_URL, browser, dolphin
from ..db import STATUSES
from ..logs import log, success
from .common import (CYAN, GREEN, MUTED, RED, YELLOW, CopyField, button, error, group, label,
                     row, run_async, set_color, warn)

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]
STATE_COLORS = {"AGUARDANDO": MUTED, "CONCLUÍDO": GREEN, "INTERROMPIDO": YELLOW, "FALHOU": RED}


class ResultDialog(QDialog):
    """Registro manual do resultado do cadastro — só o usuário confirma uma conta ativa."""
    OPTIONS = [("ativa", "Conta criada — confirmei que consigo acessá-la"),
               ("verificacao", "Aguardando verificação (e-mail, SMS ou revisão do Instagram)"),
               ("falhou", "Cadastro não concluído / falhou"),
               ("bloqueada", "Conta bloqueada ou suspensa"),
               ("preparado", "Voltar para 'preparado' (não tentei ainda)")]

    def __init__(self, parent, username: str):
        super().__init__(parent)
        self.setWindowTitle("Registrar resultado")
        lay = QVBoxLayout(self)
        lay.addWidget(label(f"Resultado do cadastro de @{username}:", "title"))
        self.group = QButtonGroup(self)
        for i, (key, text) in enumerate(self.OPTIONS):
            rb = QRadioButton(text)
            rb.setProperty("key", key)
            self.group.addButton(rb, i)
            lay.addWidget(rb)
        self.note = QLineEdit(placeholderText="Observação (opcional)")
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _accept(self):
        if self.group.checkedButton() is None:
            return warn(self, "Selecione", "Escolha uma opção de resultado.")
        self.accept()

    def result_value(self) -> tuple[str, str]:
        return self.group.checkedButton().property("key"), self.note.text().strip()


class NavegadorTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db
        self.stop_event: threading.Event | None = None
        self.managed = browser.ManagedBrowser()
        self.dolphin_busy = False

        # ---------------- seleção + dados para copiar
        self.profile = QComboBox()
        self.profile.currentIndexChanged.connect(self._show_profile)
        sel = row(label("Ficha:"), self.profile, button("↻", "icon", self.refresh, "Atualizar lista"))
        sel.setStretch(1, 1)

        box_data, grid = group("DADOS PARA COPIAR", QGridLayout())
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        self.fields = {
            "email": ("E-mail", CopyField()),
            "full_name": ("Nome completo", CopyField()),
            "username": ("Nome de usuário", CopyField()),
            "password": ("Senha", CopyField(secret=True)),
            "birth": ("Nascimento", CopyField()),
            "location": ("Localização", CopyField()),
            "bio": ("Bio", CopyField()),
        }
        for r, (text, w) in enumerate(self.fields.values()):
            grid.addWidget(label(text), r, 0)
            grid.addWidget(w, r, 1)
        self.birth_hint = label("", "muted")
        grid.addWidget(self.birth_hint, len(self.fields), 1)
        self.status_label = label("")
        grid.addWidget(label("Status"), len(self.fields) + 1, 0)
        grid.addWidget(self.status_label, len(self.fields) + 1, 1)

        # ---------------- cadastro manual
        box_manual, manual = group("CADASTRO MANUAL NO INSTAGRAM")
        manual.addWidget(label(
            "1. Abra a página oficial de cadastro.  2. Copie cada dado acima e preencha você mesmo.  "
            "3. Conclua as verificações solicitadas pelo Instagram.  4. Registre o resultado aqui.\n"
            "O aplicativo não preenche nem envia nada no site do Instagram.", "muted", wrap=True))
        self.browser_choice = QComboBox()
        for key in ("edge", "chrome"):
            self.browser_choice.addItem(browser.BROWSERS[key], key)
            if not browser.find_browser(key):
                self.browser_choice.setItemText(self.browser_choice.count() - 1,
                                                f"{browser.BROWSERS[key]} (não instalado)")
        self.browser_choice.addItem("Dolphin Anty", "dolphin")
        self.browser_choice.addItem(browser.BROWSERS["chromium"], "chromium")
        saved = self.db.get_setting("signup_browser", "edge")
        self.browser_choice.setCurrentIndex(max(0, self.browser_choice.findData(saved)))
        self.browser_choice.currentIndexChanged.connect(
            lambda: self.db.set_setting("signup_browser", self.browser_choice.currentData()))
        self.open_btn = button("🌐 ABRIR PÁGINA DE CADASTRO", "primary", self.open_signup)
        self.close_btn = button("■ FECHAR NAVEGADOR", "danger", self.close_browser)
        self.result_btn = button("✔ REGISTRAR RESULTADO", "success", self.register_result)
        self.browser_state = label("Navegador: fechado", "muted")
        manual.addLayout(row(label("Navegador"), self.browser_choice, self.browser_state, None))
        manual.addLayout(row(self.open_btn, self.close_btn, self.result_btn, None))
        manual.addWidget(label("Abre em um perfil próprio do app (o mesmo para todas as fichas), separado do seu "
                               "navegador do dia a dia — por isso o painel consegue fechá-lo.", "muted", wrap=True))
        self._watch = QTimer(self, interval=1500)
        self._watch.timeout.connect(self._check_browser)

        # ---------------- demo Selenium
        box_demo, demo = group("TESTE DE PREENCHIMENTO AUTOMÁTICO — PÁGINA DEMO LOCAL")
        demo.addWidget(label(
            "Abre demo/cadastro_demo.html no navegador (Selenium) e preenche os campos com o perfil "
            "selecionado, em duas etapas. Envie a página demo, feche a janela ou clique PARAR. "
            "Funciona apenas com a página local.", "muted", wrap=True))
        self.demo_btn = button("▶ INICIAR DEMO", "primary", self.start_demo)
        self.stop_btn = button("■ PARAR", "danger", self.stop_demo)
        self.stop_btn.setEnabled(False)
        self.state = label("AGUARDANDO")
        set_color(self.state, MUTED, bold=True)
        demo.addLayout(row(self.demo_btn, self.stop_btn, None, label("Estado:"), self.state))
        self.steps = QListWidget()
        self.steps.setMinimumHeight(110)
        demo.addWidget(self.steps)

        left = QVBoxLayout()
        left.addLayout(sel)
        left.addWidget(box_data)
        left.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(box_manual)
        right.addWidget(box_demo, 1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        lay.setSpacing(12)
        lay.addLayout(left, 1)
        lay.addLayout(right, 1)
        main.profiles_changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------ perfis
    def refresh(self):
        current = self.profile.currentData()
        self.profile.blockSignals(True)
        self.profile.clear()
        for p in self.db.list_profiles():
            self.profile.addItem(f"@{p['username']} — {p['full_name']} ({STATUSES[p['status']]})", p["id"])
        idx = self.profile.findData(current)
        self.profile.setCurrentIndex(idx if idx >= 0 else 0)
        self.profile.blockSignals(False)
        self._show_profile()

    def select(self, pid: int):
        self.profile.setCurrentIndex(max(0, self.profile.findData(pid)))

    def _show_profile(self):
        pid = self.profile.currentData()
        has = pid is not None
        for b in (self.open_btn, self.result_btn):
            b.setEnabled(has)
        self.demo_btn.setEnabled(has and self.stop_event is None)
        self._show_browser_state()
        if not has:
            for _t, w in self.fields.values():
                w.setText("")
            self.birth_hint.setText("Nenhum perfil salvo. Gere dados em DADOS e salve em PERFIL.")
            self.status_label.setText("")
            return
        p = self.db.get_profile(pid)
        born = date.fromisoformat(p["birthdate"]) if p["birthdate"] else None
        values = {"email": p["email"], "full_name": p["full_name"], "username": p["username"],
                  "password": self.db.get_password(pid), "bio": p["bio"].replace("\n", " ⏎ "),
                  "birth": f"{born:%d/%m/%Y}" if born else "",
                  "location": ", ".join(x for x in (p["city"], p["state"]) if x)}
        for key, (_t, w) in self.fields.items():
            w.setText(values[key])
        self.birth_hint.setText(f"Dia {born.day} • {MONTHS[born.month - 1]} • {born.year}" if born else "")
        self.status_label.setText(STATUSES[p["status"]])
        if not p["email"]:
            self.status_label.setText(STATUSES[p["status"]] + "   ⚠ perfil sem e-mail")

    # ------------------------------------------------------------ cadastro manual
    def open_signup(self):
        if hasattr(self.main, 'central') and (self.main.central.busy or self.main.central.active_pid is not None):
            return warn(self, "Central", "Encerre a sessao da Central de Cadastros primeiro.")
        pid = self.profile.currentData()
        choice = self.browser_choice.currentData()
        if pid is None or self.dolphin_busy:
            return
        if choice == "dolphin":
            try:
                settings = dolphin.Settings.load(self.db)
            except dolphin.DolphinError as exc:
                return warn(self, "Dolphin Anty", str(exc))
            self._dolphin_task(lambda: self.managed.open_dolphin(settings, INSTAGRAM_SIGNUP_URL),
                               lambda _: self._signup_opened(pid, choice))
            return
        try:
            options = {"chromium_exe": browser.chromium_path(self.db)} if choice == "chromium" else {}
            self.managed.open(choice, INSTAGRAM_SIGNUP_URL, DATA_DIR / "navegador", **options)
        except Exception as e:
            log.error("Não foi possível abrir o %s: %s", browser.BROWSERS[choice], e)
            return error(self, "Navegador", str(e))
        self._signup_opened(pid, choice)

    def _signup_opened(self, pid, choice):
        self._watch.start()
        self._show_browser_state()
        p = self.db.get_profile(pid)
        success("%s aberto na página oficial de cadastro (ficha @%s).",
                browser.BROWSERS.get(choice, "Dolphin Anty"), p["username"])
        if p["status"] == "preparado":
            self.db.set_status(pid, "em_cadastro", "Página oficial de cadastro aberta")
            self.main.profiles_changed.emit()

    def close_browser(self):
        if self.dolphin_busy:
            return
        if self.managed.dolphin is not None:
            self._watch.stop()
            self._dolphin_task(self.managed.close, lambda _: log.info("Aba do Dolphin Anty encerrada."))
            return
        name = self.managed.name
        try:
            closed = self.managed.close()
        except Exception as e:
            log.error("Não foi possível encerrar o %s: %s", name, e)
            return error(self, "Navegador", f"Não foi possível encerrar o navegador:\n{e}")
        self._watch.stop()
        if closed:
            log.info("%s encerrado pelo painel.", name)
        self._show_browser_state()

    def _check_browser(self):
        if self.managed.dolphin is not None:
            tab = self.managed.dolphin
            def alive():
                from selenium.common.exceptions import WebDriverException
                try:
                    return bool(tab.window_handles)
                except WebDriverException:
                    return False
            def checked(is_alive):
                if not is_alive:
                    self.close_browser()
            self._dolphin_task(alive, checked)
            return
        if not self.managed.running():
            try:
                self.managed.close()
            except OSError:
                self.browser_state.setText("Edge fechado. Aguardando liberação dos cookies.")
                return
            self._watch.stop()
            log.info("%s foi fechado.", self.managed.name or "Navegador")
            self._show_browser_state()

    def _show_browser_state(self):
        running = self.managed.running()
        self.browser_state.setText(f"{self.managed.name}: aberto" if running else "Navegador: fechado")
        set_color(self.browser_state, GREEN if running else MUTED, bold=running)
        self.open_btn.setEnabled(self.profile.currentData() is not None and not self.dolphin_busy)
        self.close_btn.setEnabled(running and not self.dolphin_busy)
        self.browser_choice.setEnabled(not running and not self.dolphin_busy)

    def _dolphin_task(self, work, done):
        if self.dolphin_busy:
            return
        self.dolphin_busy = True
        self._show_browser_state()

        def finished(result):
            self.dolphin_busy = False
            self._show_browser_state()
            done(result)

        def failed(exc):
            self.dolphin_busy = False
            self._show_browser_state()
            note = str(exc) if isinstance(exc, dolphin.DolphinError) else "Falha ao abrir ou fechar a aba do Dolphin Anty."
            log.warning("Dolphin Anty: %s", note)
            error(self, "Dolphin Anty", note)

        run_async(work, finished, failed)

    def register_result(self):
        pid = self.profile.currentData()
        p = self.db.get_profile(pid)
        dlg = ResultDialog(self, p["username"])
        if not dlg.exec():
            return
        status, note = dlg.result_value()
        self.db.set_status(pid, status, note or "Resultado registrado manualmente")
        (success if status == "ativa" else log.warning if status in ("falhou", "bloqueada") else log.info)(
            "Resultado registrado para @%s: %s.", p["username"], STATUSES[status])
        self.main.profiles_changed.emit()

    # ------------------------------------------------------------ demo Selenium
    def _set_state(self, text: str):
        if text in browser.STATES:
            self.state.setText(text)
            set_color(self.state, STATE_COLORS.get(text, CYAN), bold=True)
            self.main.set_demo_state(text, self.stop_event is not None)
        self.steps.addItem(text)
        self.steps.scrollToBottom()

    def start_demo(self):
        if hasattr(self.main, 'central') and (self.main.central.busy or self.main.central.active_pid is not None):
            return warn(self, "Central", "Encerre a sessao da Central de Cadastros primeiro.")
        pid = self.profile.currentData()
        if pid is None or self.stop_event is not None:
            return
        p = self.db.get_profile(pid)
        data = {**p, "password": self.db.get_password(pid)}
        target = browser.automation_browser(self.db.get_setting("browser", "padrao"))
        demo_options = {}
        if target == "dolphin":
            try:
                demo_options["dolphin_settings"] = dolphin.Settings.load(self.db)
            except dolphin.DolphinError as exc:
                return warn(self, "Dolphin Anty", str(exc))
        elif target == "chromium":
            try:
                demo_options["chromium_exe"] = browser.require_chromium(browser.chromium_path(self.db))
            except FileNotFoundError as exc:
                return warn(self, "Chromium", str(exc))
        self.steps.clear()
        self.stop_event = threading.Event()
        self.demo_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        log.info("Teste demo iniciado com @%s (%s).", p["username"], browser.BROWSERS[target])
        stop = self.stop_event
        run_async(lambda progress: browser.run_demo(data, target, stop, progress, **demo_options),
                  self._demo_done, self._demo_failed, self._demo_progress)

    def _demo_progress(self, text: str):
        self._set_state(text)
        if text == "PREENCHENDO CAMPOS" or text.startswith("Campo"):
            log.info("Demo: %s", text)
        elif text == "AGUARDANDO REVISÃO":
            log.warning("Demo: campos preenchidos, aguardando revisão humana na página demo.")
        elif text == "CONCLUÍDO":
            success("Demo: formulário de demonstração enviado pelo usuário.")
        elif text == "CARREGANDO PÁGINA":
            log.info("Demo: navegador aberto, carregando página local.")

    def _demo_done(self, final: str):
        self._finish()
        self._set_state(final)
        if final == "INTERROMPIDO":
            log.warning("Demo encerrada antes do envio da página demo.")

    def _demo_failed(self, exc: Exception):
        self._finish()
        self._set_state("FALHOU")
        msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        log.error("Demo falhou: %s", msg)
        error(self, "Teste demo", f"O teste de preenchimento falhou:\n\n{msg}\n\n"
                                   "Verifique o navegador em CONFIGURAÇÕES → VERIFICAR SISTEMA.")

    def _finish(self):
        self.stop_event = None
        self.stop_btn.setEnabled(False)
        self.demo_btn.setEnabled(self.profile.currentData() is not None)

    def stop_demo(self):
        if self.stop_event:
            self.stop_event.set()
            self.steps.addItem("Encerrando navegador…")

    def shutdown(self):
        self._watch.stop()
        self.stop_demo()
        try:
            self.managed.close()
        except OSError as exc:
            log.warning("O Windows ainda não liberou os cookies do Edge: %s", exc)
