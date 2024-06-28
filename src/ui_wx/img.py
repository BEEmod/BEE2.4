"""Image integrations for WxWidgets."""
from __future__ import annotations

from typing import override
from weakref import ReferenceType as WeakRef, WeakKeyDictionary
import wx
import os

from PIL import Image
from srctools.logger import get_logger
import attrs

from app import img


# Widgets with an image attribute that can be set.
type WxImgWidgets = wx.StaticBitmap | wx.MenuItem

LOGGER = get_logger(__name__)
basic_users: WeakKeyDictionary[WxImgWidgets, BasicUser] = WeakKeyDictionary()


def get_app_icon(path: os.PathLike[str]) -> wx.Bitmap:
    """On non-Windows, retrieve the application icon."""
    with open(path, 'rb') as f:
        img = Image.open(f)
        bitmap = wx.Bitmap(img.width, img.height)
        bitmap.CopyFromBuffer(img)
        return bitmap


class WxUser(img.User):
    """Common methods."""
    def set_img(self, handle: img.Handle, image: wx.Bitmap) -> None:
        """Apply this Wx image to users of it."""


@attrs.define(eq=False, init=False)
class BasicUser(WxUser):
    """A user for basic widgets that contain only one image."""
    widget: WeakRef[WxImgWidgets]
    cur_handle: img.Handle | None

    def __init__(self, widget: WxImgWidgets) -> None:
        self.widget = WeakRef(widget, self.destroyed)
        self.cur_handle = None

    @override
    def set_img(self, handle: img.Handle, image: wx.Bitmap) -> None:
        """Set the image for the basic widget."""
        wid = self.widget()
        if wid is not None:
            self.widget.SetBitmap(image)

    def destroyed(self, ref: WeakRef[WxImgWidgets]) -> None:
        """Handle the widget being destroyed."""
        if self.cur_handle is not None:
            self.cur_handle._decref(self)


class WXImages(img.UIImage):
    """Wx-specific image code."""
    # Maps a handle to the current image used for it.
    wx_img: dict[img.Handle, wx.Bitmap]

    def __init__(self) -> None:
        """Set up the TK code."""
        self.unused_img = {}
        self.wx_img = {}
        self.empty = wx.Bitmap()

    def sync_load(self, handle: img.Handle) -> wx.Bitmap:
        """Load the TK image if required immediately, then return it.

        Only available on BUILTIN type images since they cannot then be
        reloaded.
        """
        handle.force_load()
        return self._load_wx(handle, force=False)

    # noinspection PyProtectedMember
    def apply[Widget: WxImgWidgets](self, widget: Widget, image: img.Handle | None, /) -> Widget:
        """Set the image in a basic widget.

        This tracks the widget, so later reloads will affect the widget.
        If the image is None, it is instead set to an empty bitmap.
        """
        if image is None:
            widget.SetBitmap(self.empty)
            try:
                user = basic_users[widget]
            except KeyError:
                pass
            else:
                if user.cur_handle is not None:
                    user.cur_handle._decref(user)
                    user.cur_handle = None
            return widget
        try:
            user = basic_users[widget]
        except KeyError:
            user = basic_users[widget] = BasicUser(widget)
        else:
            if user.cur_handle is image:
                # Unchanged.
                return widget
            if user.cur_handle is not None:
                user.cur_handle._decref(user)
        image._incref(user)
        user.cur_handle = image
        try:
            widget.SetBitmap(self.wx_img[image])
        except KeyError:  # Need to load.
            loading = image._request_load()
            widget.SetBitmap(self._load_wx(loading, False))
        return widget

    def stats(self) -> str:
        """Return some debugging stats."""
        info = [
            f'{img.stats()}'
            'TK images:\n'
            f' - Used = {len(self.wx_img)}\n'
            f' - Basic = {len(basic_users)}\n'
        ]
        return ''.join(info)

    def _get_img(self, width: int, height: int) -> wx.Bitmap:
        """Construct a new image."""
        return wx.Bitmap(width or 16, height or 16)

    @override
    def ui_clear_handle(self, handle: img.Handle) -> None:
        """Clear cached WX images for this handle."""
        self.wx_img.pop(handle, None)

    def _load_wx(self, handle: img.Handle, force: bool) -> wx.Bitmap:
        """Load the WX image if required, then return it."""
        image = self.wx_img.get(handle)
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
                image = self.wx_img[handle] = wx.Bitmap(res.width or 16, res.height or 16)
            image.CopyFromBuffer(res)
        return image

    @override
    def ui_apply_load(self, handle: img.Handle, frame: Image.Image) -> None:
        """Copy the loading icon to all users of the main image."""
        try:
            wx_img = self.wx_img[handle]
        except KeyError:
            pass  # This isn't being used.
        else:
            # This updates the WX widget directly. TODO: Is this performant?
            wx_img.CopyFromBuffer(frame)

    @override
    def ui_load_users(self, handle: img.Handle, force: bool) -> None:
        """Load this handle into the widgets using it."""
        wx_img = self._load_wx(handle, force)
        for user in handle._users:
            if isinstance(user, WxUser):
                user.set_img(handle, wx_img)

    @override
    def ui_force_load(self, handle: img.Handle) -> None:
        """Called when this handle is reloading, and should update all its widgets."""
        loading = self._load_wx(
            img.Handle.ico_loading(handle.width, handle.height),
            False,
        )
        for user in handle._users:
            if isinstance(user, WxUser):
                user.set_img(handle, loading)


WX_IMG = WXImages()
