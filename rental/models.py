"""Модели предметной области: аренда залов фотостудии и оборудования."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .validators import validate_image, validate_reference_file


class Hall(models.Model):
    """Зал фотостудии."""

    name = models.CharField("Название", max_length=100, unique=True)
    slug = models.SlugField("Адрес страницы", unique=True)
    description = models.TextField("Описание", blank=True)
    area = models.PositiveSmallIntegerField("Площадь, м²", validators=[MinValueValidator(5)])
    capacity = models.PositiveSmallIntegerField("Вместимость, чел.", validators=[MinValueValidator(1)])
    image = models.ImageField("Фото", upload_to="halls/", blank=True, validators=[validate_image])
    is_active = models.BooleanField("Принимает брони", default=True)

    class Meta:
        verbose_name = "зал"
        verbose_name_plural = "залы"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("rental:hall_detail", args=[self.slug])


class InteriorZone(models.Model):
    """Интерьерная зона внутри зала (кирпичная стена, окно, циклорама...)."""

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="zones", verbose_name="Зал")
    name = models.CharField("Название", max_length=100)
    description = models.CharField("Описание", max_length=255, blank=True)

    class Meta:
        verbose_name = "интерьерная зона"
        verbose_name_plural = "интерьерные зоны"
        ordering = ["hall", "name"]

    def __str__(self):
        return f"{self.hall}: {self.name}"


class Tariff(models.Model):
    """Цена часа аренды зала: зависит от типа дня и времени суток."""

    WEEKDAY, WEEKEND = "weekday", "weekend"
    DAY_TYPES = [(WEEKDAY, "Будни (пн–пт)"), (WEEKEND, "Выходные (сб–вс)")]

    MORNING, DAY, EVENING = "morning", "day", "evening"
    PERIODS = [(MORNING, "Утренний"), (DAY, "Дневной"), (EVENING, "Вечерний")]
    # границы периодов: [начало, конец) в часах
    PERIOD_HOURS = {MORNING: (8, 12), DAY: (12, 18), EVENING: (18, 23)}

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="tariffs", verbose_name="Зал")
    day_type = models.CharField("Тип дня", max_length=10, choices=DAY_TYPES)
    period = models.CharField("Время суток", max_length=10, choices=PERIODS)
    price_per_hour = models.DecimalField("Цена часа, ₽", max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "тариф"
        verbose_name_plural = "тарифы по времени суток"
        constraints = [models.UniqueConstraint(fields=["hall", "day_type", "period"], name="uniq_tariff_hall_day_period")]
        ordering = ["hall", "day_type", "period"]

    def __str__(self):
        return f"{self.hall}: {self.get_day_type_display()}, {self.get_period_display().lower()} — {self.price_per_hour} ₽/ч"

    @classmethod
    def period_for_hour(cls, hour: int) -> str:
        for period, (start, end) in cls.PERIOD_HOURS.items():
            if start <= hour < end:
                return period
        raise ValueError(f"Час {hour} вне рабочего времени студии")


class MakeupSeat(models.Model):
    """Гримёрное место при зале."""

    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="makeup_seats", verbose_name="Зал")
    name = models.CharField("Название", max_length=60)
    price_per_hour = models.DecimalField("Цена часа, ₽", max_digits=7, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    is_active = models.BooleanField("Доступно", default=True)

    class Meta:
        verbose_name = "гримёрное место"
        verbose_name_plural = "гримёрные места"
        ordering = ["hall", "name"]

    def __str__(self):
        return f"{self.name} ({self.hall})"


class Equipment(models.Model):
    """Единица дополнительного светового оборудования или реквизита."""

    LIGHT, FLASH, MODIFIER, BACKGROUND, PROP = "light", "flash", "modifier", "background", "prop"
    CATEGORIES = [
        (LIGHT, "Постоянный свет"),
        (FLASH, "Импульсный свет"),
        (MODIFIER, "Модификаторы света"),
        (BACKGROUND, "Фоны"),
        (PROP, "Реквизит"),
    ]
    AVAILABLE, REPAIR, RETIRED = "available", "repair", "retired"
    STATUSES = [(AVAILABLE, "Исправно"), (REPAIR, "В ремонте"), (RETIRED, "Списано")]

    name = models.CharField("Название", max_length=120)
    category = models.CharField("Категория", max_length=12, choices=CATEGORIES)
    inventory_number = models.CharField("Инвентарный номер", max_length=30, unique=True)
    description = models.TextField("Описание", blank=True)
    price_per_hour = models.DecimalField("Цена часа, ₽", max_digits=7, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField("Состояние", max_length=10, choices=STATUSES, default=AVAILABLE)
    image = models.ImageField("Фото", upload_to="equipment/", blank=True, validators=[validate_image])
    created_at = models.DateTimeField("Добавлено", auto_now_add=True)

    class Meta:
        verbose_name = "оборудование"
        verbose_name_plural = "оборудование и реквизит"
        ordering = ["name", "inventory_number"]

    def __str__(self):
        return f"{self.name} [{self.inventory_number}]"

    @property
    def is_available(self) -> bool:
        return self.status == self.AVAILABLE


class Booking(models.Model):
    """Бронирование зала на интервал времени."""

    PENDING, CONFIRMED, COMPLETED, CANCELLED = "pending", "confirmed", "completed", "cancelled"
    STATUSES = [
        (PENDING, "Ожидает подтверждения"),
        (CONFIRMED, "Подтверждена"),
        (COMPLETED, "Завершена"),
        (CANCELLED, "Отменена"),
    ]
    ACTIVE_STATUSES = (PENDING, CONFIRMED)  # занимают зал, оборудование и гримёрки

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings", verbose_name="Арендатор")
    hall = models.ForeignKey(Hall, on_delete=models.PROTECT, related_name="bookings", verbose_name="Зал")
    start = models.DateTimeField("Начало")
    end = models.DateTimeField("Окончание")
    hours = models.PositiveSmallIntegerField("Часов", validators=[MinValueValidator(1)])
    people = models.PositiveSmallIntegerField("Человек на съёмке", default=1, validators=[MinValueValidator(1)])
    makeup_seats = models.ManyToManyField(MakeupSeat, blank=True, related_name="bookings", verbose_name="Гримёрные места")
    equipment = models.ManyToManyField(Equipment, through="BookingEquipment", blank=True, related_name="bookings", verbose_name="Оборудование")

    hall_cost = models.DecimalField("Аренда зала, ₽", max_digits=10, decimal_places=2, default=0)
    discount_percent = models.PositiveSmallIntegerField("Скидка, %", default=0, validators=[MaxValueValidator(100)])
    discount_amount = models.DecimalField("Сумма скидки, ₽", max_digits=10, decimal_places=2, default=0)
    equipment_cost = models.DecimalField("Оборудование, ₽", max_digits=10, decimal_places=2, default=0)
    seats_cost = models.DecimalField("Гримёрные, ₽", max_digits=10, decimal_places=2, default=0)
    total_price = models.DecimalField("Итого, ₽", max_digits=10, decimal_places=2, default=0)

    status = models.CharField("Статус", max_length=10, choices=STATUSES, default=PENDING)
    reference_file = models.FileField("Референс / мудборд", upload_to="references/", blank=True, validators=[validate_reference_file])
    comment = models.CharField("Комментарий", max_length=500, blank=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Изменена", auto_now=True)

    class Meta:
        verbose_name = "бронирование"
        verbose_name_plural = "бронирования"
        ordering = ["-start"]
        indexes = [models.Index(fields=["hall", "start", "end"])]

    def __str__(self):
        return f"Бронь №{self.pk}: {self.hall}, {timezone.localtime(self.start):%d.%m.%Y %H:%M}"

    def get_absolute_url(self):
        return reverse("rental:booking_detail", args=[self.pk])

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_future(self) -> bool:
        return self.start > timezone.now()

    @property
    def is_finished(self) -> bool:
        return self.status == self.COMPLETED or (self.status == self.CONFIRMED and self.end <= timezone.now())

    @property
    def can_edit(self) -> bool:
        return self.status == self.PENDING and self.is_future

    @property
    def can_cancel(self) -> bool:
        return self.status in self.ACTIVE_STATUSES and self.is_future

    @property
    def can_delete(self) -> bool:
        return self.status in (self.PENDING, self.CANCELLED)


class BookingEquipment(models.Model):
    """Выбранная в брони единица оборудования (цена фиксируется на момент брони)."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="items", verbose_name="Бронь")
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="booking_items", verbose_name="Оборудование")
    price_per_hour = models.DecimalField("Цена часа, ₽", max_digits=7, decimal_places=2)
    cost = models.DecimalField("Стоимость, ₽", max_digits=9, decimal_places=2)

    class Meta:
        verbose_name = "оборудование в брони"
        verbose_name_plural = "оборудование в бронях"
        constraints = [models.UniqueConstraint(fields=["booking", "equipment"], name="uniq_equipment_in_booking")]

    def __str__(self):
        return f"{self.equipment} в брони №{self.booking_id}"


class Penalty(models.Model):
    """Штраф за порчу оборудования или имущества студии."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="penalties", verbose_name="Бронь")
    equipment = models.ForeignKey(Equipment, on_delete=models.SET_NULL, null=True, blank=True, related_name="penalties", verbose_name="Оборудование")
    amount = models.DecimalField("Сумма, ₽", max_digits=9, decimal_places=2, validators=[MinValueValidator(1)])
    reason = models.TextField("Причина", max_length=1000)
    photo = models.ImageField("Фото повреждения", upload_to="penalties/", blank=True, validators=[validate_image])
    is_paid = models.BooleanField("Оплачен", default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="issued_penalties", verbose_name="Выписал")
    created_at = models.DateTimeField("Дата", auto_now_add=True)

    class Meta:
        verbose_name = "штраф за порчу"
        verbose_name_plural = "штрафы за порчу"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Штраф {self.amount} ₽ по брони №{self.booking_id}"


class Review(models.Model):
    """Отзыв арендатора о зале (только после состоявшейся брони)."""

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews", verbose_name="Автор")
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="reviews", verbose_name="Зал")
    rating = models.PositiveSmallIntegerField("Оценка", validators=[MinValueValidator(1), MaxValueValidator(5)])
    text = models.TextField("Текст отзыва", max_length=2000)
    created_at = models.DateTimeField("Дата", auto_now_add=True)

    class Meta:
        verbose_name = "отзыв"
        verbose_name_plural = "отзывы"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["author", "hall"], name="uniq_review_author_hall")]

    def __str__(self):
        return f"{self.author} → {self.hall}: {self.rating}/5"
