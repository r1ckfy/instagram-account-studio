"""Fill only visible signup fields; never submit or advance security screens."""
from datetime import date
import unicodedata
from urllib.parse import urlsplit

FIELDS = {'email': ('emailOrPhone', 'email'), 'full_name': ('fullName', 'full_name'),
          'username': ('username',), 'password': ('password',)}


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text or '') if not unicodedata.combining(c)).strip().casefold()

LABELS = {
    'email': ('Numero de celular ou email', 'Mobile number or email', 'Email address', 'Email'),
    'full_name': ('Nome completo', 'Full name'),
    'username': ('Nome de usuario', 'Username'),
    'password': ('Senha', 'Password'),
    'day': ('Selecionar o dia', 'Select day', 'Day'),
    'month': ('Selecionar o mes', 'Select month', 'Month'),
    'year': ('Selecionar o ano', 'Select year', 'Year'),
}
MONTHS = ('janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro'.split(),
          'january february march april may june july august september october november december'.split())


def allowed(url):
    target = urlsplit(url)
    return (target.scheme == 'https' and target.hostname in ('www.instagram.com', 'instagram.com')
            and target.path.rstrip('/') in ('/accounts/emailsignup', '/accounts/signup'))


def visible(driver, names, key):
    from selenium.webdriver.common.by import By
    for name in names:
        for element in driver.find_elements(By.NAME, name):
            if element.is_displayed() and element.is_enabled():
                return element
    if key:
        accepted = {normalized(t) for t in LABELS[key]}
        for element in driver.find_elements(By.CSS_SELECTOR, 'input,select,div[role="combobox"]'):
            if not element.is_displayed() or not element.is_enabled():
                continue
            texts = [element.get_attribute('aria-label') or '', element.get_attribute('placeholder') or '']
            texts.extend(driver.execute_script("return Array.from(arguments[0].labels || []).map(e => e.innerText)", element) or [])
            if any(normalized(text) in accepted for text in texts):
                return element
    return False


def birthday_fields(data):
    born = date.fromisoformat(data["birthdate"])
    return (("day", ("birthday_day", "day"), born.day),
            ("month", ("birthday_month", "month"), born.month),
            ("year", ("birthday_year", "year"), born.year))


def birthday_targets(key, value):
    targets = {str(value)}
    if key == "month":
        targets.update(months[value - 1] for months in MONTHS)
    return targets


def fill(driver, data, timeout=12):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.common.exceptions import TimeoutException, WebDriverException
    if not allowed(driver.current_url):
        return {'filled': [], 'missing': list(FIELDS), 'note': 'Página fora do formulário de cadastro. Resolva login/verificação manualmente e tente novamente.'}
    result = {'filled': [], 'missing': [], 'note': ''}
    for key, names in FIELDS.items():
        try:
            element = WebDriverWait(driver, timeout).until(lambda _: visible(driver, names, key))
            # Check again before each interaction in case navigation occurred while waiting.
            if not allowed(driver.current_url):
                result['missing'].extend(k for k in FIELDS if k not in result['filled'])
                break
            element.click()
            element.send_keys(Keys.CONTROL, 'a')
            element.send_keys(Keys.BACKSPACE)
            element.send_keys(data[key])
            element.send_keys(Keys.TAB)
            if element.get_attribute('value') == data[key]:
                result['filled'].append(key)
            else:
                result['missing'].append(key)
        except (TimeoutException, WebDriverException):
            result['missing'].append(key)
    # Birthday is filled only if already visible. No Next, Sign up, or submit is clicked.
    for key, names, value in birthday_fields(data):
        element = None
        try:
            if not allowed(driver.current_url):
                break
            element = visible(driver, names, key)
            if element and element.tag_name.lower() == 'select':
                Select(element).select_by_value(str(value))
                if Select(element).first_selected_option.get_attribute('value') == str(value):
                    result['filled'].append(key)
            elif element and element.get_attribute('role') == 'combobox':
                element.click()
                targets = birthday_targets(key, value)
                def matching_option(_):
                    return next((o for o in driver.find_elements(By.CSS_SELECTOR, '[role="option"]')
                                 if normalized(o.text) in targets), False)
                option = WebDriverWait(driver, 3).until(matching_option)
                driver.execute_script('arguments[0].scrollIntoView({block:"nearest"})', option)
                option.click()
                text = normalized(element.text)
                if any(t in text.split() or t == text for t in targets):
                    result['filled'].append(key)
                else:
                    result['missing'].append(key)
        except (WebDriverException, TimeoutException):
            result['missing'].append(key)
            try:
                if element:
                    element.send_keys(Keys.ESCAPE)
            except WebDriverException:
                pass
        # No submit/advance interaction is performed.
    result['missing'] = list(dict.fromkeys(result['missing']))
    result['note'] = ('Campos não preenchidos: ' + ', '.join(result['missing']) + '. Confira cookies, formulário ou verificações e tente novamente.'
                      if result['missing'] else 'Campos preenchidos e conferidos. Revise antes de enviar. Nascimento será preenchido somente quando seus campos estiverem visíveis.')
    return result

def submit(driver, data, claim, cancelled):
    """Verify the complete form and reserve one attempt before clicking."""
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    if not allowed(driver.current_url):
        return "blocked", "Abra o formulário oficial de cadastro para continuar."
    try:
        for key, names in FIELDS.items():
            element = visible(driver, names, key)
            if not element or element.get_attribute("value") != data[key]:
                return "blocked", f"Confira o campo {key} antes do envio."
        for key, names, value in birthday_fields(data):
            element = visible(driver, names, key)
            if not element:
                return "blocked", "O formulário precisa exibir os três campos de nascimento."
            if element.tag_name.lower() == "select":
                matches = element.get_attribute("value") == str(value)
            else:
                matches = bool(birthday_targets(key, value).intersection(normalized(element.text).split()))
            if not matches:
                return "blocked", "O nascimento exibido difere da ficha."
        labels = {"enviar", "sign up", "cadastre-se", "cadastrar", "criar conta", "create account"}
        controls = []
        for control in driver.find_elements(By.CSS_SELECTOR, 'button,input[type="submit"],[role="button"]'):
            if control.is_displayed() and control.is_enabled() and control.get_attribute("aria-disabled") != "true":
                title = normalized(control.text or control.get_attribute("value") or control.get_attribute("aria-label"))
                if title in labels:
                    controls.append(control)
        if len(controls) != 1 or not allowed(driver.current_url):
            return "blocked", "O botão de envio não está disponível. Confira a página do Instagram."
    except WebDriverException:
        return "blocked", "O formulário mudou durante a conferência. Revise a página."
    if cancelled():
        return "paused", "Lote pausado antes do envio."
    if not claim():
        return "pending", "Já há uma tentativa registrada. Confirme o resultado no painel."
    try:
        if allowed(driver.current_url):
            controls[0].click()
            return "sent", "Formulário enviado. Conclua as verificações no Instagram e registre o resultado."
    except WebDriverException:
        pass
    return "pending", "Envio sem confirmação. Confira o navegador e registre o resultado antes de repetir."


def feedback(driver, data):
    """Surface visible form errors while the user reviews the result."""
    if not allowed(driver.current_url):
        return ""
    errors = driver.execute_script(r"""
        const nodes = new Set(document.querySelectorAll('[role="alert"]'));
        for (const field of document.querySelectorAll('[aria-invalid="true"]')) {
            for (const id of (field.getAttribute('aria-describedby') || '').split(/\s+/)) {
                const description = document.getElementById(id);
                if (description) nodes.add(description);
            }
        }
        return Array.from(nodes).filter(node => node.getClientRects().length)
            .map(node => node.innerText.trim()).filter(Boolean).slice(0, 3).join(' · ');
    """) or ""
    for value in data.values():
        if value:
            errors = errors.replace(value, "[redigido]")
    return errors[:350]
