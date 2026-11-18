from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "rental"

urlpatterns = [
    path("", views.home, name="home"),
    path("halls/<slug:slug>/", views.hall_detail, name="hall_detail"),
    path("halls/<slug:slug>/review/", views.review_create, name="review_create"),
    path("reviews/<int:pk>/edit/", views.review_edit, name="review_edit"),
    path("reviews/<int:pk>/delete/", views.review_delete, name="review_delete"),

    path("equipment/", views.equipment_list, name="equipment_list"),
    path("equipment/add/", views.equipment_create, name="equipment_create"),
    path("equipment/<int:pk>/edit/", views.equipment_edit, name="equipment_edit"),
    path("equipment/<int:pk>/delete/", views.equipment_delete, name="equipment_delete"),

    path("bookings/", views.booking_list, name="booking_list"),
    path("bookings/new/", views.booking_create, name="booking_create"),
    path("bookings/export.csv", views.booking_export_csv, name="booking_export"),
    path("bookings/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("bookings/<int:pk>/edit/", views.booking_edit, name="booking_edit"),
    path("bookings/<int:pk>/cancel/", views.booking_cancel, name="booking_cancel"),
    path("bookings/<int:pk>/status/", views.booking_status, name="booking_status"),
    path("bookings/<int:pk>/delete/", views.booking_delete, name="booking_delete"),
    path("bookings/<int:pk>/print/", views.booking_print, name="booking_print"),
    path("bookings/<int:pk>/penalty/", views.penalty_create, name="penalty_create"),
    path("penalties/<int:pk>/paid/", views.penalty_paid, name="penalty_paid"),

    path("profile/", views.profile, name="profile"),
    path("search/", views.search, name="search"),
    path("rules/", views.rules, name="rules"),
    path("contacts/", views.contacts, name="contacts"),

    path("stats/", views.stats, name="stats"),
    path("api/quote/", views.api_quote, name="api_quote"),
    path("api/equipment/", views.api_equipment, name="api_equipment"),
    path("api/schedule/", views.api_schedule, name="api_schedule"),
    path("api/stats/", views.api_stats, name="api_stats"),

    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="rental/auth/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password-change/", auth_views.PasswordChangeView.as_view(
        template_name="rental/auth/password_change.html", success_url="/accounts/password-change/done/"), name="password_change"),
    path("accounts/password-change/done/", auth_views.PasswordChangeDoneView.as_view(
        template_name="rental/auth/password_change_done.html"), name="password_change_done"),
]
