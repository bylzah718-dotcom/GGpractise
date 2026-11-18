import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from . import services
from .models import ContactMessage, Equipment, Hall, MakeupSeat, Penalty, Review
from .validators import validate_reference_file

User = get_user_model()


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label="Электронная почта", help_text="Сюда придут уведомления о бронях.")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с такой почтой уже зарегистрирован.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class DataCheckboxSelect(forms.CheckboxSelectMultiple):
    """Чекбоксы с data-атрибутами (цена, зал) — их читает JavaScript для подсказок."""

    def __init__(self, *args, data_attrs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_attrs = data_attrs or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            for key, getter in self.data_attrs.items():
                option["attrs"][f"data-{key}"] = getter(instance)
        return option


def _hour_choices():
    return [(h, f"{h:02d}:00") for h in range(settings.STUDIO_OPEN_HOUR, settings.STUDIO_CLOSE_HOUR)]


class BookingForm(forms.Form):
    hall = forms.ModelChoiceField(Hall.objects.none(), label="Зал", empty_label=None)
    date = forms.DateField(label="Дата", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    start_hour = forms.TypedChoiceField(label="Начало", choices=_hour_choices, coerce=int)
    hours = forms.TypedChoiceField(label="Длительность, ч", coerce=int, choices=[])
    people = forms.IntegerField(label="Человек на съёмке", min_value=1, initial=1)
    makeup_seats = forms.ModelMultipleChoiceField(
        MakeupSeat.objects.none(), label="Гримёрные места", required=False,
        widget=DataCheckboxSelect(data_attrs={"hall": lambda s: s.hall_id}),
    )
    equipment = forms.ModelMultipleChoiceField(
        Equipment.objects.none(), label="Оборудование и реквизит", required=False,
        widget=DataCheckboxSelect(data_attrs={"price": lambda e: e.price_per_hour}),
    )
    reference_file = forms.FileField(
        label="Референс / мудборд", required=False, validators=[validate_reference_file],
        help_text="PDF, JPG, PNG или WEBP, до 5 МБ.",
    )
    comment = forms.CharField(label="Комментарий", required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, user=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance = instance
        self.fields["hall"].queryset = Hall.objects.filter(is_active=True)
        self.fields["hours"].choices = [(h, f"{h} ч") for h in range(1, settings.MAX_BOOKING_HOURS + 1)]
        self.fields["makeup_seats"].queryset = MakeupSeat.objects.filter(is_active=True).select_related("hall")
        self.fields["makeup_seats"].label_from_instance = lambda s: f"{s.name} — {s.price_per_hour:g} ₽/ч"
        self.fields["equipment"].queryset = Equipment.objects.filter(status=Equipment.AVAILABLE)
        self.fields["equipment"].label_from_instance = lambda e: f"{e.name} [{e.inventory_number}] — {e.price_per_hour:g} ₽/ч"
        self.fields["date"].widget.attrs["min"] = timezone.localdate().isoformat()
        self.start = None

    @classmethod
    def initial_from_booking(cls, booking):
        start = timezone.localtime(booking.start)
        return {
            "hall": booking.hall_id, "date": start.date(), "start_hour": start.hour, "hours": booking.hours,
            "people": booking.people, "makeup_seats": list(booking.makeup_seats.values_list("pk", flat=True)),
            "equipment": list(booking.equipment.values_list("pk", flat=True)), "comment": booking.comment,
        }

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        self.start = services.make_start(data["date"], data["start_hour"])
        errors = services.validate_request(
            hall=data["hall"], start=self.start, hours=data["hours"], people=data["people"],
            equipment=data.get("equipment") or [], seats=data.get("makeup_seats") or [],
            exclude_booking_id=self.instance.pk if self.instance else None,
        )
        for message in errors:
            self.add_error(None, message)
        return data


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ("name", "category", "inventory_number", "description", "price_per_hour", "status", "image")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class PenaltyForm(forms.ModelForm):
    class Meta:
        model = Penalty
        fields = ("equipment", "amount", "reason", "photo")
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, booking, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = Equipment.objects.filter(booking_items__booking=booking)
        self.fields["equipment"].required = False
        self.fields["equipment"].empty_label = "— не относится к оборудованию —"


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(label="Оценка", coerce=int, choices=[(i, "★" * i + "☆" * (5 - i)) for i in range(5, 0, -1)])

    class Meta:
        model = Review
        fields = ("rating", "text")
        widgets = {"text": forms.Textarea(attrs={"rows": 4})}


PHONE_RE = re.compile(r"^(?:\+7|8)[\s(-]*(\d{3})[\s)-]*(\d{3})[\s-]*(\d{2})[\s-]*(\d{2})$")


def normalize_phone(value: str) -> str:
    """'89001234567' → '+7 900 123-45-67'. Не подходит по формату — ValidationError."""
    m = PHONE_RE.match(value.strip())
    if not m:
        raise forms.ValidationError("Введите телефон в формате +7 900 000-00-00.")
    a, b, c, d = m.groups()
    return f"+7 {a} {b}-{c}-{d}"


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "phone", "message")
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Как к вам обращаться"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "name@example.ru"}),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "placeholder": "+7 900 000-00-00", "data-phone": "1"}),
            "message": forms.Textarea(attrs={"rows": 5, "minlength": 10, "maxlength": 1000}),
        }
        error_messages = {
            "name": {"required": "Укажите, как к вам обращаться."},
            "email": {"required": "Укажите электронную почту.", "invalid": "Введите почту в формате name@example.ru."},
            "message": {"required": "Напишите сообщение."},
        }
        help_texts = {"phone": "Необязательно. Формат: +7 900 000-00-00.", "message": "От 10 до 1000 символов."}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if len(name) < 2:
            raise forms.ValidationError("Имя должно быть не короче 2 символов.")
        return name

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        return normalize_phone(phone) if phone else ""

    def clean_message(self):
        text = self.cleaned_data["message"].strip()
        if len(text) < 10:
            raise forms.ValidationError("Сообщение слишком короткое: напишите хотя бы 10 символов.")
        return text
