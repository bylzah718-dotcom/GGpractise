"""Загрузка демонстрационных данных: python manage.py seed_demo [--reset]

Создаёт залы, тарифы, оборудование (36 единиц), 36 броней и связанные записи.
Брони создаются теми же сервисами, что и на сайте, поэтому конфликты исключены.
"""
import io
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from rental import demo_images

from rental import services
from rental.models import (Booking, Equipment, Hall, InteriorZone, MakeupSeat, Penalty, Review, Tariff)
from rental.permissions import TECH_GROUP

User = get_user_model()

HALLS = [
    ("Белый куб", "white-cube", 60, 12, "Светлый зал с белыми стенами и большими окнами — для портретов и предметной съёмки.", (240, 240, 235), 600),
    ("Лофт", "loft", 85, 15, "Кирпичные стены, металлические фермы и винтажная мебель.", (150, 90, 70), 700),
    ("Циклорама", "cyclorama", 110, 20, "Бесшовная белая циклорама для fashion-съёмок и видео.", (200, 205, 215), 900),
    ("Винтаж", "vintage", 50, 8, "Интерьер в стиле 70-х: обои, ковры, торшеры.", (170, 120, 80), 550),
    ("Неон", "neon", 70, 12, "Тёмный зал с неоновыми трубками и зеркальными панелями.", (60, 40, 110), 800),
    ("Зелёный сад", "green-garden", 95, 18, "Зимний сад с живыми растениями и естественным светом.", (70, 120, 85), 750),
]
ZONES = [("Окно в пол", "Естественный свет с севера"), ("Кирпичная стена", "Фон для портретов"), ("Диванная зона", "Мягкая мебель и пледы"),
         ("Белая стена", "Нейтральный фон"), ("Зеркальная стена", "Для интерьерной съёмки")]
# (название, категория, цена часа, количество единиц)
EQUIPMENT = [
    ("Постоянный свет Godox SL-60", "light", 250, 4), ("LED-панель Aputure 300d", "light", 450, 3),
    ("Вспышка Profoto D2 500", "flash", 700, 3), ("Вспышка Godox AD600", "flash", 500, 4),
    ("Октобокс 120 см", "modifier", 150, 4), ("Софтбокс-стрипбокс 30×120", "modifier", 120, 4),
    ("Рефлектор-тарелка 55 см", "modifier", 100, 2), ("Фон бумажный белый 2.7 м", "background", 200, 3),
    ("Фон бумажный серый 2.7 м", "background", 200, 2), ("Тканевый фон «Мрамор»", "background", 250, 2),
    ("Набор реквизита «Винтаж»", "prop", 300, 2), ("Реквизит: зеркало в раме", "prop", 150, 3),
]
FIRST_NAMES = ["anna", "ivan", "olga", "max", "sveta"]
REVIEW_TEXTS = [
    "Отличный зал, света хватило на всё. Администратор помог с настройкой.",
    "Хорошая студия, всё чисто и аккуратно. Приду ещё.",
    "Оборудование исправное, быстро выдали. Единственный минус — мало парковки.",
    "Снимали портреты, результат превзошёл ожидания.",
    "Уютно, но хотелось бы больше розеток в зоне гримёрной.",
    "Лучший зал для видео, циклорама огромная и чистая.",
]


class Command(BaseCommand):
    help = "Загружает демонстрационные данные для студии"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="удалить существующие данные студии перед загрузкой")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            for model in (Review, Penalty, Booking, Equipment, MakeupSeat, Tariff, InteriorZone, Hall):
                model.objects.all().delete()
            User.objects.filter(username__in=["admin", "tech", *FIRST_NAMES]).delete()
        elif Hall.objects.exists():
            self.stdout.write(self.style.WARNING("Данные уже есть. Для перезаписи используйте --reset."))
            return

        rng = random.Random(2026)
        users = self.make_users()
        halls = self.make_halls()
        equipment = self.make_equipment()
        self.make_bookings(rng, users, halls, equipment)
        self.make_penalties_and_reviews(rng)
        self.stdout.write(self.style.SUCCESS(
            f"Готово: залов {Hall.objects.count()}, оборудования {Equipment.objects.count()}, "
            f"броней {Booking.objects.count()}, штрафов {Penalty.objects.count()}, отзывов {Review.objects.count()}."
        ))
        self.stdout.write("Демо-аккаунты (смените пароли!): admin / Admin-demo-2026, tech / Tech-demo-2026, "
                          "anna, ivan, olga, max, sveta / Renter-demo-2026")

    # ---- пользователи ----
    def make_users(self):
        admin = User.objects.create_superuser("admin", "admin@kadr-studio.local", "Admin-demo-2026")
        tech = User.objects.create_user("tech", "tech@kadr-studio.local", "Tech-demo-2026")
        tech.groups.add(Group.objects.get_or_create(name=TECH_GROUP)[0])
        renters = [User.objects.create_user(n, f"{n}@example.com", "Renter-demo-2026") for n in FIRST_NAMES]
        return renters

    # ---- залы ----
    def make_halls(self):
        halls = []
        for idx, (name, slug, area, cap, desc, color, base) in enumerate(HALLS):
            hall = Hall.objects.create(name=name, slug=slug, area=area, capacity=cap, description=desc)
            hall.image.save(f"{slug}.jpg", demo_images.to_content(demo_images.hall_scene(slug)), save=True)
            for zone_name, zone_desc in (ZONES[idx % 5], ZONES[(idx + 2) % 5]):
                InteriorZone.objects.create(hall=hall, name=zone_name, description=zone_desc)
            # Тарифы: утро дешевле, вечер дороже, выходные дороже будней
            for day_type, day_k in ((Tariff.WEEKDAY, 1.0), (Tariff.WEEKEND, 1.25)):
                for period, period_k in ((Tariff.MORNING, 0.8), (Tariff.DAY, 1.0), (Tariff.EVENING, 1.2)):
                    price = Decimal(round(base * day_k * period_k / 50) * 50)
                    Tariff.objects.create(hall=hall, day_type=day_type, period=period, price_per_hour=price)
            for n in (1, 2):
                MakeupSeat.objects.create(hall=hall, name=f"Гримёрное место {n}", price_per_hour=Decimal("150"))
            halls.append(hall)
        return halls

    # ---- оборудование ----
    def make_equipment(self):
        items = []
        counter = 1
        for name, category, price, qty in EQUIPMENT:
            for _ in range(qty):
                unit = Equipment.objects.create(
                    name=name, category=category, price_per_hour=Decimal(price),
                    inventory_number=f"ФС-{counter:04d}", description=f"{name}. Проверено техником, комплект кабелей в наборе.",
                )
                unit.image.save(f"eq-{counter:04d}.jpg", demo_images.to_content(demo_images.equipment_image(category, name), 80), save=True)
                items.append(unit)
                counter += 1
        for item in (items[2], items[17]):  # две единицы в ремонте — для демонстрации статуса
            item.status = Equipment.REPAIR
            item.save(update_fields=["status"])
        return items

    # ---- брони ----
    def make_bookings(self, rng, users, halls, equipment):
        usable = [e for e in equipment if e.status == Equipment.AVAILABLE]
        now = timezone.localtime()
        created = attempts = 0
        target_past, target_future = 24, 12
        while created < target_past + target_future and attempts < 2000:
            attempts += 1
            past = created < target_past
            day_offset = -rng.randint(1, 60) if past else rng.randint(1, 30)
            day = (now + timedelta(days=day_offset)).date()
            hall = rng.choice(halls)
            hours = rng.choice([1, 2, 2, 3, 3, 4, 5, 6])
            hour = rng.randint(settings.STUDIO_OPEN_HOUR, settings.STUDIO_CLOSE_HOUR - hours)
            start = services.make_start(day, hour)
            seats = list(hall.makeup_seats.all()[:rng.randint(0, 2)])
            eq = rng.sample(usable, rng.randint(0, 3))
            try:
                booking = services.save_booking(
                    user=rng.choice(users), hall=hall, start=start, hours=hours, people=rng.randint(1, min(8, hall.capacity)),
                    equipment=eq, seats=seats, comment=rng.choice(["", "Съёмка lookbook", "Семейная фотосессия", "Видеоролик"]),
                    allow_past=past,
                )
            except services.BookingError:
                continue
            if past:
                booking.status = Booking.CANCELLED if rng.random() < 0.15 else Booking.COMPLETED
            else:
                booking.status = Booking.CONFIRMED if rng.random() < 0.6 else Booking.PENDING
            booking.save(update_fields=["status"])
            created += 1

    def make_penalties_and_reviews(self, rng):
        tech = User.objects.get(username="tech")
        completed = list(Booking.objects.filter(status=Booking.COMPLETED).prefetch_related("items"))
        rng.shuffle(completed)
        made = 0
        for booking in completed:
            items = list(booking.items.all())
            if items and made < 6:
                Penalty.objects.create(
                    booking=booking, equipment=items[0].equipment, amount=Decimal(rng.choice([500, 1000, 2500, 4000])),
                    reason=rng.choice(["Разбит рассеиватель", "Погнут штатив", "Загрязнён фон — требуется замена"]),
                    created_by=tech, is_paid=rng.random() < 0.5,
                )
                made += 1
        seen = set()
        for booking in completed:
            key = (booking.user_id, booking.hall_id)
            if key in seen or len(seen) >= 12:
                continue
            seen.add(key)
            Review.objects.create(author=booking.user, hall=booking.hall, rating=rng.choice([4, 5, 5, 3, 4]), text=rng.choice(REVIEW_TEXTS))
