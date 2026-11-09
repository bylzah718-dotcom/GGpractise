"""Представления. Расчёты и проверки — в services.py, здесь только HTTP-слой."""
import csv
from datetime import date as date_cls, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Min, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import emails, permissions, services
from .forms import BookingForm, EquipmentForm, PenaltyForm, RegisterForm, ReviewForm
from .models import Booking, BookingEquipment, Equipment, Hall, MakeupSeat, Penalty, Review, Tariff

PAGE_SIZE = 20


# ---------- вспомогательное ----------

def paginate(request, queryset):
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


def parse_date(value):
    try:
        return date_cls.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_booking_or_403(request, pk, *, staff_allowed=True):
    """Чужая бронь по прямой ссылке → 403. Видят свои, администратор и (для просмотра) техник."""
    booking = get_object_or_404(Booking.objects.select_related("hall", "user"), pk=pk)
    user = request.user
    if booking.user_id == user.pk:
        return booking
    if staff_allowed and permissions.is_admin(user):
        return booking
    raise PermissionDenied


def can_view_booking(user, booking) -> bool:
    return booking.user_id == user.pk or permissions.can_manage_equipment(user)


# ---------- регистрация ----------

def register(request):
    if request.user.is_authenticated:
        return redirect("rental:home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        emails.send_welcome(user)
        login(request, user)
        messages.success(request, "Регистрация прошла успешно. Добро пожаловать!")
        return redirect("rental:home")
    return render(request, "rental/auth/register.html", {"form": form})


# ---------- залы ----------

def home(request):
    halls = (
        Hall.objects.filter(is_active=True)
        .annotate(min_price=Min("tariffs__price_per_hour"), avg_rating=Avg("reviews__rating"))
        .order_by("name")
    )
    return render(request, "rental/home.html", {"halls": halls})


def hall_detail(request, slug):
    hall = get_object_or_404(Hall, slug=slug)
    prices = services.tariff_prices(hall)
    rows = []
    for period, label in Tariff.PERIODS:
        start, end = Tariff.PERIOD_HOURS[period]
        rows.append({
            "label": label, "interval": f"{start:02d}:00–{end:02d}:00",
            "weekday": prices.get((Tariff.WEEKDAY, period)), "weekend": prices.get((Tariff.WEEKEND, period)),
        })
    reviews = hall.reviews.select_related("author")
    my_review = reviews.filter(author=request.user).first() if request.user.is_authenticated else None
    can_review = request.user.is_authenticated and my_review is None and has_finished_booking(request.user, hall)
    context = {
        "hall": hall, "tariff_rows": rows, "zones": hall.zones.all(), "seats": hall.makeup_seats.filter(is_active=True),
        "reviews": reviews, "my_review": my_review, "can_review": can_review,
        "avg_rating": reviews.aggregate(a=Avg("rating"))["a"], "today": timezone.localdate(),
    }
    return render(request, "rental/hall_detail.html", context)


def has_finished_booking(user, hall) -> bool:
    now = timezone.now()
    return Booking.objects.filter(user=user, hall=hall).filter(
        Q(status=Booking.COMPLETED) | Q(status=Booking.CONFIRMED, end__lte=now)
    ).exists()


# ---------- отзывы (CRUD) ----------

@login_required
def review_create(request, slug):
    hall = get_object_or_404(Hall, slug=slug)
    if Review.objects.filter(author=request.user, hall=hall).exists():
        messages.info(request, "Вы уже оставили отзыв об этом зале — его можно изменить.")
        return redirect(hall)
    if not has_finished_booking(request.user, hall):
        raise PermissionDenied
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        review = form.save(commit=False)
        review.author, review.hall = request.user, hall
        review.save()
        messages.success(request, "Спасибо за отзыв!")
        return redirect(hall)
    return render(request, "rental/review_form.html", {"form": form, "hall": hall, "title": "Новый отзыв"})


@login_required
def review_edit(request, pk):
    review = get_object_or_404(Review.objects.select_related("hall"), pk=pk)
    if review.author_id != request.user.pk:
        raise PermissionDenied
    form = ReviewForm(request.POST or None, instance=review)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Отзыв изменён.")
        return redirect(review.hall)
    return render(request, "rental/review_form.html", {"form": form, "hall": review.hall, "title": "Изменить отзыв"})


@login_required
def review_delete(request, pk):
    review = get_object_or_404(Review.objects.select_related("hall"), pk=pk)
    if review.author_id != request.user.pk and not permissions.is_admin(request.user):
        raise PermissionDenied
    if request.method == "POST":
        hall = review.hall
        review.delete()
        messages.success(request, "Отзыв удалён.")
        return redirect(hall)
    return render(request, "rental/confirm_delete.html", {
        "object_title": f"Отзыв о зале «{review.hall}»", "cancel_url": review.hall.get_absolute_url(),
    })


# ---------- каталог оборудования ----------

EQUIPMENT_SORTS = {"name": "name", "price": "price_per_hour", "category": "category"}


def equipment_list(request):
    qs = Equipment.objects.all()
    if not permissions.can_manage_equipment(request.user):
        qs = qs.exclude(status=Equipment.RETIRED)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(inventory_number__icontains=q))

    category = request.GET.get("category", "")
    if category in dict(Equipment.CATEGORIES):
        qs = qs.filter(category=category)
    status = request.GET.get("status", "")
    if status in dict(Equipment.STATUSES):
        qs = qs.filter(status=status)
    max_price = parse_int(request.GET.get("max_price"))
    if max_price is not None:
        qs = qs.filter(price_per_hour__lte=max_price)
    free_date = parse_date(request.GET.get("free_date"))
    if free_date:
        day_start, day_end = services.local_day_bounds(free_date)
        busy_ids = BookingEquipment.objects.filter(
            booking__status__in=Booking.ACTIVE_STATUSES, booking__start__lt=day_end, booking__end__gt=day_start,
        ).values("equipment_id")
        qs = qs.exclude(pk__in=busy_ids).filter(status=Equipment.AVAILABLE)

    sort = request.GET.get("sort", "name")
    field = EQUIPMENT_SORTS.get(sort, "name")
    descending = request.GET.get("dir") == "desc"
    qs = qs.order_by(f"-{field}" if descending else field, "inventory_number")

    page, query_string = paginate(request, qs)
    return render(request, "rental/equipment_list.html", {
        "page": page, "query_string": query_string, "q": q, "category": category, "status": status,
        "max_price": request.GET.get("max_price", ""), "free_date": request.GET.get("free_date", ""),
        "sort": sort if sort in EQUIPMENT_SORTS else "name", "dir": "desc" if descending else "asc",
        "categories": Equipment.CATEGORIES, "statuses": Equipment.STATUSES,
    })


@permissions.equipment_manager_required
def equipment_create(request):
    form = EquipmentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        item = form.save()
        messages.success(request, f"«{item.name}» добавлено в каталог.")
        return redirect("rental:equipment_list")
    return render(request, "rental/equipment_form.html", {"form": form, "title": "Новая единица оборудования"})


@permissions.equipment_manager_required
def equipment_edit(request, pk):
    item = get_object_or_404(Equipment, pk=pk)
    form = EquipmentForm(request.POST or None, request.FILES or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Изменения сохранены.")
        return redirect("rental:equipment_list")
    return render(request, "rental/equipment_form.html", {"form": form, "title": f"Изменить: {item.name}", "item": item})


@permissions.equipment_manager_required
def equipment_delete(request, pk):
    item = get_object_or_404(Equipment, pk=pk)
    if request.method == "POST":
        if item.booking_items.exists():
            # Оборудование с историей броней не удаляем — списываем, чтобы не потерять данные.
            item.status = Equipment.RETIRED
            item.save(update_fields=["status"])
            messages.warning(request, "Оборудование есть в бронях, поэтому оно списано, а не удалено.")
        else:
            item.delete()
            messages.success(request, "Оборудование удалено.")
        return redirect("rental:equipment_list")
    return render(request, "rental/confirm_delete.html", {
        "object_title": str(item), "cancel_url": "rental:equipment_list",
    })


# ---------- бронирования ----------

BOOKING_SORTS = {"start": "start", "price": "total_price", "created": "created_at"}


def filtered_bookings(request):
    """Список броней с поиском/фильтрами. Обычный пользователь видит только свои."""
    qs = Booking.objects.select_related("hall", "user")
    if not permissions.is_admin(request.user):
        qs = qs.filter(user=request.user)

    q = request.GET.get("q", "").strip()
    if q:
        cond = Q(hall__name__icontains=q) | Q(comment__icontains=q)
        if permissions.is_admin(request.user):
            cond |= Q(user__username__icontains=q)
        if q.isdigit():
            cond |= Q(pk=int(q))
        qs = qs.filter(cond)
    status = request.GET.get("status", "")
    if status in dict(Booking.STATUSES):
        qs = qs.filter(status=status)
    hall_id = parse_int(request.GET.get("hall"))
    if hall_id:
        qs = qs.filter(hall_id=hall_id)
    date_from, date_to = parse_date(request.GET.get("date_from")), parse_date(request.GET.get("date_to"))
    if date_from:
        qs = qs.filter(start__gte=services.local_day_bounds(date_from)[0])
    if date_to:
        qs = qs.filter(start__lt=services.local_day_bounds(date_to)[1])

    sort = request.GET.get("sort", "start")
    field = BOOKING_SORTS.get(sort, "start")
    descending = request.GET.get("dir", "desc") != "asc"
    return qs.order_by(f"-{field}" if descending else field, "-pk")


@login_required
def booking_list(request):
    page, query_string = paginate(request, filtered_bookings(request))
    sort = request.GET.get("sort", "start")
    return render(request, "rental/booking_list.html", {
        "page": page, "query_string": query_string, "q": request.GET.get("q", ""),
        "status": request.GET.get("status", ""), "hall_id": parse_int(request.GET.get("hall")),
        "date_from": request.GET.get("date_from", ""), "date_to": request.GET.get("date_to", ""),
        "sort": sort if sort in BOOKING_SORTS else "start", "dir": "asc" if request.GET.get("dir") == "asc" else "desc",
        "statuses": Booking.STATUSES, "halls": Hall.objects.all(),
    })


def _csv_safe(value):
    """Защита от CSV-инъекции: ячейки, начинающиеся с = + - @, экранируются."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@login_required
def booking_export_csv(request):
    qs = filtered_bookings(request).prefetch_related("makeup_seats", "items__equipment")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="bookings_{timezone.localdate():%Y%m%d}.csv"'
    response.write("﻿")  # BOM, чтобы Excel открыл кириллицу
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["№", "Зал", "Арендатор", "Дата", "Начало", "Конец", "Часов", "Гримёрные", "Оборудование",
                     "Аренда зала, ₽", "Скидка, ₽", "Оборудование, ₽", "Гримёрные, ₽", "Итого, ₽", "Статус"])
    for b in qs:
        s, e = timezone.localtime(b.start), timezone.localtime(b.end)
        writer.writerow([
            b.pk, _csv_safe(b.hall), _csv_safe(b.user.username), f"{s:%d.%m.%Y}", f"{s:%H:%M}", f"{e:%H:%M}", b.hours,
            _csv_safe(", ".join(x.name for x in b.makeup_seats.all())),
            _csv_safe(", ".join(i.equipment.name for i in b.items.all())),
            b.hall_cost, b.discount_amount, b.equipment_cost, b.seats_cost, b.total_price, b.get_status_display(),
        ])
    return response


@login_required
def booking_create(request):
    initial = {"people": 1}
    hall = Hall.objects.filter(slug=request.GET.get("hall"), is_active=True).first()
    if hall:
        initial["hall"] = hall.pk
    initial["date"] = parse_date(request.GET.get("date")) or timezone.localdate()
    start_hour = parse_int(request.GET.get("start"))
    if start_hour is not None and settings.STUDIO_OPEN_HOUR <= start_hour < settings.STUDIO_CLOSE_HOUR:
        initial["start_hour"] = start_hour
    form = BookingForm(request.POST or None, request.FILES or None, initial=initial, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            booking = services.save_booking(
                user=request.user, hall=data["hall"], start=form.start, hours=data["hours"], people=data["people"],
                equipment=data["equipment"], seats=data["makeup_seats"], comment=data["comment"],
                reference_file=data.get("reference_file"),
            )
        except services.BookingError as exc:  # гонка: слот заняли между проверкой формы и записью
            for message in exc.messages:
                form.add_error(None, message)
        else:
            emails.send_booking_created(booking)
            messages.success(request, f"Бронь №{booking.pk} оформлена. Итого: {booking.total_price:g} ₽.")
            return redirect(booking)
    return render(request, "rental/booking_form.html", {"form": form, "title": "Новая бронь", "booking": None})


@login_required
def booking_edit(request, pk):
    booking = get_booking_or_403(request, pk, staff_allowed=False)
    if not booking.can_edit:
        messages.warning(request, "Изменять можно только неподтверждённую бронь до её начала.")
        return redirect(booking)
    initial = BookingForm.initial_from_booking(booking)
    form = BookingForm(request.POST or None, request.FILES or None, initial=initial, user=request.user, instance=booking)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.save_booking(
                user=request.user, hall=data["hall"], start=form.start, hours=data["hours"], people=data["people"],
                equipment=data["equipment"], seats=data["makeup_seats"], comment=data["comment"],
                reference_file=data.get("reference_file"), instance=booking,
            )
        except services.BookingError as exc:
            for message in exc.messages:
                form.add_error(None, message)
        else:
            messages.success(request, "Бронь обновлена, стоимость пересчитана.")
            return redirect(booking)
    return render(request, "rental/booking_form.html", {"form": form, "title": f"Изменить бронь №{booking.pk}", "booking": booking})


@login_required
def booking_detail(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("hall", "user"), pk=pk)
    if not can_view_booking(request.user, booking):
        raise PermissionDenied
    return render(request, "rental/booking_detail.html", {
        "booking": booking, "items": booking.items.select_related("equipment"),
        "seats": booking.makeup_seats.all(), "penalties": booking.penalties.select_related("equipment"),
        "is_owner": booking.user_id == request.user.pk,
        "can_penalize": permissions.can_manage_equipment(request.user) and booking.status in (Booking.CONFIRMED, Booking.COMPLETED),
    })


@login_required
def booking_print(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("hall", "user"), pk=pk)
    if not can_view_booking(request.user, booking):
        raise PermissionDenied
    quote = services.make_quote(
        booking.hall, booking.start, booking.hours,
        equipment=[i.equipment for i in booking.items.select_related("equipment")], seats=booking.makeup_seats.all(),
    )
    return render(request, "rental/booking_print.html", {
        "booking": booking, "quote": quote, "items": booking.items.select_related("equipment"),
        "seats": booking.makeup_seats.all(), "penalties": booking.penalties.all(),
    })


@login_required
@require_POST
def booking_cancel(request, pk):
    booking = get_booking_or_403(request, pk)
    if not booking.can_cancel:
        messages.warning(request, "Эту бронь уже нельзя отменить.")
        return redirect(booking)
    booking = services.change_status(booking, Booking.CANCELLED)
    emails.send_status_changed(booking)
    messages.success(request, f"Бронь №{booking.pk} отменена, зал и оборудование освобождены.")
    return redirect(booking)


@permissions.admin_required
@require_POST
def booking_status(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("hall", "user"), pk=pk)
    target = {"confirm": Booking.CONFIRMED, "complete": Booking.COMPLETED}.get(request.POST.get("action"))
    if not target:
        raise Http404
    try:
        booking = services.change_status(booking, target)
    except services.BookingError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        emails.send_status_changed(booking)
        messages.success(request, f"Статус брони №{booking.pk}: {booking.get_status_display()}.")
    return redirect(booking)


@login_required
def booking_delete(request, pk):
    booking = get_booking_or_403(request, pk)
    if not booking.can_delete:
        messages.warning(request, "Удалить можно только неподтверждённую или отменённую бронь.")
        return redirect(booking)
    if request.method == "POST":
        booking.delete()
        messages.success(request, "Бронь удалена.")
        return redirect("rental:booking_list")
    return render(request, "rental/confirm_delete.html", {
        "object_title": f"Бронь №{booking.pk} ({booking.hall})", "cancel_url": booking.get_absolute_url(),
    })


# ---------- штрафы ----------

@permissions.equipment_manager_required
def penalty_create(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("hall", "user"), pk=pk)
    if booking.status not in (Booking.CONFIRMED, Booking.COMPLETED):
        messages.warning(request, "Штраф можно выписать только по подтверждённой или завершённой брони.")
        return redirect(booking)
    form = PenaltyForm(request.POST or None, request.FILES or None, booking=booking)
    if request.method == "POST" and form.is_valid():
        penalty = form.save(commit=False)
        penalty.booking, penalty.created_by = booking, request.user
        penalty.save()
        emails.send_penalty(penalty)
        messages.success(request, "Штраф выписан, арендатору отправлено уведомление.")
        return redirect(booking)
    return render(request, "rental/penalty_form.html", {"form": form, "booking": booking})


@permissions.equipment_manager_required
@require_POST
def penalty_paid(request, pk):
    penalty = get_object_or_404(Penalty, pk=pk)
    penalty.is_paid = True
    penalty.save(update_fields=["is_paid"])
    messages.success(request, "Штраф отмечен как оплаченный.")
    return redirect(penalty.booking)


# ---------- JSON API (запросы fetch) ----------

def _parse_slot(params):
    """Мягкий разбор параметров слота из GET. Возвращает (hall, start, hours, people, error)."""
    hall = Hall.objects.filter(pk=parse_int(params.get("hall"))).first()
    day = parse_date(params.get("date"))
    hour, hours = parse_int(params.get("start")), parse_int(params.get("hours"))
    people = parse_int(params.get("people"), 1)
    if not hall:
        return None, None, None, None, "Выберите зал."
    if not day or hour is None or not hours:
        return hall, None, None, None, "Укажите дату, время начала и длительность."
    if not 0 <= hour <= 23 or hours < 1:
        return hall, None, None, None, "Некорректное время."
    return hall, services.make_start(day, hour), hours, max(people or 1, 1), None


@require_GET
def api_quote(request):
    """Расчёт стоимости и занятости на выбранный слот. Те же функции, что и при сохранении брони."""
    hall, start, hours, people, problem = _parse_slot(request.GET)
    payload = {"ok": False, "errors": [], "quote": None, "busy_equipment": {}, "busy_seats": {}}
    if problem:
        payload["errors"].append(problem)
        return JsonResponse(payload)

    exclude = None
    booking_id = parse_int(request.GET.get("booking"))
    if booking_id and request.user.is_authenticated:
        if Booking.objects.filter(pk=booking_id, user=request.user).exists():
            exclude = booking_id

    end = start + timedelta(hours=hours)
    payload["busy_equipment"] = {
        str(eq_id): f"занято: «{b.hall}», {timezone.localtime(b.start):%H:%M}–{timezone.localtime(b.end):%H:%M}"
        for eq_id, b in services.busy_equipment_map(start, end, exclude).items()
    }
    payload["busy_seats"] = {str(sid): "занято" for sid in services.busy_seats_map(start, end, exclude)}

    equipment = list(Equipment.objects.filter(pk__in=request.GET.getlist("equipment")))
    seats = list(MakeupSeat.objects.filter(pk__in=request.GET.getlist("seats")))
    errors = services.validate_request(
        hall=hall, start=start, hours=hours, people=people, equipment=equipment, seats=seats, exclude_booking_id=exclude,
    )
    payload["errors"] = errors
    try:
        payload["quote"] = services.make_quote(hall, start, hours, equipment, seats).as_dict()
    except services.BookingError as exc:
        payload["errors"] += exc.messages
    payload["ok"] = not payload["errors"]
    return JsonResponse(payload)


@require_GET
def api_schedule(request):
    """Почасовая сетка зала на дату: свободно/занято и цена часа."""
    hall = Hall.objects.filter(pk=parse_int(request.GET.get("hall"))).first()
    day = parse_date(request.GET.get("date"))
    if not hall or not day:
        return JsonResponse({"error": "Нужны параметры hall и date."}, status=400)
    day_start, day_end = services.local_day_bounds(day)
    bookings = list(services.hall_conflicts(hall, day_start, day_end))
    prices = services.tariff_prices(hall)
    now = timezone.now()
    slots = []
    for hour in range(settings.STUDIO_OPEN_HOUR, settings.STUDIO_CLOSE_HOUR):
        slot_start = services.make_start(day, hour)
        slot_end = slot_start + timedelta(hours=1)
        state = "free"
        if slot_start <= now:
            state = "past"
        elif any(b.start < slot_end and b.end > slot_start for b in bookings):
            state = "busy"
        price = prices.get((services.day_type_for(slot_start), Tariff.period_for_hour(hour)))
        slots.append({"hour": hour, "label": f"{hour:02d}:00", "state": state, "price": str(price) if price is not None else None})
    day_label = dict(Tariff.DAY_TYPES)[services.day_type_for(day_start)]
    return JsonResponse({"hall": hall.name, "date": day.isoformat(), "day_type": day_label, "slots": slots})


# ---------- сводные показатели ----------

def collect_stats():
    """Все показатели считаются агрегатными запросами к БД."""
    active = Booking.objects.exclude(status=Booking.CANCELLED)
    total = Booking.objects.count()
    cancelled = Booking.objects.filter(status=Booking.CANCELLED).count()
    totals = active.aggregate(revenue=Sum("total_price"), average=Avg("total_price"), hours=Sum("hours"))
    penalties = Penalty.objects.aggregate(total=Sum("amount"), count=Count("id"))
    equipment_total = Equipment.objects.exclude(status=Equipment.RETIRED).count()
    equipment_repair = Equipment.objects.filter(status=Equipment.REPAIR).count()

    by_hall = list(
        active.values("hall__name").annotate(count=Count("id"), revenue=Sum("total_price")).order_by("-revenue")
    )
    by_month = list(
        active.annotate(month=TruncMonth("start")).values("month").annotate(revenue=Sum("total_price"), count=Count("id")).order_by("month")
    )
    top_equipment = list(
        BookingEquipment.objects.exclude(booking__status=Booking.CANCELLED)
        .values("equipment__name").annotate(count=Count("id")).order_by("-count", "equipment__name")[:5]
    )
    return {
        "bookings_total": total,
        "revenue": totals["revenue"] or Decimal("0"),
        "average_price": totals["average"] or Decimal("0"),
        "hours_total": totals["hours"] or 0,
        "cancelled_share": round(cancelled * 100 / total, 1) if total else 0,
        "penalties_total": penalties["total"] or Decimal("0"),
        "penalties_count": penalties["count"],
        "repair_share": round(equipment_repair * 100 / equipment_total, 1) if equipment_total else 0,
        "by_hall": by_hall, "by_month": by_month, "top_equipment": top_equipment,
    }


@permissions.equipment_manager_required
def stats(request):
    return render(request, "rental/stats.html", {"s": collect_stats()})


@permissions.equipment_manager_required
def api_stats(request):
    s = collect_stats()
    return JsonResponse({
        "by_hall": [{"label": r["hall__name"], "value": float(r["revenue"]), "count": r["count"]} for r in s["by_hall"]],
        "by_month": [{"label": f"{r['month']:%m.%Y}", "value": float(r["revenue"]), "count": r["count"]} for r in s["by_month"]],
    })
