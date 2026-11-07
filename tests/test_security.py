import pytest

from app import security


def test_dpapi_roundtrip_unicode():
    secret = "Sênh@ çom ãcentos 🔒"
    blob = security.encrypt(secret)
    assert secret.encode() not in blob
    assert security.decrypt(blob) == secret


def test_decrypt_empty():
    assert security.decrypt(None) == "" and security.decrypt(b"") == ""


def test_tampered_blob_fails():
    blob = bytearray(security.encrypt("abc"))
    blob[-5] ^= 0xFF
    with pytest.raises(OSError):
        security.decrypt(bytes(blob))


@pytest.mark.parametrize("pw,score", [("abc", 0), ("abcdefgh1", 1), ("Abcdefghijkl", 2), ("Abcdefghijk1!", 4)])
def test_password_strength(pw, score):
    assert security.password_strength(pw)[0] == score
