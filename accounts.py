"""Создание сотрудников, логинов и паролей для приглашений."""

import re
import secrets
import string

from werkzeug.security import generate_password_hash

from models import User, db


def make_password(length: int = 10) -> str:
    """Пароль без похожих символов, чтобы удобно копировать из письма."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def make_login(email: str, preferred: str = "") -> str:
    """Логин из почты или имени. Если занят — добавляем цифру."""
    base = (preferred or email.split("@")[0]).strip().lower()
    base = re.sub(r"[^a-z0-9._-]+", "", base) or "user"
    base = base[:40]
    candidate = base
    index = 2
    while User.query.filter_by(login=candidate).first():
        candidate = f"{base}{index}"
        index += 1
    return candidate


def create_user(*, name: str, email: str, role_id: int, login: str | None = None) -> tuple[User, str]:
    """Создаём пользователя и возвращаем пару (user, пароль_открытым_текстом)."""
    email = email.strip().lower()
    if User.query.filter_by(email=email).first():
        raise ValueError("Сотрудник с такой почтой уже есть")
    password = make_password()
    user = User(
        name=name.strip(),
        email=email,
        login=make_login(email, login or ""),
        password_hash=generate_password_hash(password),
        role_id=role_id,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    return user, password
