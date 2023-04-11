"""Image integrations for TKinter."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageTk
from srctools.logger import get_logger

from app import img


LOGGER = get_logger(__name__)


def get_app_icon(path: str) -> ImageTk.PhotoImage:
    """On non-Windows, retrieve the application icon."""
    with open(path, 'rb') as f:
        return ImageTk.PhotoImage(Image.open(f))


class TKImages(img.UIImage):
    """Tk-specific image code."""
    # TK images have unique IDs, so preserve discarded image objects.
    unused_img: dict[tuple[int, int], list[ImageTk.PhotoImage]]

    # Maps a handle to the current image used for it.
    tk_img: dict[img.Handle, ImageTk.PhotoImage]

    def __init__(self) -> None:
        """Set up the TK code."""
        self.unused_img = {}
        self.tk_img = {}

    def _get_img(self, width: int, height: int) -> ImageTk.PhotoImage:
        """Recycle an old image, or construct a new one."""
        if not width:
            width = 16
        if not height:
            height = 16

        # Use setdefault and pop so each step is atomic.
        img_list = self.unused_img.setdefault((width, height), [])
        try:
            img = img_list.pop()
        except IndexError:
            img = ImageTk.PhotoImage('RGBA', (width, height))
        return img

    def _discard_img(self, img: ImageTk.PhotoImage | None) -> None:
        """Store an unused image so it can be reused."""
        if img is not None:
            # Use setdefault and append so each step is atomic.
            img_list = self.unused_img.setdefault((img.width(), img.height()), [])
            img_list.append(img)

    def ui_clear_handle(self, handle: img.Handle) -> None:
        """Clear cached TK images for this handle."""
        self._discard_img(self.tk_img.pop(handle, None))

    def sync_load(self, handle: img.Handle) -> ImageTk.PhotoImage:
        """Load the TK image if required immediately, then return it.

        Only available on BUILTIN type images since they cannot then be
        reloaded.
        """
        handle.force_load()
        return self._load_tk(handle, force=False)

    def _load_tk(self, handle: img.Handle, force: bool) -> ImageTk.PhotoImage:
        """Load the TK image if required, then return it."""
        image = self.tk_img.get(handle)
        if image is None or force:
            # LOGGER.debug('Loading {}', self)
            res = handle._load_pil()
            # Except for builtin types (icons), composite onto the PeTI BG.
            if not handle.alpha_result and res.mode == 'RGBA':
                bg = Image.new('RGBA', res.size, img.BACKGROUNDS[img.current_theme()])
                bg.alpha_composite(res)
                res = bg.convert('RGB')
                self._bg_composited = True
            if image is None:
                image = self.tk_img[handle] = self._get_img(res.width, res.height)
            image.paste(res)
        return image
