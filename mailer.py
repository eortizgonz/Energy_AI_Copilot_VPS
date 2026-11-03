import html
import os
import smtplib
from email.message import EmailMessage


def mail_configured():
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_APP_PASSWORD", "").strip()
    return bool(username and password and username != "CHANGE_ME" and password != "CHANGE_ME")


def send_password_reset(recipient, reset_url):
    if not mail_configured():
        raise RuntimeError("La configuración SMTP no está completa")

    username = os.environ["MAIL_USERNAME"].strip()
    safe_url = html.escape(reset_url, quote=True)
    message = EmailMessage()
    message["Subject"] = "Recuperación de contraseña · ZYMA 360 Energy"
    message["From"] = f'{os.getenv("MAIL_FROM_NAME", "ZYMA 360 Energy")} <{username}>'
    message["To"] = recipient
    message.set_content(
        "Recibimos una solicitud para restablecer tu contraseña de Energy AI Copilot.\n\n"
        f"Abre este enlace, válido durante 30 minutos:\n{reset_url}\n\n"
        "Si no realizaste esta solicitud, ignora el mensaje."
    )
    message.add_alternative(
        f"""<div style="font-family:Arial,sans-serif;color:#18322f;max-width:560px;margin:auto">
        <h2 style="color:#0e7772">Recuperación de contraseña</h2>
        <p>Recibimos una solicitud para restablecer tu contraseña de Energy AI Copilot.</p>
        <p><a href="{safe_url}" style="display:inline-block;background:#0e7772;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:bold">Crear nueva contraseña</a></p>
        <p style="color:#657b77;font-size:13px">El enlace vence en 30 minutos y solo puede utilizarse una vez.</p>
        <p style="color:#657b77;font-size:13px">Si no realizaste esta solicitud, ignora este mensaje.</p></div>""",
        subtype="html",
    )

    host = os.getenv("MAIL_HOST", "smtp.gmail.com")
    port = int(os.getenv("MAIL_PORT", "465"))
    password = os.environ["MAIL_APP_PASSWORD"].replace(" ", "")
    if os.getenv("MAIL_USE_SSL", "true").lower() == "true":
        with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
