"""Точка входа для gunicorn на хостинге."""

from app import app as application

# gunicorn ждёт имя `application` или `app`
app = application
