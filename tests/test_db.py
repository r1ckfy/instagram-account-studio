import csv
import io
import json
import sqlite3

import pytest

from app.db import MIGRATIONS, Database, DuplicateError, export_profiles


def test_save_and_load_profile(db, profile):
    pid = db.save_profile(profile, "S3nha!Forte#2026")
    p = db.get_profile(pid)
    assert p["username"] == "antovire" and p["status"] == "preparado"
    assert db.get_password(pid) == "S3nha!Forte#2026"


def test_password_never_stored_in_plain_text(db, profile, tmp_path):
    db.save_profile(profile, "S3nha!Forte#2026")
    db.save_imap({"name": "x", "email": "a@b.com", "host": "imap.b.com", "port": 993,
                  "security": "ssl", "username": "a@b.com"}, "ImapSecret#123")
    db.conn.execute("PRAGMA wal_checkpoint(FULL)")
    raw = db.path.read_bytes()
    assert b"S3nha!Forte#2026" not in raw and b"ImapSecret#123" not in raw
    backup = db.backup_to(tmp_path / "bk.db")
    assert b"S3nha!Forte#2026" not in backup.read_bytes()


def test_duplicate_username_is_case_insensitive(db, profile):
    db.save_profile(profile, "x")
    with pytest.raises(DuplicateError):
        db.save_profile({**profile, "username": "AntoVire"}, "y")
    assert db.username_exists("ANTOVIRE")


def test_update_keeps_password_when_none(db, profile):
    pid = db.save_profile(profile, "original")
    db.save_profile({**profile, "id": pid, "bio": "nova bio"}, None)
    assert db.get_profile(pid)["bio"] == "nova bio"
    assert db.get_password(pid) == "original"
    db.save_profile({**profile, "id": pid}, "")
    assert db.get_password(pid) == ""
    assert not db.list_profiles()[0]["has_password"]


def test_status_history_and_stats(db, profile):
    pid = db.save_profile(profile, "x")
    db.set_status(pid, "em_cadastro", "aberto")
    db.set_status(pid, "ativa", "confirmei")
    hist = db.history(pid)
    assert [h["new_status"] for h in hist] == ["ativa", "em_cadastro", "preparado"]
    assert hist[0]["old_status"] == "em_cadastro"
    db.save_profile({**profile, "username": "outra"}, "x")
    s = db.stats()
    assert s["total"] == 2 and s["ativas"] == 1 and s["preparados"] == 1
    assert "@antovire" in s["ultima_ativa"]


def test_invalid_status_rejected(db, profile):
    with pytest.raises(ValueError):
        db.save_profile({**profile, "status": "criada_automaticamente"}, "x")
    pid = db.save_profile(profile, "x")
    with pytest.raises(ValueError):
        db.set_status(pid, "qualquer")


def test_search_and_filter(db, profile):
    db.save_profile(profile, "x")
    pid = db.save_profile({**profile, "username": "bia.salles", "full_name": "Bia Salles"}, "x")
    db.set_status(pid, "ativa")
    assert [p["username"] for p in db.list_profiles("salles")] == ["bia.salles"]
    assert [p["username"] for p in db.list_profiles(status="preparado")] == ["antovire"]


def test_delete_cascades_history(db, profile):
    pid = db.save_profile(profile, "x")
    db.delete_profile(pid)
    assert db.conn.execute("SELECT COUNT(*) FROM status_history").fetchone()[0] == 0


def test_backup_and_restore_roundtrip(db, profile, tmp_path):
    db.save_profile(profile, "segredo")
    bk = db.backup_to(tmp_path / "backups" / "b.db")
    db.save_profile({**profile, "username": "depois"}, "x")
    assert len(db.list_profiles()) == 2
    db.restore_from(bk)
    rows = db.list_profiles()
    assert [p["username"] for p in rows] == ["antovire"]
    assert db.get_password(rows[0]["id"]) == "segredo"


def test_restore_rejects_foreign_file(db, tmp_path):
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE x (a)").connection.commit()
    with pytest.raises(ValueError):
        db.restore_from(other)
    with pytest.raises(FileNotFoundError):
        db.restore_from(tmp_path / "missing.db")


def test_reopen_keeps_data_and_schema_version(tmp_path, profile):
    d = Database(tmp_path / "x.db")
    d.save_profile(profile, "x")
    d.close()
    d2 = Database(tmp_path / "x.db")
    assert d2.conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert len(d2.list_profiles()) == 1
    assert d2.integrity_check() == "ok"
    d2.close()


def test_imap_accounts(db):
    cfg = {"name": "Hostinger", "email": "a@meudominio.com", "host": "imap.hostinger.com",
           "port": 993, "security": "ssl", "username": "a@meudominio.com"}
    aid = db.save_imap(cfg, "pw1")
    assert db.get_imap_password(aid) == "pw1"
    db.save_imap({**cfg, "id": aid, "port": 143}, None)
    assert db.get_imap_password(aid) == "pw1" and db.list_imap()[0]["port"] == 143
    with pytest.raises(DuplicateError):
        db.save_imap(cfg, "pw2")
    db.delete_imap(aid)
    assert db.list_imap() == []


def test_generated_history_has_no_password(db):
    db.add_generated({"full_name": "A B", "username": "ab", "email": "a@b.com",
                      "birthdate": "2000-01-01", "bio": "x", "password": "NAO-GUARDAR"})
    cols = db.list_generated()[0].keys()
    assert "password" not in cols


@pytest.mark.parametrize("ext", ["csv", "json", "txt"])
def test_export_without_passwords(db, profile, tmp_path, ext):
    db.save_profile(profile, "S3nha!Forte#2026")
    pid = db.save_profile({**profile, "username": "bia.salles", "bio": "linha 1\nlinha 2; com ponto e vírgula"},
                          "Outra#Senha1")
    db.set_status(pid, "ativa")
    out = tmp_path / f"contas.{ext}"
    assert export_profiles(db.list_profiles(), out) == 2
    text = out.read_text(encoding="utf-8-sig")
    assert "S3nha!Forte#2026" not in text and "Outra#Senha1" not in text
    assert "password" not in text and "has_password" not in text
    if ext == "json":
        data = {d["username"]: d for d in json.loads(text)}
        assert data["bia.salles"]["status_label"] == "Ativa (confirmada)"
    elif ext == "csv":
        rows = {r["username"]: r for r in csv.DictReader(io.StringIO(text), delimiter=";")}
        assert rows["bia.salles"]["bio"] == "linha 1\nlinha 2; com ponto e vírgula"
        assert rows["antovire"]["full_name"] == "Antonella Virelli"
    else:
        assert len(text.splitlines()) == 2 and "@antovire | Antonella Virelli" in text


def test_export_rejects_unknown_format(db, profile, tmp_path):
    db.save_profile(profile, "x")
    with pytest.raises(ValueError):
        export_profiles(db.list_profiles(), tmp_path / "contas.xlsx")


def test_settings(db):
    assert db.get_setting("browser", "padrao") == "padrao"
    db.set_setting("browser", "edge")
    db.set_setting("browser", "chrome")
    assert db.get_setting("browser") == "chrome"
