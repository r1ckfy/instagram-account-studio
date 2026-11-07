"""VERIFICAR SISTEMA: checagens reais, executadas em thread de trabalho."""
import platform
import socket
import sqlite3
import sys
import tempfile
from importlib import metadata
from pathlib import Path

from . import DEMO_PAGE, browser, security

OK, FAIL, WARN = "✅", "❌", "⚠️"


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder):
            pass
        return True
    except OSError:
        return False


def run(db_path: Path, data_dir: Path, backup_dir: Path, browser_choice: str,
        imap_count: int, check_driver: bool = True, *, dolphin_port: int = 3001,
        chromium_exe: str = "") -> list[tuple[str, str]]:
    r: list[tuple[str, str]] = []
    add = lambda status, text: r.append((status, text))  # noqa: E731

    add(OK, f"Python {platform.python_version()} ({'executável' if getattr(sys, 'frozen', False) else 'desenvolvimento'})")
    for pkg in ("PySide6", "selenium"):
        try:
            add(OK, f"{pkg} {metadata.version(pkg)}")
        except metadata.PackageNotFoundError:
            add(FAIL if pkg == "PySide6" else WARN, f"{pkg} não encontrado no ambiente")

    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        add(OK if result == "ok" else FAIL, f"Banco SQLite {sqlite3.sqlite_version}: integridade '{result}'")
    except sqlite3.Error as e:
        add(FAIL, f"Banco SQLite inacessível: {e}")

    try:
        add(OK if security.decrypt(security.encrypt("teste")) == "teste" else FAIL,
            "Cofre DPAPI do Windows (criptografia de senhas)")
    except OSError as e:
        add(FAIL, f"DPAPI indisponível: {e}")

    for label, folder in (("dados", data_dir), ("logs", data_dir / "logs"), ("backup", backup_dir)):
        add(OK if _writable(folder) else FAIL, f"Permissão de escrita na pasta de {label}: {folder}")

    add(OK if DEMO_PAGE.is_file() else FAIL, f"Página demo local: {DEMO_PAGE.name}")

    found = {b: browser.find_browser(b) for b in ("edge", "chrome")}
    if browser_choice == "chromium":
        found["chromium"] = chromium_exe if chromium_exe and Path(chromium_exe).is_file() else None
    for b, path in found.items():
        add(OK if path else WARN, f"{browser.BROWSERS[b]}: {path or 'não encontrado'}")
    if browser_choice == "dolphin":
        try:
            socket.create_connection(("127.0.0.1", dolphin_port), timeout=2).close()
            add(OK, f"Porta local do Dolphin Anty acessível ({dolphin_port}).")
        except OSError:
            add(WARN, f"Porta do Dolphin Anty indisponível ({dolphin_port}). Abra o Dolphin e confira a porta em Health.")
    elif browser_choice != "padrao" and not found.get(browser_choice):
        add(FAIL, f"O navegador selecionado ({browser.BROWSERS[browser_choice]}) não está instalado")

    if check_driver and browser_choice != "dolphin":
        target = browser.automation_browser(browser_choice)
        try:
            options = {"chromium_exe": chromium_exe} if target == "chromium" else {}
            driver = browser.make_driver(target, headless=True, **options)
            version = driver.capabilities.get("browserVersion", "?")
            driver.quit()
            add(OK, f"Driver Selenium para {browser.BROWSERS[target]} (versão {version})")
        except Exception as e:
            add(FAIL, f"Driver Selenium para {browser.BROWSERS[target]} falhou: {str(e).splitlines()[0][:160]}")

    try:
        socket.create_connection(("www.instagram.com", 443), timeout=5).close()
        add(OK, "Conectividade com a internet (www.instagram.com:443)")
    except OSError as e:
        add(FAIL, f"Sem conectividade com www.instagram.com:443 ({e})")

    add(OK if imap_count else WARN,
        f"{imap_count} caixa(s) IMAP configurada(s)" if imap_count else "Nenhuma caixa IMAP configurada (aba IMAP)")
    return r
