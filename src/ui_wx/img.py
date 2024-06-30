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
type WxImgWidgets = wx.StaticBitmap | wx.MenuItem | wx.BitmapButton

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
    def _set_img(self, handle: img.Handle, image: wx.Bitmap) -> None:
        """Apply this Wx image to users of it."""


# noinspection PyProtectedMember
@attrs.define(eq=False, init=False)
class BasicUser(WxUser):
    """A user for basic widgets that contain only one image."""
    widget: WeakRef[WxImgWidgets]
    cur_handle: img.Handle | None

    def __init__(self, widget: WxImgWidgets) -> None:
        self.widget = WeakRef(widget, self.destroyed)
        self.cur_handle = None

    @override
    def _set_img(self, handle: img.Handle, image: wx.Bitmap) -> None:
        """Set the image for the basic widget."""
        if (wid := self.widget()) is not None:
            wid.SetBitmap(image)

    def destroyed(self, ref: WeakRef[WxImgWidgets]) -> None:
        """Handle the widget being destroyed."""
        if self.cur_handle is not None:
            self.cur_handle._decref(self)


class WXImages(img.UIImage):
    """Wx-specific image code."""
    # Maps a handle to the current image used for it.
    wx_img: dict[img.Handle, wx.Bitmap]

    def __init__(self) -> None:
        """Set up the WX code."""
        self.wx_img = {}
        self.empty = wx.Bitmap()

    def sync_load(self, handle: img.Handle) -> wx.Bitmap:
        """Load the WX image if required immediately, then return it.

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
            'WX images:\n'
            f' - Used = {len(self.wx_img)}\n'
            f' - Basic = {len(basic_users)}\n'
        ]
        return ''.join(info)

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
            image.CopyFromBuffer(res.tobytes())
        return image

    @override
    def ui_apply_load(self, handle: img.ImgLoading, frame_handle: img.ImgLoading, frame_pil: Image.Image) -> None:
        """Copy the loading icon to all users of the main image."""
        img = self._load_wx(frame_handle, False)
        for sub_handle in handle.load_targs:
            for user in sub_handle._users:
                if isinstance(user, WxUser):
                    user._set_img(frame_handle, img)

    @override
    def ui_load_users(self, handle: img.Handle, force: bool) -> None:
        """Load this handle into the widgets using it."""
        wx_img = self._load_wx(handle, force)
        for user in handle._users:
            if isinstance(user, WxUser):
                user._set_img(handle, wx_img)

    @override
    def ui_force_load(self, handle: img.Handle) -> None:
        """Called when this handle is reloading, and should update all its widgets."""
        loading = self._load_wx(
            img.Handle.ico_loading(handle.width, handle.height),
            False,
        )
        for user in handle._users:
            if isinstance(user, WxUser):
                user._set_img(handle, loading)


WX_IMG = WXImages()
