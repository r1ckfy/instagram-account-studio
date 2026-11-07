"""Diagnóstico de proxies para testes manuais de conectividade.

Cada teste abre um pool próprio, faz algumas requisições a um serviço de IP público e fecha tudo.
Não altera proxy do sistema, variáveis de ambiente nem o navegador, e não tem vínculo com perfis
ou com qualquer automação.
"""
import json
import re
import statistics
import time
from pathlib import Path

import urllib3
from urllib3.contrib.socks import SOCKSProxyManager

from . import VERSION

PROTOCOLS = {"http": "HTTP", "https": "HTTPS", "socks5": "SOCKS5"}
SERVICES = {"fixo": "Fixo", "rotativo": "Rotativo (endpoint do provedor)"}
STATUSES = {"nao_testado": "NÃO TESTADO", "conectado": "✅ CONECTADO",
            "instavel": "⚠️ INSTÁVEL", "desconectado": "❌ DESCONECTADO"}
IP_SERVICE = "https://ipinfo.io/json"  # resposta: ip, city, region, country, org
SAMPLES = 3
SLOW_MS = 3000
EXPORT_FIELDS = ("name", "protocol", "host", "port", "username", "service", "notes")

_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$|^\[[0-9A-Fa-f:]+\]$")


def validate(cfg: dict) -> str | None:
    if not cfg.get("name", "").strip():
        return "Informe um nome para a conexão."
    if cfg.get("protocol") not in PROTOCOLS:
        return "Protocolo deve ser HTTP, HTTPS ou SOCKS5."
    if not _HOST_RE.match(cfg.get("host", "")):
        return "Host inválido (use nome ou IP, sem http:// e sem porta)."
    if not 1 <= int(cfg.get("port") or 0) <= 65535:
        return "Porta deve estar entre 1 e 65535."
    if cfg.get("service") not in SERVICES:
        return "Tipo de serviço inválido."
    return None


def _pool(cfg: dict, password: str, timeout: float):
    t = urllib3.Timeout(connect=timeout, read=timeout)
    user = cfg.get("username") or ""
    if cfg["protocol"] == "socks5":
        # socks5h: o DNS do destino é resolvido pelo próprio proxy
        return SOCKSProxyManager(f"socks5h://{cfg['host']}:{cfg['port']}", username=user or None,
                                 password=password or None, timeout=t, retries=False)
    headers = urllib3.make_headers(proxy_basic_auth=f"{user}:{password}") if user else None
    # "https" = conexão TLS até o próprio proxy; "http" = proxy HTTP comum (túnel CONNECT para HTTPS)
    return urllib3.ProxyManager(f"{cfg['protocol']}://{cfg['host']}:{cfg['port']}", proxy_headers=headers,
                                timeout=t, retries=False)


class AuthFailed(Exception):
    pass


def _fetch_ip(pool, url: str) -> tuple[dict, int]:
    started = time.monotonic()
    r = pool.request("GET", url, headers={"Accept": "application/json",
                                          "User-Agent": f"InstagramAccountStudio/{VERSION}"})
    ms = int((time.monotonic() - started) * 1000)
    if r.status == 407:
        raise AuthFailed("O proxy recusou usuário/senha (HTTP 407).")
    if r.status != 200:
        raise RuntimeError(f"Serviço de IP respondeu HTTP {r.status}.")
    try:
        data = json.loads(r.data)
    except ValueError:
        raise RuntimeError("Serviço de IP devolveu uma resposta inválida.") from None
    if not data.get("ip"):
        raise RuntimeError("Serviço de IP não informou o endereço.")
    return data, ms


def friendly_error(e: Exception) -> tuple[str, bool]:
    """(mensagem em português, falha de autenticação?)"""
    if isinstance(e, AuthFailed):
        return str(e), True
    text = str(e)
    low = text.lower()
    if "407" in text or "proxy authentication" in low:
        return "O proxy recusou usuário/senha (HTTP 407).", True
    if "socks" in low and ("auth" in low or "0x01" in low or "username" in low):
        return "O proxy SOCKS5 recusou a autenticação.", True
    if isinstance(e, urllib3.exceptions.ConnectTimeoutError) or "timed out" in low or "timeout" in low:
        return "Tempo limite esgotado ao conectar.", False
    if "refused" in low or "10061" in low:
        return "Conexão recusada pelo host/porta do proxy.", False
    if "getaddrinfo" in low or "name resolution" in low or "11001" in low:
        return "Host do proxy não encontrado no DNS.", False
    if isinstance(e, urllib3.exceptions.SSLError) or "ssl" in low:
        return "Erro de TLS. Confira se o tipo (HTTP/HTTPS) está correto.", False
    if isinstance(e, urllib3.exceptions.ProxyError):
        return f"O proxy falhou: {text.split(':')[-1].strip()[:120]}", False
    return f"{type(e).__name__}: {text[:160]}", False


def geo_text(data: dict) -> str:
    place = ", ".join(x for x in (data.get("city"), data.get("region"), data.get("country")) if x)
    return " • ".join(x for x in (place, data.get("org")) if x)


def direct_ip(timeout: float = 10, url: str | None = None) -> str:
    """IP público sem proxy, para comparação."""
    url = url or IP_SERVICE
    pool = urllib3.PoolManager(timeout=urllib3.Timeout(connect=timeout, read=timeout), retries=False)
    try:
        return _fetch_ip(pool, url)[0]["ip"]
    finally:
        pool.clear()


def diagnose(cfg: dict, password: str, timeout: float = 10, samples: int = SAMPLES,
             url: str | None = None, direct: str = "") -> dict:
    """Faz `samples` requisições pelo proxy e classifica a conexão."""
    url = url or IP_SERVICE
    pool = _pool(cfg, password, timeout)
    results = []
    try:
        for _ in range(samples):
            try:
                data, ms = _fetch_ip(pool, url)
                results.append({"ok": True, "ip": data["ip"], "geo": geo_text(data), "ms": ms})
            except Exception as e:
                msg, auth = friendly_error(e)
                results.append({"ok": False, "error": msg, "auth": auth})
                if auth:
                    break  # não insiste com credencial recusada
    finally:
        pool.clear()

    ok = [r for r in results if r["ok"]]
    errors = list(dict.fromkeys(r["error"] for r in results if not r["ok"]))
    ips = list(dict.fromkeys(r["ip"] for r in ok))
    notes = []
    latency = None
    if ok:
        times = [r["ms"] for r in ok]
        latency = {"avg": int(statistics.mean(times)), "min": min(times), "max": max(times)}
    if not ok:
        status = "desconectado"
    elif len(ok) < len(results) or statistics.median(r["ms"] for r in ok) > SLOW_MS:
        status = "instavel"
    else:
        status = "conectado"
    if len(ips) > 1:
        if cfg.get("service") == "fixo":
            status = "instavel"
            notes.append("O IP mudou entre as amostras, mas a conexão está cadastrada como fixa.")
        else:
            notes.append(f"{len(ips)} IPs diferentes observados nas amostras (esperado em endpoint rotativo).")
    if direct and direct in ips:
        status = "instavel"
        notes.append("O IP observado é o mesmo da conexão sem proxy: o tráfego pode não estar passando pelo proxy.")
    if any(r.get("auth") for r in results):
        auth = "Recusada"
    elif ok:
        auth = "OK" if cfg.get("username") else "Sem autenticação"
    else:
        auth = "Não verificada"
    return {"status": status, "ip": ips[-1] if ips else "", "ips": ips, "geo": ok[-1]["geo"] if ok else "",
            "latency": latency, "auth": auth, "samples": f"{len(ok)}/{len(results)}",
            "detail": " ".join(errors + notes) or "Todas as amostras responderam.", "protocol": cfg["protocol"]}


# --------------------------------------------------------- importar/exportar
def export_configs(rows: list[dict], path: Path) -> int:
    """JSON sem senhas."""
    data = [{k: r[k] for k in EXPORT_FIELDS} for r in rows]
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(data)


_LINE_RE = re.compile(r"^(?:(?P<proto>https?|socks5h?)://)?(?:(?P<user>[^:@\s]+)(?::(?P<pw>[^@\s]*))?@)?"
                      r"(?P<host>[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]):(?P<port>\d{1,5})$")


def parse_import(text: str) -> tuple[list[dict], list[str]]:
    """JSON exportado pelo app, ou TXT com uma conexão por linha: [protocolo://][usuario@]host:porta.
    Senhas presentes no arquivo são descartadas (cadastre-as na aba). Retorna (conexões, avisos)."""
    warnings: list[str] = []
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            items = json.loads(stripped)
        except ValueError as e:
            raise ValueError(f"JSON inválido: {e}") from None
        rows = [{"name": str(i.get("name", "")).strip(), "protocol": str(i.get("protocol", "http")).lower(),
                 "host": str(i.get("host", "")).strip(), "port": int(i.get("port") or 0),
                 "username": str(i.get("username", "")), "service": i.get("service", "fixo"),
                 "notes": str(i.get("notes", ""))} for i in items if isinstance(i, dict)]
    else:
        rows = []
        for n, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _LINE_RE.match(line)
            if not m:
                warnings.append(f"Linha {n} ignorada: formato não reconhecido.")
                continue
            if m.group("pw"):
                warnings.append(f"Linha {n}: senha descartada — cadastre-a na aba PROXY.")
            proto = {"https": "https", "socks5": "socks5", "socks5h": "socks5"}.get(
                (m.group("proto") or "").lower(), "http")
            rows.append({"name": f"{m.group('host')}:{m.group('port')}", "protocol": proto,
                         "host": m.group("host"), "port": int(m.group("port")), "username": m.group("user") or "",
                         "service": "fixo", "notes": f"Importado (linha {n})"})
    valid = []
    for r in rows:
        if err := validate(r):
            warnings.append(f"{r.get('name') or r.get('host')}: {err}")
        else:
            valid.append(r)
    return valid, warnings
