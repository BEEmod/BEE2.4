"""Image integrations for TKinter."""
from __future__ import annotations

import itertools

import attrs
import trio
from typing import Iterable, TypeVar, Union
from typing_extensions import TypeAlias
from tkinter import ttk
import tkinter as tk

from PIL import Image, ImageTk
from srctools.logger import get_logger

from app import TK_ROOT, img

# Widgets with an image attribute that can be set.
tkImgWidgets: TypeAlias = Union[tk.Label, ttk.Label, tk.Button, ttk.Button]
tkImgWidgetsT = TypeVar(
    'tkImgWidgetsT',
    tk.Label, ttk.Label,
    Union[tk.Label, ttk.Label],
    tk.Button, ttk.Button,
    Union[tk.Button, ttk.Button],
)
tkImg: TypeAlias = Union[ImageTk.PhotoImage, tk.PhotoImage]

LOGGER = get_logger(__name__)
label_to_user: dict[tkImgWidgets, LabelStyleUser] = {}


def get_app_icon(path: str) -> ImageTk.PhotoImage:
    """On non-Windows, retrieve the application icon."""
    with open(path, 'rb') as f:
        return ImageTk.PhotoImage(Image.open(f))


def on_label_destroyed(e: tk.Event) -> None:
    """When labels are destroyed, clean up their user."""
    try:
        user = label_to_user.pop(e.widget)
    except (KeyError, TypeError, NameError):
        # Interpreter could be shutting down and deleted globals, or we were
        # called twice, etc. Just ignore.
        pass
    else:
        if user.cur_handle is not None:
            user.cur_handle._decref(user)
        del user.label  # Clear this, to make GC easier.


label_destroy_cmd = TK_ROOT.register(on_label_destroyed, needcleanup=False)


@attrs.define(eq=False)
class LabelStyleUser(img.User):
    """A user for widgets with an 'image' attribute."""
    label: tkImgWidgets
    cur_handle: img.Handle | None


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

    def sync_load(self, handle: img.Handle) -> tkImg:
        """Load the TK image if required immediately, then return it.

        Only available on BUILTIN type images since they cannot then be
        reloaded.
        """
        handle.force_load()
        return self._load_tk(handle, force=False)

    # noinspection PyProtectedMember
    def apply(self, widget: tkImgWidgetsT, image: img.Handle | None, /) -> tkImgWidgetsT:
        """Set the image in a label-style widget.

        This tracks the widget, so later reloads will affect the widget.
        If the image is None, it is instead unset.
        """
        if image is None:
            widget['image'] = None
            try:
                user = label_to_user[widget]
            except KeyError:
                pass
            else:
                if user.cur_handle is not None:
                    user.cur_handle._decref(user)
                    user.cur_handle = None
            return widget
        try:
            user = label_to_user[widget]
        except KeyError:
            # No user yet, create + bind.
            user = label_to_user[widget] = LabelStyleUser(widget, None)
        else:
            if user.cur_handle is image:
                # Unchanged.
                return widget
            elif user.cur_handle is not None:
                user.cur_handle._decref(user)
        image._incref(user)
        try:
            widget['image'] = self.tk_img[image]
        except KeyError:  # Need to load.
            loading = image._request_load()
            widget['image'] = self._load_tk(loading, False)
        return widget

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

    async def ui_anim_task(self, load_handles: Iterable[tuple[img.Handle, list[img.Handle]]]) -> None:
        """Cycle loading icons."""
        for i in itertools.cycle(img.LOAD_FRAME_IND):
            await trio.sleep(0.125)
            for handle, frames in load_handles:
                # This will keep the frame loaded, so next time it's cheap.
                handle._cached_pil = frames[i].get_pil()
                try:
                    tk_img = self.tk_img[handle]
                except KeyError:
                    pass  # This isn't being used.
                else:
                    # This updates the TK widget directly.
                    tk_img.paste(handle._load_pil())

    def ui_load_users(self, handle: img.Handle, force: bool) -> None:
        """Load this handle into the widgets using it."""
        tk_img = self._load_tk(handle, force)
        for user in handle._users:
            if isinstance(user, LabelStyleUser):
                try:
                    user.label['image'] = tk_img
                except tk.TclError:
                    # Can occur if the image has been removed/destroyed, but
                    # the Python object still exists. Ignore, should be
                    # cleaned up shortly.
                    pass

    def ui_force_load(self, handle: img.Handle) -> None:
        """Called when this handle is reloading, and should update all its widgets."""
        loading = self._load_tk(
            img.Handle.ico_loading(handle.width, handle.height),
            False,
        )
        for user in handle._users:
            if isinstance(user, LabelStyleUser):
                user.label['image'] = loading
