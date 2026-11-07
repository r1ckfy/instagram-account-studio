"""Leitura de fichas de personagens em TXT (UTF-8).

Formato: linhas `Campo: valor`, fichas separadas por uma linha `---`.
`Campo: |` abre um bloco de várias linhas (ex.: Bio); o bloco termina na próxima
linha sem recuo que comece com um campo conhecido, ou no `---`.
"""
import re
import textwrap
import unicodedata
from datetime import date, datetime
from pathlib import Path

from . import generator as gen

FIELD_ALIASES = {
    "nome": "full_name", "nome completo": "full_name",
    "usuario": "username", "username": "username", "user": "username", "usuario sugerido": "username",
    "nascimento": "birthdate", "data de nascimento": "birthdate", "data nascimento": "birthdate",
    "idade": "age",
    "estado": "state", "uf": "state",
    "cidade": "city",
    "bio": "bio", "biografia": "bio",
    "email": "email", "e-mail": "email",
    "observacoes": "notes", "observacao": "notes", "obs": "notes", "notas": "notes",
}
DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d")
RESULTS = {"valido": "✓ Válido", "aviso": "⚠ Aviso", "duplicado": "⧉ Duplicado", "invalido": "✖ Inválido"}

_KEY_RE = re.compile(r"^(\S[^:]{0,30}?)\s*:(.*)$")


class TxtError(ValueError):
    pass


def _norm(key: str) -> str:
    key = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", key).strip()


def read_text(path: Path) -> str:
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        line = data[:e.start].count(b"\n") + 1
        raise TxtError(f"O arquivo não está em UTF-8 (byte inválido na linha {line}). "
                       "No Bloco de Notas use Arquivo → Salvar como → Codificação: UTF-8.") from None


def _blocks(text: str) -> list[tuple[int, list[str]]]:
    blocks, cur, start = [], [], 1
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip() == "---":
            blocks.append((start, cur))
            cur, start = [], n + 1
        else:
            cur.append(line)
    blocks.append((start, cur))
    return [(s, b) for s, b in blocks if any(x.strip() for x in b)]


def _parse_block(lines: list[str]) -> tuple[dict, list[str]]:
    parts: dict[str, list[str]] = {}
    is_block: dict[str, bool] = {}
    warnings: list[str] = []
    current = None
    for line in lines:
        m = _KEY_RE.match(line)
        field = FIELD_ALIASES.get(_norm(m.group(1))) if m else None
        if field:
            if field in parts:
                warnings.append(f"Campo '{m.group(1).strip()}' repetido; mantido o último.")
            value = m.group(2).strip()
            is_block[field] = value in ("|", "|-", "|+")
            parts[field] = [] if is_block[field] else [value]
            current = field
        elif m and current and not is_block[current]:
            warnings.append(f"Campo desconhecido ignorado: '{m.group(1).strip()}'.")
            current = None
        elif current:
            parts[current].append(line)
        elif line.strip():
            warnings.append(f"Linha fora de um campo ignorada: '{line.strip()[:40]}'.")
    values = {}
    for field, raw in parts.items():
        if is_block[field]:
            text = textwrap.dedent("\n".join(x.rstrip() for x in raw)).strip("\n")
        else:
            text = "\n".join([raw[0]] + [x.strip() for x in raw[1:]]).strip()
        values[field] = text
    return values, warnings


def _parse_date(text: str) -> date | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def validate(values: dict, today: date | None = None) -> dict:
    """Converte e valida uma ficha. Retorna dict com campos + 'errors' e 'warnings'."""
    today = today or date.today()
    errors, warnings = [], []
    f = {k: values.get(k, "") for k in ("full_name", "state", "city", "bio", "notes")}

    if not f["full_name"]:
        errors.append("Nome é obrigatório.")

    raw_user = values.get("username", "")
    user = raw_user.lstrip("@").strip()
    if user != user.lower():
        warnings.append(f"Usuário '{user}' convertido para minúsculas.")
        user = user.lower()
    f["username"] = user
    if not user:
        errors.append("Usuário é obrigatório.")
    elif err := gen.validate_username(user):
        errors.append(f"Usuário '{user}': {err}")

    f["birthdate"], f["age"] = "", None
    born_txt, age_txt = values.get("birthdate", ""), values.get("age", "")
    if born_txt:
        born = _parse_date(born_txt)
        if born is None:
            errors.append(f"Nascimento '{born_txt}' inválido. Use DD/MM/AAAA.")
        elif born > today:
            errors.append(f"Nascimento '{born_txt}' está no futuro.")
        elif err := gen.validate_birthdate(born, today):
            errors.append(err)
        else:
            f["birthdate"] = born.isoformat()
    if age_txt:
        if not age_txt.isdigit():
            errors.append(f"Idade '{age_txt}' inválida.")
        elif int(age_txt) < gen.MIN_AGE:
            errors.append(f"O personagem precisa ter {gen.MIN_AGE} anos ou mais.")
        else:
            f["age"] = int(age_txt)
            if f["birthdate"] and gen.age_on(date.fromisoformat(f["birthdate"]), today) != f["age"]:
                warnings.append(f"Idade informada ({f['age']}) não bate com o nascimento; vale o nascimento.")
    if not born_txt and not age_txt:
        errors.append("Informe Nascimento ou Idade.")
    if f["birthdate"]:
        f["age"] = gen.age_on(date.fromisoformat(f["birthdate"]), today)

    email = values.get("email", "").strip()
    if email and gen.validate_email(email):
        errors.append(f"E-mail '{email}' em formato inválido.")
    f["email"] = email.lower()

    if len(f["bio"]) > gen.BIO_MAX:
        warnings.append(f"Bio com {len(f['bio'])} caracteres (o Instagram aceita {gen.BIO_MAX}).")
    f["errors"], f["warnings"] = errors, warnings
    return f


def parse_text(text: str, today: date | None = None) -> list[dict]:
    fichas = []
    for line_no, lines in _blocks(text):
        values, warnings = _parse_block(lines)
        f = validate(values, today)
        f["warnings"] = warnings + f["warnings"]
        f["line"] = line_no
        fichas.append(f)
    return fichas


def parse_file(path: Path, today: date | None = None) -> list[dict]:
    fichas = parse_text(read_text(path), today)
    if not fichas:
        raise TxtError("Nenhuma ficha encontrada. Use linhas 'Campo: valor' e separe as fichas com '---'.")
    return fichas


def classify(fichas: list[dict], db) -> list[dict]:
    """Marca duplicidades (no arquivo e no banco) e define 'result' de cada ficha."""
    seen_users: dict[str, int] = {}
    seen_emails: dict[str, int] = {}
    for f in fichas:
        u, e = f["username"].lower(), f["email"]
        f["duplicate"] = ""
        if u and u in seen_users:
            f["duplicate"] = f"Usuário repetido no arquivo (ficha da linha {seen_users[u]})."
        elif u and db.username_exists(u):
            f["duplicate"] = f"@{u} já existe no banco local."
        if e:
            if e in seen_emails:
                f["warnings"].append(f"E-mail repetido no arquivo (ficha da linha {seen_emails[e]}).")
            if owners := db.address_owners(e):
                f["warnings"].append(f"E-mail já associado a {', '.join('@' + o for o in owners)}.")
            seen_emails.setdefault(e, f["line"])
        if u:
            seen_users.setdefault(u, f["line"])
        f["result"] = ("invalido" if f["errors"] else "duplicado" if f["duplicate"]
                       else "aviso" if f["warnings"] else "valido")
    return fichas
