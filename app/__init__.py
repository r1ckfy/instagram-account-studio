import sys
from pathlib import Path

APP_NAME = "Instagram Account Studio"
VERSION = "1.3.0"

# Empacotado (PyInstaller): dados ficam ao lado do .exe, recursos dentro de _MEIPASS.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
    RES_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = RES_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
DEMO_PAGE = RES_DIR / "demo" / "cadastro_demo.html"
INSTAGRAM_SIGNUP_URL = "https://www.instagram.com/accounts/emailsignup/"
