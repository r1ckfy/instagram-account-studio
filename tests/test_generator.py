import random
from datetime import date

import pytest

from app import generator as gen
from app.security import password_strength, strong_password


def test_generated_usernames_are_always_valid():
    rng = random.Random(42)
    for _ in range(1000):
        first, last = gen.gen_name(rng.choice(list(gen.GENDERS)), rng=rng)
        u = gen.gen_username(first, last, rng.randint(0, 4), rng.randint(0, 4),
                             rng.choice(list(gen.SEPARATORS)), rng=rng)
        assert gen.validate_username(u) is None, u


@pytest.mark.parametrize("bad", ["", ".anto", "anto.", "an..to", "Anto", "an to", "a" * 31, "ação"])
def test_invalid_usernames_rejected(bad):
    assert gen.validate_username(bad)


@pytest.mark.parametrize("good", ["antovire", "anto.vire", "anto_vire22", "a" * 30])
def test_valid_usernames_accepted(good):
    assert gen.validate_username(good) is None


def test_slug_strips_accents():
    assert gen.slug("Lívia Galvão") == "liviagalvao"


@pytest.mark.parametrize("today", [date(2026, 11, 2), date(2024, 2, 29), date(2025, 1, 1), date(2025, 12, 31)])
def test_birthdate_matches_requested_age(today):
    rng = random.Random(1)
    for age in range(gen.MIN_AGE, gen.MAX_AGE + 1):
        for _ in range(20):
            born = gen.gen_birthdate(age, today=today, rng=rng)
            assert gen.age_on(born, today) == age


def test_birthdate_never_under_18():
    assert gen.age_on(gen.gen_birthdate(5), date.today()) == gen.MIN_AGE
    assert gen.validate_birthdate(date.today().replace(year=date.today().year - 17))
    assert gen.validate_birthdate(date(2000, 1, 1)) is None


def test_bios_fit_instagram_limit_for_every_style_and_state():
    rng = random.Random(7)
    for style in gen.BIO_STYLES:
        for uf in gen.STATES:
            for g in gen.GENDERS:
                bio = gen.gen_bio(style, "Antonella", 22, uf, "", g, rng=rng)
                assert 0 < len(bio) <= gen.BIO_MAX
                assert "{" not in bio


def test_bio_uses_gendered_demonym():
    rng = random.Random(0)
    bios = {gen.gen_bio("lifestyle", "Ana", 22, "AL", "", "feminino", rng=rng) for _ in range(30)}
    assert any("alagoana" in b for b in bios)


def test_strong_password():
    for _ in range(200):
        pw = strong_password(16)
        assert len(pw) == 16
        assert password_strength(pw)[0] == 4
    assert len(strong_password(4)) == 12  # mínimo forçado


def test_generate_full_set():
    g = gen.generate({"gender": "feminino", "age": 22, "uf": "AL", "domain": "@Exemplo.com",
                      "bio_style": "praia", "sep": "ponto", "digits": 2})
    assert gen.validate_username(g["username"]) is None
    assert g["email"].endswith("@exemplo.com") and gen.validate_email(g["email"]) is None
    assert gen.age_on(date.fromisoformat(g["birthdate"]), date.today()) == 22
    assert g["location"] == "Maceió, AL"
    assert g["full_name"] == f"{g['first']} {g['last']}"


def test_generate_respects_given_names():
    g = gen.generate({"first": "Antonella", "last": "Virelli"})
    assert g["full_name"] == "Antonella Virelli"
