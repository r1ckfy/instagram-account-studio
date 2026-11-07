"""Infraestrutura de e-mail: DNS (DNS-over-HTTPS), Cloudflare Email Routing (somente leitura),
adaptador do painel de e-mails e verificação de um endereço.

Nada aqui cria endereços, regras ou registros DNS. Falhas viram IntegrationError com
mensagem em português; quem chama (sempre fora da thread da interface) decide o que mostrar.
"""
import csv
import io
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import VERSION
from . import generator as gen
from . import imap_client

DOH_URL = "https://cloudflare-dns.com/dns-query"
CF_API = "https://api.cloudflare.com/client/v4"
OK, FAIL, WARN, INFO = "✅", "❌", "⚠️", "ℹ️"

PANEL_AUTH = {"nenhuma": "Nenhuma", "bearer": "Bearer token", "x-api-key": "Cabeçalho X-API-Key"}
# A API do painel não foi documentada: listar/criar aliases fica desligado até haver documentação.
PANEL_CAN_CREATE = False
PANEL_NO_DOCS = ("A API do painel de e-mails não foi documentada para este projeto. Listar ou criar aliases "
                 "pela API será implementado em `email_infra.panel_list_addresses/panel_create_alias` quando "
                 "endpoints, autenticação e formato de resposta forem fornecidos. Até lá: crie o alias no painel "
                 "e importe/associe o endereço manualmente (TXT/CSV).")


class IntegrationError(Exception):
    pass


class ApiUnavailable(IntegrationError):
    pass


def http_json(url: str, headers: dict | None = None, timeout: float = 10) -> tuple[int, object]:
    """GET simples. Retorna (status HTTP, JSON ou None). Erros de rede viram IntegrationError."""
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": f"InstagramAccountStudio/{VERSION}",
                                               **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            status, body = r.status, r.read(2_000_000)
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read(200_000)
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, TimeoutError):
            raise IntegrationError(f"Tempo limite de {timeout:g}s esgotado.") from None
        raise IntegrationError(f"Não foi possível conectar: {reason}") from None
    except (TimeoutError, OSError) as e:
        raise IntegrationError(f"Falha de conexão: {e}") from None
    try:
        data = json.loads(body) if body else None
    except ValueError:
        data = None
    return status, data


# ------------------------------------------------------------------ DNS
def mx_records(domain: str, timeout: float = 8, doh_url: str = DOH_URL) -> list[str]:
    url = f"{doh_url}?name={urllib.parse.quote(domain)}&type=MX"
    status, data = http_json(url, {"Accept": "application/dns-json"}, timeout)
    if status != 200 or not isinstance(data, dict):
        raise IntegrationError(f"Consulta DNS falhou (HTTP {status}).")
    if data.get("Status") == 3:
        raise IntegrationError(f"O domínio {domain} não existe no DNS (NXDOMAIN).")
    return sorted(a["data"].split()[-1].rstrip(".").lower()
                  for a in data.get("Answer") or [] if a.get("type") == 15)


# ------------------------------------------------------------ Cloudflare
def _cf_get(token: str, path: str, timeout: float, base: str) -> dict:
    status, data = http_json(base + path, {"Authorization": f"Bearer {token}"}, timeout)
    if isinstance(data, dict) and data.get("success"):
        return data
    errors = (data or {}).get("errors") if isinstance(data, dict) else None
    msg = errors[0].get("message", f"HTTP {status}") if errors else f"HTTP {status}"
    if status in (401, 403):
        msg += " — verifique o token (permissão necessária: Zona → Email Routing Rules → Leitura)."
    raise IntegrationError(f"Cloudflare: {msg}")


def _forward_dest(rule: dict) -> str:
    return ", ".join(v for a in rule.get("actions") or [] if a.get("type") == "forward"
                     for v in a.get("value") or [])


def cf_forwarding(token: str, zone_id: str, address: str, timeout: float = 10, base: str = CF_API) -> dict:
    """Consulta (somente leitura) se há regra de encaminhamento para o endereço.
    Retorna {'configured': bool, 'destination': str, 'detail': str}."""
    address = address.strip().lower()
    page = 1
    while True:
        data = _cf_get(token, f"/zones/{zone_id}/email/routing/rules?page={page}&per_page=50", timeout, base)
        for rule in data.get("result") or []:
            if not any(m.get("type") == "literal" and m.get("field") == "to"
                       and (m.get("value") or "").lower() == address for m in rule.get("matchers") or []):
                continue
            dest = _forward_dest(rule)
            if not rule.get("enabled", True):
                return {"configured": False, "destination": dest, "detail": "A regra deste endereço está desativada."}
            if not dest:
                return {"configured": False, "destination": "",
                        "detail": "A regra deste endereço não encaminha (descarta ou envia a um Worker)."}
            return {"configured": True, "destination": dest, "detail": f"Regra específica encaminha para {dest}."}
        info = data.get("result_info") or {}
        if page >= int(info.get("total_pages") or 1):
            break
        page += 1
    catch_all = _cf_get(token, f"/zones/{zone_id}/email/routing/rules/catch_all", timeout, base).get("result") or {}
    dest = _forward_dest(catch_all)
    if catch_all.get("enabled") and dest:
        return {"configured": True, "destination": dest,
                "detail": f"Sem regra específica; a regra catch-all encaminha para {dest}."}
    return {"configured": False, "destination": "",
            "detail": "Nenhuma regra ativa para este endereço e catch-all desligado."}


def cf_test(token: str, zone_id: str, timeout: float = 10, base: str = CF_API) -> str:
    """Confere token + zona lendo a regra catch-all (somente leitura)."""
    catch_all = _cf_get(token, f"/zones/{zone_id}/email/routing/rules/catch_all", timeout, base).get("result") or {}
    dest = _forward_dest(catch_all)
    state = f"ativa, encaminha para {dest}" if catch_all.get("enabled") and dest else "desligada ou sem encaminhamento"
    return f"Token e zona OK. Regra catch-all: {state}."


# ------------------------------------------------------- painel de e-mails
def panel_headers(auth_type: str, credential: str) -> dict:
    if auth_type == "bearer" and credential:
        return {"Authorization": f"Bearer {credential}"}
    if auth_type == "x-api-key" and credential:
        return {"X-API-Key": credential}
    return {}


def panel_test(api_base: str, auth_type: str, credential: str, timeout: float = 10) -> str:
    """Testa se a URL base da API responde. Não presume nenhum endpoint além da própria URL."""
    if not api_base:
        raise ApiUnavailable("URL base da API não configurada. Sem API, use a importação de endereços por TXT/CSV.")
    started = time.monotonic()
    status, _ = http_json(api_base, panel_headers(auth_type, credential), timeout)
    ms = int((time.monotonic() - started) * 1000)
    if status in (401, 403):
        raise IntegrationError(f"A API recusou a credencial (HTTP {status}).")
    if status >= 500:
        raise IntegrationError(f"A API respondeu com erro do servidor (HTTP {status}).")
    return f"A URL da API respondeu HTTP {status} em {ms} ms."


def panel_list_addresses(cfg: dict) -> list[str]:
    raise ApiUnavailable(PANEL_NO_DOCS)


def panel_create_alias(cfg: dict, local_part: str) -> str:
    raise ApiUnavailable(PANEL_NO_DOCS)


def parse_address_file(text: str) -> tuple[list[str], list[str]]:
    """TXT (um por linha) ou CSV (coluna email/endereco/address, ou a primeira). Retorna (válidos, inválidos)."""
    lines = [x for x in text.splitlines() if x.strip() and not x.lstrip().startswith("#")]
    if not lines:
        return [], []
    sep = ";" if lines[0].count(";") >= lines[0].count(",") else ","
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=sep))
    header = [c.strip().lower() for c in rows[0]]
    col = next((header.index(k) for k in ("email", "e-mail", "endereco", "endereço", "address") if k in header), None)
    if col is not None:
        rows = rows[1:]
    values = [r[col or 0].strip() for r in rows if len(r) > (col or 0) and r[col or 0].strip()]
    valid, invalid, seen = [], [], set()
    for v in values:
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        if gen.validate_email(v):
            invalid.append(v)
        else:
            valid.append(key)
    return valid, invalid


# ------------------------------------------------------ verificação geral
def verify_address(address: str, cf_token: str = "", cf_zone: str = "", imap_cfg: dict | None = None,
                   imap_password: str = "", timeout: float = 10,
                   doh_url: str = DOH_URL, cf_base: str = CF_API) -> dict:
    """Checa sintaxe, MX, regra de encaminhamento (se houver token Cloudflare) e a caixa IMAP de destino.
    Retorna {'status': novo status ou None (manter), 'checks': [(ícone, texto)], 'destination': str|None}."""
    checks: list[tuple[str, str]] = []
    if err := gen.validate_email(address):
        return {"status": "pendente", "checks": [(FAIL, f"Sintaxe: {err}")], "destination": None}
    checks.append((OK, f"Sintaxe válida: {address}"))
    problem, forwarding, destination = False, None, None

    domain = address.split("@", 1)[1]
    try:
        mx = mx_records(domain, timeout, doh_url)
        if not mx:
            problem = True
            checks.append((FAIL, f"DNS: {domain} não tem registros MX — mensagens não serão recebidas."))
        elif all(h.endswith(".mx.cloudflare.net") for h in mx):
            checks.append((OK, f"DNS: MX aponta para Cloudflare Email Routing ({', '.join(mx)})."))
        else:
            checks.append((WARN, f"DNS: MX = {', '.join(mx)} (não é Cloudflare Email Routing)."))
    except IntegrationError as e:
        problem = "NXDOMAIN" in str(e)
        checks.append((FAIL if problem else WARN, f"DNS não verificado: {e}"))

    if cf_token and cf_zone:
        try:
            forwarding = cf_forwarding(cf_token, cf_zone, address, timeout, cf_base)
            destination = forwarding["destination"] or None
            checks.append((OK if forwarding["configured"] else FAIL, f"Encaminhamento: {forwarding['detail']}"))
            problem = problem or not forwarding["configured"]
        except IntegrationError as e:
            checks.append((WARN, f"Encaminhamento não verificado: {e}"))
    else:
        checks.append((WARN, "Encaminhamento não verificável: configure o token da Cloudflare (somente leitura) "
                             "em CONFIGURAÇÕES ou marque a regra manualmente."))

    if imap_cfg:
        try:
            msg = imap_client.test_connection(imap_cfg, imap_password)
            checks.append((OK, f"Caixa de destino {imap_cfg['email']}: {msg}"))
        except Exception as e:
            checks.append((FAIL, f"Caixa de destino {imap_cfg['email']}: {imap_client.friendly_error(e)}"))
    else:
        checks.append((WARN, "Nenhuma caixa IMAP de destino definida (CONFIGURAÇÕES → ENCAMINHAMENTO)."))

    checks.append((INFO, "DNS, regra e IMAP corretos não garantem a entrega. Só o teste de recebimento comprova."))
    status = "pendente" if problem else ("encaminhamento" if forwarding and forwarding["configured"] else None)
    return {"status": status, "checks": checks, "destination": destination}
