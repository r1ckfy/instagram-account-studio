"""Signup session: navigation and field filling, without submission."""
import threading
import re
from datetime import date
from . import INSTAGRAM_SIGNUP_URL, browser
from .dolphin import DolphinError, open_tab

STATES = ('PENDENTE', 'DADOS VALIDADOS', 'NAVEGADOR ABERTO', 'AGUARDANDO USUÁRIO',
          'AGUARDANDO VERIFICAÇÃO', 'CONCLUÍDO', 'FALHOU', 'INTERROMPIDO')


def validate(data):
    missing = [key for key in ('full_name', 'username', 'email', 'password', 'birthdate') if not str(data.get(key) or '').strip()]
    if missing:
        raise ValueError('Campos obrigatórios ausentes: ' + ', '.join(missing))
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', data['email']):
        raise ValueError('E-mail inválido.')
    if not re.fullmatch(r'[A-Za-z0-9._]{1,30}', data['username']):
        raise ValueError('Username invalido: use ate 30 letras, numeros, pontos ou sublinhados.')
    try:
        born = date.fromisoformat(data['birthdate'])
    except ValueError:
        raise ValueError('Nascimento inválido.') from None
    if born >= date.today():
        raise ValueError('Nascimento deve ser anterior à data atual.')


class SignupBrowser:
    def __init__(self):
        self.driver = None
        self.lock = threading.RLock()

    def open(self, choice, dolphin_settings=None, *, chromium_exe=""):
        with self.lock:
            if self.driver:
                raise RuntimeError('Já existe um navegador de cadastro aberto.')
            try:
                if choice == "dolphin":
                    self.driver = open_tab(dolphin_settings)
                elif choice == "chromium":
                    self.driver = browser.make_driver(choice, chromium_exe=chromium_exe)
                else:
                    self.driver = browser.make_driver(choice)
                self.driver.set_page_load_timeout(30)
                self.driver.get(INSTAGRAM_SIGNUP_URL)
                from selenium.webdriver.support.ui import WebDriverWait
                WebDriverWait(self.driver, 15).until(lambda d: d.execute_script('return document.readyState') in ('interactive', 'complete'))
            except DolphinError:
                self.close()
                raise
            except Exception:
                self.close()
                raise RuntimeError('Falha ao iniciar navegador/carregar página oficial. Confira navegador, driver e rede.') from None

    def fill(self, data):
        from .instagram_fill import fill
        with self.lock:
            if not self.alive():
                raise RuntimeError('Navegador fechado.')
            return fill(self.driver, data)

    def alive(self):
        with self.lock:
            try:
                return bool(self.driver and self.driver.window_handles)
            except Exception:
                return False

    def submit(self, data, claim, cancelled):
        from .instagram_fill import submit
        with self.lock:
            return submit(self.driver, data, claim, cancelled)

    def feedback(self, data):
        from .instagram_fill import feedback
        with self.lock:
            return feedback(self.driver, data)

    def reopen(self):
        with self.lock:
            if not self.alive():
                raise RuntimeError('Navegador fechado.')
            self.driver.get(INSTAGRAM_SIGNUP_URL)

    def close(self):
        with self.lock:
            if self.driver:
                try:
                    self.driver.quit()
                finally:
                    self.driver = None
