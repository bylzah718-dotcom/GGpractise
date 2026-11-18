from django.conf import settings

from . import permissions


def nav_items(request, user):
    """Пункты меню описаны именами маршрутов; адрес строит {% url %} в шаблоне.

    Элемент: (имя маршрута, подпись, это кнопка?). Что показывать — решают права пользователя.
    """
    items = [("rental:home", "Залы", False), ("rental:equipment_list", "Оборудование", False)]
    if user.is_authenticated:
        items.append(("rental:booking_list", "Все брони" if permissions.is_admin(user) else "Мои брони", False))
        items.append(("rental:booking_create", "Забронировать", True))
        if permissions.can_manage_equipment(user):
            items.append(("rental:stats", "Показатели", False))
        if permissions.is_admin(user):
            items.append(("admin:index", "Админка", False))
    else:
        items.append(("rental:login", "Войти", False))
        items.append(("rental:register", "Регистрация", True))
    current = request.resolver_match.view_name if request.resolver_match else ""
    return [{"name": n, "label": l, "button": b, "current": n == current} for n, l, b in items]


def roles(request):
    user = request.user
    return {
        "is_studio_admin": permissions.is_admin(user),
        "is_technician": permissions.is_technician(user),
        "can_manage_equipment": permissions.can_manage_equipment(user),
        "role_label": permissions.role_label(user),
        "nav_items": nav_items(request, user),
        "STUDIO_NAME": settings.STUDIO_NAME,
        "STUDIO_PHONE": settings.STUDIO_PHONE,
        "STUDIO_EMAIL": settings.STUDIO_EMAIL,
        "DISCOUNT_FROM_HOURS": settings.DISCOUNT_FROM_HOURS,
        "DISCOUNT_PERCENT": settings.DISCOUNT_PERCENT,
    }
