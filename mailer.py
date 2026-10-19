"""Отправка писем: SMTP или запись в файл, если почта ещё не настроена."""

import smtplib
from email.message import EmailMessage
from pathlib import Path

from flask import current_app


def send_mail(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """
    Шлём письмо. Возвращаем (успех, пояснение).
    Если SMTP не задан — сохраняем текст в instance/mail.log.
    """
    server = current_app.config.get("MAIL_SERVER") or ""
    mail_from = current_app.config.get("MAIL_FROM") or "noreply@bizcrm.local"

    if not server:
        log_path = Path(current_app.root_path) / "instance" / "mail.log"
        log_path.parent.mkdir(exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write("\n" + "=" * 40 + "\n")
            file.write(f"Кому: {to_email}\nТема: {subject}\n\n{body}\n")
        return True, "Письмо сохранено в instance/mail.log (SMTP ещё не настроен)"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = to_email
    message.set_content(body)

    try:
        port = int(current_app.config.get("MAIL_PORT") or 587)
        with smtplib.SMTP(server, port, timeout=20) as smtp:
            if current_app.config.get("MAIL_USE_TLS", True):
                smtp.starttls()
            username = current_app.config.get("MAIL_USERNAME") or ""
            password = current_app.config.get("MAIL_PASSWORD") or ""
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        return True, "Письмо отправлено"
    except Exception as error:  # noqa: BLE001 — новичку важно увидеть текст ошибки
        return False, f"Не удалось отправить письмо: {error}"


def credentials_email(user_name: str, login: str, password: str, site_url: str, site_name: str) -> tuple[str, str]:
    """Тема и текст письма с логином и паролем."""
    subject = f"Доступ в {site_name}"
    body = (
        f"Здравствуйте, {user_name}!\n\n"
        f"Вам открыли доступ в CRM «{site_name}».\n\n"
        f"Адрес: {site_url}/login\n"
        f"Логин: {login}\n"
        f"Пароль: {password}\n\n"
        f"После входа пароль можно сменить у администратора.\n"
        f"Если письмо пришло по ошибке — просто удалите его.\n"
    )
    return subject, body
