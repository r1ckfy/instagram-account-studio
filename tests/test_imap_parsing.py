import email
import imaplib
import socket
from email.message import EmailMessage

from app import imap_client


def _msg(html_only=False) -> email.message.Message:
    m = EmailMessage()
    m["From"] = "=?utf-8?q?Instagram?= <security@mail.instagram.com>"
    m["Subject"] = "=?utf-8?q?Confirma=C3=A7=C3=A3o?="
    if html_only:
        m.set_content("<html><style>p{}</style><p>Olá&nbsp;mundo</p><br>linha 2</html>", subtype="html")
    else:
        m.set_content("Texto simples da mensagem.")
        m.add_alternative("<p>versão html</p>", subtype="html")
        m.add_attachment(b"%PDF-1.4 SEGREDO-DO-ANEXO", maintype="application", subtype="pdf",
                         filename="anexo.pdf")
    return email.message_from_bytes(m.as_bytes())


def test_prefers_plain_text_and_ignores_attachments():
    text = imap_client._text_of(_msg())
    assert text == "Texto simples da mensagem."
    assert "SEGREDO" not in text


def test_html_fallback_is_stripped():
    text = imap_client._text_of(_msg(html_only=True))
    assert "Olá" in text and "mundo" in text and "linha 2" in text
    assert "<" not in text and "p{}" not in text


def test_header_decoding():
    assert imap_client._decode("=?utf-8?q?Confirma=C3=A7=C3=A3o?=") == "Confirmação"
    assert imap_client._decode(None) == ""


def test_friendly_errors_are_portuguese():
    assert "autenticação" in imap_client.friendly_error(imaplib.IMAP4.error("LOGIN failed"))
    assert "não encontrado" in imap_client.friendly_error(socket.gaierror())
    assert "esgotado" in imap_client.friendly_error(TimeoutError())
    assert "recusada" in imap_client.friendly_error(ConnectionRefusedError())
