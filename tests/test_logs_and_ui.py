"""Logs + fluxo principal da interface (Qt offscreen, banco temporário)."""
import pytest

from app.logs import log, setup_logging, success

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def window(qapp, db, tmp_path):
    from app.ui.main_window import MainWindow
    handler = setup_logging(tmp_path / "logs")
    w = MainWindow(db, handler)
    yield w, handler, tmp_path / "logs" / "studio.log"
    w.close()


def test_levels_and_buffer(qapp, tmp_path):
    handler = setup_logging(tmp_path / "logs")
    log.info("um")
    success("dois")
    log.warning("três")
    log.error("quatro")
    assert [r[1] for r in handler.records] == ["INFO", "SUCESSO", "AVISO", "ERRO"]
    text = (tmp_path / "logs" / "studio.log").read_text(encoding="utf-8")
    assert "[SUCESSO] dois" in text and "[ERRO] quatro" in text


def test_main_flow_generate_apply_save(window):
    w, handler, log_file = window
    w.dados.gerador.generate_all()
    assert w.dados.gerador.f_birth.text().startswith("27/01/2007")
    password = w.dados.gerador.current["password"]
    username = w.dados.gerador.current["username"]
    w.dados.gerador.apply()
    assert w.tabs.currentWidget().widget() is w.perfil
    assert w.perfil.username.text() == username
    w.perfil.save()
    profiles = w.db.list_profiles()
    assert len(profiles) == 1 and profiles[0]["username"] == username
    assert profiles[0]["birthdate"] == "2007-01-27"
    assert w.db.get_password(profiles[0]["id"]) == password
    # status inicial nunca é "ativa": só o usuário confirma
    assert profiles[0]["status"] == "preparado"
    # tabela de CONTAS e seletor do NAVEGADOR atualizados pelo sinal
    assert w.contas.table.rowCount() == 1
    assert w.navegador.fields["username"][1].text() == username
    assert w.navegador.fields["password"][1].text() == password
    # nenhuma senha em logs (arquivo ou memória)
    for h in log.handlers:
        h.flush()
    assert password not in log_file.read_text(encoding="utf-8")
    assert all(password not in m for _t, _l, m in handler.records)
    assert any(lv == "SUCESSO" and username in m for _t, lv, m in handler.records)


def test_logs_tab_filter(window):
    w, handler, _ = window
    log.info("mensagem comum")
    log.error("falha específica")
    w.logs.level.setCurrentIndex(w.logs.level.findData("ERRO"))
    text = w.logs.view.toPlainText()
    assert "falha específica" in text and "mensagem comum" not in text
    w.logs.level.setCurrentIndex(0)
    w.logs.search.setText("comum")
    assert "falha" not in w.logs.view.toPlainText()


def test_duplicate_username_blocked_in_form(window, monkeypatch):
    w, *_ = window
    warnings = []
    monkeypatch.setattr("app.ui.tab_perfil.warn", lambda *a: warnings.append(a))
    for _ in range(2):
        w.perfil.clear()
        w.perfil.full_name.setText("Antonella Virelli")
        w.perfil.username.setText("antovire")
        w.perfil.email.setText("a@b.com")
        w.perfil.save()
    assert len(w.db.list_profiles()) == 1
    assert warnings and "antovire" in warnings[-1][2]


# ------------------------------------------------------------ nova aba DADOS
FICHAS_TXT = """Nome: Rafaela Veloso
Usuario: rafavelo
Nascimento: 10/03/2004
Estado: Alagoas
Cidade: Maceió
Bio: |
  🌴 Influenciadora virtual
  Alagoana de coração
Email:
---
Nome: Só Idade
Usuario: soidade
Idade: 25
---
Nome: Inválida
Usuario: inv..alida
Idade: 30
"""


def test_all_tabs_still_present(window):
    w, *_ = window
    titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]
    for name in ("DADOS", "PERFIL", "NAVEGADOR", "IMAP", "PROXY", "CONTAS", "LOGS", "CONFIGURAÇÕES"):
        assert any(name in t for t in titles), name
    assert w.config.email is not None and w.dados.gerador is not None


def test_import_txt_select_and_apply_to_profile(window, tmp_path, monkeypatch):
    w, handler, _ = window
    path = tmp_path / "fichas.txt"
    path.write_text(FICHAS_TXT, encoding="utf-8")
    report = w.dados.import_path(path, preview=False)
    assert report == {"importadas": 2, "ignoradas": 0, "invalidas": 1}
    assert w.dados.table.rowCount() == 2
    assert w.contas.table.rowCount() == 2  # outras abas atualizadas pelo mesmo sinal
    msgs = [w.dados.activity.item(i).text() for i in range(w.dados.activity.count())]
    assert any("IMPORTAÇÃO" in m and "2 importada" in m for m in msgs)
    assert any("VALIDAÇÃO" in m and "inv..alida" in m for m in msgs)

    row = next(r for r in range(2) if w.dados.table.item(r, 2).text() == "@rafavelo")
    w.dados.table.selectRow(row)
    assert w.dados.bio.toPlainText() == "🌴 Influenciadora virtual\nAlagoana de coração"
    assert w.dados.v["loc"].text() == "Maceió, Alagoas"
    assert w.dados.v["email_st"].text().startswith("NÃO ASSOCIADO")

    w.dados.apply()
    assert w.tabs.currentWidget().widget() is w.perfil
    assert w.perfil.username.text() == "rafavelo"
    monkeypatch.setattr("app.ui.tab_perfil.confirm", lambda *a: True)  # aceita salvar sem e-mail
    w.perfil.password.setText("Senha!Forte#2026")
    w.perfil.save()
    p = w.db.get_profile(w.perfil.pid)
    assert (p["state"], p["city"]) == ("Alagoas", "Maceió")  # PERFIL não apaga dados da ficha
    assert w.db.get_password(p["id"]) == "Senha!Forte#2026"

    # ficha só com idade: aplicar avisa e sugere data compatível
    warned = []
    monkeypatch.setattr("app.ui.tab_dados.warn", lambda *a: warned.append(a))
    row = next(r for r in range(2) if w.dados.table.item(r, 2).text() == "@soidade")
    w.dados.table.selectRow(row)
    w.dados.apply()
    assert warned and "só a idade" in warned[0][2]
    from datetime import date
    assert date.today().year - w.perfil.birth.date().year() == 25


def test_import_preview_defaults(window, tmp_path):
    from app import fichas
    from app.ui.dialogs import ImportPreviewDialog
    w, *_ = window
    w.db.save_profile({"full_name": "X", "username": "soidade", "birthdate": "2000-01-01"}, None)
    items = fichas.classify(fichas.parse_text(FICHAS_TXT), w.db)
    dlg = ImportPreviewDialog(w, items, "fichas.txt")
    assert [f["username"] for f in dlg.selected()] == ["rafavelo"]  # duplicada e inválida ficam de fora
    dlg._set_all(False)
    assert dlg.selected() == []


def test_associate_email_dialog(window, monkeypatch):
    from app.ui.dialogs import AssociateEmailDialog
    w, *_ = window
    a = w.db.save_profile({"full_name": "A", "username": "aaa", "birthdate": "2000-01-01",
                           "email": "compartilhado@inboxnexo.online"}, None)
    b = w.db.save_profile({"full_name": "B", "username": "bbb", "birthdate": "2000-01-01"}, None)
    dlg = AssociateEmailDialog(w, w.db, w.db.get_profile(b))
    assert dlg.address.text() == "bbb@inboxnexo.online"  # sugestão com o domínio padrão
    asked = []
    monkeypatch.setattr("app.ui.dialogs.confirm", lambda *args: asked.append(args) or False)
    dlg.address.setText("compartilhado@inboxnexo.online")
    dlg._associate()
    assert asked and "@aaa" in asked[0][2]          # avisa antes de repetir um endereço
    assert w.db.get_profile(b)["email"] == ""      # e respeita o "não"
    dlg.address.setText("bbb@inboxnexo.online")
    dlg._associate()
    assert w.db.get_profile(b)["email"] == "bbb@inboxnexo.online"
    assert w.db.get_profile(a)["email"] == "compartilhado@inboxnexo.online"


def test_import_addresses_from_csv(window, tmp_path):
    w, *_ = window
    path = tmp_path / "enderecos.csv"
    path.write_text("email;obs\nrafa@inboxnexo.online;x\nruim;y\nrafa@inboxnexo.online;z\n", encoding="utf-8")
    assert w.config.email.import_addresses(path, quiet=True) == (1, 0, 1)
    assert [a["address"] for a in w.db.list_addresses()] == ["rafa@inboxnexo.online"]


def test_email_settings_store_credentials_encrypted(window):
    w, *_ = window
    s = w.config.email
    s.api_base.setText("https://painel.inboxnexo.online/api")
    s.credential.setText("token-secreto")
    s.save_panel()
    assert w.db.get_setting("panel_api_base") == "https://painel.inboxnexo.online/api"
    assert "token-secreto" not in w.db.get_setting("panel_credential")
    assert w.db.get_secret("panel_credential") == "token-secreto"
    assert s.credential.text() == ""  # campo limpo após salvar
