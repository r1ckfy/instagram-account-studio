"""Isolated browser diagnostic relay. No upstream failure permits direct fallback."""
import base64
import ipaddress
import json
import select
import socket
import socketserver
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

import socks
from . import proxy_check


class RotationError(RuntimeError):
    pass


class Relay(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cfg, password, timeout):
        self.cfg, self.password, self.timeout = dict(cfg), password, timeout
        self.connections = set()
        self.guard = threading.Lock()
        self.stopping = False
        self.last_error = ""
        super().__init__(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def process_request_thread(self, request, client_address):
        with self.guard:
            if self.stopping:
                request.close()
                return
            self.connections.add(request)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.guard:
                self.connections.discard(request)

    def connect(self, host, port, tunnel=True):
        c = self.cfg
        upstream = None
        try:
            if c['protocol'] == 'socks5':
                upstream = socks.socksocket()
                upstream.settimeout(self.timeout)
                upstream.set_proxy(socks.SOCKS5, c['host'].strip('[]'), int(c['port']), rdns=True,
                                   username=c.get('username') or None, password=self.password or None)
                upstream.connect((host, port))
            else:
                upstream = socket.create_connection((c['host'].strip('[]'), int(c['port'])), self.timeout)
                if c['protocol'] == 'https':
                    upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=c['host'].strip('[]'))
                if tunnel:
                    authority = f"[{host}]:{port}" if ':' in host else f"{host}:{port}"
                    auth = ''
                    if c.get('username'):
                        token = base64.b64encode(f"{c['username']}:{self.password}".encode()).decode()
                        auth = f'Proxy-Authorization: Basic {token}\r\n'
                    upstream.sendall(f'CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n{auth}\r\n'.encode())
                    header = bytearray()
                    while not header.endswith(b'\r\n\r\n'):
                        part = upstream.recv(1)
                        if not part or len(header) > 65536:
                            raise OSError('Resposta CONNECT inválida')
                        header.extend(part)
                    status = bytes(header).split(b'\r\n', 1)[0].split()[1]
                    if status == b'407':
                        raise proxy_check.AuthFailed('Autenticação recusada (407)')
                    if status != b'200':
                        raise OSError('Proxy recusou o túnel CONNECT')
            with self.guard:
                if self.stopping:
                    raise OSError('Sessão encerrada')
                self.connections.add(upstream)
            return upstream
        except Exception:
            if upstream:
                upstream.close()
            raise

    def close(self):
        with self.guard:
            self.stopping = True
            for conn in list(self.connections):
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                conn.close()
            self.connections.clear()
        self.shutdown()
        self.server_close()
        self.thread.join(2)
        self.password = ''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.timeout)

    def do_CONNECT(self):
        self._forward(True)

    def do_GET(self):
        self._forward(False)

    def _forward(self, tunnel):
        upstream = None
        try:
            target = urlsplit(('https://' if tunnel else '') + self.path)
            if not target.hostname or target.username or target.password:
                raise ValueError('Destino inválido')
            if not tunnel and target.scheme != 'http':
                raise ValueError('Invalid target protocol')
            upstream = self.server.connect(target.hostname, target.port or (443 if tunnel else 80), tunnel)
            if tunnel:
                self.send_response(200)
                self.end_headers()
            else:
                cfg = self.server.cfg
                path = self.path if cfg['protocol'] != 'socks5' else (target.path or '/') + (('?' + target.query) if target.query else '')
                auth = ''
                if cfg['protocol'] != 'socks5' and cfg.get('username'):
                    token = base64.b64encode(f"{cfg['username']}:{self.server.password}".encode()).decode()
                    auth = f'Proxy-Authorization: Basic {token}\r\n'
                upstream.sendall(f'GET {path} HTTP/1.1\r\nHost: {target.netloc}\r\nConnection: close\r\n{auth}\r\n'.encode())
            self.connection.settimeout(self.server.timeout)
            while not self.server.stopping:
                ready, _, _ = select.select([self.connection, upstream], [], [], 0.5)
                if isinstance(upstream, ssl.SSLSocket) and upstream.pending() and upstream not in ready:
                    ready.append(upstream)
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except Exception as exc:
            self.server.last_error = ('Autenticação recusada' if (isinstance(exc, (proxy_check.AuthFailed, socks.SOCKS5AuthError)) or proxy_check.friendly_error(exc)[1])
                                      else 'Falha no túnel do proxy; conexão bloqueada')
            if upstream is None:
                try:
                    self.send_error(502, 'Proxy connection failed')
                except OSError:
                    pass
        finally:
            if upstream:
                with self.server.guard:
                    self.server.connections.discard(upstream)
                upstream.close()


class DiagnosticSession:
    def __init__(self):
        self.driver = self.relay = self.profile = None
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.cfg = None
        self.direct = ''
        self.last_result = None

    def open(self, cfg, password, browser='edge', timeout=10, *, chromium_exe='', previous_ip=''):
        with self.lock:
            if self.driver:
                raise RuntimeError('Feche o navegador de teste atual primeiro.')
            if message := proxy_check.validate(cfg):
                raise ValueError(message)
            if browser == 'chromium' and (not chromium_exe or not Path(chromium_exe).is_file()):
                raise ValueError('Selecione o executável do Chromium antes de abrir o teste.')
            self.closed = threading.Event()
            self.last_result = None
            self.direct = ''
            phase = 'consulta direta de IP'
            self.cfg = dict(cfg)
            self.timeout = timeout
            try:
                self.direct = proxy_check.direct_ip(timeout)
                phase = 'autenticação/conectividade do proxy'
                preflight = proxy_check.diagnose(cfg, password, timeout, samples=1, direct=self.direct)
                self.last_result = preflight
                baseline = ''
                if cfg['service'] == 'rotativo' and preflight['ip']:
                    phase = 'confirmação da troca de IP'
                    baseline = previous_ip or preflight['ip']
                    for _ in range(3):
                        if not preflight['ip'] or preflight['ip'] not in (baseline, self.direct):
                            break
                        preflight = proxy_check.diagnose(cfg, password, timeout, samples=1, direct=self.direct)
                        self.last_result = preflight
                    if preflight['ip'] and preflight['ip'] in (baseline, self.direct):
                        raise RotationError('O provedor manteve o IP anterior nas novas conexões.')
                if not preflight['ip']:
                    raise RuntimeError(preflight['detail'])
                phase = 'inicialização do navegador/driver'
                self.relay = Relay(cfg, password, timeout)
                self.profile = tempfile.TemporaryDirectory(prefix='proxy-diagnostic-')
                from selenium import webdriver
                chrome_family = browser in ('chrome', 'chromium')
                opts = webdriver.ChromeOptions() if chrome_family else webdriver.EdgeOptions()
                if browser == 'chromium':
                    opts.binary_location = chromium_exe
                for flag in (f'--user-data-dir={self.profile.name}',
                             f'--proxy-server=http://127.0.0.1:{self.relay.server_address[1]}',
                             '--proxy-bypass-list=<-loopback>', '--disable-quic',
                             '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
                             '--disable-background-networking', '--no-first-run'):
                    opts.add_argument(flag)
                self.driver = webdriver.Chrome(options=opts) if chrome_family else webdriver.Edge(options=opts)
                self.driver.set_page_load_timeout(timeout)
                phase = 'verificação do IP no navegador'
                result = self.verify(previous_ip=baseline)
                threading.Thread(target=self._watch, args=(self.closed,), daemon=True).start()
                return result
            except Exception as exc:
                if self.last_result and not self.last_result['ip']:
                    detail = self.last_result['detail']
                    for secret in (password, cfg.get('username', '')):
                        if secret:
                            detail = detail.replace(secret, '[redigido]')
                    self.last_result['detail'] = detail
                if not self.last_result or self.last_result.get('status') != 'desconectado':
                    self.last_result = {'status': 'desconectado', 'ip': '', 'geo': '', 'latency': None,
                                        'auth': (self.last_result or {}).get('auth', 'Não verificada'),
                                        'detail': str(exc) if isinstance(exc, RotationError) else
                                        f'Falha na etapa: {phase}. ({type(exc).__name__})'}
                self.close()
                # Never expose webdriver errors, URLs, or upstream credentials to logs/UI.
                raise RuntimeError('Não foi possível iniciar/verificar o navegador pelo proxy. '
                                   'Confira conectividade, autenticação e instalação do navegador/driver. '
                                   f'Etapa: {phase}. {self.last_result["detail"]}') from None

    def verify(self, *, previous_ip=''):
        with self.lock:
            if not self.driver:
                raise RuntimeError('Nenhum navegador de teste ativo.')
            try:
                self.direct = proxy_check.direct_ip(self.timeout)
                started = time.monotonic()
                self.driver.get(proxy_check.IP_SERVICE + ('&' if '?' in proxy_check.IP_SERVICE else '?') + f'_diag={time.time_ns()}')
                data = json.loads(self.driver.find_element('tag name', 'body').text)
                observed = str(ipaddress.ip_address(data['ip']))
                if previous_ip and observed in (previous_ip, self.direct):
                    raise RotationError('O navegador não confirmou um IP diferente do anterior e do direto.')
                elapsed = int((time.monotonic() - started) * 1000)
                same = observed == self.direct
                return {'status': 'instavel' if same else 'conectado', 'ip': observed, 'direct': self.direct,
                        'geo': proxy_check.geo_text(data), 'latency': {'avg': elapsed},
                        'auth': 'OK' if self.cfg.get('username') else 'Sem autenticação',
                        'detail': ('Novo IP confirmado no navegador pelo proxy rotativo.' if previous_ip else
                                   'IP igual ao direto: passagem pelo proxy não confirmada.' if same else
                                   'IP diferente do direto, observado na página pelo navegador via proxy.'),
                        'samples': '1/1'}
            except Exception as exc:
                detail = str(exc) if isinstance(exc, RotationError) else (self.relay.last_error if self.relay else '')
                self.last_result = {'status': 'desconectado', 'ip': '', 'geo': '', 'latency': None,
                                    'auth': 'Recusada' if 'Autenticação' in detail else 'Não verificada',
                                    'detail': detail or 'Falha ao obter IP pelo navegador; sessão encerrada.'}
                self.close()
                raise RuntimeError(detail or 'Falha ao verificar IP no navegador; sessão encerrada, sem fallback direto.') from None

    def _watch(self, closed):
        while not closed.wait(1):
            with self.lock:
                try:
                    if self.closed is not closed or not self.driver or not self.driver.window_handles:
                        break
                except Exception:
                    break
        with self.lock:
            if self.closed is closed:
                self.close()

    def close(self):
        with self.lock:
            self.closed.set()
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            if self.relay:
                self.relay.close()
                self.relay = None
            if self.profile:
                try:
                    self.profile.cleanup()
                except OSError:
                    pass
                self.profile = None
