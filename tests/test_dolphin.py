from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace
import pytest

from app import dolphin


@pytest.mark.parametrize("status", [200, 402])
def test_local_start_reads_automation_port(status):
    paths = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'{"success": true, "automation": {"port": 50123}}')
        def log_message(self, *_args):
            pass

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()
        settings = dolphin.Settings('12345', server.server_port, '')
        if status == 402:
            with pytest.raises(dolphin.DolphinError, match="plano com automação"):
                dolphin.start_profile(settings)
        else:
            assert dolphin.start_profile(settings) == 50123
        thread.join(5)
    assert paths == ['/v1.0/browser_profiles/12345/start?automation=1']


def test_managed_tab_closes_only_its_own_handle():
    calls = []
    class Driver:
        window_handles = ['existing']
        current_window_handle = 'existing'
        def __init__(self):
            self.switch_to = SimpleNamespace(new_window=self.new_window, window=self.select)
            self.service = SimpleNamespace(stop=lambda: calls.append('stop'))
        def new_window(self, kind):
            assert kind == 'tab'
            self.window_handles.append('owned')
            self.current_window_handle = 'owned'
        def select(self, handle):
            self.current_window_handle = handle
        def close(self):
            calls.append(self.current_window_handle)
            self.window_handles.remove(self.current_window_handle)

    driver = Driver()
    tab = dolphin.ProfileTab(driver)
    driver.select('existing')
    assert tab.window_handles == ['owned']
    tab.quit()
    assert calls == ['owned', 'stop']
    assert driver.window_handles == ['existing']


def test_dolphin_choices_reach_signup_flows(db, profile, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QThreadPool
    from app.logs import setup_logging
    from app.ui.main_window import MainWindow
    from test_signup import wait

    app = QApplication.instance() or QApplication([])
    pid = db.save_profile(profile, 'senha-de-teste')
    db.set_setting('dolphin_profile', '9876')
    db.set_setting('dolphin_port', '3003')
    window = MainWindow(db, setup_logging(tmp_path / 'logs'))
    central, nav = window.central, window.navegador
    called = []

    def manual(settings, url):
        called.append(('manual', settings.profile, settings.port, url))

    monkeypatch.setattr(nav.managed, 'open_dolphin', manual)
    window.config.browser.setCurrentIndex(window.config.browser.findData('dolphin'))
    assert db.get_setting('browser') == 'dolphin'
    assert nav.browser_choice.currentData() == central.choice.currentData() == 'dolphin'
    nav.open_btn.click()
    assert QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()
    assert called[0][:3] == ('manual', '9876', 3003)
    nav._watch.stop()
    central.select(pid)
    monkeypatch.setattr(central.session, 'open',
                        lambda choice, settings: called.append((choice, settings.profile, settings.port)))
    monkeypatch.setattr(central.session, 'fill', lambda _data: None)
    central.start_btn.click()
    wait(app, central)
    assert called[1] == ('dolphin', '9876', 3003)
    window.close()


def test_running_profile_checks_matching_debug_endpoint(tmp_path, monkeypatch):
    endpoint = '/devtools/browser/session-id'
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == '/json/version'
            self.send_response(200)
            self.end_headers()
            ws = f'ws://127.0.0.1:{self.server.server_port}{endpoint}'
            self.wfile.write(f'{{"webSocketDebuggerUrl":"{ws}"}}'.encode())
        def log_message(self, *_args):
            pass

    monkeypatch.setenv('APPDATA', str(tmp_path))
    folder = tmp_path / 'dolphin_anty' / 'browser_profiles' / '12345' / 'data_dir'
    folder.mkdir(parents=True)
    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            active_port = folder / 'DevToolsActivePort'
            active_port.write_text(f'{server.server_port}\n{endpoint}\n', encoding='utf-8')
            assert dolphin.running_port('12345') == server.server_port
            active_port.write_text(f'{server.server_port}\n/devtools/browser/stale\n', encoding='utf-8')
            assert dolphin.running_port('12345') is None
        finally:
            server.shutdown()
            thread.join(5)
