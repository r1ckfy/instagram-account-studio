"""Saved batch plan and model generation for the signup queue."""
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

from . import generator
from .db import Database

BIRTHDATE = generator.MODEL_BIRTHDATE
SETTING = "signup_model_batch"
FINAL_RESULTS = {"ativa", "falhou", "bloqueada"}
SEND_MARKER = "envio_automatico_iniciado"
DRAFT_SOURCE = "central-modelos"


def load(db):
    return json.loads(db.get_setting(SETTING, "null"))


def create(db, total):
    plan = {"source": f"lote-modelos:{uuid4().hex}", "total": total}
    with db.conn:
        db.conn.execute("BEGIN IMMEDIATE")
        current = load(db)
        if current:
            saved = profiles(db, current)
            if len(saved) < current["total"] or any(p["status"] not in FINAL_RESULTS for p in saved):
                raise ValueError("Já existe um lote em andamento. Retome o lote salvo.")
        db.set_setting(SETTING, json.dumps(plan))
    return plan


def profiles(db, plan):
    return sorted((p for p in db.list_profiles() if p["source"] == plan["source"]),
                  key=lambda p: p["id"])


def pending(db, pid):
    for event in db.signup_history(pid):
        if event["result"] in FINAL_RESULTS:
            return False
        if event["result"] == SEND_MARKER:
            return True
    return False


def claim_send(path, pid, operation):
    db = Database(path)
    try:
        with db.conn:
            db.conn.execute("BEGIN IMMEDIATE")
            if pending(db, pid) or db.get_profile(pid)["status"] in FINAL_RESULTS:
                return False
            db.conn.execute(
                """INSERT INTO signup_events
                   (profile_id, operation_id, previous_state, state, result, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))""",
                (pid, operation, "DADOS VALIDADOS", "AGUARDANDO VERIFICAÇÃO", SEND_MARKER,
                 "Tentativa registrada antes do envio. Confirme o resultado antes de repetir."),
            )
            return True
    finally:
        db.close()


def generate(db, plan, email):
    email = email.strip().lower()
    if generator.validate_email(email):
        raise ValueError("Informe um e-mail válido para receber o código.")
    with db.conn:
        db.conn.execute("BEGIN IMMEDIATE")
        if load(db) != plan:
            raise ValueError("O lote ativo mudou. Retome o lote salvo.")
        existing = profiles(db, plan)
        if len(existing) >= plan["total"] or any(p["status"] not in FINAL_RESULTS for p in existing):
            raise ValueError("Já existe uma ficha em andamento neste lote.")
        default_password = db.get_secret(generator.DEFAULT_PASSWORD_SETTING)
        for _ in range(50):
            model = generator.generate({"gender": "feminino", "digits": 3,
                                        "domain": email.rsplit("@", 1)[1]}, birthdate=BIRTHDATE,
                                       password=default_password)
            if not db.username_exists(model["username"]):
                password = model.pop("password")
                model.update(email=email, state=generator.STATES[model["uf"]][0], source=plan["source"],
                             profile_type="Modelo virtual")
                return db.save_profile(model, password)
        raise ValueError("Não foi possível gerar um nome de usuário único. Tente novamente.")


def generate_drafts(path, count):
    db = Database(path)
    try:
        used = {profile["username"] for profile in db.list_profiles()}
        default_password = db.get_secret(generator.DEFAULT_PASSWORD_SETTING)
        entries = []
        for _ in range(count):
            for _ in range(50):
                model = generator.generate(
                    {"gender": "feminino", "digits": 3, "bio_style": "modelo_virtual"},
                    birthdate=BIRTHDATE,
                    password=default_password,
                )
                if model["username"] not in used:
                    break
            else:
                raise ValueError("Não foi possível gerar nomes de usuário únicos. Tente novamente.")
            used.add(model["username"])
            password = model.pop("password")
            model.update(email="", state=generator.STATES[model["uf"]][0], source=DRAFT_SOURCE,
                         profile_type="Modelo virtual")
            entries.append((model, password))
        return db.save_profiles(entries)
    finally:
        db.close()


def export(path: Path, rows):
    blocks = []
    for profile in rows:
        birth = date.fromisoformat(profile["birthdate"]).strftime("%d/%m/%Y")
        bio = "\n".join(f"  {line}" for line in profile["bio"].splitlines())
        blocks.append(
            f"Nome: {profile['full_name']}\nUsuario: {profile['username']}\nNascimento: {birth}\n"
            f"Estado: {profile['state']}\nCidade: {profile['city']}\nBio: |\n{bio}\nEmail: {profile['email']}"
        )
    path.write_text("\n---\n".join(blocks) + "\n", encoding="utf-8")
