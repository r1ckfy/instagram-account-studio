import pytest

from app import fichas, signup_batch


def test_batch_generation_export_and_attempt_recovery(db, tmp_path):
    plan = signup_batch.create(db, 2)
    pid = signup_batch.generate(db, plan, 'first@example.org')
    first = db.get_profile(pid)
    assert first['birthdate'] == '2007-01-27'
    assert first['email'] == 'first@example.org'
    assert db.get_password(pid)
    assert signup_batch.claim_send(db.path, pid, 'attempt-1')
    assert signup_batch.pending(db, pid)
    assert not signup_batch.claim_send(db.path, pid, 'attempt-2')
    assert signup_batch.load(db) == plan
    assert [p['id'] for p in signup_batch.profiles(db, plan)] == [pid]

    db.set_status(pid, 'ativa', 'Confirmado no teste')
    db.signup_event(pid, 'attempt-1', 'AGUARDANDO VERIFICAÇÃO', 'CONCLUÍDO', 'ativa')
    second = signup_batch.generate(db, plan, 'second@example.org')
    assert db.get_profile(second)['username'] != first['username']
    path = tmp_path / 'modelos.txt'
    signup_batch.export(path, signup_batch.profiles(db, plan))
    records = fichas.parse_file(path)
    assert len(records) == 2 and all(not row['errors'] for row in records)
    assert all(row['birthdate'] == '2007-01-27' and len(row['bio']) <= 150 for row in records)
    assert db.get_password(pid) not in path.read_text(encoding='utf-8')


def test_batch_ui_prompts_each_email_and_does_not_resubmit(db, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QInputDialog
    from app.logs import setup_logging
    from app.ui import tab_central
    from app.ui.main_window import MainWindow
    from test_signup import wait

    app = QApplication.instance() or QApplication([])
    window = MainWindow(db, setup_logging(tmp_path / 'logs'))
    tab = window.central
    count_calls = []
    prompts = []
    sends = []
    def count(*args):
        count_calls.append(args[3])
        return 2, True
    def email(_parent, title, _message):
        assert len(signup_batch.profiles(db, tab.batch_plan)) == len(prompts)
        prompts.append(title)
        return f'ficha{len(prompts)}@example.org', True
    def send(data, claim, cancelled):
        assert not cancelled() and claim()
        sends.append(data['email'])
        return 'sent', 'Enviado no simulador.'
    monkeypatch.setattr(QInputDialog, 'getInt', count)
    monkeypatch.setattr(QInputDialog, 'getText', email)
    monkeypatch.setattr(tab.session, 'open', lambda _choice: None)
    monkeypatch.setattr(tab.session, 'fill', lambda _data: None)
    monkeypatch.setattr(tab.session, 'submit', send)
    monkeypatch.setattr(tab.session, 'close', lambda: None)
    monkeypatch.setattr(tab.session, 'alive', lambda: True)
    monkeypatch.setattr(tab.session, 'feedback', lambda _data: '')

    tab.batch_btn.click()
    wait(app, tab)
    assert count_calls == [10]
    assert prompts == ['Ficha 1 de 2']
    assert sends == ['ficha1@example.org']
    assert tab.operation_state == 'AGUARDANDO VERIFICAÇÃO'
    pid = tab.active_pid
    tab.pause_batch()
    tab.close_browser()
    wait(app, tab)
    tab.start_batch()
    assert tab.active_pid is None and tab.pid() == pid
    assert sends == ['ficha1@example.org']

    class Confirmed:
        def __init__(self, *_args): pass
        def exec(self): return True
        def result_value(self): return 'ativa', ''
    monkeypatch.setattr(tab_central, 'ResultDialog', Confirmed)
    tab.result()
    app.processEvents()
    wait(app, tab)
    assert prompts == ['Ficha 1 de 2', 'Ficha 2 de 2']
    assert sends == ['ficha1@example.org', 'ficha2@example.org']
    assert db.get_profile(pid)['status'] == 'ativa'
    assert db.get_profile(tab.active_pid)['status'] == 'preparado'
    window.close()


def test_generate_and_edit_drafts_from_central(db, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication
    from app.logs import setup_logging
    from app.ui.dialogs import FichaDialog
    from app.ui import tab_central
    from app.ui.main_window import MainWindow
    from test_signup import wait

    app = QApplication.instance() or QApplication([])
    window = MainWindow(db, setup_logging(tmp_path / 'draft-logs'))
    tab = window.central
    default_password = 'SenhaDeTeste@39'
    db.set_secret(signup_batch.generator.DEFAULT_PASSWORD_SETTING, default_password)
    monkeypatch.setattr(tab.session, 'open', lambda *_args: pytest.fail('Draft generation opened the browser'))
    tab.draft_count.setValue(3)
    tab.generate_btn.click()
    wait(app, tab)
    rows = db.list_profiles()
    assert len(rows) == 3
    assert len({p['username'] for p in rows}) == 3
    assert all(p['birthdate'] == '2007-01-27' and not p['email'] for p in rows)
    assert all(db.get_password(p['id']) == default_password for p in rows)
    assert all('virtual' not in p['bio'].casefold() and ' por ia' not in p['bio'].casefold() for p in rows)
    assert tab.table.rowCount() == 3 and tab.edit_btn.isEnabled()

    pid = tab.pid()
    original_password = db.get_password(pid)
    def save_edit():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, FichaDialog)
        assert dialog.birth.isReadOnly()
        dialog.full_name.setText('Nome Revisado')
        dialog.email.setText('revisado@example.org')
        dialog._save()
    QTimer.singleShot(0, save_edit)
    tab.edit_btn.click()

    edited = db.get_profile(pid)
    assert edited['full_name'] == 'Nome Revisado'
    assert edited['email'] == 'revisado@example.org'
    assert edited['birthdate'] == '2007-01-27'
    assert db.get_password(pid) == original_password
    assert tab.fields['email'].text() == 'revisado@example.org'
    chosen = tab.table.item(0, 0).data(Qt.UserRole)
    tab.table.item(0, 0).setCheckState(Qt.Checked)
    monkeypatch.setattr(tab_central, 'confirm', lambda *_args: False)
    tab.delete_btn.click()
    assert len(db.list_profiles()) == 3
    monkeypatch.setattr(tab_central, 'confirm', lambda *_args: True)
    tab.delete_btn.click()
    assert {p['id'] for p in db.list_profiles()} == {p['id'] for p in rows} - {chosen}
    window.close()
