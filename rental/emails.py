"""Почтовые уведомления. Отправка не должна ломать бизнес-операцию, поэтому ошибки логируются."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)


def _send(subject: str, body: str, to: str | None) -> bool:
    if not to:
        return False
    try:
        send_mail(f"[{settings.STUDIO_NAME}] {subject}", body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        return True
    except Exception:  # noqa: BLE001 — почтовый сервер недоступен: бронь уже сохранена
        logger.exception("Не удалось отправить письмо: %s", subject)
        return False


def _when(booking) -> str:
    s, e = timezone.localtime(booking.start), timezone.localtime(booking.end)
    return f"{s:%d.%m.%Y}, {s:%H:%M}–{e:%H:%M}"


def send_welcome(user) -> bool:
    return _send(
        "Добро пожаловать!",
        f"Здравствуйте, {user.username}!\n\nВы зарегистрировались в фотостудии «{settings.STUDIO_NAME}». "
        "Теперь вы можете бронировать залы и оборудование онлайн.",
        user.email,
    )


def send_booking_created(booking) -> bool:
    return _send(
        f"Бронь №{booking.pk} оформлена",
        f"Здравствуйте, {booking.user.username}!\n\nЗал: {booking.hall}\nВремя: {_when(booking)}\n"
        f"Итого: {booking.total_price} ₽\nСтатус: {booking.get_status_display()}.\n\n"
        "Мы сообщим, когда администратор подтвердит бронь.",
        booking.user.email,
    )


def send_status_changed(booking) -> bool:
    return _send(
        f"Бронь №{booking.pk}: {booking.get_status_display().lower()}",
        f"Здравствуйте, {booking.user.username}!\n\nСтатус вашей брони №{booking.pk} ({booking.hall}, {_when(booking)}) "
        f"изменён: {booking.get_status_display()}.",
        booking.user.email,
    )


def send_penalty(penalty) -> bool:
    b = penalty.booking
    return _send(
        f"Штраф по брони №{b.pk}",
        f"Здравствуйте, {b.user.username}!\n\nПо брони №{b.pk} ({b.hall}, {_when(b)}) выставлен штраф "
        f"{penalty.amount} ₽.\nПричина: {penalty.reason}",
        b.user.email,
    )
