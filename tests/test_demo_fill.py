"""Selenium contra a página demo local (headless). Pulado se não houver navegador/driver."""
from pathlib import Path

import pytest

from app import DEMO_PAGE, browser

pytest.importorskip("selenium")


@pytest.fixture(scope="module")
def driver():
    last_error = None
    for name in ("edge", "chrome"):
        if not browser.find_browser(name):
            continue
        try:
            d = browser.make_driver(name, headless=True)
            break
        except Exception as e:  # sem driver/sem internet para o Selenium Manager
            last_error = e
    else:
        pytest.skip(f"Nenhum navegador automatizável disponível: {last_error}")
    yield d
    d.quit()


DATA = {"email": "anto@example.com", "full_name": "Antonella Virelli", "username": "antovire",
        "password": "S3nha!Forte#2026", "birthdate": "2003-04-14"}


def test_fill_demo_two_steps_and_submit(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    driver.get(Path(DEMO_PAGE).as_uri())
    steps = []
    filled = browser.fill_demo(driver, DATA, steps.append)
    assert "PREENCHENDO CAMPOS" in steps
    assert filled[:4] == ["E-mail", "Nome completo", "Nome de usuário", "Senha"]
    for name in ("email", "full_name", "username", "password"):
        assert driver.find_element(By.NAME, name).get_attribute("value") == DATA[name]
    assert Select(driver.find_element(By.NAME, "birthday_day")).first_selected_option.text == "14"
    assert Select(driver.find_element(By.NAME, "birthday_month")).first_selected_option.text == "Abril"
    assert Select(driver.find_element(By.NAME, "birthday_year")).first_selected_option.text == "2003"
    # não envia sozinho: só o usuário envia
    assert driver.execute_script("return document.body.dataset.status || ''") == ""
    driver.find_element(By.ID, "submit").click()
    assert driver.execute_script("return document.body.dataset.status") == "enviado"
    summary = driver.find_element(By.ID, "summary").text
    assert "@antovire" in summary and DATA["password"] not in summary


def test_refuses_pages_other_than_demo(driver):
    driver.get("data:text/html,<form><input name='email'></form>")
    with pytest.raises(PermissionError):
        browser.fill_demo(driver, DATA)


def test_missing_field_reports_clear_error(driver, tmp_path):
    page = tmp_path / DEMO_PAGE.name  # mesmo nome, mas sem os campos esperados
    page.write_text("<html><body><form><input name='email'></form></body></html>", encoding="utf-8")
    driver.get(page.as_uri())
    with pytest.raises(RuntimeError, match="Nome completo"):
        browser.fill_demo(driver, DATA, timeout=1)
