"""Criptografia de segredos com a DPAPI do Windows (CryptProtectData).

O texto cifrado só pode ser aberto pelo mesmo usuário do Windows que o criou,
então o banco (e seus backups) nunca guardam senhas em texto puro.
"""
import ctypes
import secrets
import string
import sys
from ctypes import wintypes

if sys.platform != "win32":
    raise ImportError("Este módulo requer Windows (DPAPI).")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.windll.crypt32
_kernel32 = ctypes.windll.kernel32
_ENTROPY = b"InstagramAccountStudio/v1"
_UI_FORBIDDEN = 0x01


def _call(fn, data: bytes) -> bytes:
    # Buffers ficam em variáveis locais para continuarem vivos durante a chamada.
    data_buf = ctypes.create_string_buffer(data, len(data))
    ent_buf = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    data_in = _Blob(len(data), ctypes.cast(data_buf, ctypes.POINTER(ctypes.c_char)))
    entropy = _Blob(len(_ENTROPY), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    ok = fn(ctypes.byref(data_in), None, ctypes.byref(entropy),
            None, None, _UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError(ctypes.FormatError())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(out.pbData)


def encrypt(text: str) -> bytes:
    return _call(_crypt32.CryptProtectData, text.encode("utf-8"))


def decrypt(blob: bytes | None) -> str:
    if not blob:
        return ""
    return _call(_crypt32.CryptUnprotectData, bytes(blob)).decode("utf-8")


SYMBOLS = "!@#$%&*?-_+="


def strong_password(length: int = 16) -> str:
    """Senha aleatória com minúscula, maiúscula, dígito e símbolo garantidos."""
    length = max(length, 12)
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, SYMBOLS]
    chars = [secrets.choice(p) for p in pools]
    everything = "".join(pools)
    chars += [secrets.choice(everything) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def password_strength(pw: str) -> tuple[int, str]:
    """Pontuação 0-4 e rótulo em pt-BR."""
    score = sum([len(pw) >= 12,
                 any(c.islower() for c in pw) and any(c.isupper() for c in pw),
                 any(c.isdigit() for c in pw),
                 any(not c.isalnum() for c in pw)])
    if len(pw) < 8:
        score = min(score, 1)
    return score, ["Muito fraca", "Fraca", "Média", "Boa", "Forte"][score]
