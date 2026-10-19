"""Настройки из окружения. На хостинге секреты кладём в переменные, не в код."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Локальный .env подхватываем, если файл есть. Сам файл в чат не читаем.
load_dotenv(Path(__file__).resolve().parent / ".env")


def database_url() -> str:
    """SQLite локально, на Render/Railway обычно PostgreSQL из DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        # instance/ — стандартная папка Flask для данных
        instance = Path(__file__).resolve().parent / "instance"
        instance.mkdir(exist_ok=True)
        return "sqlite:///" + str(instance / "bizcrm.db")
    # Heroku/Render иногда отдают postgres:// — SQLAlchemy ждёт postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "bizcrm-dev-key-change-later")
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Публичный адрес сайта для ссылок в письмах
    SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:5001").rstrip("/")
    SITE_NAME = os.environ.get("SITE_NAME", "BizCRM Автосервис")

    # Почта. Без MAIL_SERVER письма пишутся в instance/mail.log (удобно для проверки)
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "").strip()
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") != "0"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "").strip()
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "").strip()
    MAIL_FROM = os.environ.get("MAIL_FROM", os.environ.get("MAIL_USERNAME", "noreply@bizcrm.local"))

    # Открытая регистрация с сайта. Приглашения администратора работают всегда.
    ALLOW_PUBLIC_REGISTER = os.environ.get("ALLOW_PUBLIC_REGISTER", "1") != "0"
