"""Кто вошёл в CRM и какие воронки ему можно открывать."""

from flask import g, session

from models import Deal, Funnel, FunnelAccess, User, ViewAccess, db


def current_user():
    """Сотрудник из сессии. Повторно в базу за этим запросом не ходим."""
    if hasattr(g, "crm_user"):
        return g.crm_user
    user = None
    user_id = session.get("user_id")
    if user_id:
        user = db.session.get(User, user_id)
    g.crm_user = user
    return user


def can_view_funnel(user, funnel_id) -> bool:
    """Роли разрешено открыть эту воронку."""
    if user is None or funnel_id is None:
        return False
    if user.role.is_admin:
        return True
    row = FunnelAccess.query.filter_by(
        role_id=user.role_id,
        funnel_id=funnel_id,
        can_view=True,
    ).first()
    return row is not None


def can_edit_funnel(user, funnel_id) -> bool:
    """Роли разрешено создавать и перетаскивать сделки в этой воронке."""
    if user is None or funnel_id is None:
        return False
    if user.role.is_admin:
        return True
    row = FunnelAccess.query.filter_by(
        role_id=user.role_id,
        funnel_id=funnel_id,
        can_edit=True,
    ).first()
    return row is not None


def visible_funnels(user):
    """Воронки, которые сотрудник видит в переключателе."""
    query = Funnel.query.order_by(Funnel.sort, Funnel.id)
    if user is None:
        return []
    if user.role.is_admin:
        return query.all()
    ids = [
        row.funnel_id
        for row in FunnelAccess.query.filter_by(role_id=user.role_id, can_view=True)
    ]
    if not ids:
        return []
    return query.filter(Funnel.id.in_(ids)).all()


def editable_funnels(user):
    """Воронки, в которых можно менять сделки."""
    if user is None:
        return []
    if user.role.is_admin:
        return visible_funnels(user)
    ids = [
        row.funnel_id
        for row in FunnelAccess.query.filter_by(role_id=user.role_id, can_edit=True)
    ]
    if not ids:
        return []
    return Funnel.query.filter(Funnel.id.in_(ids)).order_by(Funnel.sort, Funnel.id).all()


def visible_views(user, funnel):
    """Просмотры выбранной воронки, которые роли можно открыть."""
    from models import CrmView

    views = CrmView.query.filter_by(funnel_id=funnel.id).order_by(CrmView.sort, CrmView.id).all()
    if user.role.is_admin:
        return views
    allowed = {
        row.view_id
        for row in ViewAccess.query.filter_by(role_id=user.role_id, can_view=True)
    }
    return [view for view in views if view.id in allowed]


def limit_deals(query, user):
    """Оставляем в выборке только сделки из доступных воронок."""
    ids = [funnel.id for funnel in visible_funnels(user)]
    if not ids:
        return query.filter(Deal.id == 0)
    return query.filter(Deal.funnel_id.in_(ids))
