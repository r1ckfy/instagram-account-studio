import sqlite3
from datetime import date
from pathlib import Path

import pytest

from app import fichas
from app.db import MIGRATIONS, Database

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 2)

SAMPLE = """Nome: Rafaela Veloso
Usuario: rafavelo
Nascimento: 10/03/2004
Estado: Alagoas
Cidade: Maceió
Bio: |
  🌴 Influenciadora virtual
  Alagoana de coração
  22y
Email:
---
Nome: Lavínia Morelli
Usuario: lavimore
Nascimento: 18/06/2003
Estado: São Paulo
Cidade: Campinas
Bio: |
  ✨ Lifestyle e moda

  Compartilhando meus melhores momentos
  Influenciadora virtual
Email: Lavi@InboxNexo.online
"""


def test_parses_multiple_fichas():
    items = fichas.parse_text(SAMPLE, TODAY)
    assert [f["username"] for f in items] == ["rafavelo", "lavimore"]
    a, b = items
    assert (a["full_name"], a["birthdate"], a["age"], a["state"], a["city"], a["email"]) == \
        ("Rafaela Veloso", "2004-03-10", 22, "Alagoas", "Maceió", "")
    assert b["email"] == "lavi@inboxnexo.online" and b["line"] == 12
    assert not a["errors"] and not b["errors"]


def test_bio_keeps_emojis_and_line_breaks_exactly():
    a, b = fichas.parse_text(SAMPLE, TODAY)
    assert a["bio"] == "🌴 Influenciadora virtual\nAlagoana de coração\n22y"
    assert b["bio"] == "✨ Lifestyle e moda\n\nCompartilhando meus melhores momentos\nInfluenciadora virtual"


def test_example_file_is_valid():
    items = fichas.parse_file(ROOT / "exemplos" / "fichas_exemplo.txt", TODAY)
    assert len(items) == 2 and all(not f["errors"] for f in items)
    assert "Observacoes" not in items[1]["bio"] and items[1]["notes"].startswith("Ficha de exemplo")


def test_unindented_block_lines_and_bio_with_colon():
    text = "Nome: Ana\nUsuario: ana.x\nIdade: 25\nBio: |\nlinha 1\nContato: link na bio\n  recuada\nCidade: Recife\n"
    (f,) = fichas.parse_text(text, TODAY)
    assert f["bio"] == "linha 1\nContato: link na bio\n  recuada"
    assert f["city"] == "Recife" and f["age"] == 25 and f["birthdate"] == ""


def test_accepts_field_aliases_and_crlf():
    text = "Nome completo: Ana Lima\r\nUsuário: @Ana_Lima\r\nData de nascimento: 2000-01-31\r\nUF: PE\r\nE-mail: \r\n"
    (f,) = fichas.parse_text(text, TODAY)
    assert f["username"] == "ana_lima" and f["state"] == "PE" and f["birthdate"] == "2000-01-31"
    assert any("minúsculas" in w for w in f["warnings"])


@pytest.mark.parametrize("block,err", [
    ("Usuario: x1\nIdade: 30", "Nome é obrigatório"),
    ("Nome: A\nIdade: 30", "Usuário é obrigatório"),
    ("Nome: A\nUsuario: a1", "Nascimento ou Idade"),
    ("Nome: A\nUsuario: a1\nNascimento: 31/02/2000", "inválido"),
    ("Nome: A\nUsuario: a1\nNascimento: 01/01/2015", "18 anos"),
    ("Nome: A\nUsuario: a1\nIdade: 16", "18 anos"),
    ("Nome: A\nUsuario: a..b\nIdade: 30", "Usuário"),
    ("Nome: A\nUsuario: a1\nIdade: 30\nEmail: sem-arroba", "E-mail"),
])
def test_required_fields_and_validation(block, err):
    (f,) = fichas.parse_text(block, TODAY)
    assert any(err in e for e in f["errors"]), f["errors"]


def test_warnings_for_unknown_field_long_bio_and_age_mismatch():
    text = "Nome: A\nUsuario: a1\nNascimento: 10/03/2004\nIdade: 30\nInstagram: algo\nBio: " + "x" * 151
    (f,) = fichas.parse_text(text, TODAY)
    assert not f["errors"]
    joined = " ".join(f["warnings"])
    assert "desconhecido" in joined and "151 caracteres" in joined and "não bate" in joined


def test_non_utf8_file_reports_line(tmp_path):
    p = tmp_path / "latin1.txt"
    p.write_bytes("Nome: Ana\nCidade: Maceió\n".encode("latin-1"))
    with pytest.raises(fichas.TxtError, match="linha 2"):
        fichas.parse_file(p)


def test_empty_file_rejected(tmp_path):
    p = tmp_path / "vazio.txt"
    p.write_text("\n---\n\n", encoding="utf-8")
    with pytest.raises(fichas.TxtError):
        fichas.parse_file(p)


def test_duplicates_in_file_and_in_database(db):
    db.save_profile({"full_name": "Já Existe", "username": "lavimore", "email": "x@y.com",
                     "birthdate": "2000-01-01"}, None)
    text = SAMPLE + "---\nNome: Outra\nUsuario: RAFAVELO\nIdade: 30\nEmail: x@y.com\n"
    items = fichas.classify(fichas.parse_text(text, TODAY), db)
    assert [f["result"] for f in items] == ["valido", "duplicado", "duplicado"]
    assert "banco local" in items[1]["duplicate"] and "repetido no arquivo" in items[2]["duplicate"]
    assert any("já associado a @lavimore" in w for w in items[2]["warnings"])


def test_import_saves_all_fields(db):
    items = fichas.classify(fichas.parse_text(SAMPLE, TODAY), db)
    ids, skipped = db.import_fichas(items, "TXT: teste.txt")
    assert len(ids) == 2 and not skipped
    p = db.get_profile(ids[0])
    assert (p["state"], p["city"], p["age"], p["source"], p["status"]) == \
        ("Alagoas", "Maceió", 22, "TXT: teste.txt", "preparado")
    assert p["bio"] == "🌴 Influenciadora virtual\nAlagoana de coração\n22y"
    assert p["email_status"] == "nao_associado"
    assert db.get_profile(ids[1])["email_status"] == "associado"
    assert db.history(ids[0])[0]["note"] == "Importado de TXT: teste.txt"
    _, skipped = db.import_fichas(items, "TXT: de novo.txt")
    assert len(skipped) == 2  # duplicados não entram duas vezes


def test_partial_update_keeps_ficha_fields(db):
    (pid,), _ = db.import_fichas(fichas.parse_text(SAMPLE, TODAY)[:1], "TXT: t.txt")
    # o formulário PERFIL não conhece estado/cidade/idade: não pode apagá-los
    db.save_profile({"id": pid, "full_name": "Rafaela V.", "username": "rafavelo", "email": "",
                     "birthdate": "2004-03-10", "bio": "nova", "profile_type": "Pessoal", "notes": "",
                     "status": "em_cadastro"}, "senha")
    p = db.get_profile(pid)
    assert (p["full_name"], p["state"], p["city"], p["age"]) == ("Rafaela V.", "Alagoas", "Maceió", 22)
    assert db.get_password(pid) == "senha"


def test_email_association_and_statuses(db):
    a = db.save_profile({"full_name": "A", "username": "aaa", "birthdate": "2000-01-01"}, None)
    b = db.save_profile({"full_name": "B", "username": "bbb", "birthdate": "2000-01-01"}, None)
    assert db.get_profile(a)["email_status"] == "nao_associado"
    db.associate_email(a, " AAA@InboxNexo.online ")
    assert db.get_profile(a)["email"] == "aaa@inboxnexo.online"
    assert db.get_profile(a)["email_status"] == "associado"
    assert db.address_owners("aaa@inboxnexo.online", exclude_id=b) == ["aaa"]
    db.set_address_check("aaa@inboxnexo.online", "encaminhamento", "regra ok", "meu@gmail.com")
    assert db.get_profile(a)["email_status"] == "encaminhamento"
    db.set_address_check("aaa@inboxnexo.online", None, "só registro")
    assert db.get_profile(a)["email_status"] == "encaminhamento"
    db.set_address_check("aaa@inboxnexo.online", "testado", "chegou")
    addr = db.get_address("aaa@inboxnexo.online")
    assert (addr["status"], addr["destination"], addr["last_result"]) == ("testado", "meu@gmail.com", "chegou")
    with pytest.raises(ValueError):
        db.set_address_check("aaa@inboxnexo.online", "criado", "x")
    token = db.start_receipt_test("aaa@inboxnexo.online")
    assert token.startswith("IAS-") and db.get_address("aaa@inboxnexo.online")["test_token"] == token
    db.associate_email(a, "")
    assert db.get_profile(a)["email_status"] == "nao_associado"
    assert "aaa@inboxnexo.online" in [x["address"] for x in db.list_addresses()]  # o endereço continua no banco
    kinds = [x["message"] for x in db.list_activity("alteracao")]
    assert any("associado a @aaa" in m for m in kinds) and any("desassociado" in m for m in kinds)


def test_email_status_filter(db):
    a = db.save_profile({"full_name": "A", "username": "aaa", "birthdate": "2000-01-01", "email": "a@x.com"}, None)
    db.save_profile({"full_name": "B", "username": "bbb", "birthdate": "2000-01-01"}, None)
    db.set_address_check("a@x.com", "testado", "ok")
    assert [p["id"] for p in db.list_profiles(email_status="testado")] == [a]
    assert [p["username"] for p in db.list_profiles(email_status="nao_associado")] == ["bbb"]


def test_secrets_are_encrypted_in_settings(db):
    db.set_secret("cf_token", "segredo-cloudflare")
    raw = db.get_setting("cf_token")
    assert raw.startswith("dpapi:") and "segredo" not in raw
    assert db.get_secret("cf_token") == "segredo-cloudflare"
    db.set_secret("cf_token", "")
    assert db.get_secret("cf_token") == ""


def test_safe_migration_from_v1_keeps_data_and_backs_up(tmp_path):
    path = tmp_path / "studio.db"
    conn = sqlite3.connect(path)
    conn.executescript(MIGRATIONS[0])
    conn.execute("INSERT INTO profiles (full_name, username, email, birthdate, created_at, updated_at)"
                 " VALUES ('Antiga', 'antiga', 'Antiga@Ex.com', '2000-01-01', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO imap_accounts (name, email, host, username, created_at, updated_at)"
                 " VALUES ('Gmail', 'g@gmail.com', 'imap.gmail.com', 'g@gmail.com', 'x', 'x')")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    db = Database(path)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    (p,) = db.list_profiles()
    assert (p["username"], p["state"], p["age"], p["email_status"]) == ("antiga", "", None, "associado")
    assert db.get_address("antiga@ex.com") is not None
    assert len(db.list_imap()) == 1
    backups = list((tmp_path / "backups").glob("antes_migracao_v1_*.db"))
    assert len(backups) == 1
    old = sqlite3.connect(backups[0])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 1
    assert old.execute("SELECT username FROM profiles").fetchone()[0] == "antiga"
    old.close()
    db.close()
    Database(path).close()  # já migrado: não cria outro backup
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1
