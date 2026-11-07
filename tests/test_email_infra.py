"""Integrações de e-mail sem rede externa: servidor HTTP local imita DoH/Cloudflare, IMAP falso."""
import imaplib
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import email_infra, imap_client


@pytest.fixture
def fake_http():
    routes: dict[str, tuple[int, object]] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = routes.get(self.path, (404, {"success": False, "errors": [{"message": "not found"}]}))
            routes.setdefault("_auth", []).append(self.headers.get("Authorization", ""))
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", routes
    server.shutdown()
    server.server_close()


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


ZONE = "zona123"
RULES = f"/zones/{ZONE}/email/routing/rules?page=1&per_page=50"
CATCH = f"/zones/{ZONE}/email/routing/rules/catch_all"


def _rule(address, dest="destino@gmail.com", enabled=True):
    return {"enabled": enabled, "matchers": [{"type": "literal", "field": "to", "value": address}],
            "actions": [{"type": "forward", "value": [dest]}]}


# ------------------------------------------------------------ painel
def test_panel_without_api_is_unavailable():
    with pytest.raises(email_infra.ApiUnavailable):
        email_infra.panel_test("", "nenhuma", "", 2)
    with pytest.raises(email_infra.ApiUnavailable):
        email_infra.panel_list_addresses({})
    with pytest.raises(email_infra.ApiUnavailable):
        email_infra.panel_create_alias({}, "rafavelo")
    assert email_infra.PANEL_CAN_CREATE is False


def test_panel_api_offline_is_friendly_error():
    with pytest.raises(email_infra.IntegrationError, match="conectar|conexão"):
        email_infra.panel_test(f"http://127.0.0.1:{_closed_port()}/api", "bearer", "tok", 3)


def test_panel_api_status_codes(fake_http):
    base, routes = fake_http
    routes["/api"] = (200, {"ok": True})
    routes["/negado"] = (401, {})
    routes["/quebrado"] = (500, {})
    assert "HTTP 200" in email_infra.panel_test(base + "/api", "bearer", "tok-123", 3)
    assert "Bearer tok-123" in routes["_auth"]
    with pytest.raises(email_infra.IntegrationError, match="credencial"):
        email_infra.panel_test(base + "/negado", "x-api-key", "k", 3)
    with pytest.raises(email_infra.IntegrationError, match="servidor"):
        email_infra.panel_test(base + "/quebrado", "nenhuma", "", 3)


# ------------------------------------------------------------ Cloudflare
def test_cloudflare_specific_rule(fake_http):
    base, routes = fake_http
    routes[RULES] = (200, {"success": True, "result": [_rule("outra@x.com"), _rule("rafa@x.com")],
                           "result_info": {"total_pages": 1}})
    r = email_infra.cf_forwarding("tok", ZONE, "RAFA@x.com", 3, base)
    assert r == {"configured": True, "destination": "destino@gmail.com",
                 "detail": "Regra específica encaminha para destino@gmail.com."}


def test_cloudflare_catch_all_and_disabled_rule(fake_http):
    base, routes = fake_http
    routes[RULES] = (200, {"success": True, "result": [_rule("off@x.com", enabled=False)],
                           "result_info": {"total_pages": 1}})
    routes[CATCH] = (200, {"success": True, "result": {"enabled": True, "matchers": [{"type": "all"}],
                                                       "actions": [{"type": "forward", "value": ["g@gmail.com"]}]}})
    assert email_infra.cf_forwarding("tok", ZONE, "off@x.com", 3, base)["configured"] is False
    r = email_infra.cf_forwarding("tok", ZONE, "qualquer@x.com", 3, base)
    assert r["configured"] and "catch-all" in r["detail"]
    assert "catch-all: ativa" in email_infra.cf_test("tok", ZONE, 3, base)


def test_cloudflare_no_rule(fake_http):
    base, routes = fake_http
    routes[RULES] = (200, {"success": True, "result": [], "result_info": {"total_pages": 1}})
    routes[CATCH] = (200, {"success": True, "result": {"enabled": False, "actions": []}})
    assert email_infra.cf_forwarding("tok", ZONE, "a@x.com", 3, base)["configured"] is False


def test_cloudflare_bad_token(fake_http):
    base, routes = fake_http
    routes[RULES] = (403, {"success": False, "errors": [{"message": "Authentication error"}]})
    with pytest.raises(email_infra.IntegrationError, match="Authentication error.*permissão"):
        email_infra.cf_forwarding("ruim", ZONE, "a@x.com", 3, base)


# ------------------------------------------------------------ DNS + verificação
def test_mx_records_via_doh(fake_http):
    base, routes = fake_http
    routes["/dns?name=inboxnexo.online&type=MX"] = (200, {"Status": 0, "Answer": [
        {"type": 15, "data": "10 route2.mx.cloudflare.net."}, {"type": 15, "data": "5 route1.mx.cloudflare.net."}]})
    routes["/dns?name=naoexiste.test&type=MX"] = (200, {"Status": 3})
    assert email_infra.mx_records("inboxnexo.online", 3, base + "/dns") == \
        ["route1.mx.cloudflare.net", "route2.mx.cloudflare.net"]
    with pytest.raises(email_infra.IntegrationError, match="NXDOMAIN"):
        email_infra.mx_records("naoexiste.test", 3, base + "/dns")


def test_verify_address_statuses(fake_http):
    base, routes = fake_http
    routes["/dns?name=x.com&type=MX"] = (200, {"Status": 0, "Answer": [{"type": 15, "data": "10 route1.mx.cloudflare.net."}]})
    routes[RULES] = (200, {"success": True, "result": [_rule("rafa@x.com")], "result_info": {"total_pages": 1}})
    routes[CATCH] = (200, {"success": True, "result": {"enabled": False}})
    kw = {"timeout": 3, "doh_url": base + "/dns", "cf_base": base}

    ok = email_infra.verify_address("rafa@x.com", "tok", ZONE, **kw)
    assert ok["status"] == "encaminhamento" and ok["destination"] == "destino@gmail.com"
    missing = email_infra.verify_address("nao@x.com", "tok", ZONE, **kw)
    assert missing["status"] == "pendente"
    # sem Cloudflare configurada: não promove nada, só avisa
    unknown = email_infra.verify_address("rafa@x.com", **kw)
    assert unknown["status"] is None
    assert any("não verificável" in t for _i, t in unknown["checks"])
    assert any("não garantem a entrega" in t for _i, t in unknown["checks"])
    assert email_infra.verify_address("sem-arroba", **kw)["status"] == "pendente"


def test_verify_survives_offline_services():
    dead = f"http://127.0.0.1:{_closed_port()}"
    res = email_infra.verify_address("a@x.com", "tok", ZONE, timeout=2, doh_url=dead + "/dns", cf_base=dead)
    icons = [i for i, _t in res["checks"]]
    assert email_infra.WARN in icons and res["status"] is None


def test_parse_address_file_txt_and_csv():
    valid, invalid = email_infra.parse_address_file("# lista\na@x.com\nB@X.com\nruim\na@x.com\n")
    assert valid == ["a@x.com", "b@x.com"] and invalid == ["ruim"]
    valid, invalid = email_infra.parse_address_file("nome;email\nRafa;rafa@x.com\nLavi;lavi@x.com\n")
    assert valid == ["rafa@x.com", "lavi@x.com"] and not invalid


# ------------------------------------------------------------ IMAP (falso + porta fechada)
class FakeIMAP:
    boxes = {"INBOX": [], "[Gmail]/Spam": [(b"7", "Teste IAS-ABC123", "rafa@x.com")]}

    def __init__(self, host, port, ssl_context=None, timeout=None):
        self.selected = None

    def login(self, user, password):
        if password != "certa":
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"logged in"]

    def shutdown(self):
        pass

    def logout(self):
        return "BYE", [b""]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"']

    def select(self, mailbox, readonly=False):
        assert readonly, "o app nunca abre caixas em modo escrita"
        name = mailbox.strip('"')
        if name not in self.boxes:
            return "NO", [b"unknown"]
        self.selected = name
        return "OK", [str(len(self.boxes[name])).encode()]

    def uid(self, cmd, *args):
        msgs = self.boxes[self.selected]
        if cmd == "search":
            subject, to = args[2].strip('"'), args[4].strip('"')
            return "OK", [b" ".join(u for u, s, t in msgs if subject in s and t == to)]
        assert "PEEK" in args[1]
        return "OK", [(b"7 (UID 7 BODY[HEADER] {60}", b"From: Eu <eu@ex.com>\r\nDate: Mon, 2 Nov 2026 10:00:00 -0300\r\n\r\n"), b")"]


CFG = {"host": "imap.gmail.com", "port": 993, "security": "ssl", "username": "g@gmail.com", "email": "g@gmail.com"}


def test_imap_connection_test(monkeypatch):
    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeIMAP)
    assert imap_client.test_connection(CFG, "certa") == "Conexão OK — 0 mensagens na caixa de entrada."
    with pytest.raises(imaplib.IMAP4.error) as e:
        imap_client.test_connection(CFG, "errada")
    assert "autenticação" in imap_client.friendly_error(e.value)


def test_imap_receipt_search_checks_spam_folder(monkeypatch):
    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", FakeIMAP)
    found = imap_client.find_message(CFG, "certa", "IAS-ABC123", "rafa@x.com")
    assert found["folder"] == "[Gmail]/Spam" and "eu@ex.com" in found["from"]
    assert imap_client.find_message(CFG, "certa", "IAS-OUTRO", "rafa@x.com") is None
    assert imap_client.find_message(CFG, "certa", "IAS-ABC123", "outro@x.com") is None


def test_imap_closed_port_is_friendly():
    cfg = {**CFG, "host": "127.0.0.1", "port": _closed_port()}
    with pytest.raises(OSError) as e:
        imap_client.test_connection(cfg, "x")
    assert "recusada" in imap_client.friendly_error(e.value) or "esgotado" in imap_client.friendly_error(e.value)
