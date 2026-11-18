from django.contrib import admin

from .models import (Booking, ContactMessage, BookingEquipment, Equipment, Hall, InteriorZone, MakeupSeat, Penalty, Review, Tariff)

admin.site.site_header = "Фотостудия «Кадр» — администрирование"
admin.site.site_title = "Фотостудия «Кадр»"


class ZoneInline(admin.TabularInline):
    model = InteriorZone
    extra = 1


class TariffInline(admin.TabularInline):
    model = Tariff
    extra = 0


class SeatInline(admin.TabularInline):
    model = MakeupSeat
    extra = 0


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ("name", "area", "capacity", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ZoneInline, TariffInline, SeatInline]


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("name", "inventory_number", "category", "price_per_hour", "status")
    list_filter = ("category", "status")
    search_fields = ("name", "inventory_number")
    list_editable = ("status",)


class BookingEquipmentInline(admin.TabularInline):
    model = BookingEquipment
    extra = 0
    autocomplete_fields = ("equipment",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "hall", "user", "start", "hours", "total_price", "status")
    list_filter = ("status", "hall")
    search_fields = ("user__username", "hall__name", "comment")
    date_hierarchy = "start"
    inlines = [BookingEquipmentInline]
    filter_horizontal = ("makeup_seats",)


@admin.register(Penalty)
class PenaltyAdmin(admin.ModelAdmin):
    list_display = ("booking", "equipment", "amount", "is_paid", "created_at")
    list_filter = ("is_paid",)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("hall", "author", "rating", "created_at")
    list_filter = ("rating", "hall")


admin.site.register(InteriorZone)
admin.site.register(Tariff)
admin.site.register(MakeupSeat)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "created_at", "is_processed")
    list_filter = ("is_processed",)
    search_fields = ("name", "email", "message")
    readonly_fields = ("created_at",)
