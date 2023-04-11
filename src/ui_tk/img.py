"""Image integrations for TKinter."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageTk
from srctools.logger import get_logger


LOGGER = get_logger(__name__)


def get_app_icon(path: str) -> ImageTk.PhotoImage:
    """On non-Windows, retrieve the application icon."""
    with open(path, 'rb') as f:
        return ImageTk.PhotoImage(Image.open(f))
