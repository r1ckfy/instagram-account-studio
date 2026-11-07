import os
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QGridLayout, QLineEdit,
                               QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget)

from .. import DATA_DIR, browser, diagnostics, dolphin, generator
from ..logs import log, success
from . import common
from .common import (GREEN, MUTED, RED, YELLOW, button, confirm, error, group, info, label, row,
                     run_async, set_color)
from .config_email import EmailSettings


class ConfigTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db

        # ---------------- banco
        box_db, f_db = group("BANCO DE DADOS", QFormLayout())
        self.db_path = label(str(self.db.path), wrap=True)
        self.db_size = label("", "muted")
        f_db.addRow("Arquivo", self.db_path)
        f_db.addRow("Tamanho", self.db_size)
        f_db.addRow(row(button("Verificar integridade", None, self.check_integrity),
                        button("Otimizar (VACUUM)", None, self.vacuum),
                        button("Abrir pasta de dados", None, lambda: os.startfile(DATA_DIR)), None))
        f_db.addRow(label("Modo WAL ativo: transações confirmadas sobrevivem a um encerramento inesperado.",
                          "muted", wrap=True))

        # ---------------- backup
        box_bk, f_bk = group("BACKUP", QFormLayout())
        self.backup_dir = QLineEdit(self.db.get_setting("backup_dir", str(DATA_DIR / "backups")))
        self.backup_dir.editingFinished.connect(
            lambda: self.db.set_setting("backup_dir", self.backup_dir.text().strip()))
        f_bk.addRow("Pasta de backup", row(self.backup_dir, button("Escolher…", None, self.choose_backup_dir)))
        f_bk.addRow(row(button("💾 Fazer backup agora", "success", self.backup),
                        button("Restaurar backup…", "danger", self.restore), None))
        f_bk.addRow(label("Backups guardam as senhas cifradas: só abrem neste usuário do Windows.",
                          "muted", wrap=True))

        # ---------------- navegador
        box_br, f_br = group("NAVEGADOR", QFormLayout())
        self.browser = QComboBox()
        for k, v in browser.BROWSERS.items():
            self.browser.addItem(v, k)
        self.browser.setCurrentIndex(max(0, self.browser.findData(self.db.get_setting("browser", "padrao"))))
        self.browser.currentIndexChanged.connect(self._save_browser)
        self.browser_info = label("", wrap=True)
        f_br.addRow("Abrir páginas com", self.browser)
        f_br.addRow("", self.browser_info)
        self.chromium_exe = QLineEdit(browser.chromium_path(self.db), readOnly=True)
        self.chromium_exe.setPlaceholderText("Selecione o chrome.exe ou chromium.exe")
        f_br.addRow("Executável do Chromium", row(
            self.chromium_exe, button("Escolher Chromium…", None, self.choose_chromium)))
        f_br.addRow(label("A escolha é aplicada à Central, ao Navegador e à demonstração. "
                          "A opção 'Padrão do sistema' usa Edge para sessões do Studio.",
                          "muted", wrap=True))

        box_dolphin, f_dolphin = group("DOLPHIN ANTY", QFormLayout())
        self.dolphin_profile = QLineEdit(self.db.get_setting("dolphin_profile"), placeholderText="ID numérico do perfil")
        self.dolphin_port = QSpinBox(minimum=1, maximum=65535, value=int(self.db.get_setting("dolphin_port", "3001")))
        self.dolphin_driver = QLineEdit(self.db.get_setting("dolphin_driver"), placeholderText="Opcional. Caminho do ChromeDriver compatível")
        self.dolphin_profile.editingFinished.connect(
            lambda: self.db.set_setting("dolphin_profile", self.dolphin_profile.text().strip()))
        self.dolphin_port.valueChanged.connect(lambda value: self.db.set_setting("dolphin_port", str(value)))
        self.dolphin_driver.editingFinished.connect(
            lambda: self.db.set_setting("dolphin_driver", self.dolphin_driver.text().strip()))
        self.dolphin_profile.editingFinished.connect(self._update_browser_info)
        self.dolphin_port.valueChanged.connect(self._update_browser_info)
        self.dolphin_driver.editingFinished.connect(self._update_browser_info)
        f_dolphin.addRow("ID do perfil", self.dolphin_profile)
        f_dolphin.addRow("Porta da API local", self.dolphin_port)
        f_dolphin.addRow("ChromeDriver", self.dolphin_driver)
        f_dolphin.addRow(label("Deixe o Dolphin Anty aberto e conectado. Se a porta for diferente de 3001, "
                               "consulte a janela Health no Dolphin.", "muted", wrap=True))

        # ---------------- segurança
        box_sec, f_sec = group("SEGURANÇA", QFormLayout())
        self.default_password = QLineEdit(echoMode=QLineEdit.Password)
        self._show_default_password()
        f_sec.addRow("Senha padrão das fichas", row(
            self.default_password, button("Salvar padrão", None, self.save_default_password)))
        f_sec.addRow(label("Para voltar a gerar senhas aleatórias, salve o campo em branco.", "muted", wrap=True))
        self.clip = QSpinBox(minimum=0, maximum=600, suffix=" s")
        self.clip.setValue(int(self.db.get_setting("clipboard_clear", "30")))
        self.clip.valueChanged.connect(self._save_clip)
        f_sec.addRow("Limpar senha copiada após", self.clip)
        f_sec.addRow(label("0 = não limpar. Vale para senhas copiadas nas abas DADOS e NAVEGADOR.", "muted"))
        f_sec.addRow(row(button("Limpar área de transferência agora", None,
                                lambda: QGuiApplication.clipboard().clear()), None))
        f_sec.addRow(label("• Senhas de perfis e de e-mail são cifradas com a DPAPI do Windows.\n"
                           "• Os logs nunca registram senhas, tokens ou conteúdo de e-mails.\n"
                           "• As mensagens IMAP são lidas sob demanda e não ficam salvas em disco.",
                           "muted", wrap=True))

        # ---------------- diagnóstico
        box_diag, diag = group("DIAGNÓSTICO DO SISTEMA")
        self.diag_btn = button("🩺 VERIFICAR SISTEMA", "primary", self.run_diagnostics)
        self.diag_summary = label("")
        diag.addLayout(row(self.diag_btn, self.diag_summary, None))
        self.report = QPlainTextEdit(readOnly=True)
        self.report.setMinimumHeight(220)
        self.report.setPlaceholderText("Clique em VERIFICAR SISTEMA para checar Python, dependências, banco, "
                                       "criptografia, pastas, navegadores, driver e conectividade.")
        diag.addWidget(self.report, 1)

        grid = QGridLayout(self)
        grid.setContentsMargins(14, 8, 14, 14)
        grid.setSpacing(12)
        left = QVBoxLayout()
        for b in (box_db, box_bk, box_br, box_dolphin, box_sec):
            left.addWidget(b)
        left.addStretch(1)
        grid.addLayout(left, 0, 0)
        self.email = EmailSettings(main)
        right = QVBoxLayout()
        right.addWidget(self.email)
        right.addWidget(box_diag, 1)
        grid.addLayout(right, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        common.clipboard_clear_seconds = self.clip.value()
        self._update_db_info()
        self._update_browser_info()

    def _show_default_password(self):
        saved = self.db.get_setting(generator.DEFAULT_PASSWORD_SETTING)
        self.default_password.setPlaceholderText("Senha padrão salva" if saved else "Senhas aleatórias")

    def save_default_password(self):
        try:
            self.db.set_secret(generator.DEFAULT_PASSWORD_SETTING, self.default_password.text())
        except OSError:
            return error(self, "Senha padrão", "O Windows não conseguiu proteger a senha padrão.")
        self.default_password.clear()
        self._show_default_password()
        info(self, "Senha padrão", "Configuração atualizada para as próximas fichas.")

    # ------------------------------------------------------------ banco
    def _update_db_info(self):
        try:
            self.db_size.setText(f"{self.db.path.stat().st_size / 1024:.1f} KB")
        except OSError:
            self.db_size.setText("—")

    def check_integrity(self):
        result = self.db.integrity_check()
        if result == "ok":
            success("Integridade do banco verificada: ok.")
            info(self, "Integridade", "Banco de dados íntegro.")
        else:
            log.error("Integridade do banco: %s", result)
            error(self, "Integridade", f"Problemas encontrados:\n{result}\n\nRestaure um backup.")

    def vacuum(self):
        self.db.vacuum()
        self._update_db_info()
        success("Banco otimizado (VACUUM).")

    # ------------------------------------------------------------ backup
    def choose_backup_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta de backup", self.backup_dir.text())
        if d:
            self.backup_dir.setText(d)
            self.db.set_setting("backup_dir", d)

    def backup(self) -> Path | None:
        folder = Path(self.backup_dir.text().strip() or DATA_DIR / "backups")
        dest = folder / f"studio_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
        try:
            self.db.backup_to(dest)
        except Exception as e:
            log.error("Falha no backup: %s", e)
            error(self, "Backup", f"Não foi possível criar o backup:\n{e}")
            return None
        success("Backup criado: %s", dest.name)
        info(self, "Backup", f"Backup criado em:\n{dest}")
        return dest

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restaurar backup", self.backup_dir.text(),
                                              "Banco SQLite (*.db)")
        if not path or not confirm(self, "Restaurar backup",
                                   "Os dados atuais serão substituídos pelo backup selecionado.\n"
                                   "Um backup de segurança do estado atual será criado antes. Continuar?"):
            return
        if self.backup() is None:
            return
        try:
            self.db.restore_from(Path(path))
        except Exception as e:
            log.error("Falha ao restaurar backup: %s", e)
            return error(self, "Restaurar", f"Não foi possível restaurar:\n{e}")
        success("Backup restaurado: %s", Path(path).name)
        self._update_db_info()
        self.main.reload_all()

    # ------------------------------------------------------------ navegador / segurança
    def _save_browser(self):
        choice = self.browser.currentData()
        self.db.set_setting("browser", choice)
        target = browser.automation_browser(choice)
        for selector in (self.main.central.choice, self.main.navegador.browser_choice):
            selector.setCurrentIndex(selector.findData(target))
        log.info("Navegador selecionado: %s.", self.browser.currentText())
        self._update_browser_info()

    def _update_browser_info(self):
        choice = self.browser.currentData()
        if choice == "dolphin":
            try:
                settings = dolphin.Settings.load(self.db)
            except dolphin.DolphinError as exc:
                self.browser_info.setText(str(exc))
                set_color(self.browser_info, YELLOW)
            else:
                self.browser_info.setText(f"Perfil {settings.profile}, porta local {settings.port}.")
                set_color(self.browser_info, MUTED)
            return
        if choice == "padrao":
            self.browser_info.setText("Usa o navegador padrão do Windows.")
            set_color(self.browser_info, MUTED)
            return
        path = browser.chromium_path(self.db) if choice == "chromium" else browser.find_browser(choice)
        if choice == "chromium" and not Path(path).is_file():
            path = None
        self.browser_info.setText(f"✓ {path}" if path else "✖ Não encontrado neste computador.")
        set_color(self.browser_info, GREEN if path else RED)

    def choose_chromium(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Executável do Chromium", browser.chromium_path(self.db), "Executáveis (*.exe)")
        if path:
            self.db.set_setting(browser.CHROMIUM_SETTING, path)
            self.chromium_exe.setText(path)
            self.browser.setCurrentIndex(self.browser.findData("chromium"))
            self._update_browser_info()

    def showEvent(self, event):
        super().showEvent(event)
        self.chromium_exe.setText(browser.chromium_path(self.db))
        self._update_browser_info()

    def _save_clip(self, v: int):
        common.clipboard_clear_seconds = v
        self.db.set_setting("clipboard_clear", v)

    # ------------------------------------------------------------ diagnóstico
    def run_diagnostics(self):
        self.diag_btn.setEnabled(False)
        self.report.setPlainText("Verificando… (o teste do driver pode levar alguns segundos)")
        self.main.set_busy("Verificando sistema")
        log.info("Verificação do sistema iniciada.")
        args = (self.db.path, DATA_DIR, Path(self.backup_dir.text().strip() or DATA_DIR / "backups"),
                self.browser.currentData(), len(self.db.list_imap()))
        dolphin_port = self.dolphin_port.value()
        chromium_exe = browser.chromium_path(self.db)

        def done(results):
            self.diag_btn.setEnabled(True)
            self.main.set_busy("")
            ok = sum(s == diagnostics.OK for s, _ in results)
            fail = sum(s == diagnostics.FAIL for s, _ in results)
            warns = len(results) - ok - fail
            self.report.setPlainText("\n".join(f"{s}  {t}" for s, t in results) +
                                     f"\n\n✅ {ok} confirmadas   ❌ {fail} falhas   ⚠️ {warns} exigem configuração")
            self.diag_summary.setText(f"✅ {ok}   ❌ {fail}   ⚠️ {warns}")
            set_color(self.diag_summary, RED if fail else YELLOW if warns else GREEN, bold=True)
            (log.warning if fail else success)("Verificação do sistema: %d ok, %d falhas, %d avisos.", ok, fail, warns)

        def failed(exc):
            self.diag_btn.setEnabled(True)
            self.main.set_busy("")
            self.report.setPlainText(f"A verificação não pôde ser concluída: {exc}")
            log.error("Verificação do sistema falhou: %s", exc)

        run_async(lambda: diagnostics.run(*args, dolphin_port=dolphin_port, chromium_exe=chromium_exe), done, failed)
