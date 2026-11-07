"""Leitura IMAP somente leitura (SELECT readonly + BODY.PEEK): nada é marcado,
movido ou apagado no servidor, e anexos não são baixados.
"""
import email
import html
import imaplib
import re
import socket
import ssl
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

PRESETS = {
    "Personalizado": ("", 993, "ssl"),
    "Gmail (senha de app)": ("imap.gmail.com", 993, "ssl"),
    "Hostinger": ("imap.hostinger.com", 993, "ssl"),
    "Yahoo (senha de app)": ("imap.mail.yahoo.com", 993, "ssl"),
    "Zoho Mail": ("imap.zoho.com", 993, "ssl"),
}
BODY_LIMIT = 200_000  # bytes lidos por mensagem


def connect(cfg: dict, password: str, timeout: int = 20) -> imaplib.IMAP4:
    ctx = ssl.create_default_context()
    if cfg["security"] == "ssl":
        conn = imaplib.IMAP4_SSL(cfg["host"], int(cfg["port"]), ssl_context=ctx, timeout=timeout)
    else:
        conn = imaplib.IMAP4(cfg["host"], int(cfg["port"]), timeout=timeout)
        conn.starttls(ssl_context=ctx)
    try:
        conn.login(cfg["username"], password)
    except Exception:
        conn.shutdown()
        raise
    return conn


def friendly_error(e: Exception) -> str:
    if isinstance(e, imaplib.IMAP4.error):
        return ("Falha de autenticação ou comando recusado pelo servidor. Verifique usuário e senha "
                "(no Gmail/Yahoo use uma senha de app).")
    if isinstance(e, socket.gaierror):
        return "Servidor IMAP não encontrado. Verifique o endereço."
    if isinstance(e, (TimeoutError, socket.timeout)):
        return "Tempo de conexão esgotado. Verifique servidor, porta e sua internet."
    if isinstance(e, ConnectionRefusedError):
        return "Conexão recusada. Verifique a porta e o tipo de segurança."
    if isinstance(e, ssl.SSLError):
        return f"Erro de TLS/SSL: {e.reason or e}. Confira porta e tipo de segurança."
    return f"{type(e).__name__}: {e}"


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def test_connection(cfg: dict, password: str) -> str:
    conn = connect(cfg, password)
    try:
        typ, data = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error("Não foi possível abrir a caixa de entrada.")
        return f"Conexão OK — {int(data[0])} mensagens na caixa de entrada."
    finally:
        conn.logout()


def fetch_recent(cfg: dict, password: str, limit: int = 20, folder: str = "INBOX") -> list[dict]:
    conn = connect(cfg, password)
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"Pasta '{folder}' não encontrada.")
        _, data = conn.uid("search", None, "ALL")
        uids = data[0].split()[-limit:]
        if not uids:
            return []
        _, data = conn.uid("fetch", b",".join(uids),
                           "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        out = []
        for item in data:
            if not isinstance(item, tuple):
                continue
            m = re.search(rb"UID (\d+)", item[0])
            msg = email.message_from_bytes(item[1])
            try:
                when = parsedate_to_datetime(msg["Date"]).strftime("%d/%m/%Y %H:%M")
            except Exception:
                when = msg["Date"] or ""
            out.append({"uid": m.group(1).decode() if m else "", "date": when,
                        "from": _decode(msg["From"]), "subject": _decode(msg["Subject"])})
        return out[::-1]  # mais recentes primeiro
    finally:
        conn.logout()


def _junk_folders(conn: imaplib.IMAP4) -> list[str]:
    """Pastas marcadas como spam (\\Junk) pelo servidor, ex.: '[Gmail]/Spam'."""
    typ, data = conn.list()
    if typ != "OK":
        return []
    out = []
    for line in data or []:
        m = re.match(rb'\((?P<flags>[^)]*)\) "?[^"]*"? (?P<name>.+)', line or b"")
        if m and b"\\Junk" in m.group("flags"):
            out.append(m.group("name").decode("ascii", "replace").strip().strip('"'))
    return out


def find_message(cfg: dict, password: str, subject_token: str, to_address: str) -> dict | None:
    """Procura (somente leitura) uma mensagem com o token no assunto enviada ao endereço,
    na caixa de entrada e na pasta de spam. Retorna {'folder', 'date', 'from'} ou None."""
    conn = connect(cfg, password)
    try:
        for folder in ["INBOX", *_junk_folders(conn)]:
            typ, _ = conn.select(f'"{folder}"', readonly=True)
            if typ != "OK":
                continue
            typ, data = conn.uid("search", None, "SUBJECT", f'"{subject_token}"', "TO", f'"{to_address}"')
            uids = data[0].split() if typ == "OK" and data and data[0] else []
            if not uids:
                continue
            _, data = conn.uid("fetch", uids[-1], "(BODY.PEEK[HEADER.FIELDS (FROM DATE)])")
            raw = next((i[1] for i in data if isinstance(i, tuple)), b"")
            msg = email.message_from_bytes(raw)
            return {"folder": folder, "date": msg["Date"] or "", "from": _decode(msg["From"])}
        return None
    finally:
        conn.logout()


def _text_of(msg: email.message.Message) -> str:
    plain, rich = [], []
    for part in msg.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain if ctype == "text/plain" else rich).append(text)
    if plain:
        return "\n".join(plain).strip()
    raw = "\n".join(rich)
    raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", raw)
    return re.sub(r"\n\s*\n+", "\n\n", html.unescape(re.sub(r"<[^>]+>", "", raw))).strip()


def fetch_body(cfg: dict, password: str, uid: str, folder: str = "INBOX") -> str:
    conn = connect(cfg, password)
    try:
        conn.select(folder, readonly=True)
        _, data = conn.uid("fetch", uid, f"(BODY.PEEK[]<0.{BODY_LIMIT}>)")
        raw = next((i[1] for i in data if isinstance(i, tuple)), None)
        if raw is None:
            return "(mensagem não encontrada)"
        text = _text_of(email.message_from_bytes(raw))
        return text or "(mensagem sem conteúdo de texto)"
    finally:
        conn.logout()
