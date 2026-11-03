"""Подготовка фото товаров к хранению в базе."""

import io
import warnings

from PIL import Image, ImageOps

from .constants import PHOTO_MAX_BYTES, PHOTO_MAX_PIXELS, PHOTO_MAX_SIDE

_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")


class PhotoError(ValueError):
    """Ошибка с понятным текстом, который можно показать пользователю."""


def prepare_image(source):
    """Принимает файл (путь, байты или файловый объект) и возвращает байты JPEG для сохранения в базе.

    Фото уменьшается, поворачивается по EXIF (снимки с телефона), прозрачность заменяется белым фоном.
    Все метаданные, включая геолокацию съёмки, отбрасываются. Ошибки — PhotoError.
    """
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif hasattr(source, "read"):
        raw = source.read(PHOTO_MAX_BYTES + 1)
    else:
        try:
            with open(source, "rb") as fh:
                raw = fh.read(PHOTO_MAX_BYTES + 1)
        except OSError:
            raise PhotoError("Не удалось прочитать файл")
    if not raw:
        raise PhotoError("Файл пустой")
    if len(raw) > PHOTO_MAX_BYTES:
        raise PhotoError(f"Файл слишком большой (максимум {PHOTO_MAX_BYTES // 2 ** 20} МБ)")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            old_limit, Image.MAX_IMAGE_PIXELS = Image.MAX_IMAGE_PIXELS, PHOTO_MAX_PIXELS
            try:
                with Image.open(io.BytesIO(raw)) as img:
                    img.load()
                    img = ImageOps.exif_transpose(img)
                    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                        rgba = img.convert("RGBA")
                        img = Image.new("RGB", rgba.size, (255, 255, 255))
                        img.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        img = img.convert("RGB")
            finally:
                Image.MAX_IMAGE_PIXELS = old_limit
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PhotoError("Слишком большая картинка. Уменьшите её и попробуйте снова.")
    except Exception:
        raise PhotoError("Не удалось открыть файл как изображение. Поддерживаются JPG, PNG, WEBP, BMP и GIF.")
    img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE), _LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()
