"""Бизнес-логика бронирования. Все расчёты и проверки выполняются здесь, на сервере.

Особое требование варианта 3:
1. Цена часа зависит от дня недели (будни/выходные) и времени суток
   (утренний 08–12, дневной 12–18, вечерний 18–23). Если бронь пересекает границу
   периодов, каждый час тарифицируется по своему периоду.
2. Бронь от 3 часов получает скидку на аренду зала.
3. Одну единицу оборудования нельзя закрепить за двумя бронями (то есть за двумя
   залами) на пересекающееся время.
"""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Booking, BookingEquipment, Equipment, Hall, MakeupSeat, Tariff

CENT = Decimal("0.01")


class BookingError(Exception):
    """Нарушено бизнес-правило; messages — список понятных пользователю текстов."""

    def __init__(self, messages):
        self.messages = list(messages)
        super().__init__("; ".join(self.messages))


@dataclass
class Quote:
    hours: int
    segments: list = field(default_factory=list)   # [{period, label, day_label, hours, price, amount}]
    hall_cost: Decimal = Decimal("0")
    discount_percent: int = 0
    discount_amount: Decimal = Decimal("0")
    equipment_items: list = field(default_factory=list)  # [{equipment, price_per_hour, cost}]
    equipment_cost: Decimal = Decimal("0")
    seats_items: list = field(default_factory=list)
    seats_cost: Decimal = Decimal("0")

    @property
    def hall_total(self) -> Decimal:
        return self.hall_cost - self.discount_amount

    @property
    def total(self) -> Decimal:
        return self.hall_total + self.equipment_cost + self.seats_cost

    def as_dict(self) -> dict:
        return {
            "hours": self.hours,
            "segments": [
                {**s, "price": str(s["price"]), "amount": str(s["amount"])} for s in self.segments
            ],
            "hall_cost": str(self.hall_cost),
            "discount_percent": self.discount_percent,
            "discount_amount": str(self.discount_amount),
            "hall_total": str(self.hall_total),
            "equipment": [
                {"name": i["equipment"].name, "cost": str(i["cost"])} for i in self.equipment_items
            ],
            "equipment_cost": str(self.equipment_cost),
            "seats": [{"name": i["seat"].name, "cost": str(i["cost"])} for i in self.seats_items],
            "seats_cost": str(self.seats_cost),
            "total": str(self.total),
        }


# ---------- время ----------

def day_type_for(dt: datetime) -> str:
    return Tariff.WEEKEND if timezone.localtime(dt).weekday() >= 5 else Tariff.WEEKDAY


def make_start(date, hour: int) -> datetime:
    return timezone.make_aware(datetime.combine(date, time(hour=hour)))


def local_day_bounds(date):
    start = timezone.make_aware(datetime.combine(date, time.min))
    return start, start + timedelta(days=1)


def tariff_prices(hall: Hall) -> dict:
    return {(t.day_type, t.period): t.price_per_hour for t in hall.tariffs.all()}


# ---------- расчёт стоимости ----------

def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def make_quote(hall: Hall, start: datetime, hours: int, equipment=(), seats=()) -> Quote:
    """Рассчитывает стоимость брони. Бросает BookingError, если для часа нет тарифа."""
    prices = tariff_prices(hall)
    quote = Quote(hours=hours)
    labels = dict(Tariff.PERIODS)
    day_labels = dict(Tariff.DAY_TYPES)
    local_start = timezone.localtime(start)

    for i in range(hours):
        moment = local_start + timedelta(hours=i)
        day_type = Tariff.WEEKEND if moment.weekday() >= 5 else Tariff.WEEKDAY
        period = Tariff.period_for_hour(moment.hour)
        try:
            price = prices[(day_type, period)]
        except KeyError:
            raise BookingError([f"Для зала «{hall}» не задан тариф: {day_labels[day_type]}, {labels[period].lower()}."])
        if quote.segments and quote.segments[-1]["period"] == period and quote.segments[-1]["day_type"] == day_type:
            seg = quote.segments[-1]
            seg["hours"] += 1
            seg["amount"] = money(seg["price"] * seg["hours"])
        else:
            quote.segments.append({
                "period": period, "day_type": day_type,
                "label": labels[period], "day_label": day_labels[day_type],
                "hours": 1, "price": price, "amount": money(price),
            })

    quote.hall_cost = sum((s["amount"] for s in quote.segments), Decimal("0"))
    if hours >= settings.DISCOUNT_FROM_HOURS:
        quote.discount_percent = settings.DISCOUNT_PERCENT
        quote.discount_amount = money(quote.hall_cost * settings.DISCOUNT_PERCENT / 100)

    for eq in equipment:
        cost = money(eq.price_per_hour * hours)
        quote.equipment_items.append({"equipment": eq, "price_per_hour": eq.price_per_hour, "cost": cost})
    quote.equipment_cost = sum((i["cost"] for i in quote.equipment_items), Decimal("0"))

    for seat in seats:
        cost = money(seat.price_per_hour * hours)
        quote.seats_items.append({"seat": seat, "cost": cost})
    quote.seats_cost = sum((i["cost"] for i in quote.seats_items), Decimal("0"))
    return quote


# ---------- занятость ----------

def _fmt_range(start, end) -> str:
    s, e = timezone.localtime(start), timezone.localtime(end)
    return f"{s:%d.%m.%Y %H:%M}–{e:%H:%M}"


def busy_equipment_map(start, end, exclude_booking_id=None) -> dict:
    """{equipment_id: Booking} — оборудование, уже закреплённое за активной бронью в этот интервал."""
    qs = BookingEquipment.objects.filter(
        booking__status__in=Booking.ACTIVE_STATUSES,
        booking__start__lt=end,
        booking__end__gt=start,
    ).select_related("booking", "booking__hall")
    if exclude_booking_id:
        qs = qs.exclude(booking_id=exclude_booking_id)
    return {item.equipment_id: item.booking for item in qs}


def busy_seats_map(start, end, exclude_booking_id=None) -> dict:
    qs = Booking.objects.filter(status__in=Booking.ACTIVE_STATUSES, start__lt=end, end__gt=start, makeup_seats__isnull=False)
    if exclude_booking_id:
        qs = qs.exclude(pk=exclude_booking_id)
    result = {}
    for booking in qs.prefetch_related("makeup_seats").select_related("hall"):
        for seat in booking.makeup_seats.all():
            result[seat.pk] = booking
    return result


def hall_conflicts(hall, start, end, exclude_booking_id=None):
    qs = Booking.objects.filter(hall=hall, status__in=Booking.ACTIVE_STATUSES, start__lt=end, end__gt=start)
    if exclude_booking_id:
        qs = qs.exclude(pk=exclude_booking_id)
    return qs


# ---------- проверка заявки ----------

def validate_request(*, hall, start, hours, people, equipment=(), seats=(), exclude_booking_id=None, allow_past=False) -> list:
    """Возвращает список ошибок (пустой — заявка допустима)."""
    errors = []
    open_h, close_h = settings.STUDIO_OPEN_HOUR, settings.STUDIO_CLOSE_HOUR
    local_start = timezone.localtime(start)

    if not hall.is_active:
        errors.append(f"Зал «{hall}» сейчас не принимает брони.")
    if hours < 1 or hours > settings.MAX_BOOKING_HOURS:
        errors.append(f"Длительность брони — от 1 до {settings.MAX_BOOKING_HOURS} часов.")
    if local_start.minute or local_start.second:
        errors.append("Бронь начинается с начала часа.")
    if local_start.hour < open_h or local_start.hour >= close_h:
        errors.append(f"Студия работает с {open_h:02d}:00 до {close_h:02d}:00.")
    elif local_start.hour + hours > close_h:
        errors.append(f"Бронь должна закончиться не позже {close_h:02d}:00 — уменьшите длительность или начните раньше.")
    if not allow_past and start <= timezone.now():
        errors.append("Нельзя бронировать время в прошлом.")
    if people > hall.capacity:
        errors.append(f"Зал вмещает не более {hall.capacity} чел., указано {people}.")
    if errors:
        return errors

    end = start + timedelta(hours=hours)
    for other in hall_conflicts(hall, start, end, exclude_booking_id):
        errors.append(f"Зал «{hall}» уже занят в это время ({_fmt_range(other.start, other.end)}).")
        break

    busy_eq = busy_equipment_map(start, end, exclude_booking_id)
    for eq in equipment:
        if eq.status != Equipment.AVAILABLE:
            errors.append(f"«{eq.name}» [{eq.inventory_number}] недоступно: {eq.get_status_display().lower()}.")
        elif eq.pk in busy_eq:
            other = busy_eq[eq.pk]
            errors.append(
                f"«{eq.name}» [{eq.inventory_number}] уже закреплено за залом «{other.hall}» "
                f"на пересекающееся время ({_fmt_range(other.start, other.end)})."
            )

    busy_st = busy_seats_map(start, end, exclude_booking_id)
    for seat in seats:
        if seat.hall_id != hall.pk:
            errors.append(f"Гримёрное место «{seat.name}» относится к другому залу.")
        elif not seat.is_active:
            errors.append(f"Гримёрное место «{seat.name}» недоступно.")
        elif seat.pk in busy_st:
            errors.append(f"Гримёрное место «{seat.name}» занято в это время.")
    return errors


@transaction.atomic
def save_booking(*, user, hall, start, hours, people=1, equipment=(), seats=(), comment="",
                 reference_file=None, instance=None, allow_past=False) -> Booking:
    """Создаёт или обновляет бронь: проверка + расчёт + запись нескольких таблиц одной транзакцией."""
    equipment, seats = list(equipment), list(seats)
    # Блокируем зал и выбранное оборудование на время проверки (на SQLite — no-op, на PostgreSQL — реальная блокировка).
    Hall.objects.select_for_update().get(pk=hall.pk)
    if equipment:
        list(Equipment.objects.select_for_update().filter(pk__in=[e.pk for e in equipment]))
    if seats:
        list(MakeupSeat.objects.select_for_update().filter(pk__in=[s.pk for s in seats]))

    errors = validate_request(
        hall=hall, start=start, hours=hours, people=people, equipment=equipment, seats=seats,
        exclude_booking_id=instance.pk if instance else None, allow_past=allow_past,
    )
    if errors:
        raise BookingError(errors)
    quote = make_quote(hall, start, hours, equipment, seats)

    booking = instance or Booking(user=user)
    booking.hall = hall
    booking.start = start
    booking.end = start + timedelta(hours=hours)
    booking.hours = hours
    booking.people = people
    booking.comment = comment
    booking.hall_cost = quote.hall_cost
    booking.discount_percent = quote.discount_percent
    booking.discount_amount = quote.discount_amount
    booking.equipment_cost = quote.equipment_cost
    booking.seats_cost = quote.seats_cost
    booking.total_price = quote.total
    if reference_file:
        booking.reference_file = reference_file
    booking.save()

    booking.makeup_seats.set(seats)
    BookingEquipment.objects.filter(booking=booking).delete()
    BookingEquipment.objects.bulk_create([
        BookingEquipment(booking=booking, equipment=i["equipment"], price_per_hour=i["price_per_hour"], cost=i["cost"])
        for i in quote.equipment_items
    ])
    return booking


@transaction.atomic
def change_status(booking: Booking, new_status: str) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    allowed = {
        Booking.PENDING: {Booking.CONFIRMED, Booking.CANCELLED},
        Booking.CONFIRMED: {Booking.COMPLETED, Booking.CANCELLED},
    }
    if new_status not in allowed.get(booking.status, set()):
        raise BookingError([f"Нельзя перевести бронь из статуса «{booking.get_status_display()}» в выбранный."])
    booking.status = new_status
    booking.save(update_fields=["status", "updated_at"])
    return booking


def day_board(halls, day):
    """Доска «Свободно сегодня»: для каждого зала — почасовые состояния на дату одним запросом к броням."""
    halls = list(halls)
    day_start, day_end = local_day_bounds(day)
    busy = Booking.objects.filter(
        hall__in=halls, status__in=Booking.ACTIVE_STATUSES, start__lt=day_end, end__gt=day_start,
    ).values_list("hall_id", "start", "end")
    by_hall = {}
    for hall_id, start, end in busy:
        by_hall.setdefault(hall_id, []).append((start, end))
    now = timezone.now()
    rows = []
    for hall in halls:
        slots = []
        for hour in range(settings.STUDIO_OPEN_HOUR, settings.STUDIO_CLOSE_HOUR):
            slot_start = make_start(day, hour)
            slot_end = slot_start + timedelta(hours=1)
            if slot_start <= now:
                state = "past"
            elif any(s < slot_end and e > slot_start for s, e in by_hall.get(hall.pk, [])):
                state = "busy"
            else:
                state = "free"
            slots.append({"hour": hour, "state": state})
        free = [x["hour"] for x in slots if x["state"] == "free"]
        rows.append({"hall": hall, "slots": slots, "free_count": len(free), "first_free": free[0] if free else None})
    return rows
