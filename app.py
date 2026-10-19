"""
BizCRM — простая CRM для малого бизнеса.
Сущности и воронка сделаны по логике Bitrix24 (контакты, компании, лиды, сделки, стадии).
"""

from datetime import date, datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_, text
from werkzeug.security import check_password_hash, generate_password_hash

from access import (
    can_edit_funnel,
    can_view_funnel,
    current_user,
    editable_funnels,
    limit_deals,
    visible_funnels,
    visible_views,
)
from accounts import create_user, make_password
from config import Config
from mailer import credentials_email, send_mail
from models import (
    Company,
    Contact,
    CrmView,
    Deal,
    DealStage,
    Funnel,
    FunnelAccess,
    Lead,
    Role,
    Task,
    User,
    ViewAccess,
    db,
)
from seed import PRESETS, add_stages, add_system_views, seed_autoservice, seed_demo

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)


def parse_date(value: str):
    """Безопасно читаем дату из формы YYYY-MM-DD."""
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def ensure_column(connection, table: str, column: str, ddl: str) -> None:
    """Добавляет колонку в уже существующую таблицу SQLite."""
    rows = connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
    if not rows:
        return
    names = {row[1] for row in rows}
    if column not in names:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_schema() -> None:
    """Старую базу дополняем новыми полями — create_all сам их не добавит."""
    with db.engine.begin() as connection:
        ensure_column(connection, "deals", "board_sort", "board_sort INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "deals", "funnel_id", "funnel_id INTEGER")
        ensure_column(connection, "deals", "car", "car VARCHAR(120)")
        ensure_column(connection, "deal_stages", "funnel_id", "funnel_id INTEGER")
        ensure_column(connection, "users", "email", "email VARCHAR(120)")
        ensure_column(connection, "users", "is_active", "is_active BOOLEAN DEFAULT 1")
        ensure_column(connection, "users", "created_at", "created_at DATETIME")


def top_sort(stage_id: int) -> int:
    """Новая сделка встаёт самой верхней в колонке."""
    current_min = (
        db.session.query(db.func.min(Deal.board_sort))
        .filter(Deal.stage_id == stage_id)
        .scalar()
    )
    if current_min is None:
        return 10
    return current_min - 10


def money_label(value) -> str:
    """Сумма как в карточке: 1 250 000 ₽."""
    return f"{float(value or 0):,.0f}".replace(",", " ") + " ₽"


@app.context_processor
def inject_globals():
    # Подсказки для шаблонов: сегодня, кто вошёл, может ли создавать воронки
    user = current_user()
    can_manage = bool(user and (user.role.is_admin or user.role.code == "director"))
    return {"today": date.today(), "current_user": user, "can_manage": can_manage}


@app.before_request
def require_login():
    """Без входа CRM не открывается. Вход, регистрация и стили — исключение."""
    if request.endpoint in {"login", "register", "static", "health"}:
        return None
    if current_user() is None:
        return redirect(url_for("login", next=request.path))
    return None


def can_manage_settings(user) -> bool:
    """Новые воронки создают руководитель и администратор."""
    return bool(user and (user.role.is_admin or user.role.code == "director"))


def find_user_by_login_or_email(value: str):
    """Вход и по логину, и по почте."""
    value = value.strip()
    if not value:
        return None
    user = User.query.filter_by(login=value).first()
    if user:
        return user
    return User.query.filter_by(email=value.lower()).first()


def deliver_credentials(user: User, password: str) -> str:
    """Письмо с доступом. Если SMTP нет — текст уходит в mail.log."""
    subject, body = credentials_email(
        user.name,
        user.login,
        password,
        app.config["SITE_URL"],
        app.config["SITE_NAME"],
    )
    ok, info = send_mail(user.email, subject, body)
    if not ok:
        raise RuntimeError(info)
    return info


DEMO_LOGINS = [
    ("admin", "Администратор", "Все воронки, права и новые направления"),
    ("director", "Руководитель", "Все цеха, без настройки прав"),
    ("receiver", "Мастер-приёмщик", "Ремонт, шиномонтаж и ТО"),
    ("painter", "Маляр", "Только покраска"),
    ("body", "Жестянщик", "Только жестянка"),
    ("tire", "Шиномонтажник", "Только шиномонтаж"),
]


@app.route("/health")
def health():
    """Проверка для хостинга: жив ли сайт."""
    return {"ok": True}


@app.route("/login", methods=["GET", "POST"])
def login():
    """Вход сотрудника. В демо пароль совпадает с логином."""
    if request.method == "POST":
        login_name = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        user = find_user_by_login_or_email(login_name)
        if (
            user
            and user.is_active
            and check_password_hash(user.password_hash, password)
        ):
            session["user_id"] = user.id
            nxt = request.args.get("next") or request.form.get("next") or url_for("deals_kanban")
            # Не пускаем на чужой адрес, только на страницы этого сайта
            if not nxt.startswith("/"):
                nxt = url_for("deals_kanban")
            return redirect(nxt)
        flash("Неверный логин или пароль", "ok")
    return render_template(
        "login.html",
        demo_logins=DEMO_LOGINS,
        next_url=request.args.get("next", ""),
        allow_register=app.config.get("ALLOW_PUBLIC_REGISTER", True),
    )


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    """Саморегистрация: создаём аккаунт и шлём логин с паролем на почту."""
    if not app.config.get("ALLOW_PUBLIC_REGISTER", True):
        flash("Открытая регистрация выключена. Попросите приглашение у администратора.", "ok")
        return redirect(url_for("login"))

    # Новичкам даём роль мастер-приёмщик — самые частые права на приёмку
    default_role = Role.query.filter_by(code="receiver").first() or Role.query.filter_by(is_admin=False).first()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not name or not email or "@" not in email:
            flash("Укажите имя и рабочую почту", "ok")
            return redirect(url_for("register"))
        if default_role is None:
            flash("Роли ещё не созданы. Запустите CRM один раз и повторите.", "ok")
            return redirect(url_for("register"))
        try:
            user, password = create_user(name=name, email=email, role_id=default_role.id)
            info = deliver_credentials(user, password)
            db.session.commit()
            flash(f"Аккаунт создан. {info}. Проверьте почту — там логин и пароль.", "ok")
            return redirect(url_for("login"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "ok")
        except RuntimeError as error:
            db.session.rollback()
            flash(str(error), "ok")
    return render_template("register.html", role_name=default_role.name if default_role else "Сотрудник")


@app.route("/users")
def users_list():
    """Список сотрудников — только администратор."""
    user = current_user()
    if not user.role.is_admin:
        flash("Сотрудников видит только администратор", "ok")
        return redirect(url_for("dashboard"))
    return render_template(
        "users/list.html",
        users=User.query.order_by(User.id.desc()).all(),
    )


@app.route("/users/invite", methods=["GET", "POST"])
def users_invite():
    """Приглашение: администратор указывает почту и роль, пароль уходит письмом."""
    user = current_user()
    if not user.role.is_admin:
        flash("Приглашать может только администратор", "ok")
        return redirect(url_for("dashboard"))
    roles = Role.query.order_by(Role.id).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role_id = int(request.form.get("role_id") or 0)
        role = db.session.get(Role, role_id)
        if not name or not email or "@" not in email or role is None:
            flash("Заполните имя, почту и роль", "ok")
            return redirect(url_for("users_invite"))
        try:
            invited, password = create_user(name=name, email=email, role_id=role.id)
            info = deliver_credentials(invited, password)
            db.session.commit()
            flash(f"{invited.name} приглашён. {info}", "ok")
            return redirect(url_for("users_list"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "ok")
        except RuntimeError as error:
            db.session.rollback()
            flash(str(error), "ok")
    return render_template("users/invite.html", roles=roles)


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
def users_reset_password(user_id):
    """Новый пароль и повторная отправка на почту."""
    admin = current_user()
    if not admin.role.is_admin:
        flash("Сбрасывать пароль может только администратор", "ok")
        return redirect(url_for("dashboard"))
    target = User.query.get_or_404(user_id)
    if not target.email:
        flash("У сотрудника нет почты", "ok")
        return redirect(url_for("users_list"))
    password = make_password()
    target.password_hash = generate_password_hash(password)
    try:
        info = deliver_credentials(target, password)
        db.session.commit()
        flash(f"Новый пароль отправлен. {info}", "ok")
    except RuntimeError as error:
        db.session.rollback()
        flash(str(error), "ok")
    return redirect(url_for("users_list"))


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
def users_toggle(user_id):
    """Включить или отключить вход сотруднику."""
    admin = current_user()
    if not admin.role.is_admin:
        flash("Менять сотрудников может только администратор", "ok")
        return redirect(url_for("dashboard"))
    target = User.query.get_or_404(user_id)
    if target.id == admin.id:
        flash("Нельзя отключить свой аккаунт", "ok")
        return redirect(url_for("users_list"))
    target.is_active = not target.is_active
    db.session.commit()
    flash("Доступ обновлён", "ok")
    return redirect(url_for("users_list"))


# ---------- Дашборд ----------

def visible_tasks(user):
    """Задачи без сделки видны всем, чужие воронки — нет."""
    ids = [funnel.id for funnel in visible_funnels(user)]
    query = Task.query.outerjoin(Deal, Task.deal_id == Deal.id)
    if not ids:
        return query.filter(Task.deal_id.is_(None))
    return query.filter(or_(Task.deal_id.is_(None), Deal.funnel_id.in_(ids)))


@app.route("/")
def dashboard():
    user = current_user()
    open_deals = (
        limit_deals(Deal.query, user)
        .join(DealStage)
        .filter(DealStage.semantics == "process")
        .all()
    )
    won_sum = (
        limit_deals(Deal.query, user)
        .join(DealStage)
        .filter(DealStage.semantics == "success")
        .with_entities(db.func.coalesce(db.func.sum(Deal.opportunity), 0))
        .scalar()
    )
    tasks_today = visible_tasks(user).filter(
        Task.is_done.is_(False),
        Task.deadline == date.today(),
    ).all()
    overdue = visible_tasks(user).filter(
        Task.is_done.is_(False),
        Task.deadline < date.today(),
    ).all()

    funnel_stats = []
    for funnel in visible_funnels(user):
        rows = (
            Deal.query.join(DealStage)
            .filter(Deal.funnel_id == funnel.id, DealStage.semantics == "process")
            .all()
        )
        funnel_stats.append({
            "funnel": funnel,
            "count": len(rows),
            "sum": sum(deal.opportunity or 0 for deal in rows),
        })

    return render_template(
        "dashboard.html",
        contacts_count=Contact.query.count(),
        companies_count=Company.query.count(),
        leads_count=Lead.query.filter(Lead.status_id.in_(["NEW", "IN_PROCESS"])).count(),
        open_deals_count=len(open_deals),
        open_deals_sum=sum(deal.opportunity or 0 for deal in open_deals),
        won_sum=won_sum or 0,
        tasks_today=tasks_today,
        overdue=overdue,
        recent_deals=limit_deals(Deal.query, user).order_by(Deal.created_at.desc()).limit(5).all(),
        funnel_stats=funnel_stats,
        money_label=money_label,
    )


# ---------- Контакты ----------

@app.route("/contacts")
def contacts_list():
    return render_template(
        "contacts/list.html",
        contacts=Contact.query.order_by(Contact.id.desc()).all(),
    )


@app.route("/contacts/new", methods=["GET", "POST"])
def contacts_new():
    companies = Company.query.order_by(Company.title).all()
    if request.method == "POST":
        contact = Contact(
            name=request.form["name"].strip(),
            last_name=request.form.get("last_name", "").strip(),
            phone=request.form.get("phone", "").strip(),
            email=request.form.get("email", "").strip(),
            post=request.form.get("post", "").strip(),
            comments=request.form.get("comments", "").strip(),
            company_id=request.form.get("company_id") or None,
        )
        db.session.add(contact)
        db.session.commit()
        flash("Контакт создан", "ok")
        return redirect(url_for("contacts_list"))
    return render_template("contacts/form.html", contact=None, companies=companies)


@app.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
def contacts_edit(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    companies = Company.query.order_by(Company.title).all()
    if request.method == "POST":
        contact.name = request.form["name"].strip()
        contact.last_name = request.form.get("last_name", "").strip()
        contact.phone = request.form.get("phone", "").strip()
        contact.email = request.form.get("email", "").strip()
        contact.post = request.form.get("post", "").strip()
        contact.comments = request.form.get("comments", "").strip()
        contact.company_id = request.form.get("company_id") or None
        db.session.commit()
        flash("Контакт обновлён", "ok")
        return redirect(url_for("contacts_list"))
    return render_template("contacts/form.html", contact=contact, companies=companies)


@app.route("/contacts/<int:contact_id>/delete", methods=["POST"])
def contacts_delete(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    db.session.delete(contact)
    db.session.commit()
    flash("Контакт удалён", "ok")
    return redirect(url_for("contacts_list"))


# ---------- Компании ----------

@app.route("/companies")
def companies_list():
    return render_template(
        "companies/list.html",
        companies=Company.query.order_by(Company.id.desc()).all(),
    )


@app.route("/companies/new", methods=["GET", "POST"])
def companies_new():
    if request.method == "POST":
        company = Company(
            title=request.form["title"].strip(),
            phone=request.form.get("phone", "").strip(),
            email=request.form.get("email", "").strip(),
            address=request.form.get("address", "").strip(),
            comments=request.form.get("comments", "").strip(),
        )
        db.session.add(company)
        db.session.commit()
        flash("Компания создана", "ok")
        return redirect(url_for("companies_list"))
    return render_template("companies/form.html", company=None)


@app.route("/companies/<int:company_id>/edit", methods=["GET", "POST"])
def companies_edit(company_id):
    company = Company.query.get_or_404(company_id)
    if request.method == "POST":
        company.title = request.form["title"].strip()
        company.phone = request.form.get("phone", "").strip()
        company.email = request.form.get("email", "").strip()
        company.address = request.form.get("address", "").strip()
        company.comments = request.form.get("comments", "").strip()
        db.session.commit()
        flash("Компания обновлена", "ok")
        return redirect(url_for("companies_list"))
    return render_template("companies/form.html", company=company)


@app.route("/companies/<int:company_id>/delete", methods=["POST"])
def companies_delete(company_id):
    company = Company.query.get_or_404(company_id)
    db.session.delete(company)
    db.session.commit()
    flash("Компания удалена", "ok")
    return redirect(url_for("companies_list"))


# ---------- Лиды ----------

@app.route("/leads")
def leads_list():
    return render_template(
        "leads/list.html",
        leads=Lead.query.order_by(Lead.id.desc()).all(),
        statuses=Lead.STATUSES,
    )


@app.route("/leads/new", methods=["GET", "POST"])
def leads_new():
    if request.method == "POST":
        lead = Lead(
            title=request.form["title"].strip(),
            name=request.form.get("name", "").strip(),
            phone=request.form.get("phone", "").strip(),
            email=request.form.get("email", "").strip(),
            status_id=request.form.get("status_id", "NEW"),
            source_id=request.form.get("source_id", "CALL"),
            opportunity=float(request.form.get("opportunity") or 0),
            comments=request.form.get("comments", "").strip(),
        )
        db.session.add(lead)
        db.session.commit()
        flash("Лид создан", "ok")
        return redirect(url_for("leads_list"))
    return render_template(
        "leads/form.html",
        lead=None,
        statuses=Lead.STATUSES,
        sources=Lead.SOURCES,
    )


@app.route("/leads/<int:lead_id>/edit", methods=["GET", "POST"])
def leads_edit(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if request.method == "POST":
        lead.title = request.form["title"].strip()
        lead.name = request.form.get("name", "").strip()
        lead.phone = request.form.get("phone", "").strip()
        lead.email = request.form.get("email", "").strip()
        lead.status_id = request.form.get("status_id", "NEW")
        lead.source_id = request.form.get("source_id", "CALL")
        lead.opportunity = float(request.form.get("opportunity") or 0)
        lead.comments = request.form.get("comments", "").strip()
        db.session.commit()
        flash("Лид обновлён", "ok")
        return redirect(url_for("leads_list"))
    return render_template(
        "leads/form.html",
        lead=lead,
        statuses=Lead.STATUSES,
        sources=Lead.SOURCES,
    )


@app.route("/leads/<int:lead_id>/delete", methods=["POST"])
def leads_delete(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    flash("Лид удалён", "ok")
    return redirect(url_for("leads_list"))


@app.route("/leads/<int:lead_id>/convert", methods=["POST"])
def leads_convert(lead_id):
    """Конвертация лида в сделку — типичный сценарий Bitrix CRM."""
    lead = Lead.query.get_or_404(lead_id)
    # Лид падает в первую воронку, которую сотруднику можно менять
    funnel = editable_funnels(current_user())
    funnel = funnel[0] if funnel else None
    first_stage = None
    if funnel is not None:
        first_stage = (
            DealStage.query.filter_by(funnel_id=funnel.id).order_by(DealStage.sort).first()
        )
    if first_stage is None:
        flash("Нет воронки, в которую можно положить сделку", "ok")
        return redirect(url_for("leads_list"))
    deal = Deal(
        title=f"Сделка: {lead.title}",
        opportunity=lead.opportunity or 0,
        stage_id=first_stage.id,
        funnel_id=funnel.id,
        board_sort=top_sort(first_stage.id),
        comments=f"Создано из лида #{lead.id}. {lead.comments or ''}".strip(),
    )
    # Если есть имя — создаём контакт
    if lead.name:
        contact = Contact(
            name=lead.name,
            phone=lead.phone,
            email=lead.email,
            comments=f"Из лида: {lead.title}",
        )
        db.session.add(contact)
        db.session.flush()
        deal.contact_id = contact.id

    lead.status_id = "CONVERTED"
    db.session.add(deal)
    db.session.commit()
    flash("Лид сконвертирован в сделку", "ok")
    return redirect(url_for("deals_kanban", funnel=funnel.id))


# ---------- Сделки и воронка ----------

def pick_funnel(user):
    """Берём воронку из адреса, иначе последнюю открытую, иначе первую доступную."""
    funnels = visible_funnels(user)
    requested = request.args.get("funnel", type=int)
    if requested:
        match = next((item for item in funnels if item.id == requested), None)
        if match is not None:
            session["funnel_id"] = match.id
            return match, funnels
    saved_id = session.get("funnel_id")
    match = next((item for item in funnels if item.id == saved_id), None)
    if match is None and funnels:
        match = funnels[0]
    if match is not None:
        session["funnel_id"] = match.id
    return match, funnels


def pick_view(user, funnel):
    """Просмотр внутри воронки. По умолчанию — «В работе»."""
    views = visible_views(user, funnel)
    requested = request.args.get("view", type=int)
    if requested:
        match = next((item for item in views if item.id == requested), None)
        if match is not None:
            return match, views
    match = next((item for item in views if item.semantics == "process"), None)
    return (match or (views[0] if views else None)), views


@app.route("/deals")
def deals_kanban():
    """Канбан одной воронки и одного просмотра."""
    user = current_user()
    funnel, funnels = pick_funnel(user)
    if funnel is None:
        return render_template(
            "deals/kanban.html",
            stages=[],
            deals_by_stage={},
            open_tasks={},
            overdue_tasks={},
            open_count=0,
            open_sum=0,
            won_sum=0,
            lose_count=0,
            money_label=money_label,
            funnels=[],
            funnel=None,
            views=[],
            current_view=None,
            can_edit=False,
        )

    current_view, views = pick_view(user, funnel)
    all_stages = DealStage.query.filter_by(funnel_id=funnel.id).order_by(DealStage.sort).all()
    stages = all_stages
    # Просмотр «В работе» прячет успешные и проваленные колонки
    if current_view and current_view.semantics != "all":
        stages = [stage for stage in all_stages if stage.semantics == current_view.semantics]

    deals_by_stage = {stage.id: [] for stage in stages}
    # Сначала по ручному порядку, новые с sort=0 остаются сверху за счёт id
    deals = (
        Deal.query.filter_by(funnel_id=funnel.id)
        .order_by(Deal.board_sort.asc(), Deal.id.desc())
        .all()
    )
    for deal in deals:
        if deal.stage_id in deals_by_stage:
            deals_by_stage[deal.stage_id].append(deal)

    # Сколько открытых и просроченных дел висит на каждой сделке
    open_tasks = dict(
        db.session.query(Task.deal_id, db.func.count(Task.id))
        .filter(Task.is_done.is_(False), Task.deal_id.isnot(None))
        .group_by(Task.deal_id)
        .all()
    )
    overdue_tasks = dict(
        db.session.query(Task.deal_id, db.func.count(Task.id))
        .filter(
            Task.is_done.is_(False),
            Task.deal_id.isnot(None),
            Task.deadline.isnot(None),
            Task.deadline < date.today(),
        )
        .group_by(Task.deal_id)
        .all()
    )

    stage_by_id = {stage.id: stage for stage in all_stages}
    open_count = 0
    open_sum = 0
    won_sum = 0
    lose_count = 0
    for deal in deals:
        stage = stage_by_id.get(deal.stage_id)
        if stage is None:
            continue
        if stage.semantics == "process":
            open_count += 1
            open_sum += deal.opportunity or 0
        elif stage.semantics == "success":
            won_sum += deal.opportunity or 0
        elif stage.semantics == "failure":
            lose_count += 1

    return render_template(
        "deals/kanban.html",
        stages=stages,
        deals_by_stage=deals_by_stage,
        open_tasks=open_tasks,
        overdue_tasks=overdue_tasks,
        open_count=open_count,
        open_sum=open_sum,
        won_sum=won_sum,
        lose_count=lose_count,
        money_label=money_label,
        funnels=funnels,
        funnel=funnel,
        views=views,
        current_view=current_view,
        can_edit=can_edit_funnel(user, funnel.id),
    )


@app.route("/deals/list")
def deals_list():
    user = current_user()
    edit_ids = [funnel.id for funnel in editable_funnels(user)]
    return render_template(
        "deals/list.html",
        deals=limit_deals(Deal.query, user).order_by(Deal.id.desc()).all(),
        edit_ids=edit_ids,
    )


def stages_for_funnels(funnels):
    """Стадии только тех воронок, которые передали в форму."""
    ids = [funnel.id for funnel in funnels]
    if not ids:
        return []
    return (
        DealStage.query.filter(DealStage.funnel_id.in_(ids))
        .order_by(DealStage.sort)
        .all()
    )


@app.route("/deals/new", methods=["GET", "POST"])
def deals_new():
    user = current_user()
    funnels = editable_funnels(user)
    if not funnels:
        flash("Нет воронки, в которой вам можно создавать сделки", "ok")
        return redirect(url_for("deals_kanban"))
    stages = stages_for_funnels(funnels)
    contacts = Contact.query.order_by(Contact.name).all()
    companies = Company.query.order_by(Company.title).all()
    selected_funnel_id = request.args.get("funnel", type=int) or funnels[0].id
    if selected_funnel_id not in {item.id for item in funnels}:
        selected_funnel_id = funnels[0].id
    if request.method == "POST":
        stage = DealStage.query.get_or_404(int(request.form["stage_id"]))
        if not can_edit_funnel(user, stage.funnel_id):
            flash("Эту воронку нельзя менять", "ok")
            return redirect(url_for("deals_kanban"))
        deal = Deal(
            title=request.form["title"].strip(),
            car=request.form.get("car", "").strip(),
            opportunity=float(request.form.get("opportunity") or 0),
            stage_id=stage.id,
            funnel_id=stage.funnel_id,
            board_sort=top_sort(stage.id),
            contact_id=request.form.get("contact_id") or None,
            company_id=request.form.get("company_id") or None,
            comments=request.form.get("comments", "").strip(),
            close_date=parse_date(request.form.get("close_date", "")),
        )
        db.session.add(deal)
        db.session.commit()
        flash("Сделка создана", "ok")
        return redirect(url_for("deals_kanban", funnel=stage.funnel_id))
    return render_template(
        "deals/form.html",
        deal=None,
        stages=stages,
        funnels=funnels,
        selected_funnel_id=selected_funnel_id,
        contacts=contacts,
        companies=companies,
    )


@app.route("/deals/<int:deal_id>/edit", methods=["GET", "POST"])
def deals_edit(deal_id):
    user = current_user()
    deal = Deal.query.get_or_404(deal_id)
    if not can_view_funnel(user, deal.funnel_id):
        flash("Эта сделка в недоступной воронке", "ok")
        return redirect(url_for("deals_kanban"))
    if not can_edit_funnel(user, deal.funnel_id):
        flash("Эту воронку можно только смотреть", "ok")
        return redirect(url_for("deals_kanban", funnel=deal.funnel_id))
    funnels = editable_funnels(user)
    stages = stages_for_funnels(funnels)
    contacts = Contact.query.order_by(Contact.name).all()
    companies = Company.query.order_by(Company.title).all()
    if request.method == "POST":
        stage = DealStage.query.get_or_404(int(request.form["stage_id"]))
        if not can_edit_funnel(user, stage.funnel_id):
            flash("Эту воронку нельзя менять", "ok")
            return redirect(url_for("deals_kanban"))
        deal.title = request.form["title"].strip()
        deal.car = request.form.get("car", "").strip()
        deal.opportunity = float(request.form.get("opportunity") or 0)
        deal.stage_id = stage.id
        deal.funnel_id = stage.funnel_id
        deal.contact_id = request.form.get("contact_id") or None
        deal.company_id = request.form.get("company_id") or None
        deal.comments = request.form.get("comments", "").strip()
        deal.close_date = parse_date(request.form.get("close_date", ""))
        db.session.commit()
        flash("Сделка обновлена", "ok")
        return redirect(url_for("deals_kanban", funnel=stage.funnel_id))
    return render_template(
        "deals/form.html",
        deal=deal,
        stages=stages,
        funnels=funnels,
        selected_funnel_id=deal.funnel_id,
        contacts=contacts,
        companies=companies,
    )


@app.route("/deals/<int:deal_id>/move", methods=["POST"])
def deals_move(deal_id):
    """Перенос сделки. Канбан шлёт JSON и сразу пишет стадию и порядок."""
    user = current_user()
    deal = Deal.query.get_or_404(deal_id)
    payload = request.get_json(silent=True)

    if payload:
        stage = DealStage.query.get_or_404(int(payload["stage_id"]))
        if not can_edit_funnel(user, deal.funnel_id) or not can_edit_funnel(user, stage.funnel_id):
            return jsonify({"ok": False, "error": "Нет права менять эту воронку"}), 403
        columns = payload.get("columns") or {}
        # В каждой затронутой колонке запоминаем новый порядок карточек
        for deal_ids in columns.values():
            for index, raw_deal_id in enumerate(deal_ids):
                item = db.session.get(Deal, int(raw_deal_id))
                if item is None:
                    continue
                item.board_sort = (index + 1) * 10
                if item.id == deal.id:
                    item.stage_id = stage.id
                    item.funnel_id = stage.funnel_id
        if not columns:
            deal.stage_id = stage.id
            deal.funnel_id = stage.funnel_id
        db.session.commit()
        return jsonify({"ok": True, "stage_id": stage.id, "stage_name": stage.name})

    stage = DealStage.query.get_or_404(int(request.form["stage_id"]))
    if not can_edit_funnel(user, stage.funnel_id):
        flash("Эту воронку нельзя менять", "ok")
        return redirect(url_for("deals_kanban"))
    deal.stage_id = stage.id
    deal.funnel_id = stage.funnel_id
    db.session.commit()
    return redirect(url_for("deals_kanban", funnel=stage.funnel_id))


@app.route("/api/deals", methods=["POST"])
def deals_quick():
    """Быстрое создание сделки из колонки канбана, без перехода на форму."""
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "Введите название сделки"}), 400

    stage = DealStage.query.get_or_404(int(payload.get("stage_id") or 0))
    if not can_edit_funnel(current_user(), stage.funnel_id):
        return jsonify({"ok": False, "error": "Нет права создавать сделки в этой воронке"}), 403
    raw_sum = payload.get("opportunity") or 0
    try:
        opportunity = float(raw_sum)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Сумма должна быть числом"}), 400

    deal = Deal(
        title=title,
        car=(payload.get("car") or "").strip(),
        opportunity=opportunity,
        stage_id=stage.id,
        funnel_id=stage.funnel_id,
        board_sort=top_sort(stage.id),
    )
    db.session.add(deal)
    db.session.commit()
    return jsonify({
        "ok": True,
        "html": render_template(
            "deals/_card.html",
            deal=deal,
            tasks_open=0,
            overdue_open=0,
        ),
    })


@app.route("/deals/<int:deal_id>/delete", methods=["POST"])
def deals_delete(deal_id):
    deal = Deal.query.get_or_404(deal_id)
    if not can_edit_funnel(current_user(), deal.funnel_id):
        flash("Эту воронку нельзя менять", "ok")
        return redirect(url_for("deals_kanban"))
    funnel_id = deal.funnel_id
    db.session.delete(deal)
    db.session.commit()
    flash("Сделка удалена", "ok")
    return redirect(url_for("deals_kanban", funnel=funnel_id))


# ---------- Задачи ----------

@app.route("/tasks")
def tasks_list():
    return render_template(
        "tasks/list.html",
        tasks=Task.query.order_by(Task.is_done, Task.deadline).all(),
    )


@app.route("/tasks/new", methods=["GET", "POST"])
def tasks_new():
    deals = limit_deals(Deal.query, current_user()).order_by(Deal.title).all()
    contacts = Contact.query.order_by(Contact.name).all()
    if request.method == "POST":
        task = Task(
            title=request.form["title"].strip(),
            description=request.form.get("description", "").strip(),
            deadline=parse_date(request.form.get("deadline", "")),
            deal_id=request.form.get("deal_id") or None,
            contact_id=request.form.get("contact_id") or None,
        )
        db.session.add(task)
        db.session.commit()
        flash("Задача создана", "ok")
        return redirect(url_for("tasks_list"))
    return render_template("tasks/form.html", task=None, deals=deals, contacts=contacts)


@app.route("/tasks/<int:task_id>/toggle", methods=["POST"])
def tasks_toggle(task_id):
    task = Task.query.get_or_404(task_id)
    task.is_done = not task.is_done
    db.session.commit()
    return redirect(url_for("tasks_list"))


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
def tasks_delete(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash("Задача удалена", "ok")
    return redirect(url_for("tasks_list"))


def grant_funnel(role, funnel) -> None:
    """Выдаёт роли просмотр и редактирование новой воронки и всех её просмотров."""
    if role is None or role.is_admin:
        return
    exists = FunnelAccess.query.filter_by(role_id=role.id, funnel_id=funnel.id).first()
    if exists is None:
        db.session.add(
            FunnelAccess(
                role_id=role.id,
                funnel_id=funnel.id,
                can_view=True,
                can_edit=True,
            )
        )
    for view in CrmView.query.filter_by(funnel_id=funnel.id):
        already = ViewAccess.query.filter_by(role_id=role.id, view_id=view.id).first()
        if already is None:
            db.session.add(ViewAccess(role_id=role.id, view_id=view.id, can_view=True))


# ---------- Воронки, просмотры, права ----------

@app.route("/funnels/new", methods=["GET", "POST"])
def funnels_new():
    """Новое направление: ремонт, покраска или свой набор стадий."""
    user = current_user()
    if not can_manage_settings(user):
        flash("Создавать воронки могут руководитель и администратор", "ok")
        return redirect(url_for("deals_kanban"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        preset_code = request.form.get("preset") or "generic"
        preset = PRESETS.get(preset_code) or PRESETS["generic"]
        if not name:
            flash("Введите название воронки", "ok")
            return redirect(url_for("funnels_new"))
        funnel = Funnel(
            name=name,
            code="tmp",
            color=preset["color"],
            sort=(db.session.query(db.func.max(Funnel.sort)).scalar() or 0) + 10,
        )
        db.session.add(funnel)
        db.session.flush()
        # Код нужен для уникальных стадий и больше не меняется
        funnel.code = f"c{funnel.id}"
        add_stages(funnel, preset["stages"])
        add_system_views(funnel)
        db.session.flush()
        grant_funnel(user.role, funnel)
        grant_funnel(Role.query.filter_by(code="director").first(), funnel)
        db.session.commit()
        flash(f"Воронка «{funnel.name}» создана", "ok")
        return redirect(url_for("deals_kanban", funnel=funnel.id))
    return render_template("funnels/form.html", presets=PRESETS)


@app.route("/views/new", methods=["GET", "POST"])
def views_new():
    """Свой просмотр: например, только успешные сделки покраски."""
    user = current_user()
    if not user.role.is_admin:
        flash("Просмотры настраивает администратор", "ok")
        return redirect(url_for("deals_kanban"))
    funnels = Funnel.query.order_by(Funnel.sort).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        funnel = Funnel.query.get_or_404(int(request.form["funnel_id"]))
        semantics = request.form.get("semantics") or "all"
        if semantics not in {"all", "process", "success", "failure"}:
            semantics = "all"
        if not name:
            flash("Введите название просмотра", "ok")
            return redirect(url_for("views_new"))
        view = CrmView(
            name=name,
            funnel_id=funnel.id,
            semantics=semantics,
            sort=50,
            is_system=False,
        )
        db.session.add(view)
        db.session.flush()
        # Кто уже видит воронку, сразу видит и новый просмотр
        for access in FunnelAccess.query.filter_by(funnel_id=funnel.id, can_view=True):
            db.session.add(ViewAccess(role_id=access.role_id, view_id=view.id, can_view=True))
        db.session.commit()
        flash("Просмотр сохранён", "ok")
        return redirect(url_for("deals_kanban", funnel=funnel.id, view=view.id))
    return render_template("views/form.html", funnels=funnels)


@app.route("/views/<int:view_id>/delete", methods=["POST"])
def views_delete(view_id):
    user = current_user()
    view = CrmView.query.get_or_404(view_id)
    if not user.role.is_admin:
        flash("Просмотры удаляет администратор", "ok")
        return redirect(url_for("deals_kanban"))
    if view.is_system:
        flash("Базовый просмотр удалить нельзя", "ok")
        return redirect(url_for("deals_kanban", funnel=view.funnel_id))
    funnel_id = view.funnel_id
    ViewAccess.query.filter_by(view_id=view.id).delete()
    db.session.delete(view)
    db.session.commit()
    flash("Просмотр удалён", "ok")
    return redirect(url_for("deals_kanban", funnel=funnel_id))


@app.route("/access", methods=["GET", "POST"])
def access_edit():
    """Таблица: какая роль какую воронку и какой просмотр видит."""
    user = current_user()
    if not user.role.is_admin:
        flash("Права меняет только администратор", "ok")
        return redirect(url_for("deals_kanban"))
    roles = Role.query.filter_by(is_admin=False).order_by(Role.id).all()
    funnels = Funnel.query.order_by(Funnel.sort, Funnel.id).all()
    views = CrmView.query.order_by(CrmView.funnel_id, CrmView.sort).all()
    if request.method == "POST":
        FunnelAccess.query.delete()
        ViewAccess.query.delete()
        for role in roles:
            for funnel in funnels:
                can_edit = f"edit-{role.id}-{funnel.id}" in request.form
                can_view = can_edit or f"view-{role.id}-{funnel.id}" in request.form
                if not can_view:
                    continue
                db.session.add(
                    FunnelAccess(
                        role_id=role.id,
                        funnel_id=funnel.id,
                        can_view=True,
                        can_edit=can_edit,
                    )
                )
            for view in views:
                if f"v-{role.id}-{view.id}" not in request.form:
                    continue
                # Просмотр без доступа к воронке не открывается, но галочку сохраняем
                db.session.add(ViewAccess(role_id=role.id, view_id=view.id, can_view=True))
        db.session.commit()
        flash("Права сохранены", "ok")
        return redirect(url_for("access_edit"))

    funnel_rights = {
        (row.role_id, row.funnel_id): row
        for row in FunnelAccess.query.all()
    }
    view_rights = {(row.role_id, row.view_id) for row in ViewAccess.query.all()}
    return render_template(
        "access.html",
        roles=roles,
        funnels=funnels,
        views=views,
        funnel_rights=funnel_rights,
        view_rights=view_rights,
    )


# ---------- Запуск ----------

with app.app_context():
    db.create_all()
    ensure_schema()
    seed_demo()
    seed_autoservice()


if __name__ == "__main__":
    # 0.0.0.0 — открывается и с компьютера, и с телефона в той же Wi‑Fi сети
    app.run(host="0.0.0.0", debug=True, port=5001)
