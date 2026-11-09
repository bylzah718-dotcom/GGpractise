import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import services
from .models import Booking, BookingEquipment, Equipment, Hall, MakeupSeat, Tariff
from .permissions import TECH_GROUP

User = get_user_model()

TEST_MEDIA = tempfile.mkdtemp(prefix="photostudio-test-media-")


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class MediaTestCase(TestCase):
    """Загрузки в тестах уходят во временную папку, а не в media/ проекта."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)


def next_weekday(weekday: int, weeks_ahead: int = 1) -> date:
    """Ближайшая будущая дата с нужным днём недели (0 = понедельник)."""
    today = timezone.localdate()
    days = (weekday - today.weekday()) % 7 + 7 * weeks_ahead
    return today + timedelta(days=days)


def make_hall(name="Зал", slug="hall", capacity=10):
    hall = Hall.objects.create(name=name, slug=slug, area=40, capacity=capacity)
    prices = {
        (Tariff.WEEKDAY, Tariff.MORNING): 400, (Tariff.WEEKDAY, Tariff.DAY): 500, (Tariff.WEEKDAY, Tariff.EVENING): 600,
        (Tariff.WEEKEND, Tariff.MORNING): 500, (Tariff.WEEKEND, Tariff.DAY): 625, (Tariff.WEEKEND, Tariff.EVENING): 750,
    }
    for (day_type, period), price in prices.items():
        Tariff.objects.create(hall=hall, day_type=day_type, period=period, price_per_hour=price)
    return hall


def png_bytes(size=(10, 10)):
    buf = BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return buf.getvalue()


class PricingTests(MediaTestCase):
    def setUp(self):
        self.hall = make_hall()

    def quote(self, day, hour, hours, **kw):
        return services.make_quote(self.hall, services.make_start(day, hour), hours, **kw)

    def test_weekday_tariffs_by_time_of_day(self):
        monday = next_weekday(0)
        self.assertEqual(self.quote(monday, 9, 1).hall_cost, Decimal("400"))
        self.assertEqual(self.quote(monday, 13, 1).hall_cost, Decimal("500"))
        self.assertEqual(self.quote(monday, 19, 1).hall_cost, Decimal("600"))

    def test_weekend_costs_more_than_weekday(self):
        self.assertEqual(self.quote(next_weekday(5), 13, 1).hall_cost, Decimal("625"))
        self.assertEqual(self.quote(next_weekday(6), 19, 1).hall_cost, Decimal("750"))

    def test_booking_crossing_period_boundary_is_split(self):
        q = self.quote(next_weekday(1), 11, 2)  # 11–12 утро, 12–13 день
        self.assertEqual([s["period"] for s in q.segments], ["morning", "day"])
        self.assertEqual(q.hall_cost, Decimal("900"))

    def test_no_discount_under_three_hours(self):
        q = self.quote(next_weekday(0), 12, 2)
        self.assertEqual(q.discount_amount, Decimal("0"))
        self.assertEqual(q.total, Decimal("1000"))

    def test_discount_from_three_hours(self):
        q = self.quote(next_weekday(0), 12, 3)  # 3 × 500 = 1500, скидка 10%
        self.assertEqual(q.hall_cost, Decimal("1500"))
        self.assertEqual(q.discount_percent, 10)
        self.assertEqual(q.discount_amount, Decimal("150.00"))
        self.assertEqual(q.total, Decimal("1350.00"))

    def test_equipment_and_seats_are_not_discounted(self):
        eq = Equipment.objects.create(name="Свет", category="light", inventory_number="E1", price_per_hour=100)
        seat = MakeupSeat.objects.create(hall=self.hall, name="М1", price_per_hour=50)
        q = self.quote(next_weekday(0), 12, 3, equipment=[eq], seats=[seat])
        self.assertEqual(q.equipment_cost, Decimal("300.00"))
        self.assertEqual(q.seats_cost, Decimal("150.00"))
        self.assertEqual(q.total, Decimal("1350.00") + 300 + 150)

    def test_missing_tariff_raises(self):
        Tariff.objects.filter(hall=self.hall, day_type=Tariff.WEEKDAY, period=Tariff.EVENING).delete()
        with self.assertRaises(services.BookingError):
            self.quote(next_weekday(0), 19, 1)


class BookingRulesTests(MediaTestCase):
    def setUp(self):
        self.hall_a = make_hall("A", "a")
        self.hall_b = make_hall("B", "b")
        self.user = User.objects.create_user("u1", "u1@example.com", "pass-12345")
        self.other = User.objects.create_user("u2", "u2@example.com", "pass-12345")
        self.eq = Equipment.objects.create(name="Вспышка", category="flash", inventory_number="F1", price_per_hour=300)
        self.day = next_weekday(2)

    def book(self, hall, hour, hours, user=None, **kw):
        return services.save_booking(
            user=user or self.user, hall=hall, start=services.make_start(self.day, hour), hours=hours, **kw)

    def test_save_creates_snapshot_and_items(self):
        b = self.book(self.hall_a, 12, 3, equipment=[self.eq])
        self.assertEqual(b.total_price, Decimal("1350.00") + Decimal("900.00"))
        self.assertEqual(BookingEquipment.objects.filter(booking=b).count(), 1)

    def test_same_equipment_cannot_be_in_two_halls_at_overlapping_time(self):
        self.book(self.hall_a, 12, 3, equipment=[self.eq])
        with self.assertRaises(services.BookingError) as ctx:
            self.book(self.hall_b, 14, 2, user=self.other, equipment=[self.eq])  # 14–16 пересекается с 12–15
        self.assertIn("уже закреплено за залом «A»", ctx.exception.messages[0])

    def test_failed_booking_leaves_no_partial_data(self):
        self.book(self.hall_a, 12, 3, equipment=[self.eq])
        before = Booking.objects.count()
        with self.assertRaises(services.BookingError):
            self.book(self.hall_b, 13, 2, user=self.other, equipment=[self.eq])
        self.assertEqual(Booking.objects.count(), before)
        self.assertEqual(BookingEquipment.objects.count(), 1)

    def test_same_equipment_allowed_when_times_do_not_overlap(self):
        self.book(self.hall_a, 10, 2, equipment=[self.eq])           # 10–12
        self.book(self.hall_b, 12, 2, user=self.other, equipment=[self.eq])  # 12–14 вплотную

    def test_cancelled_booking_frees_equipment(self):
        b = self.book(self.hall_a, 12, 3, equipment=[self.eq])
        services.change_status(b, Booking.CANCELLED)
        self.book(self.hall_b, 12, 3, user=self.other, equipment=[self.eq])

    def test_equipment_in_repair_rejected(self):
        self.eq.status = Equipment.REPAIR
        self.eq.save()
        with self.assertRaises(services.BookingError):
            self.book(self.hall_a, 12, 1, equipment=[self.eq])

    def test_hall_cannot_be_double_booked(self):
        self.book(self.hall_a, 12, 3)
        with self.assertRaises(services.BookingError):
            self.book(self.hall_a, 13, 1, user=self.other)

    def test_past_and_after_closing_rejected(self):
        with self.assertRaises(services.BookingError):
            services.save_booking(user=self.user, hall=self.hall_a, hours=1,
                                  start=services.make_start(timezone.localdate() - timedelta(days=1), 12))
        with self.assertRaises(services.BookingError):
            self.book(self.hall_a, 21, 4)  # закончится после 23:00

    def test_capacity_limit(self):
        with self.assertRaises(services.BookingError):
            self.book(self.hall_a, 12, 1, people=11)

    def test_edit_excludes_own_booking_from_conflicts(self):
        b = self.book(self.hall_a, 12, 2, equipment=[self.eq])
        services.save_booking(user=self.user, hall=self.hall_a, start=b.start, hours=3, equipment=[self.eq], instance=b)
        b.refresh_from_db()
        self.assertEqual(b.hours, 3)
        self.assertEqual(BookingEquipment.objects.filter(booking=b).count(), 1)


class ViewAccessTests(MediaTestCase):
    def setUp(self):
        self.hall = make_hall()
        self.owner = User.objects.create_user("owner", "owner@example.com", "pass-12345")
        self.stranger = User.objects.create_user("stranger", "s@example.com", "pass-12345")
        self.admin = User.objects.create_superuser("boss", "boss@example.com", "pass-12345")
        self.tech = User.objects.create_user("tech", "t@example.com", "pass-12345")
        self.tech.groups.add(Group.objects.create(name=TECH_GROUP))
        self.booking = services.save_booking(
            user=self.owner, hall=self.hall, start=services.make_start(next_weekday(3), 12), hours=2)

    def test_guest_redirected_to_login(self):
        url = reverse("rental:booking_detail", args=[self.booking.pk])
        self.assertRedirects(self.client.get(url), f"{reverse('rental:login')}?next={url}")

    def test_foreign_booking_returns_403(self):
        self.client.force_login(self.stranger)
        for name in ("booking_detail", "booking_edit", "booking_print", "booking_delete"):
            r = self.client.get(reverse(f"rental:{name}", args=[self.booking.pk]))
            self.assertEqual(r.status_code, 403, name)
        r = self.client.post(reverse("rental:booking_cancel", args=[self.booking.pk]))
        self.assertEqual(r.status_code, 403)

    def test_owner_and_admin_can_open(self):
        for user in (self.owner, self.admin, self.tech):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.booking.get_absolute_url()).status_code, 200, user)

    def test_list_shows_only_own_for_regular_user(self):
        self.client.force_login(self.stranger)
        self.assertNotContains(self.client.get(reverse("rental:booking_list")), f"/bookings/{self.booking.pk}/")

    def test_only_admin_confirms(self):
        url = reverse("rental:booking_status", args=[self.booking.pk])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url, {"action": "confirm"}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(url, {"action": "confirm"})
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.CONFIRMED)

    def test_equipment_management_roles(self):
        url = reverse("rental:equipment_create")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_stats_and_api_stats_restricted(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("rental:stats")).status_code, 403)
        self.assertEqual(self.client.get(reverse("rental:api_stats")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("rental:stats")).status_code, 200)


class FlowTests(MediaTestCase):
    def setUp(self):
        self.hall = make_hall()
        self.user = User.objects.create_user("renter", "renter@example.com", "pass-12345")
        self.eq = Equipment.objects.create(name="Фон", category="background", inventory_number="B1", price_per_hour=100)
        self.day = next_weekday(1)

    def payload(self, **over):
        data = {"hall": self.hall.pk, "date": self.day.isoformat(), "start_hour": 12, "hours": 3,
                "people": 2, "equipment": [self.eq.pk], "comment": "тест"}
        data.update(over)
        return data

    def test_register_sends_welcome_and_logs_in(self):
        r = self.client.post(reverse("rental:register"), {
            "username": "newbie", "email": "new@example.com", "password1": "Str0ng-pass-77", "password2": "Str0ng-pass-77"})
        self.assertRedirects(r, reverse("rental:home"))
        user = User.objects.get(username="newbie")
        self.assertNotEqual(user.password, "Str0ng-pass-77")
        self.assertTrue(user.password.startswith(("pbkdf2_", "argon2", "scrypt")))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new@example.com"])

    def test_create_booking_via_form_sends_email(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("rental:booking_create"), self.payload())
        booking = Booking.objects.get()
        self.assertRedirects(r, booking.get_absolute_url())
        self.assertEqual(booking.total_price, Decimal("1350.00") + Decimal("300.00"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Бронь", mail.outbox[0].subject)

    def test_form_shows_conflict_error(self):
        other = User.objects.create_user("other", "o@example.com", "pass-12345")
        services.save_booking(user=other, hall=self.hall, start=services.make_start(self.day, 12), hours=3)
        self.client.force_login(self.user)
        r = self.client.post(reverse("rental:booking_create"), self.payload())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "уже занят")
        self.assertEqual(Booking.objects.count(), 1)

    def test_cancel_and_status_emails(self):
        self.client.force_login(self.user)
        self.client.post(reverse("rental:booking_create"), self.payload())
        booking = Booking.objects.get()
        mail.outbox.clear()
        self.client.post(reverse("rental:booking_cancel", args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CANCELLED)
        self.assertEqual(len(mail.outbox), 1)

    def test_delete_booking(self):
        self.client.force_login(self.user)
        self.client.post(reverse("rental:booking_create"), self.payload())
        booking = Booking.objects.get()
        self.client.post(reverse("rental:booking_delete", args=[booking.pk]))
        self.assertFalse(Booking.objects.exists())

    def test_reference_file_validation(self):
        self.client.force_login(self.user)
        bad = SimpleUploadedFile("virus.exe", b"MZ....", content_type="application/octet-stream")
        r = self.client.post(reverse("rental:booking_create"), {**self.payload(), "reference_file": bad})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Booking.objects.exists())
        fake = SimpleUploadedFile("a.png", b"not really png", content_type="image/png")
        r = self.client.post(reverse("rental:booking_create"), {**self.payload(), "reference_file": fake})
        self.assertFalse(Booking.objects.exists())
        good = SimpleUploadedFile("ref.png", png_bytes(), content_type="image/png")
        self.client.post(reverse("rental:booking_create"), {**self.payload(), "reference_file": good})
        self.assertTrue(Booking.objects.get().reference_file.name.startswith("references/"))
        Booking.objects.get().reference_file.delete()

    def test_oversized_image_rejected(self):
        tech = User.objects.create_user("t2", "t2@example.com", "pass-12345")
        tech.groups.add(Group.objects.get_or_create(name=TECH_GROUP)[0])
        self.client.force_login(tech)
        big = SimpleUploadedFile("big.png", png_bytes() + b"0" * (2 * 1024 * 1024 + 1), content_type="image/png")
        r = self.client.post(reverse("rental:equipment_create"), {
            "name": "X", "category": "light", "inventory_number": "BIG1", "price_per_hour": 10, "status": "available", "image": big})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Equipment.objects.filter(inventory_number="BIG1").exists())

    def test_review_only_after_finished_booking(self):
        self.client.force_login(self.user)
        url = reverse("rental:review_create", args=[self.hall.slug])
        self.assertEqual(self.client.get(url).status_code, 403)
        b = services.save_booking(user=self.user, hall=self.hall, start=services.make_start(self.day, 10), hours=1)
        b.status = Booking.COMPLETED
        b.save()
        self.assertEqual(self.client.post(url, {"rating": 5, "text": "Отлично"}).status_code, 302)
        self.assertEqual(self.hall.reviews.count(), 1)


class ApiAndExportTests(MediaTestCase):
    def setUp(self):
        self.hall = make_hall()
        self.user = User.objects.create_user("u", "u@example.com", "pass-12345")
        self.eq = Equipment.objects.create(name="Свет", category="light", inventory_number="L1", price_per_hour=200)
        self.day = next_weekday(4)

    def test_quote_api_returns_server_calculation(self):
        r = self.client.get(reverse("rental:api_quote"), {
            "hall": self.hall.pk, "date": self.day.isoformat(), "start": 12, "hours": 3, "equipment": [self.eq.pk]})
        data = r.json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["quote"]["discount_percent"], 10)
        self.assertEqual(Decimal(data["quote"]["total"]), Decimal("1350.00") + Decimal("600.00"))

    def test_quote_api_marks_busy_equipment(self):
        services.save_booking(user=self.user, hall=self.hall, start=services.make_start(self.day, 12), hours=2, equipment=[self.eq])
        hall2 = make_hall("B", "b")
        data = self.client.get(reverse("rental:api_quote"), {
            "hall": hall2.pk, "date": self.day.isoformat(), "start": 13, "hours": 2, "equipment": [self.eq.pk]}).json()
        self.assertIn(str(self.eq.pk), data["busy_equipment"])
        self.assertFalse(data["ok"])

    def test_quote_api_bad_input(self):
        data = self.client.get(reverse("rental:api_quote"), {"hall": "x"}).json()
        self.assertFalse(data["ok"])

    def test_schedule_api(self):
        services.save_booking(user=self.user, hall=self.hall, start=services.make_start(self.day, 12), hours=2)
        data = self.client.get(reverse("rental:api_schedule"), {"hall": self.hall.pk, "date": self.day.isoformat()}).json()
        states = {s["hour"]: s["state"] for s in data["slots"]}
        self.assertEqual((states[11], states[12], states[13], states[14]), ("free", "busy", "busy", "free"))
        self.assertEqual(self.client.get(reverse("rental:api_schedule")).status_code, 400)

    def test_csv_export(self):
        services.save_booking(user=self.user, hall=self.hall, start=services.make_start(self.day, 12), hours=3, equipment=[self.eq])
        self.client.force_login(self.user)
        r = self.client.get(reverse("rental:booking_export"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        text = r.content.decode("utf-8-sig")
        self.assertIn("Свет", text)
        self.assertIn("1950.00", text)  # 1350 (зал со скидкой) + 600 (оборудование)

    def test_print_form(self):
        b = services.save_booking(user=self.user, hall=self.hall, start=services.make_start(self.day, 12), hours=3, equipment=[self.eq])
        self.client.force_login(self.user)
        r = self.client.get(reverse("rental:booking_print", args=[b.pk]))
        self.assertContains(r, "Итого к оплате")


class CatalogTests(MediaTestCase):
    @classmethod
    def setUpTestData(cls):
        for i in range(45):
            Equipment.objects.create(name=f"Прибор {i:02d}", category="light" if i % 2 else "flash",
                                     inventory_number=f"INV{i:03d}", price_per_hour=100 + i * 10)

    def test_pagination_by_20(self):
        r = self.client.get(reverse("rental:equipment_list"))
        self.assertEqual(len(r.context["page"]), 20)
        self.assertEqual(r.context["page"].paginator.num_pages, 3)

    def test_filters_search_sort_preserved_in_page_links(self):
        r = self.client.get(reverse("rental:equipment_list"), {"category": "light", "sort": "price", "dir": "desc", "q": "Прибор"})
        names = [e.price_per_hour for e in r.context["page"]]
        self.assertEqual(names, sorted(names, reverse=True))
        self.assertTrue(all(e.category == "light" for e in r.context["page"]))
        self.assertIn("category=light", r.context["query_string"])
        self.assertContains(r, "sort=price")
        self.assertContains(r, "page=2")

    def test_max_price_filter(self):
        r = self.client.get(reverse("rental:equipment_list"), {"max_price": 150})
        self.assertTrue(all(e.price_per_hour <= 150 for e in r.context["page"]))

    def test_free_date_filter_excludes_busy(self):
        hall = make_hall()
        user = User.objects.create_user("c", "c@example.com", "pass-12345")
        eq = Equipment.objects.get(inventory_number="INV000")
        day = next_weekday(2)
        services.save_booking(user=user, hall=hall, start=services.make_start(day, 12), hours=2, equipment=[eq])
        r = self.client.get(reverse("rental:equipment_list"), {"free_date": day.isoformat(), "q": "INV000"})
        self.assertEqual(len(r.context["page"]), 0)


class SeedTests(MediaTestCase):
    def test_seed_meets_volume_requirements(self):
        call_command("seed_demo", verbosity=0)
        self.assertGreaterEqual(Equipment.objects.count(), 30)
        self.assertGreaterEqual(Booking.objects.count(), 30)
        self.assertGreaterEqual(Tariff.objects.count(), 10)
        self.assertGreaterEqual(MakeupSeat.objects.count(), 10)
        # ни одна единица оборудования не пересекается по времени в активных бронях
        items = list(BookingEquipment.objects.filter(booking__status__in=Booking.ACTIVE_STATUSES).select_related("booking"))
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if a.equipment_id == b.equipment_id:
                    self.assertFalse(a.booking.start < b.booking.end and b.booking.start < a.booking.end)
        for hall in Hall.objects.all():
            self.assertTrue(Hall.objects.get(pk=hall.pk).image.name)
            hall.image.delete(save=False)
