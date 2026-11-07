"""Navegador aberto pelo painel: comando, abrir, detectar fechamento e encerrar."""
import sys
from pathlib import Path

import pytest

from app import browser

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def test_command_uses_app_profile_and_no_private_mode(tmp_path):
    cmd = browser.ManagedBrowser.command("msedge.exe", "https://www.instagram.com/accounts/emailsignup/",
                                         tmp_path / "edge")
    assert cmd[0] == "msedge.exe" and cmd[-1].startswith("https://www.instagram.com/")
    assert f"--user-data-dir={tmp_path / 'edge'}" in cmd
    assert not any(a in cmd for a in ("--incognito", "--inprivate", "--proxy-server"))


def test_start_running_and_close():
    mb = browser.ManagedBrowser()
    assert not mb.running() and mb.close() is False
    mb.start(SLEEPER, "Teste")
    assert mb.running()
    with pytest.raises(RuntimeError, match="já está aberto"):
        mb.start(SLEEPER, "Teste")
    assert mb.close() is True
    assert not mb.running()


def test_missing_browser_is_friendly(monkeypatch, tmp_path):
    monkeypatch.setattr(browser, "find_browser", lambda name: None)
    with pytest.raises(FileNotFoundError, match="não foi encontrado"):
        browser.ManagedBrowser().open("chrome", "https://x", tmp_path)


@pytest.mark.parametrize("closed_by_user", [False, True])
def test_edge_cookies_removed_after_exit(monkeypatch, tmp_path, closed_by_user):
    monkeypatch.setattr(browser, "find_browser", lambda _name: sys.executable)
    monkeypatch.setattr(browser.ManagedBrowser, "command", staticmethod(lambda *_args: SLEEPER))
    managed = browser.ManagedBrowser()
    managed.open("edge", "about:blank", tmp_path)
    edge = tmp_path / "edge"
    network = edge / "Default" / "Network"
    network.mkdir(parents=True)
    cookies = [network / "Cookies", network / "Cookies-wal", edge / "Default" / "Cookies"]
    preferences = edge / "Default" / "Preferences"
    other = tmp_path / "Cookies"
    try:
        for path in (*cookies, preferences, other):
            path.write_text("test", encoding="utf-8")
        if closed_by_user:
            managed.proc.terminate()
            managed.proc.wait(5)
        managed.close()
        assert all(not path.exists() for path in cookies)
        assert preferences.is_file() and other.is_file()
    finally:
        managed.close()


def test_navegador_tab_open_close_and_logs(monkeypatch, db, tmp_path):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from app.logs import setup_logging
    from app.ui.main_window import MainWindow

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    pid = db.save_profile({"full_name": "Rafaela Veloso", "username": "rafavelo", "birthdate": "2004-03-10",
                           "email": "rafavelo@inboxnexo.online", "state": "Alagoas", "city": "Maceió"}, "S3nha!")
    launched = []

    def fake_open(self, name, url, root):
        launched.append((name, url, Path(root)))
        self.start(SLEEPER, browser.BROWSERS[name])

    monkeypatch.setattr(browser.ManagedBrowser, "open", fake_open)
    handler = setup_logging(tmp_path / "logs")
    w = MainWindow(db, handler)
    nav = w.navegador
    nav.select(pid)
    assert nav.fields["username"][1].text() == "rafavelo"
    assert nav.fields["location"][1].text() == "Maceió, Alagoas"
    nav.browser_choice.setCurrentIndex(nav.browser_choice.findData("chrome"))
    assert db.get_setting("signup_browser") == "chrome"

    nav.open_signup()
    from app import INSTAGRAM_SIGNUP_URL
    assert launched[0][:2] == ("chrome", INSTAGRAM_SIGNUP_URL)
    assert launched[0][2].name == "navegador"
    assert nav.managed.running() and nav.close_btn.isEnabled() and not nav.browser_choice.isEnabled()
    assert db.get_profile(pid)["status"] == "em_cadastro"

    nav.close_browser()
    assert not nav.managed.running() and not nav.close_btn.isEnabled()
    msgs = [m for _t, _l, m in handler.records]
    assert any("aberto na página oficial" in m and "@rafavelo" in m for m in msgs)
    assert any("encerrado pelo painel" in m for m in msgs)
    assert all("S3nha!" not in m for m in msgs)

    # navegador fechado pelo próprio usuário: o painel percebe e registra
    nav.open_signup()
    nav.managed.proc.kill()
    nav.managed.proc.wait()
    nav._check_browser()
    assert any(m.endswith("foi fechado.") for _t, _l, m in handler.records)
    w.close()


def test_chromium_option_shares_saved_executable(db, tmp_path):
    from PySide6.QtWidgets import QApplication
    from app.logs import setup_logging
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    exe = tmp_path / "chrome.exe"
    exe.touch()
    db.set_setting(browser.CHROMIUM_SETTING, str(exe))
    window = MainWindow(db, setup_logging(tmp_path / "logs"))
    try:
        config = window.config
        config.browser.setCurrentIndex(config.browser.findData("chromium"))
        assert config.chromium_exe.text() == str(exe)
        assert db.get_setting("browser") == "chromium"
        assert window.central.choice.currentData() == "chromium"
        assert window.navegador.browser_choice.currentData() == "chromium"
    finally:
        window.close()
        app.processEvents()
