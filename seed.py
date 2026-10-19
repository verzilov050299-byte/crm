"""Демо-данные: старая общая воронка и направления автосервиса."""

from datetime import date, timedelta

from werkzeug.security import generate_password_hash

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

# Готовые наборы стадий. Последние две в каждом наборе — успех и отказ.
PRESETS = {
    "repair": {
        "name": "Ремонт",
        "color": "#39A8EF",
        "sort": 10,
        "stages": [
            ("Заявка", "process", "#39A8EF"),
            ("Диагностика", "process", "#2FC6F6"),
            ("Согласование", "process", "#55D0E0"),
            ("Ремонт", "process", "#47E4C2"),
            ("Готово к выдаче", "process", "#FFA900"),
            ("Выдано", "success", "#7BD500"),
            ("Отказ", "failure", "#FF5752"),
        ],
    },
    "paint": {
        "name": "Покраска",
        "color": "#FFA900",
        "sort": 20,
        "stages": [
            ("Заявка", "process", "#39A8EF"),
            ("Осмотр", "process", "#2FC6F6"),
            ("Подбор цвета", "process", "#55D0E0"),
            ("Покраска", "process", "#FFA900"),
            ("Полировка", "process", "#47E4C2"),
            ("Готово", "success", "#7BD500"),
            ("Отказ", "failure", "#FF5752"),
        ],
    },
    "tire": {
        "name": "Шиномонтаж",
        "color": "#47E4C2",
        "sort": 30,
        "stages": [
            ("Запись", "process", "#39A8EF"),
            ("Приём колёс", "process", "#2FC6F6"),
            ("Шиномонтаж", "process", "#47E4C2"),
            ("Балансировка", "process", "#FFA900"),
            ("Выдано", "success", "#7BD500"),
            ("Отказ", "failure", "#FF5752"),
        ],
    },
    "body": {
        "name": "Жестянка",
        "color": "#FF5752",
        "sort": 40,
        "stages": [
            ("Заявка", "process", "#39A8EF"),
            ("Дефектовка", "process", "#2FC6F6"),
            ("Согласование", "process", "#55D0E0"),
            ("Рихтовка", "process", "#FF5752"),
            ("Под покраску", "process", "#FFA900"),
            ("Готово", "success", "#7BD500"),
            ("Отказ", "failure", "#FF5752"),
        ],
    },
    "service": {
        "name": "ТО",
        "color": "#2FC6F6",
        "sort": 50,
        "stages": [
            ("Запись", "process", "#39A8EF"),
            ("Приём", "process", "#2FC6F6"),
            ("Работы", "process", "#47E4C2"),
            ("Готово", "success", "#7BD500"),
            ("Отказ", "failure", "#FF5752"),
        ],
    },
    "generic": {
        "name": "Новая воронка",
        "color": "#39A8EF",
        "sort": 80,
        "stages": [
            ("Заявка", "process", "#39A8EF"),
            ("В работе", "process", "#47E4C2"),
            ("Согласование", "process", "#FFA900"),
            ("Готово", "success", "#7BD500"),
            ("Отказ", "failure", "#FF5752"),
        ],
    },
}

# Какие направления видит роль, если права ещё никто не настраивал.
# (смотреть, менять сделки)
DEFAULT_ACCESS = {
    "director": {
        "repair": (True, True),
        "paint": (True, True),
        "tire": (True, True),
        "body": (True, True),
        "service": (True, True),
        "general": (True, True),
    },
    "receiver": {
        "repair": (True, True),
        "tire": (True, True),
        "service": (True, True),
    },
    "painter": {"paint": (True, True)},
    "body": {"body": (True, True)},
    "tire": {"tire": (True, True)},
}

SYSTEM_VIEWS = [
    ("Все", "all", 10),
    ("В работе", "process", 20),
    ("Успешные", "success", 30),
    ("Отказы", "failure", 40),
]


def seed_stages() -> None:
    """Стадии основной воронки (как DEAL_STAGE в Bitrix)."""
    stages = [
        ("NEW", "Новая", "process", "#39A8EF", 10),
        ("PREPARATION", "Подготовка документов", "process", "#2FC6F6", 20),
        ("PREPAYMENT_INVOICE", "Счёт на предоплату", "process", "#55D0E0", 30),
        ("EXECUTING", "В работе", "process", "#47E4C2", 40),
        ("FINAL_INVOICE", "Финальный счёт", "process", "#FFA900", 50),
        ("WON", "Сделка успешна", "success", "#7BD500", 60),
        ("LOSE", "Сделка провалена", "failure", "#FF5752", 70),
    ]
    for status_id, name, semantics, color, sort in stages:
        db.session.add(
            DealStage(
                status_id=status_id,
                name=name,
                semantics=semantics,
                color=color,
                sort=sort,
            )
        )
    db.session.commit()


def seed_demo() -> None:
    """Заполняем базу примерами для малого бизнеса."""
    if DealStage.query.first():
        return  # уже есть данные — не дублируем

    seed_stages()

    alpha = Company(
        title="ООО Альфа Сервис",
        phone="+7 495 111-22-33",
        email="info@alpha-service.ru",
        address="Москва, ул. Тверская, 10",
        comments="Постоянный клиент, B2B",
    )
    beta = Company(
        title="ИП Бета",
        phone="+7 812 444-55-66",
        email="hello@beta.shop",
        address="Санкт-Петербург",
        comments="Интернет-магазин",
    )
    db.session.add_all([alpha, beta])
    db.session.flush()

    ivan = Contact(
        name="Иван",
        last_name="Петров",
        phone="+7 900 111-22-33",
        email="ivan@alpha-service.ru",
        post="Директор",
        company_id=alpha.id,
    )
    maria = Contact(
        name="Мария",
        last_name="Сидорова",
        phone="+7 900 222-33-44",
        email="maria@beta.shop",
        post="Закупки",
        company_id=beta.id,
    )
    oleg = Contact(
        name="Олег",
        last_name="Козлов",
        phone="+7 900 333-44-55",
        email="oleg@mail.ru",
        post="Частный клиент",
    )
    db.session.add_all([ivan, maria, oleg])
    db.session.flush()

    leads = [
        Lead(
            title="Запрос на внедрение CRM",
            name="Анна",
            phone="+7 900 555-66-77",
            email="anna@newco.ru",
            status_id="NEW",
            source_id="WEB",
            opportunity=120000,
            comments="Оставила заявку на сайте",
        ),
        Lead(
            title="Звонок: консультация по тарифам",
            name="Дмитрий",
            phone="+7 900 777-88-99",
            status_id="IN_PROCESS",
            source_id="CALL",
            opportunity=45000,
        ),
        Lead(
            title="Партнёрская рекомендация",
            name="Елена",
            email="elena@partner.ru",
            status_id="PROCESSED",
            source_id="PARTNER",
            opportunity=80000,
        ),
    ]
    db.session.add_all(leads)

    stage_map = {s.status_id: s.id for s in DealStage.query.all()}

    deals = [
        Deal(
            title="Подписка на год — Альфа",
            opportunity=180000,
            stage_id=stage_map["EXECUTING"],
            contact_id=ivan.id,
            company_id=alpha.id,
            comments="Ждём оплату второго этапа",
            close_date=date.today() + timedelta(days=20),
        ),
        Deal(
            title="Поставка ПО для Бета",
            opportunity=65000,
            stage_id=stage_map["PREPAYMENT_INVOICE"],
            contact_id=maria.id,
            company_id=beta.id,
            close_date=date.today() + timedelta(days=10),
        ),
        Deal(
            title="Разовая консультация",
            opportunity=15000,
            stage_id=stage_map["NEW"],
            contact_id=oleg.id,
            close_date=date.today() + timedelta(days=5),
        ),
        Deal(
            title="Апселл модулей — Альфа",
            opportunity=42000,
            stage_id=stage_map["WON"],
            contact_id=ivan.id,
            company_id=alpha.id,
            close_date=date.today() - timedelta(days=3),
        ),
        Deal(
            title="Пилот для Бета (отказ)",
            opportunity=30000,
            stage_id=stage_map["LOSE"],
            contact_id=maria.id,
            company_id=beta.id,
            comments="Выбрали конкурента",
            close_date=date.today() - timedelta(days=7),
        ),
    ]
    db.session.add_all(deals)
    db.session.flush()

    tasks = [
        Task(
            title="Позвонить Ивану по оплате",
            description="Уточнить срок второго платежа",
            deadline=date.today(),
            deal_id=deals[0].id,
            contact_id=ivan.id,
        ),
        Task(
            title="Отправить КП Марии",
            deadline=date.today() + timedelta(days=1),
            deal_id=deals[1].id,
            contact_id=maria.id,
        ),
        Task(
            title="Подготовить договор для Олега",
            deadline=date.today() - timedelta(days=1),
            deal_id=deals[2].id,
            contact_id=oleg.id,
        ),
        Task(
            title="Закрыть отчёт по выигранной сделке",
            deadline=date.today() + timedelta(days=2),
            deal_id=deals[3].id,
            is_done=True,
        ),
    ]
    db.session.add_all(tasks)
    db.session.commit()


def add_stages(funnel: Funnel, stages) -> None:
    """Создаёт стадии воронки. Код стадии уникальный: repair_1, paint_2 и т.д."""
    for index, (name, semantics, color) in enumerate(stages, start=1):
        db.session.add(
            DealStage(
                funnel_id=funnel.id,
                status_id=f"{funnel.code}_{index}",
                name=name,
                semantics=semantics,
                color=color,
                sort=index * 10,
            )
        )


def add_system_views(funnel: Funnel) -> None:
    """Четыре просмотра, без которых воронку неудобно открывать."""
    for name, semantics, sort in SYSTEM_VIEWS:
        exists = CrmView.query.filter_by(funnel_id=funnel.id, name=name).first()
        if exists:
            continue
        db.session.add(
            CrmView(
                name=name,
                funnel_id=funnel.id,
                semantics=semantics,
                sort=sort,
                is_system=True,
            )
        )


def seed_autoservice() -> None:
    """Роли, сотрудники и воронки автосервиса. Повторный запуск ничего не дублирует."""
    _ensure_roles()
    _attach_old_stages()
    _ensure_preset_funnels()
    for funnel in Funnel.query.all():
        add_system_views(funnel)
    db.session.flush()
    _ensure_default_access()
    _ensure_service_deals()
    db.session.commit()


def _ensure_roles() -> None:
    """Сотрудники цеха. Пароль для входа совпадает с логином."""
    people = [
        ("admin", "Администратор", True, "Анна Соколова"),
        ("director", "Руководитель", False, "Игорь Белов"),
        ("receiver", "Мастер-приёмщик", False, "Марина Кузнецова"),
        ("painter", "Маляр", False, "Денис Орлов"),
        ("body", "Жестянщик", False, "Павел Морозов"),
        ("tire", "Шиномонтажник", False, "Сергей Волков"),
    ]
    for code, role_name, is_admin, person_name in people:
        role = Role.query.filter_by(code=code).first()
        if role is None:
            role = Role(code=code, name=role_name, is_admin=is_admin)
            db.session.add(role)
            db.session.flush()
        user = User.query.filter_by(login=code).first()
        email = f"{code}@bizcrm.local"
        if user is None:
            db.session.add(
                User(
                    name=person_name,
                    email=email,
                    login=code,
                    password_hash=generate_password_hash(code),
                    role_id=role.id,
                    is_active=True,
                )
            )
        elif not user.email:
            # Старые демо-аккаунты дополняем почтой
            user.email = email
    db.session.flush()


def _attach_old_stages() -> None:
    """Старые стадии без воронки складываем в «Общую», чтобы сделки не пропали."""
    orphans = DealStage.query.filter(DealStage.funnel_id.is_(None)).all()
    funnel = Funnel.query.filter_by(code="general").first()
    if orphans and funnel is None:
        funnel = Funnel(name="Общая", code="general", color="#8B98A5", sort=90)
        db.session.add(funnel)
        db.session.flush()
    if funnel is not None:
        for stage in orphans:
            stage.funnel_id = funnel.id
    db.session.flush()
    for deal in Deal.query.filter(Deal.funnel_id.is_(None)):
        if deal.stage is not None and deal.stage.funnel_id:
            deal.funnel_id = deal.stage.funnel_id


def _ensure_preset_funnels() -> None:
    for code, preset in PRESETS.items():
        if code == "generic":
            continue  # пустой шаблон только для кнопки «Новая воронка»
        if Funnel.query.filter_by(code=code).first():
            continue
        funnel = Funnel(
            code=code,
            name=preset["name"],
            color=preset["color"],
            sort=preset["sort"],
        )
        db.session.add(funnel)
        db.session.flush()
        add_stages(funnel, preset["stages"])
    db.session.flush()


def _ensure_default_access() -> None:
    """Первичная матрица прав. Если администратор уже сохранял её — не затираем."""
    if FunnelAccess.query.first():
        return
    funnels = {funnel.code: funnel for funnel in Funnel.query.all()}
    for role_code, grants in DEFAULT_ACCESS.items():
        role = Role.query.filter_by(code=role_code).first()
        if role is None:
            continue
        for funnel_code, (can_view, can_edit) in grants.items():
            funnel = funnels.get(funnel_code)
            if funnel is None:
                continue
            db.session.add(
                FunnelAccess(
                    role_id=role.id,
                    funnel_id=funnel.id,
                    can_view=can_view,
                    can_edit=can_edit,
                )
            )
            if not can_view:
                continue
            for view in CrmView.query.filter_by(funnel_id=funnel.id):
                db.session.add(
                    ViewAccess(role_id=role.id, view_id=view.id, can_view=True)
                )
    db.session.flush()


def _owner(name: str, last_name: str, phone: str) -> Contact:
    found = Contact.query.filter_by(phone=phone).first()
    if found:
        return found
    contact = Contact(name=name, last_name=last_name, phone=phone, post="Автовладелец")
    db.session.add(contact)
    db.session.flush()
    return contact


def _ensure_service_deals() -> None:
    """Несколько машин в цеху, чтобы канбан автосервиса был не пустой."""
    if Deal.query.filter_by(title="Замена ГРМ").first():
        return
    owners = {
        "camry": _owner("Олег", "Козлов", "+7 900 333-44-55"),
        "bmw": _owner("Сергей", "Волков", "+7 900 410-20-30"),
        "kia": _owner("Анна", "Орлова", "+7 900 510-20-30"),
        "solaris": _owner("Павел", "Морозов", "+7 900 610-20-30"),
    }
    samples = [
        ("repair", 4, "Замена ГРМ", "Toyota Camry, А123АА77", 18500, "camry"),
        ("repair", 2, "Стучит подвеска", "Kia Rio, В456ВВ77", 4500, "kia"),
        ("paint", 4, "Покраска бампера", "BMW X5, К789КК77", 32000, "bmw"),
        ("tire", 3, "Зимний комплект", "Kia Rio, В456ВВ77", 8000, "kia"),
        ("body", 2, "Крыло после ДТП", "Hyundai Solaris, О321ОО77", 54000, "solaris"),
        ("service", 3, "ТО-2", "Hyundai Solaris, О321ОО77", 12000, "solaris"),
    ]
    for code, stage_no, title, car, amount, owner_key in samples:
        stage = DealStage.query.filter_by(status_id=f"{code}_{stage_no}").first()
        if stage is None:
            continue
        db.session.add(
            Deal(
                title=title,
                car=car,
                opportunity=amount,
                stage_id=stage.id,
                funnel_id=stage.funnel_id,
                contact_id=owners[owner_key].id,
                close_date=date.today() + timedelta(days=3),
            )
        )
