"""Persistência SQLite (stdlib). Segredos são gravados cifrados via DPAPI."""
import base64
import csv
import json
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

from . import security

STATUSES = {
    "preparado": "Preparado",
    "em_cadastro": "Em cadastro",
    "verificacao": "Verificação pendente",
    "ativa": "Ativa (confirmada)",
    "bloqueada": "Bloqueada",
    "desativada": "Desativada",
    "falhou": "Falhou",
}

# Situação do e-mail de uma personagem. Associado ≠ regra configurada ≠ recebimento comprovado.
EMAIL_STATUSES = {
    "nao_associado": "NÃO ASSOCIADO",
    "associado": "ASSOCIADO",
    "pendente": "CONFIGURAÇÃO PENDENTE",
    "encaminhamento": "ENCAMINHAMENTO CONFIGURADO",
    "testado": "RECEBIMENTO TESTADO",
    "erro": "ERRO DE ENTREGA",
}

ACTIVITY_KINDS = {"importacao": "Importação", "validacao": "Validação",
                  "integracao": "Integração", "alteracao": "Alteração"}

PROFILE_FIELDS = ("full_name", "username", "email", "birthdate", "bio",
                  "profile_type", "notes", "status", "state", "city", "source")

_PROFILE_SELECT = (
    "SELECT p.id, p.full_name, p.username, p.email, p.birthdate, p.bio, p.profile_type, p.notes,"
    " p.status, p.state, p.city, p.source, p.age, p.created_at, p.updated_at,"
    " p.password_enc IS NOT NULL AND length(p.password_enc) > 0 AS has_password,"
    " CASE WHEN p.email = '' THEN 'nao_associado'"
    "      ELSE COALESCE(NULLIF(ea.status, ''), 'associado') END AS email_status"
    " FROM profiles p LEFT JOIN email_addresses ea ON ea.address = p.email COLLATE NOCASE")

# Cada item é uma migração; a posição + 1 vira o PRAGMA user_version.
MIGRATIONS = [
    """
    CREATE TABLE profiles (
        id INTEGER PRIMARY KEY,
        full_name TEXT NOT NULL,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        email TEXT NOT NULL DEFAULT '',
        password_enc BLOB,
        birthdate TEXT NOT NULL DEFAULT '',
        bio TEXT NOT NULL DEFAULT '',
        profile_type TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'preparado',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE status_history (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        old_status TEXT,
        new_status TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        changed_at TEXT NOT NULL
    );
    CREATE TABLE generated (
        id INTEGER PRIMARY KEY,
        full_name TEXT, username TEXT, email TEXT, birthdate TEXT, bio TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE imap_accounts (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL,
        host TEXT NOT NULL,
        port INTEGER NOT NULL DEFAULT 993,
        security TEXT NOT NULL DEFAULT 'ssl',
        username TEXT NOT NULL,
        password_enc BLOB,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # v2: fichas importadas por TXT + endereços de e-mail + atividades (só adiciona, nunca apaga)
    """
    ALTER TABLE profiles ADD COLUMN state TEXT NOT NULL DEFAULT '';
    ALTER TABLE profiles ADD COLUMN city TEXT NOT NULL DEFAULT '';
    ALTER TABLE profiles ADD COLUMN age INTEGER;
    ALTER TABLE profiles ADD COLUMN source TEXT NOT NULL DEFAULT '';
    CREATE TABLE email_addresses (
        id INTEGER PRIMARY KEY,
        address TEXT NOT NULL UNIQUE COLLATE NOCASE,
        status TEXT NOT NULL DEFAULT '',
        destination TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'manual',
        last_result TEXT NOT NULL DEFAULT '',
        checked_at TEXT,
        test_token TEXT,
        test_started_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE activity (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    INSERT OR IGNORE INTO email_addresses (address, source, created_at, updated_at)
        SELECT DISTINCT lower(email), 'perfil', created_at, created_at FROM profiles WHERE email <> '';
    """,
    # v3: diagnóstico de proxies (cadastro + histórico de testes). Sem vínculo com perfis.
    """
    CREATE TABLE proxies (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        protocol TEXT NOT NULL,
        host TEXT NOT NULL,
        port INTEGER NOT NULL,
        username TEXT NOT NULL DEFAULT '',
        password_enc BLOB,
        service TEXT NOT NULL DEFAULT 'fixo',
        notes TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'nao_testado',
        last_ip TEXT NOT NULL DEFAULT '',
        last_geo TEXT NOT NULL DEFAULT '',
        last_latency_ms INTEGER,
        auth_status TEXT NOT NULL DEFAULT '',
        checked_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE proxy_tests (
        id INTEGER PRIMARY KEY,
        proxy_id INTEGER NOT NULL REFERENCES proxies(id) ON DELETE CASCADE,
        status TEXT NOT NULL,
        ip TEXT NOT NULL DEFAULT '',
        geo TEXT NOT NULL DEFAULT '',
        latency_ms INTEGER,
        auth_status TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    """,
    # Additive migration: existing profiles, IMAP and proxies remain unchanged.
    """
    CREATE TABLE signup_events (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        operation_id TEXT NOT NULL,
        previous_state TEXT NOT NULL,
        state TEXT NOT NULL,
        result TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX signup_events_profile ON signup_events(profile_id, id);
    """,
    # Remove the exact phrases emitted by the old bio templates.
    "\n".join("""
    UPDATE {table}
    SET bio = trim(replace(replace(replace(replace(bio,
        char(10) || 'personagem virtual criada com IA 🤖' || char(10), char(10)),
        'modelo virtual 🤖 | ', ''), ' (no mundo digital)', ''),
        '🤖 influencer virtual • conteúdo gerado por IA' || char(10), ''), char(10))
    WHERE instr(bio, char(10) || 'personagem virtual criada com IA 🤖' || char(10))
       OR instr(bio, 'modelo virtual 🤖 | ')
       OR instr(bio, '🤖 influencer virtual • conteúdo gerado por IA' || char(10));
    """.format(table=table) for table in ("profiles", "generated")),
]


def now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _enc(password: str | None) -> bytes | None:
    return security.encrypt(password) if password else None


class DuplicateError(ValueError):
    pass


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = self._open(self.path)
        self.migrate()

    @staticmethod
    def _open(path) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # resiste a encerramento inesperado
        return conn

    def migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if 0 < version < len(MIGRATIONS):
            # Banco antigo: cópia de segurança antes de qualquer alteração de esquema.
            self.backup_to(self.path.parent / "backups" /
                           f"antes_migracao_v{version}_{datetime.now():%Y%m%d_%H%M%S}.db")
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            self.conn.executescript(f"BEGIN;{script};PRAGMA user_version = {i};COMMIT;")

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------ perfis
    def username_exists(self, username: str, exclude_id: int | None = None) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM profiles WHERE username = ? AND id IS NOT ?",
            (username, exclude_id)).fetchone()
        return row is not None

    def save_profile(self, data: dict, password: str | None = None) -> int:
        with self.conn:
            return self._save_profile(data, password)

    def save_profiles(self, entries: list[tuple[dict, str]]) -> list[int]:
        """Persist generated profiles as a single transaction."""
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            return [self._save_profile(data, password) for data, password in entries]

    def _save_profile(self, data: dict, password: str | None = None) -> int:
        """Insere (sem 'id') ou atualiza. `password=None` mantém a senha atual."""
        pid = data.get("id")
        # Inserção grava todos os campos; atualização só os que vieram em `data`
        # (assim o formulário PERFIL não apaga estado/cidade/idade da ficha importada).
        values = {k: str(data.get(k) or "").strip() for k in PROFILE_FIELDS if pid is None or k in data}
        if "email" in values:
            values["email"] = values["email"].lower()
        if "status" in values:
            values["status"] = values["status"] or "preparado"
            if values["status"] not in STATUSES:
                raise ValueError(f"Status desconhecido: {values['status']}")
        if "age" in data:
            values["age"] = int(data["age"]) if data["age"] not in (None, "") else None
        if "username" in values and self.username_exists(values["username"], pid):
            raise DuplicateError(f"O usuário @{values['username']} já existe no banco local.")
        ts = now()
        if pid is None:
            cols = list(values)
            cur = self.conn.execute(
                f"INSERT INTO profiles ({', '.join(cols)}, password_enc, created_at, updated_at)"
                f" VALUES ({', '.join('?' * len(cols))}, ?, ?, ?)",
                (*values.values(), _enc(password), ts, ts))
            pid = cur.lastrowid
            self._history(pid, None, values["status"], data.get("history_note") or "Registro criado")
        else:
            old = self.conn.execute("SELECT status FROM profiles WHERE id = ?", (pid,)).fetchone()
            if old is None:
                raise KeyError(f"Perfil {pid} não encontrado.")
            sets = ", ".join(f"{k} = ?" for k in values) + ", updated_at = ?"
            params = [*values.values(), ts]
            if password is not None:
                sets += ", password_enc = ?"
                params.append(_enc(password))
            self.conn.execute(f"UPDATE profiles SET {sets} WHERE id = ?", (*params, pid))
            if values.get("status", old["status"]) != old["status"]:
                self._history(pid, old["status"], values["status"], "Alterado no formulário")
        if values.get("email"):
            self._ensure_address(values["email"], "perfil")
        return pid

    def _history(self, pid, old, new, note):
        self.conn.execute(
            "INSERT INTO status_history (profile_id, old_status, new_status, note, changed_at)"
            " VALUES (?, ?, ?, ?, ?)", (pid, old, new, note, now()))

    def set_status(self, pid: int, status: str, note: str = ""):
        if status not in STATUSES:
            raise ValueError(f"Status desconhecido: {status}")
        old = self.get_profile(pid)["status"]
        with self.conn:
            self.conn.execute("UPDATE profiles SET status = ?, updated_at = ? WHERE id = ?",
                              (status, now(), pid))
            self._history(pid, old, status, note)

    def get_profile(self, pid: int) -> dict:
        row = self.conn.execute(_PROFILE_SELECT + " WHERE p.id = ?", (pid,)).fetchone()
        if row is None:
            raise KeyError(f"Perfil {pid} não encontrado.")
        return dict(row)

    def get_password(self, pid: int) -> str:
        row = self.conn.execute("SELECT password_enc FROM profiles WHERE id = ?", (pid,)).fetchone()
        return security.decrypt(row["password_enc"]) if row else ""

    def list_profiles(self, search: str = "", status: str | None = None,
                      email_status: str | None = None) -> list[dict]:
        sql = _PROFILE_SELECT + " WHERE (p.full_name LIKE ? OR p.username LIKE ? OR p.email LIKE ?)"
        like = f"%{search.strip()}%"
        params = [like, like, like]
        if status:
            sql += " AND p.status = ?"
            params.append(status)
        rows = [dict(r) for r in self.conn.execute(sql + " ORDER BY p.created_at DESC, p.id DESC", params)]
        return [r for r in rows if r["email_status"] == email_status] if email_status else rows

    def last_profile(self) -> dict | None:
        row = self.conn.execute("SELECT id FROM profiles ORDER BY updated_at DESC, id DESC LIMIT 1").fetchone()
        return self.get_profile(row["id"]) if row else None

    def delete_profile(self, pid: int):
        self.delete_profiles([pid])

    def delete_profiles(self, ids: list[int]):
        with self.conn:
            self.conn.executemany("DELETE FROM profiles WHERE id = ?", ((pid,) for pid in ids))

    def history(self, pid: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM status_history WHERE profile_id = ? ORDER BY id DESC", (pid,))]

    def stats(self) -> dict:
        counts = dict(self.conn.execute("SELECT status, COUNT(*) FROM profiles GROUP BY status").fetchall())
        last = self.conn.execute(
            "SELECT p.username, h.changed_at FROM status_history h JOIN profiles p ON p.id = h.profile_id"
            " WHERE h.new_status = 'ativa' ORDER BY h.id DESC LIMIT 1").fetchone()
        return {
            "total": sum(counts.values()),
            "ativas": counts.get("ativa", 0),
            "pendentes": sum(counts.get(s, 0) for s in ("preparado", "em_cadastro", "verificacao")),
            "falhas": counts.get("falhou", 0) + counts.get("bloqueada", 0),
            "preparados": counts.get("preparado", 0),
            "ultima_ativa": f"@{last['username']} em {last['changed_at']}" if last else "—",
        }

    # ------------------------------------------------------------ fichas TXT
    def import_fichas(self, fichas: list[dict], source: str) -> tuple[list[int], list[str]]:
        """Grava fichas já validadas como perfis 'preparado'. Retorna (ids, motivos dos ignorados)."""
        ids, skipped = [], []
        for f in fichas:
            try:
                ids.append(self.save_profile({
                    "full_name": f["full_name"], "username": f["username"], "email": f.get("email", ""),
                    "birthdate": f.get("birthdate", ""), "age": f.get("age"), "bio": f.get("bio", ""),
                    "state": f.get("state", ""), "city": f.get("city", ""), "notes": f.get("notes", ""),
                    "profile_type": "Modelo virtual", "status": "preparado", "source": source,
                    "history_note": f"Importado de {source}"}))
            except DuplicateError as e:
                skipped.append(str(e))
        return ids, skipped

    # ----------------------------------------------------- endereços de e-mail
    def _ensure_address(self, address: str, source: str) -> bool:
        """Cadastra o endereço no banco local se ainda não existir. True = novo."""
        ts = now()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO email_addresses (address, source, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)", (address.strip().lower(), source, ts, ts))
        return cur.rowcount == 1

    def add_addresses(self, addresses: list[str], source: str) -> tuple[int, int]:
        """Retorna (novos, já existentes)."""
        with self.conn:
            new = sum(self._ensure_address(a, source) for a in addresses)
        return new, len(addresses) - new

    def list_addresses(self, search: str = "") -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT ea.*, GROUP_CONCAT('@' || p.username, ', ') AS owners"
            " FROM email_addresses ea LEFT JOIN profiles p ON p.email = ea.address COLLATE NOCASE"
            " WHERE ea.address LIKE ? GROUP BY ea.id ORDER BY ea.address", (f"%{search.strip()}%",))]

    def get_address(self, address: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM email_addresses WHERE address = ?",
                                (address.strip().lower(),)).fetchone()
        return dict(row) if row else None

    def address_owners(self, address: str, exclude_id: int | None = None) -> list[str]:
        return [r["username"] for r in self.conn.execute(
            "SELECT username FROM profiles WHERE email = ? COLLATE NOCASE AND id IS NOT ?",
            (address.strip(), exclude_id))]

    def associate_email(self, pid: int, address: str):
        """Associa (ou, com address='', desassocia) um endereço à personagem."""
        p = self.get_profile(pid)
        address = address.strip().lower()
        with self.conn:
            self.conn.execute("UPDATE profiles SET email = ?, updated_at = ? WHERE id = ?",
                              (address, now(), pid))
            if address:
                self._ensure_address(address, "associacao")
            self._activity("alteracao", f"E-mail {address} associado a @{p['username']}" if address
                           else f"E-mail {p['email']} desassociado de @{p['username']}")

    def set_address_check(self, address: str, status: str | None, result: str,
                          destination: str | None = None):
        """Grava o resultado de uma verificação. status=None mantém o atual; 'associado' zera."""
        if status is not None and status not in EMAIL_STATUSES:
            raise ValueError(f"Status de e-mail desconhecido: {status}")
        stored = None if status is None else ("" if status in ("associado", "nao_associado") else status)
        with self.conn:
            self._ensure_address(address, "verificacao")
            self.conn.execute(
                "UPDATE email_addresses SET status = COALESCE(?, status), last_result = ?,"
                " destination = COALESCE(?, destination), checked_at = ?, updated_at = ?"
                " WHERE address = ?",
                (stored, result, destination, now(), now(), address.strip().lower()))

    def start_receipt_test(self, address: str) -> str:
        token = "IAS-" + secrets.token_hex(4).upper()
        with self.conn:
            self._ensure_address(address, "verificacao")
            self.conn.execute("UPDATE email_addresses SET test_token = ?, test_started_at = ?,"
                              " updated_at = ? WHERE address = ?",
                              (token, now(), now(), address.strip().lower()))
        return token

    # ------------------------------------------------------------ atividades
    def _activity(self, kind: str, message: str):
        self.conn.execute("INSERT INTO activity (kind, message, created_at) VALUES (?, ?, ?)",
                          (kind, message, now()))

    def add_activity(self, kind: str, message: str):
        if kind not in ACTIVITY_KINDS:
            raise ValueError(f"Tipo de atividade desconhecido: {kind}")
        with self.conn:
            self._activity(kind, message)

    def list_activity(self, kind: str | None = None, limit: int = 300) -> list[dict]:
        sql, params = "SELECT * FROM activity", []
        if kind:
            sql, params = sql + " WHERE kind = ?", [kind]
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, limit))]

    # ------------------------------------------------------ histórico gerador
    def add_generated(self, g: dict):
        with self.conn:
            self.conn.execute(
                "INSERT INTO generated (full_name, username, email, birthdate, bio, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (g["full_name"], g["username"], g["email"], g["birthdate"], g["bio"], now()))
            # ponytail: mantém só os 200 mais recentes; aumente se precisar de mais histórico
            self.conn.execute("DELETE FROM generated WHERE id NOT IN"
                              " (SELECT id FROM generated ORDER BY id DESC LIMIT 200)")

    def list_generated(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM generated ORDER BY id DESC LIMIT ?", (limit,))]

    def clear_generated(self):
        with self.conn:
            self.conn.execute("DELETE FROM generated")

    # ----------------------------------------------------------------- IMAP
    def list_imap(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT id, name, email, host, port, security, username, updated_at"
            " FROM imap_accounts ORDER BY name")]

    def save_imap(self, data: dict, password: str | None = None) -> int:
        aid = data.get("id")
        fields = ("name", "email", "host", "port", "security", "username")
        values = [data[k] for k in fields]
        ts = now()
        try:
            with self.conn:
                if aid is None:
                    cur = self.conn.execute(
                        "INSERT INTO imap_accounts (name, email, host, port, security, username,"
                        " password_enc, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (*values, _enc(password), ts, ts))
                    return cur.lastrowid
                self.conn.execute(
                    "UPDATE imap_accounts SET name=?, email=?, host=?, port=?, security=?, username=?,"
                    " updated_at=? WHERE id=?", (*values, ts, aid))
                if password is not None:
                    self.conn.execute("UPDATE imap_accounts SET password_enc=? WHERE id=?",
                                      (_enc(password), aid))
                return aid
        except sqlite3.IntegrityError:
            raise DuplicateError(f"Já existe uma conexão chamada '{data['name']}'.") from None

    def get_imap_password(self, aid: int) -> str:
        row = self.conn.execute("SELECT password_enc FROM imap_accounts WHERE id = ?", (aid,)).fetchone()
        return security.decrypt(row["password_enc"]) if row else ""

    def delete_imap(self, aid: int):
        with self.conn:
            self.conn.execute("DELETE FROM imap_accounts WHERE id = ?", (aid,))

    # ------------------------------------------------------------ proxies
    PROXY_FIELDS = ("name", "protocol", "host", "port", "username", "service", "notes")

    def signup_event(self, pid, operation_id, previous, state, result='', note=''):
        from .signup import STATES
        if state not in STATES:
            raise ValueError('Invalid signup state')
        with self.conn:
            self.conn.execute('INSERT INTO signup_events (profile_id,operation_id,previous_state,state,result,note,created_at) VALUES (?,?,?,?,?,?,?)',
                              (pid, operation_id, previous, state, result, note, now()))

    def signup_history(self, pid):
        return [dict(r) for r in self.conn.execute('SELECT * FROM signup_events WHERE profile_id=? ORDER BY id DESC', (pid,))]

    def list_proxies(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT id, name, protocol, host, port, username, service, notes, status, last_ip, last_geo,"
            " last_latency_ms, auth_status, checked_at, updated_at,"
            " password_enc IS NOT NULL AND length(password_enc) > 0 AS has_password"
            " FROM proxies ORDER BY name")]

    def get_proxy(self, pid: int) -> dict:
        row = next((p for p in self.list_proxies() if p["id"] == pid), None)
        if row is None:
            raise KeyError(f"Proxy {pid} não encontrado.")
        return row

    def save_proxy(self, data: dict, password: str | None = None) -> int:
        """Insere (sem 'id') ou atualiza. `password=None` mantém a senha atual."""
        pid = data.get("id")
        values = [data[k] for k in self.PROXY_FIELDS]
        ts = now()
        try:
            with self.conn:
                if pid is None:
                    cur = self.conn.execute(
                        f"INSERT INTO proxies ({', '.join(self.PROXY_FIELDS)}, password_enc, created_at, updated_at)"
                        f" VALUES ({', '.join('?' * len(self.PROXY_FIELDS))}, ?, ?, ?)",
                        (*values, _enc(password), ts, ts))
                    return cur.lastrowid
                sets = ", ".join(f"{k} = ?" for k in self.PROXY_FIELDS)
                self.conn.execute(f"UPDATE proxies SET {sets}, updated_at = ? WHERE id = ?", (*values, ts, pid))
                if password is not None:
                    self.conn.execute("UPDATE proxies SET password_enc = ? WHERE id = ?", (_enc(password), pid))
                return pid
        except sqlite3.IntegrityError:
            raise DuplicateError(f"Já existe uma conexão chamada '{data['name']}'.") from None

    def get_proxy_password(self, pid: int) -> str:
        row = self.conn.execute("SELECT password_enc FROM proxies WHERE id = ?", (pid,)).fetchone()
        return security.decrypt(row["password_enc"]) if row else ""

    def delete_proxy(self, pid: int):
        with self.conn:
            self.conn.execute("DELETE FROM proxies WHERE id = ?", (pid,))

    def record_proxy_test(self, pid: int, r: dict):
        """Grava um diagnóstico (saída de proxy_check.diagnose) no histórico e no resumo da conexão."""
        ts = now()
        latency = r["latency"]["avg"] if r.get("latency") else None
        with self.conn:
            self.conn.execute(
                "INSERT INTO proxy_tests (proxy_id, status, ip, geo, latency_ms, auth_status, detail, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, r["status"], r["ip"], r["geo"], latency, r["auth"], r["detail"], ts))
            self.conn.execute(
                "UPDATE proxies SET status = ?, last_ip = ?, last_geo = ?, last_latency_ms = ?, auth_status = ?,"
                " checked_at = ? WHERE id = ?", (r["status"], r["ip"], r["geo"], latency, r["auth"], ts, pid))
            # ponytail: guarda os 200 testes mais recentes por conexão; aumente se precisar
            self.conn.execute("DELETE FROM proxy_tests WHERE proxy_id = ? AND id NOT IN (SELECT id FROM proxy_tests"
                              " WHERE proxy_id = ? ORDER BY id DESC LIMIT 200)", (pid, pid))

    def proxy_history(self, pid: int, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM proxy_tests WHERE proxy_id = ? ORDER BY id DESC LIMIT ?", (pid, limit))]

    # ------------------------------------------------------------ settings
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.conn:
            self.conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                              " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    def delete_setting(self, key: str):
        with self.conn:
            self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def set_secret(self, key: str, value: str):
        """Credenciais de integração: cifradas com DPAPI antes de irem para a tabela settings."""
        if not value:
            return self.delete_setting(key)
        self.set_setting(key, "dpapi:" + base64.b64encode(security.encrypt(value)).decode())

    def get_secret(self, key: str) -> str:
        raw = self.get_setting(key)
        return security.decrypt(base64.b64decode(raw[6:])) if raw.startswith("dpapi:") else ""

    # ----------------------------------------------------- manutenção/backup
    def integrity_check(self) -> str:
        return self.conn.execute("PRAGMA integrity_check").fetchone()[0]

    def backup_to(self, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        out = sqlite3.connect(dest)
        try:
            self.conn.backup(out)
            out.execute("PRAGMA journal_mode = DELETE")  # backup em arquivo único, sem -wal
        finally:
            out.close()
        return dest

    def restore_from(self, src: Path):
        """Valida o arquivo e copia o conteúdo dele por cima do banco atual."""
        if not Path(src).is_file():
            raise FileNotFoundError(f"Arquivo não encontrado: {src}")
        src_conn = sqlite3.connect(src)
        try:
            if src_conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("O arquivo de backup está corrompido.")
            tables = {r[0] for r in src_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "profiles" not in tables:
                raise ValueError("O arquivo não é um backup do Instagram Account Studio.")
            src_conn.backup(self.conn)
        finally:
            src_conn.close()
        self.migrate()

    def vacuum(self):
        self.conn.execute("VACUUM")


EXPORT_FIELDS = ("id", "full_name", "username", "email", "email_status", "birthdate", "age", "state",
                 "city", "profile_type", "status", "status_label", "bio", "notes", "created_at", "updated_at")


def export_profiles(rows: list[dict], path: Path) -> int:
    """Exporta registros de `list_profiles` SEM senhas. Formato pela extensão: .csv, .json ou .txt."""
    path = Path(path)
    data = [{k: (STATUSES[r["status"]] if k == "status_label" else r[k]) for k in EXPORT_FIELDS} for r in rows]
    ext = path.suffix.lower()
    if ext == ".json":
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    elif ext == ".csv":
        # ';' + BOM: abre direto no Excel em português
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, delimiter=";")
            writer.writeheader()
            writer.writerows(data)
    elif ext == ".txt":
        lines = [f"#{d['id']} | @{d['username']} | {d['full_name']} | {d['email'] or '—'} | "
                 f"{d['birthdate']} | {d['status_label']} | criado em {d['created_at']}" for d in data]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        raise ValueError("Formato não suportado. Use .csv, .json ou .txt.")
    return len(data)

