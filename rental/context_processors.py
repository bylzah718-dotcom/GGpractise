from django.conf import settings

from . import permissions


def roles(request):
    user = request.user
    return {
        "is_studio_admin": permissions.is_admin(user),
        "is_technician": permissions.is_technician(user),
        "can_manage_equipment": permissions.can_manage_equipment(user),
        "role_label": permissions.role_label(user),
        "STUDIO_NAME": settings.STUDIO_NAME,
        "DISCOUNT_FROM_HOURS": settings.DISCOUNT_FROM_HOURS,
        "DISCOUNT_PERCENT": settings.DISCOUNT_PERCENT,
    }
