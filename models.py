"""
Модели CRM в духе Bitrix24:
контакт, компания, лид, сделка, стадия (со семантикой), задача.
"""

from datetime import datetime, date

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Company(db.Model):
    """Компания — как crm.company в Bitrix24."""

    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    # TITLE в Bitrix
    title = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contacts = db.relationship("Contact", back_populates="company", lazy=True)
    deals = db.relationship("Deal", back_populates="company", lazy=True)

    def __repr__(self) -> str:
        return f"<Company {self.title}>"


class Contact(db.Model):
    """Контакт — как crm.contact (NAME, LAST_NAME, PHONE, EMAIL)."""

    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), default="")
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    post = db.Column(db.String(120))  # должность
    comments = db.Column(db.Text)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    company = db.relationship("Company", back_populates="contacts")
    deals = db.relationship("Deal", back_populates="contact", lazy=True)

    @property
    def full_name(self) -> str:
        # Собираем ФИО для списков
        return f"{self.name} {self.last_name}".strip()

    def __repr__(self) -> str:
        return f"<Contact {self.full_name}>"


class Lead(db.Model):
    """Лид — как crm.lead: необработанный интерес до сделки."""

    __tablename__ = "leads"

    # Статусы лида в стиле Bitrix STATUS_ID
    STATUSES = {
        "NEW": "Необработанный",
        "IN_PROCESS": "В работе",
        "PROCESSED": "Обработан",
        "CONVERTED": "Сконвертирован",
        "JUNK": "Некачественный",
    }

    SOURCES = {
        "CALL": "Звонок",
        "WEB": "Сайт",
        "EMAIL": "Почта",
        "PARTNER": "Партнёр",
        "OTHER": "Другое",
    }

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    status_id = db.Column(db.String(30), default="NEW")
    source_id = db.Column(db.String(30), default="CALL")
    opportunity = db.Column(db.Float, default=0)  # ожидаемая сумма
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def status_label(self) -> str:
        return self.STATUSES.get(self.status_id, self.status_id)

    @property
    def source_label(self) -> str:
        return self.SOURCES.get(self.source_id, self.source_id)


class DealStage(db.Model):
    """
    Стадия воронки сделок.
    Как в Bitrix: STATUS_ID + NAME + SEMANTICS (process / success / failure).
    """

    __tablename__ = "deal_stages"

    id = db.Column(db.Integer, primary_key=True)
    status_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    # process | success | failure — семантика из EXTRA.SEMANTICS
    semantics = db.Column(db.String(20), default="process")
    color = db.Column(db.String(20), default="#39A8EF")
    sort = db.Column(db.Integer, default=100)
    # К какой воронке относится стадия. У ремонта и покраски стадии разные.
    funnel_id = db.Column(db.Integer, db.ForeignKey("funnels.id"))

    deals = db.relationship("Deal", back_populates="stage", lazy=True)
    funnel = db.relationship("Funnel", back_populates="stages")


class Deal(db.Model):
    """Сделка — как crm.deal: TITLE, STAGE_ID, OPPORTUNITY, связи."""

    __tablename__ = "deals"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    opportunity = db.Column(db.Float, default=0)  # сумма
    currency = db.Column(db.String(10), default="RUB")
    stage_id = db.Column(db.Integer, db.ForeignKey("deal_stages.id"))
    # Дублируем воронку на сделке, чтобы быстро фильтровать канбан
    funnel_id = db.Column(db.Integer, db.ForeignKey("funnels.id"))
    # Машина клиента: марка и госномер
    car = db.Column(db.String(120))
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"))
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"))
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    close_date = db.Column(db.Date)
    # Порядок карточки внутри колонки канбана (меньше — выше)
    board_sort = db.Column(db.Integer, default=0)

    stage = db.relationship("DealStage", back_populates="deals")
    funnel = db.relationship("Funnel", back_populates="deals")
    contact = db.relationship("Contact", back_populates="deals")
    company = db.relationship("Company", back_populates="deals")


class Task(db.Model):
    """Простая задача, привязанная к сделке или контакту."""

    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    deadline = db.Column(db.Date)
    is_done = db.Column(db.Boolean, default=False)
    deal_id = db.Column(db.Integer, db.ForeignKey("deals.id"))
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    deal = db.relationship("Deal")
    contact = db.relationship("Contact")

    @property
    def is_overdue(self) -> bool:
        # Просрочена, если срок прошёл и ещё не сделана
        if self.is_done or not self.deadline:
            return False
        return self.deadline < date.today()


class Role(db.Model):
    """Роль сотрудника. Администратор видит всё, остальные — только выданные воронки."""

    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    users = db.relationship("User", back_populates="role", lazy=True)


class User(db.Model):
    """Сотрудник, который входит в CRM."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True)
    login = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    role = db.relationship("Role", back_populates="users")


class Funnel(db.Model):
    """Воронка продаж. Как направление в Bitrix: ремонт, покраска, шиномонтаж."""

    __tablename__ = "funnels"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    color = db.Column(db.String(20), default="#39A8EF")
    sort = db.Column(db.Integer, default=100)

    stages = db.relationship("DealStage", back_populates="funnel", lazy=True)
    deals = db.relationship("Deal", back_populates="funnel", lazy=True)
    views = db.relationship("CrmView", back_populates="funnel", lazy=True)


class FunnelAccess(db.Model):
    """Можно ли роли смотреть воронку и менять в ней сделки."""

    __tablename__ = "funnel_access"
    __table_args__ = (db.UniqueConstraint("role_id", "funnel_id"),)

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    funnel_id = db.Column(db.Integer, db.ForeignKey("funnels.id"), nullable=False)
    can_view = db.Column(db.Boolean, default=False)
    can_edit = db.Column(db.Boolean, default=False)

    role = db.relationship("Role")
    funnel = db.relationship("Funnel")


class CrmView(db.Model):
    """Просмотр — сохранённый срез воронки: все, в работе, успешные или отказы."""

    __tablename__ = "crm_views"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    funnel_id = db.Column(db.Integer, db.ForeignKey("funnels.id"), nullable=False)
    # all | process | success | failure
    semantics = db.Column(db.String(20), default="all")
    sort = db.Column(db.Integer, default=100)
    # Системный просмотр нельзя удалить: он создаётся вместе с воронкой
    is_system = db.Column(db.Boolean, default=False)

    funnel = db.relationship("Funnel", back_populates="views")


class ViewAccess(db.Model):
    """Какие просмотры роли разрешено открывать."""

    __tablename__ = "view_access"
    __table_args__ = (db.UniqueConstraint("role_id", "view_id"),)

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    view_id = db.Column(db.Integer, db.ForeignKey("crm_views.id"), nullable=False)
    can_view = db.Column(db.Boolean, default=True)

    role = db.relationship("Role")
    view = db.relationship("CrmView")
