"""Gerador de dados para personagens virtuais adultos (18+).

Nada aqui consulta serviços externos: usernames e e-mails são apenas sugestões.
"""
import random
import re
import unicodedata
from datetime import date, timedelta

from .security import strong_password

MIN_AGE, MAX_AGE = 18, 60
MODEL_BIRTHDATE = date(2007, 1, 27)
DEFAULT_PASSWORD_SETTING = "generated_profile_password"
BIO_MAX = 150
USERNAME_MAX = 30

FEMALE = ["Antonella", "Giovanna", "Isabella", "Valentina", "Manuela", "Helena", "Alice",
          "Laura", "Beatriz", "Mariana", "Larissa", "Bianca", "Camila", "Fernanda", "Gabriela",
          "Luana", "Yasmin", "Lívia", "Sofia", "Melissa", "Carolina", "Rafaela", "Nicole",
          "Júlia", "Letícia", "Marina", "Clara", "Lorena", "Vitória", "Bruna", "Aurora", "Stella"]
MALE = ["Lorenzo", "Enzo", "Matteo", "Gabriel", "Rafael", "Davi", "Bernardo", "Heitor",
        "Theo", "Lucas", "Pedro", "Miguel", "Arthur", "Benício", "Joaquim", "Caio", "Vicente",
        "Henrique", "Murilo", "Gustavo", "Felipe", "Bruno", "Diego", "Thiago", "Leonardo"]
SURNAMES = ["Virelli", "Moretti", "Albuquerque", "Bellini", "Carvalho", "Duarte", "Ferraz",
            "Galvão", "Lacerda", "Marchetti", "Monteiro", "Nogueira", "Pacheco", "Queiroz",
            "Rossetti", "Sampaio", "Siqueira", "Tavares", "Valente", "Vasconcelos", "Zanetti",
            "Brandão", "Castello", "Fontana", "Leal", "Medeiros", "Paiva", "Rezende", "Salles",
            "Veloso", "Amaral", "Bittencourt", "Cavalcanti", "Lombardi", "Ventura"]

# UF: (estado, capital, gentílico masculino, gentílico feminino)
STATES = {
    "AC": ("Acre", "Rio Branco", "acreano", "acreana"),
    "AL": ("Alagoas", "Maceió", "alagoano", "alagoana"),
    "AP": ("Amapá", "Macapá", "amapaense", "amapaense"),
    "AM": ("Amazonas", "Manaus", "amazonense", "amazonense"),
    "BA": ("Bahia", "Salvador", "baiano", "baiana"),
    "CE": ("Ceará", "Fortaleza", "cearense", "cearense"),
    "DF": ("Distrito Federal", "Brasília", "brasiliense", "brasiliense"),
    "ES": ("Espírito Santo", "Vitória", "capixaba", "capixaba"),
    "GO": ("Goiás", "Goiânia", "goiano", "goiana"),
    "MA": ("Maranhão", "São Luís", "maranhense", "maranhense"),
    "MT": ("Mato Grosso", "Cuiabá", "mato-grossense", "mato-grossense"),
    "MS": ("Mato Grosso do Sul", "Campo Grande", "sul-mato-grossense", "sul-mato-grossense"),
    "MG": ("Minas Gerais", "Belo Horizonte", "mineiro", "mineira"),
    "PA": ("Pará", "Belém", "paraense", "paraense"),
    "PB": ("Paraíba", "João Pessoa", "paraibano", "paraibana"),
    "PR": ("Paraná", "Curitiba", "paranaense", "paranaense"),
    "PE": ("Pernambuco", "Recife", "pernambucano", "pernambucana"),
    "PI": ("Piauí", "Teresina", "piauiense", "piauiense"),
    "RJ": ("Rio de Janeiro", "Rio de Janeiro", "carioca", "carioca"),
    "RN": ("Rio Grande do Norte", "Natal", "potiguar", "potiguar"),
    "RS": ("Rio Grande do Sul", "Porto Alegre", "gaúcho", "gaúcha"),
    "RO": ("Rondônia", "Porto Velho", "rondoniense", "rondoniense"),
    "RR": ("Roraima", "Boa Vista", "roraimense", "roraimense"),
    "SC": ("Santa Catarina", "Florianópolis", "catarinense", "catarinense"),
    "SP": ("São Paulo", "São Paulo", "paulista", "paulista"),
    "SE": ("Sergipe", "Aracaju", "sergipano", "sergipana"),
    "TO": ("Tocantins", "Palmas", "tocantinense", "tocantinense"),
}

GENDERS = {"feminino": "Feminino", "masculino": "Masculino", "neutro": "Neutro"}
SEPARATORS = {"nenhum": "", "ponto": ".", "underline": "_"}

BIO_STYLES = {
    "modelo_virtual": ("Estilo e rotina", [
        "{age}y | {demonym} ✨\nmoda, café e pequenos momentos 💫",
        "{age}y | 📍 {city}\nentre arte, estilo e boas histórias ✨",
        "{demonym} de coração 💜\n{age}y | vivendo dias leves",
    ]),
    "lifestyle": ("Lifestyle", [
        "{age}y | {demonym} 🌴\nvivendo meus melhores momentos ✨",
        "📍 {city}, {uf}\ncafé, viagens e boas vibes ☕✈️",
        "{first} • {age}\ncolecionando momentos, não coisas 🌙",
    ]),
    "praia": ("Praia", [
        "☀️ {city} • {age}\nsal, sol e mar 🌊",
        "{demonym} 🌴 | {age}y\nmeu lugar favorito é a beira-mar 🐚",
        "🌊 vida leve, pé na areia\n📍 {city}",
    ]),
    "universitaria": ("Universitária", [
        "📚 {age}y • {city}\nentre provas e cafés ☕",
        "universitári{o_a} 🎓 | {demonym}\nestudando hoje pro futuro de amanhã ✨",
        "{first} • {age}\n📖 faculdade, amigos e playlists 🎧",
    ]),
    "fitness": ("Fitness", [
        "🏋️ {age} | {demonym}\nfoco, treino e constância 💪",
        "treino é terapia 🧘 | 📍 {city}\nsaúde em primeiro lugar 🥗",
        "{first} • fitness lifestyle 💪\n{age}y | {uf}",
    ]),
    "fashion": ("Fashion", [
        "👗 {city}\nmoda é minha forma de expressão ✨",
        "{demonym} | {age}y\nlooks, tendências e atitude 🖤",
        "fashion lover 👠 • {city}, {uf}\nestilo não tem regra ✨",
    ]),
    "pessoal": ("Perfil pessoal", [
        "{first} • {age}\n📍 {city}, {uf}",
        "{demonym} 💛 | {age}y\nsó coisas boas por aqui ✨",
        "📍 {city}\n{age} anos de histórias 🌻",
    ]),
}

_USERNAME_RE = re.compile(r"^(?!\.)(?!.*\.\.)(?!.*\.$)[a-z0-9._]{1,30}$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_DOMAIN_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


def slug(text: str) -> str:
    """'Antonella Virêlli' -> 'antonellavirelli' (só a-z0-9)."""
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_.lower())


def validate_username(username: str) -> str | None:
    """Retorna mensagem de erro ou None se o formato for válido para o Instagram."""
    if not username:
        return "Informe um nome de usuário."
    if len(username) > USERNAME_MAX:
        return f"O nome de usuário deve ter no máximo {USERNAME_MAX} caracteres."
    if not _USERNAME_RE.match(username):
        return ("Use apenas letras minúsculas, números, ponto e underline; "
                "sem ponto no início/fim nem dois pontos seguidos.")
    return None


def validate_email(email: str) -> str | None:
    return None if _EMAIL_RE.match(email or "") else "E-mail em formato inválido."


def validate_birthdate(born: date, today: date | None = None) -> str | None:
    age = age_on(born, today or date.today())
    if age < MIN_AGE:
        return f"O personagem precisa ter {MIN_AGE} anos ou mais."
    if age > 120:
        return "Data de nascimento inválida."
    return None


def validate_bio(bio: str) -> str | None:
    return None if len(bio) <= BIO_MAX else f"A bio tem {len(bio)} caracteres (máximo {BIO_MAX})."


def age_on(born: date, today: date) -> int:
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29/02 em ano não bissexto
        return d.replace(year=d.year - years, day=28)


def gen_birthdate(age: int, today: date | None = None, rng=random) -> date:
    """Data de nascimento aleatória para alguém que tem exatamente `age` anos hoje."""
    age = max(MIN_AGE, min(MAX_AGE, age))
    today = today or date.today()
    latest = _years_ago(today, age)
    earliest = _years_ago(today, age + 1) + timedelta(days=1)
    return earliest + timedelta(days=rng.randint(0, (latest - earliest).days))


def gen_name(gender: str, first: str = "", last: str = "", rng=random) -> tuple[str, str]:
    pool = {"feminino": FEMALE, "masculino": MALE}.get(gender, FEMALE + MALE)
    return (first.strip() or rng.choice(pool), last.strip() or rng.choice(SURNAMES))


def gen_username(first: str, last: str, extra_letters: int = 0, digits: int = 0,
                 sep: str = "nenhum", rng=random) -> str:
    f, l = slug(first) or "user", slug(last) or "perfil"
    s = SEPARATORS.get(sep, "")
    style = rng.randint(0, 3)
    if style == 0:
        base = f[:4] + s + l[:4]           # antovire / anto.vire
    elif style == 1:
        base = f + s + l[:3]
    elif style == 2:
        base = f[:5] + s + l
    else:
        base = f + s + l
    base += "".join(rng.choice("aeiouxyzklm") for _ in range(max(0, extra_letters)))
    suffix = "".join(rng.choice("0123456789") for _ in range(max(0, digits)))
    base = base[:USERNAME_MAX - len(suffix)].strip("._")
    return base + suffix


def gen_email(username: str, domain: str) -> str:
    local = re.sub(r"[^a-z0-9._-]", "", username.lower()).strip(".") or "contato"
    return f"{local}@{domain.strip().lstrip('@').lower()}"


def gen_bio(style: str, first: str, age: int, uf: str, city: str, gender: str,
            rng=random) -> str:
    _, templates = BIO_STYLES.get(style, BIO_STYLES["pessoal"])
    _, capital, dem_m, dem_f = STATES.get(uf, STATES["SP"])
    fem = gender != "masculino"
    for _ in range(10):
        bio = rng.choice(templates).format(
            age=age, first=first, uf=uf, city=city or capital,
            demonym=dem_f if fem else dem_m, o_a="a" if fem else "o")
        if len(bio) <= BIO_MAX:
            return bio
    return bio[:BIO_MAX]


def generate(opts: dict, rng=random, *, birthdate: date | None = None, password: str | None = None) -> dict:
    """Gera um conjunto completo. `opts` vem do formulário da aba DADOS."""
    gender = opts.get("gender", "feminino")
    today = date.today()
    age = (age_on(birthdate, today) if birthdate is not None
           else max(MIN_AGE, min(MAX_AGE, int(opts.get("age", 22)))))
    uf = opts.get("uf", "SP")
    city = opts.get("city", "").strip() or STATES[uf][1]
    first, last = gen_name(gender, opts.get("first", ""), opts.get("last", ""), rng)
    username = gen_username(first, last, opts.get("extra_letters", 0),
                            opts.get("digits", 0), opts.get("sep", "nenhum"), rng)
    return {
        "first": first, "last": last, "full_name": f"{first} {last}",
        "gender": gender, "age": age, "uf": uf, "city": city,
        "birthdate": (birthdate or gen_birthdate(age, today=today, rng=rng)).isoformat(),
        "username": username,
        "email": gen_email(username, opts.get("domain", "gmail.com")),
        "bio": gen_bio(opts.get("bio_style", "lifestyle"), first, age, uf, city, gender, rng),
        "bio_style": opts.get("bio_style", "lifestyle"),
        "password": password or strong_password(int(opts.get("password_len", 16))),
        "location": f"{city}, {uf}",
    }
