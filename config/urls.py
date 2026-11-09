from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("rental.urls")),
    # Учебный режим: раздаём статику и загруженные файлы средствами Django даже при DEBUG=False.
    # В боевой среде это делает веб-сервер (nginx и т. п.).
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
