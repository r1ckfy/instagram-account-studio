import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThreadPool
from app import signup
from app.logs import setup_logging
from app.ui.main_window import MainWindow


def wait(app, tab):
    for _ in range(15):
        QThreadPool.globalInstance().waitForDone(10000)
        app.processEvents()
        if not tab.busy:
            return
    assert not tab.busy


def test_validate():
    with pytest.raises(ValueError, match='ausentes'):
        signup.validate({})
    good = dict(full_name='Ana', username='ana', email='ana@example.org', password='secret', birthdate='2001-02-03')
    signup.validate(good)
    for update in ({'username': 'bad user'}, {'email': '@example.com'}, {'full_name': ' '}):
        with pytest.raises(ValueError):
            signup.validate(dict(good, **update))
    with pytest.raises(ValueError):
        signup.validate(dict(good, birthdate='bad'))


def test_central_existing_data_button_history_and_close(db, profile, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    pid = db.save_profile(profile, 'NaoVazarSenha')
    handler = setup_logging(tmp_path/'logs')
    window = MainWindow(db, handler)
    t = window.central
    opened = []
    monkeypatch.setattr(t.session, 'open', lambda choice: opened.append(choice))
    monkeypatch.setattr(t.session, 'fill', lambda data: None)
    monkeypatch.setattr(t.session, 'close', lambda: None)
    monkeypatch.setattr(t.session, 'alive', lambda: True)
    t.select(pid)
    assert t.fields['email'].text() == profile['email']
    assert t.fields['day'].text() == '14'
    t.start_btn.click()
    assert t.busy and not t.start_btn.isEnabled()
    wait(app, t)
    assert opened == ['edge']
    assert t.operation_state == 'AGUARDANDO USUÁRIO'
    t.start()
    assert len(opened) == 1
    assert 'CONCLUÍDO' not in [e['state'] for e in db.signup_history(pid)]
    t.close_browser()
    wait(app, t)
    assert t.operation_state == 'INTERROMPIDO'
    assert len(db.signup_history(pid)) == 5
    assert all('NaoVazarSenha' not in message for _, _, message in handler.records)
    assert window.proxy and window.imap and window.dados and window.navegador
    window.close()


def test_open_failure_cleans_session(monkeypatch):
    class Driver:
        quit_called = False
        def set_page_load_timeout(self, timeout): pass
        def get(self, url): raise RuntimeError('sensitive failure')
        def quit(self): self.quit_called = True
    d = Driver()
    monkeypatch.setattr(signup.browser, 'make_driver', lambda choice: d)
    session = signup.SignupBrowser()
    with pytest.raises(RuntimeError, match='Falha'):
        session.open('edge')
    assert d.quit_called and session.driver is None


def test_history_survives_reopen(db, profile):
    from app.db import Database
    pid = db.save_profile(profile)
    db.signup_event(pid, 'op1', 'PENDENTE', 'DADOS VALIDADOS')
    second = Database(db.path)
    assert second.signup_history(pid)[0]['operation_id'] == 'op1'
    assert second.get_profile(pid)['username'] == profile['username']
    second.close()

def test_user_confirmed_result_and_dados_button(db, profile, tmp_path, monkeypatch):
    import app.ui.tab_central as module
    app = QApplication.instance() or QApplication([])
    pid = db.save_profile(profile, 'secret')
    w = MainWindow(db, setup_logging(tmp_path/'logs'))
    t = w.central
    monkeypatch.setattr(t.session, 'open', lambda _: None)
    monkeypatch.setattr(t.session, 'fill', lambda data: None)
    monkeypatch.setattr(t.session, 'close', lambda: None)
    monkeypatch.setattr(t.session, 'alive', lambda: True)
    w.dados.table.selectRow(0)
    w.dados.signup_btn.click()
    wait(app, t)
    assert t.active_pid == pid
    assert t.operation_state == 'AGUARDANDO USUÁRIO'
    class Confirmation:
        def __init__(self, *args): pass
        def exec(self): return True
        def result_value(self): return 'ativa', 'confirmed secret'
    monkeypatch.setattr(module, 'ResultDialog', Confirmation)
    t.result_btn.click()
    assert t.operation_state == 'CONCLUÍDO'
    assert db.get_profile(pid)['status'] == 'ativa'
    assert 'secret' not in db.signup_history(pid)[0]['note']
    t.close_browser()
    wait(app, t)
    assert db.signup_history(pid)[0]['state'] == 'CONCLUÍDO'
    t.result_btn.click()
    assert t.active_pid is None and db.signup_history(pid)[0]['result'] == 'ativa'
    w.close()
