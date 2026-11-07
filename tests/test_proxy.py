"""Diagnóstico de proxies contra servidores locais reais: serviço de IP, proxy HTTP e proxy SOCKS5."""
import base64
import json
import select
import socket
import socketserver
import struct
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import proxy_check

PROXIED_IP, DIRECT_IP = "203.0.113.7", "198.51.100.1"


def _serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def ip_service():
    """Imita o ipinfo: devolve um IP diferente quando a requisição chega pelo proxy de teste."""
    state = {"rotate": False, "fail_every": 0, "count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["count"] += 1
            if state["fail_every"] and state["count"] % state["fail_every"] == 0:
                self.send_response(500)
                self.end_headers()
                return
            via_proxy = self.headers.get("X-Test-Proxy") or state.get("socks")
            ip = PROXIED_IP if via_proxy else DIRECT_IP
            if state["rotate"]:
                ip = f"203.0.113.{state['count']}"
            body = json.dumps({"ip": ip, "city": "Recife", "region": "Pernambuco", "country": "BR",
                               "org": "AS64500 Teste"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = _serve(ThreadingHTTPServer(("127.0.0.1", 0), Handler))
    yield f"http://127.0.0.1:{server.server_port}/json", state
    server.shutdown()
    server.server_close()


def _http_proxy(auth: tuple[str, str] | None):
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if auth:
                expected = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
                if self.headers.get("Proxy-Authorization") != expected:
                    self.send_response(407)
                    self.send_header("Proxy-Authenticate", 'Basic realm="teste"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            req = urllib.request.Request(self.path, headers={"X-Test-Proxy": "1"})
            try:
                with direct.open(req, timeout=5) as r:
                    status, body = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, body = e.code, b""
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return _serve(ThreadingHTTPServer(("127.0.0.1", 0), Handler))


class _Socks5(socketserver.BaseRequestHandler):
    auth: tuple[str, str] | None = None

    def _recv(self, n):
        data = b""
        while len(data) < n:
            chunk = self.request.recv(n - len(data))
            if not chunk:
                raise ConnectionError
            data += chunk
        return data

    def handle(self):
        s = self.request
        ver, nmethods = self._recv(2)
        methods = self._recv(nmethods)
        want = 0x02 if self.auth else 0x00
        if want not in methods:
            s.sendall(b"\x05\xff")
            return
        s.sendall(bytes([5, want]))
        if self.auth:
            _v, ulen = self._recv(2)
            user = self._recv(ulen).decode()
            (plen,) = self._recv(1)
            pw = self._recv(plen).decode()
            ok = (user, pw) == self.auth
            s.sendall(b"\x01\x00" if ok else b"\x01\x01")
            if not ok:
                return
        _v, cmd, _r, atyp = self._recv(4)
        if atyp == 1:
            host = socket.inet_ntoa(self._recv(4))
        elif atyp == 3:
            host = self._recv(self._recv(1)[0]).decode()
        else:
            host = socket.inet_ntop(socket.AF_INET6, self._recv(16))
        (port,) = struct.unpack("!H", self._recv(2))
        target = socket.create_connection((host, port), timeout=5)
        s.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        socks = [s, target]
        while True:
            readable, _, _ = select.select(socks, [], [], 5)
            if not readable:
                break
            for r in readable:
                data = r.recv(65536)
                if not data:
                    target.close()
                    return
                (target if r is s else s).sendall(data)


def _socks_proxy(auth):
    handler = type("H", (_Socks5,), {"auth": auth})
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    return _serve(server)


def _cfg(server, protocol="http", user="", service="fixo"):
    return {"name": "teste", "protocol": protocol, "host": "127.0.0.1", "port": server.server_address[1],
            "username": user, "service": service, "notes": ""}


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ------------------------------------------------------------ diagnóstico
def test_http_proxy_connected(ip_service):
    url, _ = ip_service
    proxy = _http_proxy(None)
    r = proxy_check.diagnose(_cfg(proxy), "", timeout=5, url=url)
    assert r["status"] == "conectado" and r["ip"] == PROXIED_IP and r["samples"] == "3/3"
    assert "Recife" in r["geo"] and "BR" in r["geo"] and "AS64500" in r["geo"]
    assert r["auth"] == "Sem autenticação" and r["latency"]["min"] <= r["latency"]["avg"] <= r["latency"]["max"]
    proxy.shutdown()


def test_http_proxy_authentication(ip_service):
    url, state = ip_service
    proxy = _http_proxy(("ana", "s3nha"))
    ok = proxy_check.diagnose(_cfg(proxy, user="ana"), "s3nha", timeout=5, url=url)
    assert ok["status"] == "conectado" and ok["auth"] == "OK"
    before = state["count"]
    bad = proxy_check.diagnose(_cfg(proxy, user="ana"), "errada", timeout=5, url=url)
    assert bad["status"] == "desconectado" and bad["auth"] == "Recusada"
    assert bad["samples"] == "0/1" and "407" in bad["detail"]  # não insiste com senha errada
    assert state["count"] == before
    proxy.shutdown()


@pytest.mark.parametrize("auth", [None, ("bia", "p4ss")])
def test_socks5_proxy(ip_service, auth):
    url, state = ip_service
    state["socks"] = True
    proxy = _socks_proxy(auth)
    r = proxy_check.diagnose(_cfg(proxy, "socks5", user=auth[0] if auth else ""), auth[1] if auth else "",
                             timeout=5, url=url)
    assert r["status"] == "conectado" and r["ip"] == PROXIED_IP
    assert r["auth"] == ("OK" if auth else "Sem autenticação")
    if auth:
        bad = proxy_check.diagnose(_cfg(proxy, "socks5", user="bia"), "errada", timeout=5, url=url)
        assert bad["status"] == "desconectado" and bad["auth"] == "Recusada"
    proxy.shutdown()


def test_offline_proxy_is_disconnected(ip_service):
    url, _ = ip_service
    cfg = {"name": "x", "protocol": "http", "host": "127.0.0.1", "port": _closed_port(),
           "username": "", "service": "fixo"}
    r = proxy_check.diagnose(cfg, "", timeout=3, samples=1, url=url)
    assert r["status"] == "desconectado" and r["ip"] == "" and r["latency"] is None
    assert "recusada" in r["detail"].lower() or "proxy falhou" in r["detail"].lower()


def test_silent_proxy_times_out(ip_service):
    url, _ = ip_service
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    cfg = {"name": "x", "protocol": "http", "host": "127.0.0.1", "port": srv.getsockname()[1],
           "username": "", "service": "fixo"}
    started = time.monotonic()
    r = proxy_check.diagnose(cfg, "", timeout=1, samples=1, url=url)
    assert time.monotonic() - started < 10
    assert r["status"] == "desconectado" and "tempo limite" in r["detail"].lower()
    srv.close()


def test_rotating_endpoint_vs_fixed(ip_service):
    url, state = ip_service
    state["rotate"] = True
    proxy = _http_proxy(None)
    rot = proxy_check.diagnose(_cfg(proxy, service="rotativo"), "", timeout=5, url=url)
    assert rot["status"] == "conectado" and len(rot["ips"]) == 3 and "rotativo" in rot["detail"]
    fixed = proxy_check.diagnose(_cfg(proxy, service="fixo"), "", timeout=5, url=url)
    assert fixed["status"] == "instavel" and "fixa" in fixed["detail"]
    proxy.shutdown()


def test_partial_failures_are_unstable(ip_service):
    url, state = ip_service
    state["fail_every"] = 2
    proxy = _http_proxy(None)
    r = proxy_check.diagnose(_cfg(proxy), "", timeout=5, url=url)
    assert r["status"] == "instavel" and r["samples"] == "2/3" and "HTTP 500" in r["detail"]
    proxy.shutdown()


def test_same_ip_as_direct_is_flagged(ip_service):
    url, _ = ip_service
    assert proxy_check.direct_ip(5, url) == DIRECT_IP
    proxy = _http_proxy(None)
    r = proxy_check.diagnose(_cfg(proxy), "", timeout=5, url=url, direct=PROXIED_IP)
    assert r["status"] == "instavel" and "sem proxy" in r["detail"]
    proxy.shutdown()


def test_does_not_touch_system_proxy_settings(ip_service):
    import os
    env_before = dict(os.environ)
    system_before = urllib.request.getproxies()  # inclui o proxy do Windows (registro)
    url, _ = ip_service
    proxy = _http_proxy(None)
    proxy_check.diagnose(_cfg(proxy), "", timeout=5, url=url)
    assert dict(os.environ) == env_before and urllib.request.getproxies() == system_before
    proxy.shutdown()


# ------------------------------------------------------------ validação e arquivos
@pytest.mark.parametrize("field,value", [("name", ""), ("protocol", "ftp"), ("host", "http://x.com"),
                                         ("host", "x.com:80"), ("port", 0), ("port", 70000), ("service", "x")])
def test_validate_rejects(field, value):
    cfg = {"name": "a", "protocol": "http", "host": "gate.provedor.com", "port": 7000, "service": "rotativo"}
    assert proxy_check.validate(cfg) is None
    assert proxy_check.validate({**cfg, field: value})


def test_export_has_no_passwords_and_imports_back(tmp_path, db):
    pid = db.save_proxy({"name": "P1", "protocol": "socks5", "host": "gate.x.com", "port": 7000,
                         "username": "u1", "service": "rotativo", "notes": "n"}, "SenhaSecreta!")
    out = tmp_path / "proxies.json"
    assert proxy_check.export_configs(db.list_proxies(), out) == 1
    text = out.read_text(encoding="utf-8")
    assert "SenhaSecreta" not in text and "password" not in text
    rows, warnings = proxy_check.parse_import(text)
    assert rows == [{"name": "P1", "protocol": "socks5", "host": "gate.x.com", "port": 7000, "username": "u1",
                     "service": "rotativo", "notes": "n"}] and not warnings
    assert db.get_proxy_password(pid) == "SenhaSecreta!"


def test_import_txt_lines_drop_passwords():
    rows, warnings = proxy_check.parse_import(
        "# lista\n1.2.3.4:8080\nsocks5h://ana:segredo@gate.x.com:7000\nhttps://bia@px.y.com:443\nlixo aqui\n")
    assert [(r["protocol"], r["host"], r["port"], r["username"]) for r in rows] == [
        ("http", "1.2.3.4", 8080, ""), ("socks5", "gate.x.com", 7000, "ana"), ("https", "px.y.com", 443, "bia")]
    assert any("senha descartada" in w for w in warnings) and any("Linha 5" in w for w in warnings)
    assert "segredo" not in json.dumps(rows)


def test_db_stores_proxy_password_encrypted_and_history(db):
    pid = db.save_proxy({"name": "P", "protocol": "http", "host": "h.com", "port": 80, "username": "u",
                         "service": "fixo", "notes": ""}, "NaoPodeVazar#1")
    db.conn.execute("PRAGMA wal_checkpoint(FULL)")
    assert b"NaoPodeVazar#1" not in db.path.read_bytes()
    result = {"status": "conectado", "ip": "203.0.113.7", "geo": "Recife", "latency": {"avg": 120, "min": 100,
              "max": 140}, "auth": "OK", "detail": "ok"}
    db.record_proxy_test(pid, result)
    p = db.get_proxy(pid)
    assert (p["status"], p["last_ip"], p["last_latency_ms"], p["auth_status"]) == ("conectado", "203.0.113.7", 120, "OK")
    assert db.proxy_history(pid)[0]["ip"] == "203.0.113.7"
    db.save_proxy({**{k: p[k] for k in db.PROXY_FIELDS}, "id": pid, "notes": "editado"}, None)
    assert db.get_proxy_password(pid) == "NaoPodeVazar#1"  # editar sem senha mantém a atual
    db.delete_proxy(pid)
    assert db.conn.execute("SELECT COUNT(*) FROM proxy_tests").fetchone()[0] == 0


def test_proxies_not_linked_to_profiles(db):
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(profiles)")}
    assert not any("proxy" in c for c in cols)
    proxy_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(proxies)")}
    assert not any("profile" in c for c in proxy_cols)


# ------------------------------------------------------------ aba PROXY (Qt offscreen)
def test_proxy_tab_save_test_and_history(ip_service, db, tmp_path, monkeypatch):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import QThreadPool

    from app.logs import setup_logging
    from app.ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    url, _ = ip_service
    monkeypatch.setattr(proxy_check, "IP_SERVICE", url)
    handler = setup_logging(tmp_path / "logs")
    w = MainWindow(db, handler)
    proxy = _http_proxy(("ana", "s3nha-da-ana"))
    t = w.proxy
    t.new()
    t.name.setText("Local")
    t.host.setText("127.0.0.1")
    t.port.setValue(proxy.server_address[1])
    t.user.setText("ana")
    t.password.setText("s3nha-da-ana")
    pid = t.save()
    assert pid and t.password.text() == "" and db.get_proxy_password(pid) == "s3nha-da-ana"

    t.test_selected()
    assert t.busy and not t.test_btn.isEnabled()  # interface livre, teste em segundo plano
    assert QThreadPool.globalInstance().waitForDone(30000)
    for _ in range(5):
        app.processEvents()
    p = db.get_proxy(pid)
    assert (p["status"], p["last_ip"], p["auth_status"]) == ("conectado", PROXIED_IP, "OK")
    assert t.direct_ip == DIRECT_IP and not t.busy
    assert t.d["ip"].text() == PROXIED_IP and "Recife" in t.d["geo"].text()
    assert t.history.rowCount() == 1 and t.table.rowCount() == 1
    assert all("s3nha-da-ana" not in m for _t, _l, m in handler.records)
    assert any(lv == "SUCESSO" and "Local" in m for _t, lv, m in handler.records)
    w.close()
    proxy.shutdown()
