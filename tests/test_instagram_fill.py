import pytest
from pathlib import Path
from app import instagram_fill
from test_demo_fill import driver, DATA

@pytest.mark.parametrize('url,expected', [
    ('https://www.instagram.com/accounts/emailsignup/', True),
    ('https://instagram.com/accounts/signup/', True),
    ('https://www.instagram.com/challenge/', False),
    ('https://www.instagram.com/accounts/login/', False),
    ('https://instagram.com.evil.org/accounts/emailsignup/', False),
    ('http://www.instagram.com/accounts/emailsignup/', False)])
def test_origin_guard(url, expected):
    assert instagram_fill.allowed(url) is expected


def test_real_selenium_fields_no_submit(driver, tmp_path, monkeypatch):
    page = tmp_path/'signup.html'
    page.write_text('''<form onsubmit="document.body.dataset.submitted='yes';return false">
      <input name="emailOrPhone" value="old"><input name="fullName"><input name="username">
      <input name="password" type="password"><button type="submit">Sign up</button>
      <select name="birthday_day"><option value="14">14</option></select>
      <select name="birthday_month"><option value="4">April</option></select>
      <select name="birthday_year"><option value="2003">2003</option></select>
    </form>''', encoding='utf-8')
    driver.get(page.as_uri())
    # Test transport only: origin restriction remains enabled in production.
    monkeypatch.setattr(instagram_fill, 'allowed', lambda url: url == page.as_uri())
    result = instagram_fill.fill(driver, DATA, timeout=.2)
    assert result['filled'] == ['email','full_name','username','password','day','month','year']
    assert not result['missing']
    assert driver.execute_script('return document.body.dataset.submitted || ""') == ''
    assert DATA['password'] not in str(result)


def test_missing_fields_and_restricted_page(driver, tmp_path, monkeypatch):
    page = tmp_path/'missing.html';page.write_text('<input name="username">',encoding='utf-8')
    driver.get(page.as_uri())
    blocked = instagram_fill.fill(driver, DATA, timeout=.1)
    assert not blocked['filled']
    monkeypatch.setattr(instagram_fill, 'allowed', lambda url: url == page.as_uri())
    result = instagram_fill.fill(driver, DATA, timeout=.1)
    assert result['filled'] == ['username']
    assert set(result['missing']) == {'email','full_name','password'}

def test_meta_unnamed_inputs_and_accessible_birthdays(driver, tmp_path, monkeypatch):
    page = tmp_path/'meta.html'
    fields = ''.join(f'<input id="{key}" type="{kind}"><label for="{key}">{title}</label>' for key,kind,title in
                     [('e','text','Mobile number or email'),('n','text','Full name'),('u','search','Username'),('p','password','Password')])
    combos = ''.join(f'''<div role="combobox" tabindex="0" aria-label="Select {key}" onclick="this.lastElementChild.style.display='block'">{key}
       <div style="display:none" role="option" onclick="event.stopPropagation();this.parentElement.textContent='{value}'">{value}</div></div>'''
       for key,value in [('day','14'),('month','april'),('year','2003')])
    page.write_text('<form onsubmit="document.body.dataset.submitted=1;return false">'+fields+combos+'<button>Submit</button></form>',encoding='utf-8')
    driver.get(page.as_uri())
    monkeypatch.setattr(instagram_fill,'allowed',lambda url:url == page.as_uri())
    result=instagram_fill.fill(driver,DATA,timeout=.2)
    assert result['filled'] == ['email','full_name','username','password','day','month','year']
    assert not result['missing']
    assert driver.execute_script('return document.body.dataset.submitted || ""') == ''


def test_batch_submit_checks_fields_and_claims_before_click(driver, tmp_path, monkeypatch):
    page = tmp_path / 'submit.html'
    page.write_text('''<form onsubmit="window.submits++;return false">
        <input name="email"><input name="fullName"><input name="username">
        <input name="password" type="password">
        <select name="day"><option value="14">14</option></select>
        <select name="month"><option value="4">April</option></select>
        <select name="year"><option value="2003">2003</option></select>
        <button>Enviar</button></form><script>window.submits=0</script>''', encoding='utf-8')
    driver.get(page.as_uri())
    monkeypatch.setattr(instagram_fill, 'allowed', lambda url: url == page.as_uri())
    attempts = []
    def claim():
        if attempts:
            return False
        assert driver.execute_script('return window.submits') == 0
        attempts.append(1)
        return True

    assert not instagram_fill.fill(driver, DATA, timeout=.3)['missing']
    assert instagram_fill.submit(driver, dict(DATA, birthdate='2000-04-14'), claim, lambda: False)[0] == 'blocked'
    assert instagram_fill.submit(driver, DATA, claim, lambda: True)[0] == 'paused'
    assert not attempts
    assert instagram_fill.submit(driver, DATA, claim, lambda: False)[0] == 'sent'
    assert instagram_fill.submit(driver, DATA, claim, lambda: False)[0] == 'pending'
    assert driver.execute_script('return window.submits') == 1
