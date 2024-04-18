"""Image integrations for TKinter."""
from __future__ import annotations
from typing import TypeVar, Union
from typing_extensions import TypeAlias, override
from tkinter import ttk
import tkinter as tk

from PIL import Image, ImageTk
from srctools.logger import get_logger
import attrs

from app import img
from ui_tk import TK_ROOT


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
textwid_to_user: dict[tk.Text, TextWidUser] = {}
menu_to_user: dict[tk.Menu, MenuIconUser] = {}


def get_app_icon(path: str) -> ImageTk.PhotoImage:
    """On non-Windows, retrieve the application icon."""
    with open(path, 'rb') as f:
        return ImageTk.PhotoImage(Image.open(f))


def _on_destroyed(e: tk.Event[tk.Misc]) -> None:
    """When widgets are destroyed, clear their associated images."""
    if isinstance(e.widget, tk.Text):
        _on_textwid_destroyed(e.widget)
        return
    elif isinstance(e.widget, tk.Menu):
        _on_menu_destroyed(e.widget)
        return

    user = label_to_user.pop(e.widget, None)  # type: ignore
    if user is None:
        # It's not got an image.
        return
    if user.cur_handle is not None:
        user.cur_handle._decref(user)
    del user.label  # Remove a GC cycle for easier cleanup.


def _on_textwid_destroyed(textwid: tk.Text) -> None:
    """When text widgets are destroyed, clean up their user."""
    try:
        user = textwid_to_user.pop(textwid)
    except (KeyError, TypeError, NameError):
        # Interpreter could be shutting down and deleted globals, or we were
        # called twice, etc. Just ignore.
        pass
    else:
        for handle in user.handle_to_ids:
            handle._decref(user)
        user.handle_to_ids.clear()
        del user.text  # Remove a GC cycle for easier cleanup.


def _on_menu_destroyed(menu: tk.Menu) -> None:
    """When text widgets are destroyed, clean up their user."""
    try:
        user = menu_to_user.pop(menu)
    except (KeyError, TypeError, NameError):
        # Interpreter could be shutting down and deleted globals, or we were
        # called twice, etc. Just ignore.
        pass
    else:
        for handle in user.handle_to_pos:
            handle._decref(user)
        user.handle_to_pos.clear()
        del user.menu  # Remove a GC cycle for easier cleanup.


# When any widget is destroyed, notify us to allow clean-up.
TK_ROOT.bind_class('all', '<Destroy>', _on_destroyed, add='+')


class TkUser(img.User):
    """Common methods."""
    def set_img(self, handle: img.Handle, image: tkImg) -> None:
        """Apply this Tk image to users of it.

        This needs to catch TclError - that can occur if the image
        has been removed/destroyed, but  the Python object still exists.
        Ignore, should be cleaned up shortly.
        """


@attrs.define(eq=False)
class LabelStyleUser(TkUser):
    """A user for widgets with an 'image' attribute."""
    label: tkImgWidgets
    cur_handle: img.Handle | None

    @override
    def set_img(self, handle: img.Handle, image: tkImg) -> None:
        """Set the image on the label."""
        try:
            self.label['image'] = image
        except tk.TclError:
            pass


@attrs.define(eq=False)
class TextWidUser(TkUser):
    """A user for Text widgets, which may have multiple images inserted."""
    text: tk.Text
    handle_to_ids: dict[img.Handle, list[str]]

    @override
    def set_img(self, handle: img.Handle, image: tkImg) -> None:
        """Set this image for text elements using this handle."""
        try:
            img_ids = self.handle_to_ids[handle]
        except KeyError:
            return
        for img_id in img_ids:
            try:
                self.text.image_configure(img_id, image=image)
            except tk.TclError:
                pass

@attrs.define(eq=False)
class MenuIconUser(TkUser):
    """A user for menus, which may use images for icons."""
    menu: tk.Menu
    handle_to_pos: dict[img.Handle, set[int]]

    @override
    def set_img(self, handle: img.Handle, image: tkImg) -> None:
        """Set this image for menu options that use this handle."""
        try:
            pos_set = self.handle_to_pos[handle]
        except KeyError:
            return
        for pos in pos_set:
            try:
                self.menu.entryconfigure(pos, image=image)
            except tk.TclError:
                pass


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
            user = label_to_user[widget] = LabelStyleUser(widget, None)
        else:
            if user.cur_handle is image:
                # Unchanged.
                return widget
            if user.cur_handle is not None:
                user.cur_handle._decref(user)
        image._incref(user)
        user.cur_handle = image
        try:
            widget['image'] = self.tk_img[image]
        except KeyError:  # Need to load.
            loading = image._request_load()
            widget['image'] = self._load_tk(loading, False)
        return widget

    def menu_set_icon(self, menu: tk.Menu, index: int, image: img.Handle) -> None:
        """Set the icon used by a menu option at the specified location."""
        try:
            user = menu_to_user[menu]
        except KeyError:
            # No user yet, create + bind.
            user = menu_to_user[menu] = MenuIconUser(menu, {})
        try:
            pos_set = user.handle_to_pos[image]
        except KeyError:  # First time this is added to this widget.
            pos_set = user.handle_to_pos[image] = {index}
            image._incref(user)
        else:
            pos_set.add(index)
        try:
            tk_img = self.tk_img[image]
        except KeyError:  # Need to load.
            loading = image._request_load()
            tk_img = self._load_tk(loading, False)

        menu.entryconfigure(index, image=tk_img)

    def menu_clear(self, menu: tk.Menu) -> None:
        """Remove all added icons from this menu, freeing resources."""
        try:
            user = menu_to_user.pop(menu)
        except KeyError:
            return  # Not used at all, don't care.
        for handle in user.handle_to_pos:
            handle._decref(user)

    def textwid_add(self, textwid: tk.Text, index: str, image: img.Handle) -> str:
        """Add an image to a tkinter.Text widget, at the specified location."""
        try:
            user = textwid_to_user[textwid]
        except KeyError:
            # No user yet, create + bind.
            user = textwid_to_user[textwid] = TextWidUser(textwid, {})
        try:
            ids_list = user.handle_to_ids[image]
        except KeyError:  # First time this is added to this widget.
            ids_list = user.handle_to_ids[image] = []
            image._incref(user)
        try:
            tk_img = self.tk_img[image]
        except KeyError:  # Need to load.
            loading = image._request_load()
            tk_img = self._load_tk(loading, False)
        new_id: str = textwid.image_create(index, image=tk_img)
        ids_list.append(new_id)
        return new_id

    def textwid_clear(self, textwid: tk.Text) -> None:
        """Remove all added images from this text widget, freeing resources."""
        try:
            user = textwid_to_user.pop(textwid)
        except KeyError:
            return  # Not used at all, don't care.
        for handle, ids_list in user.handle_to_ids.items():
            handle._decref(user)
            for img_id in ids_list:
                textwid.delete(img_id)

    def stats(self) -> str:
        """Return some debugging stats."""
        info = [
            f'{img.stats()}'
            'TK images:\n'
            f' - Used = {len(self.tk_img)}\n'
            f' - Labels = {len(label_to_user)}\n'
            f' - Menus = {sum(len(user.handle_to_pos) for user in menu_to_user.values())}\n'
            f' - Texts = {sum(len(user.handle_to_ids) for user in textwid_to_user.values())}\n'
        ]
        for (x, y), unused in self.unused_img.items():
            info.append(f' - Unused {x}x{y} = {len(unused)}\n')
        return ''.join(info)

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

    @override
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
                handle._bg_composited = True
            if image is None:
                image = self.tk_img[handle] = self._get_img(res.width, res.height)
            image.paste(res)
        return image

    @override
    def ui_apply_load(self, handle: img.Handle, frame: Image.Image) -> None:
        """Copy the loading icon to all users of the main image."""
        try:
            tk_img = self.tk_img[handle]
        except KeyError:
            pass  # This isn't being used.
        else:
            # This updates the TK widget directly.
            tk_img.paste(frame)

    @override
    def ui_load_users(self, handle: img.Handle, force: bool) -> None:
        """Load this handle into the widgets using it."""
        tk_img = self._load_tk(handle, force)
        for user in handle._users:
            if isinstance(user, TkUser):
                user.set_img(handle, tk_img)

    @override
    def ui_force_load(self, handle: img.Handle) -> None:
        """Called when this handle is reloading, and should update all its widgets."""
        loading = self._load_tk(
            img.Handle.ico_loading(handle.width, handle.height),
            False,
        )
        for user in handle._users:
            if isinstance(user, TkUser):
                user.set_img(handle, loading)

TK_IMG = TKImages()
