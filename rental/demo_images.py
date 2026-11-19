"""Иллюстрации для демо-данных: интерьеры залов и предметы оборудования.

Это не фотографии, а нарисованные сцены, чтобы каталог выглядел живым без загрузки файлов.
Настоящие фото загружаются в админке или формой оборудования; здесь они не нужны.
"""
import io
import math
import random

from django.core.files.base import ContentFile
from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 1200, 800


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vgrad(size, top, bottom):
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=_lerp(top, bottom, y / max(1, h - 1)))
    return img


def _glow(base, shape_fn, color, radius, alpha=200):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shape_fn(ImageDraw.Draw(layer), color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    base.paste(layer, (0, 0), layer)


def _finish(img, seed, vignette=0.45, grain=9):
    """Виньетка и плёночное зерно — чтобы картинка не выглядела плоской."""
    rnd = random.Random(seed)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((-img.width * .25, -img.height * .35, img.width * 1.25, img.height * 1.35), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(img.width // 6))
    dark = Image.new("RGB", img.size, (10, 8, 6))
    img = Image.composite(img, Image.blend(img, dark, vignette), mask)
    noise = Image.effect_noise(img.size, grain).convert("RGB")
    img = ImageChops.add(img, noise, scale=1, offset=-128 + 0)
    return img


def _softbox(draw, x, y, w, h, tilt=0):
    """Софтбокс на стойке: трапеция, ножка, ребро."""
    draw.polygon([(x - w, y), (x + w, y - tilt), (x + w * .8, y + h), (x - w * .8, y + h + tilt)], fill=(245, 244, 240), outline=(60, 55, 50))
    draw.line([(x, y + h), (x, y + h + 250)], fill=(40, 38, 36), width=8)
    draw.line([(x - 70, y + h + 250), (x + 70, y + h + 250)], fill=(40, 38, 36), width=8)


def hall_scene(slug: str) -> Image.Image:
    rnd = random.Random(slug)
    floor_y = int(H * .66)
    if slug == "neon":
        img = _vgrad((W, H), (14, 12, 28), (30, 22, 50))
        _glow(img, lambda d, c: (d.rectangle((110, 100, 530, 160), fill=c), d.rectangle((690, 180, 1090, 240), fill=c)), (255, 60, 160), 34, 255)
        _glow(img, lambda d, c: d.rectangle((290, 310, 910, 365), fill=c), (60, 190, 255), 34, 255)
        d = ImageDraw.Draw(img)
        for x in range(60, W, 190):                       # зеркальные панели
            d.rectangle((x, 380, x + 120, floor_y), outline=(120, 110, 170), width=3, fill=(36, 30, 62))
        d.rectangle((120, 120, 520, 140), fill=(255, 190, 225))
        d.rectangle((700, 200, 1080, 220), fill=(255, 190, 225))
        d.rectangle((300, 330, 900, 345), fill=(190, 235, 255))
        floor = _vgrad((W, H - floor_y), (22, 18, 40), (8, 6, 16))
        img.paste(floor, (0, floor_y))
        _glow(img, lambda d, c: d.ellipse((260, floor_y + 20, 940, floor_y + 150), fill=c), (255, 60, 160), 50, 90)
    else:
        walls = {"white-cube": ((246, 245, 240), (226, 224, 218)), "loft": ((156, 92, 68), (118, 68, 50)),
                 "cyclorama": ((236, 238, 242), (214, 218, 226)), "vintage": ((196, 150, 78), (156, 108, 52)),
                 "green-garden": ((196, 214, 196), (150, 184, 158))}.get(slug, ((230, 226, 220), (200, 194, 186)))
        img = _vgrad((W, H), *walls)
        d = ImageDraw.Draw(img)
        if slug == "loft":                                  # кирпичная кладка и фермы
            for row, y in enumerate(range(0, floor_y, 34)):
                for x in range(-60 if row % 2 else 0, W, 120):
                    t = rnd.uniform(-14, 14)
                    c = tuple(int(max(0, min(255, v + t))) for v in (150, 84, 62))
                    d.rectangle((x + 2, y + 2, x + 116, y + 31), fill=c)
            for x in range(-100, W, 260):
                d.line([(x, 0), (x + 130, 110), (x + 260, 0)], fill=(30, 28, 28), width=10)
            d.rectangle((0, 0, W, 16), fill=(30, 28, 28))
        elif slug == "vintage":                              # обои в полоску
            for x in range(0, W, 60):
                d.rectangle((x, 0, x + 28, floor_y), fill=(176, 126, 62))
            d.rectangle((90, 230, 330, 480), outline=(70, 44, 24), width=10, fill=(236, 214, 170))
        elif slug == "white-cube":                           # большие окна с лучами
            for x0 in (110, 470, 830):
                d.rectangle((x0, 110, x0 + 260, 470), fill=(252, 253, 255), outline=(190, 188, 182), width=8)
                d.line([(x0 + 130, 110), (x0 + 130, 470)], fill=(190, 188, 182), width=6)
            _glow(img, lambda dd, c: [dd.polygon([(x0, 470), (x0 + 260, 470), (x0 + 160, floor_y + 90), (x0 - 150, floor_y + 90)], fill=c) for x0 in (110, 470, 830)], (255, 252, 235), 28, 120)
        elif slug == "green-garden":                         # стеклянная стена и растения
            for x0 in range(0, W, 200):
                d.rectangle((x0, 60, x0 + 196, floor_y - 40), fill=(226, 240, 230), outline=(80, 100, 90), width=6)
            for _ in range(46):
                cx, cy = rnd.randint(0, W), rnd.randint(floor_y - 330, floor_y + 20)
                rw, rh = rnd.randint(28, 70), rnd.randint(70, 190)
                g = rnd.randint(70, 130)
                d.ellipse((cx - rw, cy - rh, cx + rw, cy + rh // 3), fill=(30, g, 60))
        if slug == "cyclorama":                              # бесшовный переход стены в пол
            sweep = _vgrad((W, 220), walls[0], (250, 250, 252))
            img.paste(sweep, (0, floor_y - 120))
        floors = {"loft": ((88, 58, 44), (52, 34, 26)), "vintage": ((96, 52, 40), (62, 32, 26)), "green-garden": ((120, 112, 100), (86, 80, 72)),
                  "cyclorama": ((250, 250, 252), (232, 234, 240))}
        ft, fb = floors.get(slug, ((200, 194, 186), (150, 144, 136)))
        floor = _vgrad((W, H - floor_y), ft, fb)
        if slug != "cyclorama":
            img.paste(floor, (0, floor_y))
        else:
            img.paste(floor, (0, floor_y + 20))
        d = ImageDraw.Draw(img)
        if slug in ("loft", "vintage", "green-garden"):
            for i in range(1, 9):                            # доски пола в перспективе
                d.line([(W / 2 + (i - 4.5) * 40, floor_y), (W / 2 + (i - 4.5) * 280, H)], fill=tuple(int(v * .8) for v in fb), width=2)
    d = ImageDraw.Draw(img)
    if slug in ("white-cube", "cyclorama", "loft"):          # осветители в кадре
        _glow(img, lambda dd, c: dd.ellipse((130, 180, 430, 420), fill=c), (255, 246, 225), 40, 180)
        _softbox(d, 280, 250, 110, 170, tilt=14)
        _glow(img, lambda dd, c: dd.ellipse((820, 220, 1100, 440), fill=c), (255, 246, 225), 40, 150)
        _softbox(d, 960, 270, 90, 150, tilt=-10)
    if slug == "vintage":                                    # торшер и ковёр
        d.polygon([(880, 300), (1010, 300), (1050, 420), (840, 420)], fill=(240, 214, 150), outline=(70, 44, 24))
        d.line([(945, 420), (945, floor_y + 130)], fill=(50, 32, 20), width=10)
        d.ellipse((240, floor_y + 70, 960, floor_y + 210), fill=(150, 56, 48), outline=(230, 190, 120), width=6)
        _glow(img, lambda dd, c: dd.ellipse((820, 260, 1070, 460), fill=c), (255, 220, 150), 50, 190)
    if slug == "green-garden":
        d.rectangle((420, floor_y + 90, 800, floor_y + 130), fill=(110, 74, 48))
    return _finish(img, slug, vignette=.35 if slug != "neon" else .25)


def _object(d, category, cx, cy, accent):
    ink = (34, 32, 30)
    if category == "light":                                   # LED-панель на стойке
        d.rounded_rectangle((cx - 120, cy - 100, cx + 120, cy + 40), 14, fill=(244, 243, 238), outline=ink, width=6)
        for i in range(5):
            d.line([(cx - 100 + i * 50, cy - 90), (cx - 100 + i * 50, cy + 30)], fill=(205, 202, 194), width=3)
        d.line([(cx, cy + 40), (cx, cy + 150)], fill=ink, width=8)
        for dx in (-80, 0, 80):
            d.line([(cx, cy + 150), (cx + dx, cy + 175)], fill=ink, width=7)
    elif category == "flash":                                 # голова вспышки
        d.rounded_rectangle((cx - 70, cy - 40, cx + 70, cy + 90), 20, fill=accent, outline=ink, width=6)
        d.ellipse((cx - 110, cy - 130, cx + 110, cy + 20), fill=(250, 250, 246), outline=ink, width=6)
        d.ellipse((cx - 40, cy - 90, cx + 40, cy - 20), fill=(255, 226, 150), outline=ink, width=4)
    elif category == "modifier":                              # октобокс
        pts = [(cx + 135 * math.cos(math.pi / 8 + k * math.pi / 4), cy - 20 + 135 * math.sin(math.pi / 8 + k * math.pi / 4)) for k in range(8)]
        d.polygon(pts, fill=(246, 245, 240), outline=ink)
        for p in pts:
            d.line([(cx, cy - 20), p], fill=(190, 186, 178), width=3)
        d.line(pts + [pts[0]], fill=ink, width=6)
        d.ellipse((cx - 22, cy - 42, cx + 22, cy + 2), fill=accent, outline=ink, width=4)
    elif category == "background":                            # бумажный фон на штанге
        d.rectangle((cx - 150, cy - 130, cx + 150, cy - 112), fill=(70, 66, 62))
        d.rectangle((cx - 120, cy - 112, cx + 120, cy + 110), fill=accent, outline=ink, width=4)
        d.ellipse((cx - 132, cy + 80, cx + 132, cy + 128), fill=_lerp(accent, (255, 255, 255), .25), outline=ink, width=4)
        for x in (cx - 150, cx + 150):
            d.line([(x, cy - 120), (x, cy + 150)], fill=ink, width=8)
    else:                                                     # реквизит: зеркало в раме
        d.rounded_rectangle((cx - 90, cy - 140, cx + 90, cy + 120), 90, fill=(120, 80, 48), outline=ink, width=5)
        d.rounded_rectangle((cx - 68, cy - 118, cx + 68, cy + 98), 68, fill=(214, 230, 238))
        d.line([(cx - 40, cy - 70), (cx + 10, cy - 100)], fill=(255, 255, 255), width=8)


def equipment_image(category: str, name: str) -> Image.Image:
    rnd = random.Random(name)
    bg = {"light": ((74, 66, 60), (38, 34, 32)), "flash": ((92, 62, 50), (42, 30, 26)), "modifier": ((70, 76, 84), (34, 38, 44)),
          "background": ((204, 198, 188), (150, 144, 134)), "prop": ((120, 96, 70), (64, 50, 38))}.get(category, ((90, 90, 90), (40, 40, 40)))
    img = _vgrad((800, 500), *bg)
    accent = [(180, 83, 42), (60, 110, 150), (110, 130, 80), (190, 160, 70), (200, 200, 205), (90, 90, 96)][rnd.randint(0, 5)]
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((200, 400, 600, 450), fill=(0, 0, 0, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    img.paste(shadow, (0, 0), shadow)
    _object(ImageDraw.Draw(img), category, 400, 235, accent)
    return _finish(img, name, vignette=.3, grain=6)


def to_content(img: Image.Image, quality=82) -> ContentFile:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return ContentFile(buf.getvalue())
