"""Navegador: abrir páginas para uso manual e o teste Selenium da página DEMO local.

O preenchimento automático só funciona na página demo/cadastro_demo.html:
`fill_demo` recusa qualquer outra URL. O cadastro no Instagram é sempre manual.
"""
import os
import shutil
import subprocess
import threading
from datetime import date
from pathlib import Path

from . import DEMO_PAGE

BROWSERS = {"padrao": "Padrão do sistema", "edge": "Microsoft Edge", "chrome": "Google Chrome",
            "dolphin": "Dolphin Anty", "chromium": "Chromium"}
CHROMIUM_SETTING = "proxy_chromium_exe"  # Reuse paths already saved in the Proxy tab.

_CANDIDATES = {
    "edge": [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
             r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"],
    "chrome": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
               r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
               r"%LocalAppData%\Google\Chrome\Application\chrome.exe"],
}

# Estados exibidos na aba CADASTRO durante o teste demo.
STATES = ["AGUARDANDO", "ABRINDO NAVEGADOR", "CARREGANDO PÁGINA", "PREENCHENDO CAMPOS",
          "AGUARDANDO REVISÃO", "CONCLUÍDO", "INTERROMPIDO", "FALHOU"]


def find_browser(name: str) -> str | None:
    if name == "chromium":
        local = os.getenv("LOCALAPPDATA")
        if not local:
            return None
        installed = Path(local) / "Chromium" / "Application" / "chrome.exe"
        if installed.is_file():
            return str(installed)
        candidates = (
            (int(folder.name.removeprefix("chromium-")), folder / "chrome-win64" / "chrome.exe")
            for folder in (Path(local) / "ms-playwright").glob("chromium-*")
            if folder.name.removeprefix("chromium-").isdigit()
        )
        available = [(revision, exe) for revision, exe in candidates if exe.is_file()]
        return str(max(available)[1]) if available else None
    for path in _CANDIDATES.get(name, []):
        p = os.path.expandvars(path)
        if os.path.isfile(p):
            return p
    return shutil.which({"edge": "msedge", "chrome": "chrome"}.get(name, ""))


def chromium_path(db) -> str:
    return db.get_setting(CHROMIUM_SETTING).strip() or find_browser("chromium") or ""


def require_chromium(path: str) -> str:
    if not path or not Path(path).is_file():
        raise FileNotFoundError("Escolha o executável do Chromium em Configurações → Navegador.")
    return path


class ManagedBrowser:
    """Uma janela de Chrome/Edge aberta pelo app, que o painel consegue encerrar.

    Usa um perfil próprio do app (uma pasta só, a mesma para todas as fichas): assim o navegador
    abre como processo separado do seu navegador do dia a dia e o botão FECHAR atinge só ele.
    """

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.dolphin = None
        self._edge_profile: Path | None = None
        self.name = ""

    @staticmethod
    def command(exe: str, url: str, profile_dir: Path) -> list[str]:
        return [exe, f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check",
                "--new-window", url]

    def start(self, cmd: list[str], name: str):
        if self.running():
            raise RuntimeError(f"{self.name} já está aberto pelo painel. Feche-o antes de abrir outro.")
        self._clear_edge_cookies()
        self.proc = subprocess.Popen(cmd, close_fds=True)
        self.name = name

    def open(self, browser: str, url: str, profile_root: Path, *, chromium_exe: str = ""):
        exe = require_chromium(chromium_exe) if browser == "chromium" else find_browser(browser)
        if not exe:
            raise FileNotFoundError(f"{BROWSERS[browser]} não foi encontrado neste computador.")
        profile = profile_root / browser
        profile.mkdir(parents=True, exist_ok=True)
        self.start(self.command(exe, url, profile), BROWSERS[browser])
        if browser == "edge":
            self._edge_profile = profile_root.resolve() / "edge"

    def running(self) -> bool:
        return self.dolphin is not None or (self.proc is not None and self.proc.poll() is None)

    def _clear_edge_cookies(self):
        root = self._edge_profile
        if root is None:
            return
        if root.resolve() != root:
            raise OSError("A pasta do perfil do Edge foi redirecionada. Confira a pasta de dados do Studio.")
        for profile in (root / "Default", *root.glob("Profile *")):
            for folder in (profile, profile / "Network"):
                for name in ("Cookies", "Cookies-journal", "Cookies-wal", "Cookies-shm"):
                    cookie = folder / name
                    if cookie.resolve().is_relative_to(root):
                        cookie.unlink(missing_ok=True)
        self._edge_profile = None

    def open_dolphin(self, settings, url):
        from .dolphin import open_tab
        if self.running():
            raise RuntimeError("Feche a sessão atual do Navegador primeiro.")
        self._clear_edge_cookies()
        self.dolphin = open_tab(settings)
        try:
            self.dolphin.set_page_load_timeout(30)
            self.dolphin.get(url)
        except Exception:
            self.close()
            raise RuntimeError("A aba abriu no Dolphin Anty, mas a página não carregou.") from None
        self.name = "Dolphin Anty"

    def close(self, timeout: float = 5) -> bool:
        """Encerra o navegador e os processos filhos. False se já não estava aberto."""
        if self.dolphin is not None:
            tab, self.dolphin = self.dolphin, None
            tab.quit()
            return True
        if not self.running():
            self.proc = None
            self._clear_edge_cookies()
            return False
        subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout)
        self.proc = None
        self._clear_edge_cookies()
        return True


def automation_browser(choice: str) -> str:
    """Selenium precisa de um navegador concreto; 'padrão' usa o Edge (presente no Windows)."""
    return choice if choice in ("chrome", "dolphin", "chromium") else "edge"


def make_driver(browser: str, headless: bool = False, *, chromium_exe: str = ""):
    from selenium import webdriver  # import tardio: o app abre mesmo sem Selenium

    chrome_family = browser in ("chrome", "chromium")
    opts = webdriver.ChromeOptions() if chrome_family else webdriver.EdgeOptions()
    if browser == "chromium":
        opts.binary_location = require_chromium(chromium_exe)
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1100,900")
    # Selenium Manager (Selenium 4.6+) localiza/baixa o driver compatível automaticamente.
    return webdriver.Chrome(options=opts) if chrome_family else webdriver.Edge(options=opts)


STEP1 = [("email", "email", "E-mail"), ("full_name", "full_name", "Nome completo"),
         ("username", "username", "Nome de usuário"), ("password", "password", "Senha")]


def fill_demo(driver, data: dict, progress=lambda s: None, timeout: int = 15) -> list[str]:
    """Preenche a página demo local em duas etapas, sem enviar. Retorna os campos preenchidos."""
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import Select, WebDriverWait

    url = driver.current_url
    if not (url.startswith("file:") and url.endswith(DEMO_PAGE.name)):
        raise PermissionError("O preenchimento automático só é permitido na página demo local.")

    wait = WebDriverWait(driver, timeout)

    def find(name, label):
        try:
            return wait.until(EC.element_to_be_clickable((By.NAME, name)))
        except TimeoutException:
            raise RuntimeError(f"Campo '{label}' não encontrado na página demo.") from None

    progress("PREENCHENDO CAMPOS")
    filled = []
    for name, key, label in STEP1:
        value = data.get(key) or ""
        if not value:
            progress(f"Campo sem valor no perfil, ignorado: {label}")
            continue
        el = find(name, label)
        el.clear()
        el.send_keys(value)
        if el.get_attribute("value") != value:
            raise RuntimeError(f"Valor inserido diverge no campo {label}.")
        filled.append(label)
        progress(f"Campo preenchido: {label}")

    find("next", "Botão Avançar").click()
    born = date.fromisoformat(data["birthdate"]) if data.get("birthdate") else None
    if born:
        for name, value, label in [("birthday_day", born.day, "Dia"),
                                   ("birthday_month", born.month, "Mês"),
                                   ("birthday_year", born.year, "Ano")]:
            Select(find(name, label)).select_by_value(str(value))
            if Select(find(name, label)).first_selected_option.get_attribute("value") != str(value):
                raise RuntimeError(f"Valor de nascimento diverge: {label}.")
            filled.append(f"Nascimento ({label})")
        progress("Campo preenchido: Data de nascimento")
    else:
        progress("Perfil sem data de nascimento; etapa 2 ficou para revisão manual.")
    return filled


def run_demo(data: dict, browser: str, stop: threading.Event, progress, *,
             dolphin_settings=None, chromium_exe: str = "") -> str:
    """Executa o teste demo completo em uma thread de trabalho. Retorna o estado final."""
    from selenium.common.exceptions import WebDriverException

    progress("ABRINDO NAVEGADOR")
    if browser == "dolphin":
        from .dolphin import DolphinError, open_tab
        if dolphin_settings is None:
            raise DolphinError("Configure o perfil do Dolphin Anty antes de abrir a demonstração.")
        driver = open_tab(dolphin_settings)
    elif browser == "chromium":
        driver = make_driver(browser, chromium_exe=chromium_exe)
    else:
        driver = make_driver(browser)
    try:
        progress("CARREGANDO PÁGINA")
        driver.get(Path(DEMO_PAGE).as_uri())
        fill_demo(driver, data, progress)
        progress("AGUARDANDO REVISÃO")
        sent = False
        # Espera o usuário revisar/enviar a página demo, fechar a janela ou clicar PARAR.
        while not stop.wait(1):
            try:
                status = driver.execute_script("return document.body.dataset.status || ''")
            except WebDriverException:
                return "CONCLUÍDO" if sent else "INTERROMPIDO"
            if status == "enviado" and not sent:
                sent = True
                progress("CONCLUÍDO")
        return "CONCLUÍDO" if sent else "INTERROMPIDO"
    finally:
        try:
            driver.quit()
        except Exception:
            pass
