"""Оптимизация загружаемых изображений: уменьшаем до разумного размера и пережимаем."""
import io
import os

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_SIDE = 1200      # самая длинная сторона, px: хватает для карточки и страницы зала
JPEG_QUALITY = 82


def shrink_field_file(field_file, max_side=MAX_SIDE):
    """Если в поле лежит свежая загрузка — уменьшить её. Уже сохранённые файлы не трогаем."""
    if not field_file or getattr(field_file, "_committed", True):
        return
    field_file.file.seek(0)
    with Image.open(field_file.file) as img:
        fmt = img.format
        img = ImageOps.exif_transpose(img)
        if max(img.size) <= max_side and fmt != "PNG":
            field_file.file.seek(0)
            return
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        if fmt == "PNG" and img.mode in ("RGBA", "LA", "P"):
            img.save(buf, "PNG", optimize=True)
            ext = ".png"
        else:
            img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
            ext = ".jpg"
    base = os.path.splitext(os.path.basename(field_file.name))[0]
    field_file.save(base + ext, ContentFile(buf.getvalue()), save=False)
