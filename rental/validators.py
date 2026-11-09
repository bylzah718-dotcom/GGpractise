"""Проверка загружаемых файлов: тип (по расширению и по содержимому) и размер."""
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
REFERENCE_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}


def _is_stored(f) -> bool:
    """Уже сохранённый файл повторно не проверяем — только новые загрузки."""
    return bool(getattr(f, "_committed", False))


def _size_error(limit: int) -> ValidationError:
    return ValidationError(f"Файл слишком большой: допустимо не более {limit // (1024 * 1024)} МБ.")


def validate_image(f):
    if _is_stored(f):
        return
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationError("Допустимые форматы изображений: JPG, PNG, WEBP.")
    if f.size > settings.MAX_IMAGE_SIZE:
        raise _size_error(settings.MAX_IMAGE_SIZE)
    try:
        f.seek(0)
        with Image.open(f) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValidationError("Файл не является корректным изображением.")
    finally:
        try:
            f.seek(0)
        except Exception:  # noqa: BLE001
            pass
    if fmt not in IMAGE_FORMATS:
        raise ValidationError("Допустимые форматы изображений: JPG, PNG, WEBP.")


def validate_reference_file(f):
    """Референс/мудборд к брони: изображение или PDF до 5 МБ."""
    if _is_stored(f):
        return
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in REFERENCE_EXTENSIONS:
        raise ValidationError("Допустимые форматы: PDF, JPG, PNG, WEBP.")
    if f.size > settings.MAX_REFERENCE_SIZE:
        raise _size_error(settings.MAX_REFERENCE_SIZE)
    if ext == ".pdf":
        f.seek(0)
        head = f.read(5)
        f.seek(0)
        if head != b"%PDF-":
            raise ValidationError("Файл не является корректным PDF.")
    else:
        validate_image(f)
