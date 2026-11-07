import socket
import time
import urllib3
import pytest
from app.proxy_browser import Relay, DiagnosticSession
from test_proxy import ip_service, _socks_proxy, _cfg, DIRECT_IP

@pytest.mark.parametrize('auth', [None, ('ana', 'SenhaSecreta')])
def test_relay_real_socks_http_and_connect(ip_service, auth):
    url, _ = ip_service
    upstream = _socks_proxy(auth)
    relay = Relay(_cfg(upstream, 'socks5', user=auth[0] if auth else ''), auth[1] if auth else '', 3)
    pool = urllib3.ProxyManager(f'http://127.0.0.1:{relay.server_address[1]}', retries=False)
    try:
        assert pool.request('GET', url).status == 200
        target = urllib3.util.parse_url(url)
        with socket.create_connection(relay.server_address, 3) as conn:
            conn.sendall(f'CONNECT {target.host}:{target.port} HTTP/1.1\r\nHost: {target.host}\r\n\r\n'.encode())
            header = b''
            while not header.endswith(b'\r\n\r\n'):
                header += conn.recv(1)
            assert b'200' in header
            conn.sendall(b'GET /json HTTP/1.0\r\nHost: localhost\r\n\r\n')
            assert b'200' in conn.recv(4096)
    finally:
        pool.clear()
        address = relay.server_address
        relay.close()
        upstream.shutdown()
        upstream.server_close()
    assert not relay.thread.is_alive() and not relay.connections and relay.password == ''
    with pytest.raises(OSError):
        socket.create_connection(address, .2)


def test_relay_bad_auth_no_direct_fallback(ip_service):
    url, state = ip_service
    upstream = _socks_proxy(('ana', 'secret'))
    relay = Relay(_cfg(upstream, 'socks5', user='ana'), 'wrong', 2)
    pool = urllib3.ProxyManager(f'http://127.0.0.1:{relay.server_address[1]}', retries=False)
    try:
        assert pool.request('GET', url).status == 502
        assert state['count'] == 0
        assert relay.last_error == 'Autenticação recusada'
    finally:
        pool.clear()
        relay.close()
        upstream.shutdown()
        upstream.server_close()


def test_relay_offline_no_fallback(ip_service):
    url, state = ip_service
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    cfg = dict(name='x', protocol='http', host='127.0.0.1', port=port, service='fixo')
    relay = Relay(cfg, '', 1)
    pool = urllib3.ProxyManager(f'http://127.0.0.1:{relay.server_address[1]}', retries=False)
    try:
        assert pool.request('GET', url).status == 502
        assert state['count'] == 0
    finally:
        pool.clear()
        relay.close()


def test_session_cleanup_idempotent():
    session = DiagnosticSession()
    session.close()
    session.close()
    assert session.closed.is_set()
    with pytest.raises(RuntimeError):
        session.verify()
import base64
import select
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from test_proxy import _serve

@pytest.fixture
def connect_proxy(request, tmp_path):
    use_tls = request.param
    auth = ('ana', 'SenhaSecreta')
    class ProxyHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_CONNECT(self):
            expected = 'Basic ' + base64.b64encode(':'.join(auth).encode()).decode()
            if self.headers.get('Proxy-Authorization') != expected:
                self.send_error(407)
                return
            host, port = self.path.rsplit(':', 1)
            with socket.create_connection((host, int(port)), 3) as target:
                self.send_response(200)
                self.end_headers()
                while True:
                    ready, _, _ = select.select([self.connection, target], [], [], 3)
                    if not ready:
                        return
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (target if source is self.connection else self.connection).sendall(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), ProxyHandler)
    cert = None
    if use_tls:
        from pathlib import Path
        exe = Path('C:/Program Files/Git/usr/bin/openssl.exe')
        if not exe.exists():
            pytest.skip('OpenSSL required to generate local TLS fixture')
        cert, key = tmp_path/'cert.pem', tmp_path/'key.pem'
        subprocess.run([str(exe), 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                        '-out', str(cert), '-days', '1', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=IP:127.0.0.1'], check=True, capture_output=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    _serve(server)
    yield server, cert
    server.shutdown()
    server.server_close()

@pytest.mark.parametrize('connect_proxy', [False, True], indirect=True)
def test_http_https_authenticated_connect(connect_proxy, ip_service, monkeypatch):
    server, cert = connect_proxy
    if cert:
        original = ssl.create_default_context
        monkeypatch.setattr(ssl, 'create_default_context', lambda: original(cafile=str(cert)))
    relay = Relay(_cfg(server, 'https' if cert else 'http', user='ana'), 'SenhaSecreta', 3)
    url, _ = ip_service
    target = urllib3.util.parse_url(url)
    try:
        with socket.create_connection(relay.server_address, 3) as conn:
            conn.sendall(f'CONNECT {target.host}:{target.port} HTTP/1.1\r\nHost: test\r\n\r\n'.encode())
            header = b''
            while not header.endswith(b'\r\n\r\n'):
                header += conn.recv(1)
            assert b'200' in header
            conn.sendall(b'GET /json HTTP/1.0\r\nHost: localhost\r\n\r\n')
            result = b''
            while chunk := conn.recv(4096):
                result += chunk
            assert DIRECT_IP.encode() in result
    finally:
        relay.close()


def test_browser_manual_close_cleans_resources():
    class Driver:
        window_handles = []
        quit_called = False
        def quit(self):
            self.quit_called = True
    session = DiagnosticSession()
    driver = Driver()
    session.driver = driver
    session._watch(session.closed)
    assert driver.quit_called and session.driver is None and session.closed.is_set()


@pytest.mark.parametrize('changes_ip', [False, True])
def test_rotating_proxy_checks_ip_before_launch(monkeypatch, tmp_path, changes_ip):
    from types import SimpleNamespace
    from selenium import webdriver
    from app import proxy_check

    chromium = tmp_path / 'chromium.exe'
    chromium.touch()
    cfg = dict(name='Rotativo', protocol='http', host='127.0.0.1', port=8000, service='rotativo')
    previous = '203.0.113.5'
    new_ip = '203.0.113.6'
    probes = []
    launched = []

    def diagnose(*_args, **_kwargs):
        probes.append(True)
        ip = new_ip if changes_ip and len(probes) >= 2 else previous
        return dict(status='conectado', ip=ip, auth='OK', detail='')

    class Driver:
        window_handles = ['test']
        def set_page_load_timeout(self, _timeout): pass
        def get(self, _url): pass
        def find_element(self, *_args):
            return SimpleNamespace(text='{"ip":"203.0.113.6"}')
        def quit(self): pass

    def launch(options):
        assert len(probes) >= 2
        launched.append(options.binary_location)
        return Driver()

    monkeypatch.setattr(proxy_check, 'direct_ip', lambda *_args: DIRECT_IP)
    monkeypatch.setattr(proxy_check, 'diagnose', diagnose)
    monkeypatch.setattr(webdriver, 'Chrome', launch)
    session = DiagnosticSession()
    try:
        if changes_ip:
            result = session.open(cfg, '', 'chromium', 3, chromium_exe=str(chromium), previous_ip=previous)
            assert result['ip'] == new_ip and launched == [str(chromium)]
        else:
            with pytest.raises(RuntimeError, match='manteve o IP anterior'):
                session.open(cfg, '', 'chromium', 3, chromium_exe=str(chromium), previous_ip=previous)
            assert not launched
    finally:
        session.close()
