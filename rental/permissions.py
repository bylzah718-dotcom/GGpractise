"""Роли: гость, арендатор (любой вошедший пользователь), техник, администратор студии."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

TECH_GROUP = "Техник"


def is_admin(user) -> bool:
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def is_technician(user) -> bool:
    return user.is_authenticated and user.groups.filter(name=TECH_GROUP).exists()


def can_manage_equipment(user) -> bool:
    return is_admin(user) or is_technician(user)


def role_label(user) -> str:
    if not user.is_authenticated:
        return "Гость"
    if is_admin(user):
        return "Администратор студии"
    if is_technician(user):
        return "Техник по оборудованию"
    return "Арендатор"


def role_required(check):
    """Гость → на страницу входа, вошедший без нужной роли → 403."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


admin_required = role_required(is_admin)
equipment_manager_required = role_required(can_manage_equipment)
