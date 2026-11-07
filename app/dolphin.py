"""Open an app-owned tab in a Dolphin Anty profile over its local API."""
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


class DolphinError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    profile: str
    port: int
    driver_path: str

    @classmethod
    def load(cls, db):
        profile = db.get_setting("dolphin_profile").strip()
        if not re.fullmatch(r"[0-9]+", profile):
            raise DolphinError("Informe o ID numérico do perfil em Configurações → Dolphin Anty.")
        try:
            port = int(db.get_setting("dolphin_port", "3001"))
        except ValueError:
            port = 0
        if not 1 <= port <= 65535:
            raise DolphinError("Confira a porta da API local em Configurações → Dolphin Anty.")
        driver_path = db.get_setting("dolphin_driver").strip()
        if driver_path and not Path(driver_path).is_file():
            raise DolphinError("O arquivo do ChromeDriver configurado não foi encontrado.")
        return cls(profile, port, driver_path)


def start_profile(settings):
    connection = HTTPConnection("127.0.0.1", settings.port, timeout=30)
    try:
        connection.request("GET", f"/v1.0/browser_profiles/{settings.profile}/start?automation=1")
        response = connection.getresponse()
        if response.status == 402:
            raise DolphinError(
                "O Dolphin Anty exige um plano com automação pela API (HTTP 402). "
                "Confira a assinatura no Dolphin ou selecione Microsoft Edge ou Google Chrome no Studio."
            )
        if response.status in (401, 403):
            raise DolphinError("Entre na sua conta no Dolphin Anty e confira o acesso à automação pela API.")
        if response.status != 200:
            raise DolphinError(f"O Dolphin Anty recusou a abertura do perfil (HTTP {response.status}).")
        payload = json.loads(response.read(65536))
    except (OSError, HTTPException, ValueError):
        raise DolphinError("Abra o Dolphin Anty e confira a porta da API local na janela Health.") from None
    finally:
        connection.close()
    automation = payload.get("automation") if isinstance(payload, dict) else None
    port = automation.get("port") if isinstance(automation, dict) else None
    if type(port) is not int or not 1 <= port <= 65535 or not payload.get("success"):
        raise DolphinError("O perfil não forneceu uma porta de automação. Confira o ID, o plano e o estado do perfil.")
    return port


def running_port(profile):
    appdata = os.getenv("APPDATA")
    if not appdata:
        return None
    active_port = Path(appdata) / "dolphin_anty" / "browser_profiles" / profile / "data_dir" / "DevToolsActivePort"
    try:
        port, endpoint, *_ = active_port.read_text(encoding="utf-8").splitlines()
        port = int(port)
        if not 1 <= port <= 65535 or not endpoint.startswith("/devtools/browser/"):
            return None
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/json/version")
            response = connection.getresponse()
            if response.status == 200:
                websocket = json.loads(response.read(65536))["webSocketDebuggerUrl"]
                if isinstance(websocket, str) and urlsplit(websocket).path == endpoint:
                    return port
        finally:
            connection.close()
    except (OSError, HTTPException, ValueError, KeyError, TypeError):
        return None
    return None


class ProfileTab:
    """Expose WebDriver operations while limiting cleanup to the tab we opened."""

    def __init__(self, driver):
        self.driver = driver
        driver.switch_to.new_window("tab")
        self.handle = driver.current_window_handle

    def __getattr__(self, name):
        return getattr(self.driver, name)

    @property
    def window_handles(self):
        return [self.handle] if self.handle in self.driver.window_handles else []

    def quit(self):
        from selenium.common.exceptions import WebDriverException
        try:
            if self.window_handles:
                self.driver.switch_to.window(self.handle)
                self.driver.close()
        except WebDriverException:
            pass
        finally:
            self.driver.service.stop()


def open_tab(settings):
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.chrome.service import Service
    options = webdriver.ChromeOptions()
    port = running_port(settings.profile) or start_profile(settings)
    options.debugger_address = f"127.0.0.1:{port}"
    service = Service(executable_path=settings.driver_path or None)
    try:
        return ProfileTab(webdriver.Chrome(service=service, options=options))
    except (OSError, WebDriverException):
        service.stop()
        raise DolphinError("Falha ao conectar ao perfil. Confira a versão do ChromeDriver em Configurações.") from None
