"""Handles displaying Markdown documents, including images."""
from typing_extensions import deprecated
from typing import Any

from srctools.logger import get_logger
from wx.html import HtmlWindow
import mistletoe
import wx

from app import mdown, img
import utils
from utils import PackagePath
from .img import ImageFSHandler


__all__ = ['RichWindow']


class _MarkdownConverter(mdown.BaseRenderer[str]):
    def _convert(self, text: str, package: utils.ObjectID | None) -> str:
        """Convert to HTML."""
        return mistletoe.markdown(text)

    def _join(self, children: list[str]) -> str:
        """Join two fragments together."""
        return '<br /><br />\n'.join(children)


LOGGER = get_logger(__name__)
MARKDOWN = _MarkdownConverter(str)


class RichWindow(HtmlWindow):
    """Subclass of HTML windows."""
    def __init__(self, parent: wx.Window, id: int = wx.ID_ANY, **kwargs: Any) -> None:
        super().__init__(parent, id, **kwargs)
        self.img_handler = ImageFSHandler(self._refresh_markdown)
        self.fsys = wx.FileSystem()
        self.fsys.AddHandler(self.img_handler)
        self.Parser.SetFS(self.fsys)
        self._markdown = ""
        self.package: utils.SpecialID | None = utils.ID_NONE

    @deprecated("Use set_markdown() instead.")
    def SetPage(self, source: str) -> bool:
        """Use set_markdown instead."""
        raise ValueError("Use set_markdown()!")

    def set_markdown(self, source: mdown.MarkdownData) -> None:
        """Set the page used for display."""
        self.img_handler.clear()
        self._markdown = MARKDOWN.convert(source)
        self.package = source.package
        super().SetPage(self._markdown)

    def _refresh_markdown(self) -> None:
        """Reload the markdown, so images update."""
        super().SetPage(self._markdown)

    def OnOpeningURL(
        self, url_type: wx.html.HtmlURLType, url: str, /
    ) -> tuple[wx.html.HtmlOpeningStatus, str]:
        """Filter URLs being opened."""
        match url_type:
            case wx.html.HTML_URL_IMAGE:
                LOGGER.debug('Opening image URL {}', url)
                if self.img_handler.is_valid(url):  # Already converted, pass through.
                    return wx.html.HTML_OPEN, url
                try:
                    handle = img.Handle.parse_uri(PackagePath.parse(url, self.package or utils.ID_NONE))
                except ValueError as exc:
                    LOGGER.warning('Could not parse image URL: "{}"', url, exc_info=exc)
                    return wx.html.HTML_BLOCK, url
                else:
                    fname = self.img_handler.add(handle, self)
                    return wx.html.HTML_REDIRECT, fname
            case wx.html.HTML_URL_PAGE:
                LOGGER.debug('Opening new page URL {}', url)
                # Don't allow swapping pages, etc.
                return wx.html.HTML_BLOCK, ''
            case wx.html.HTML_URL_OTHER:
                LOGGER.debug('Opening "other" URL {}', url)
                # What triggers this?
                return wx.html.HTML_BLOCK, ''
            case unknown:
                raise ValueError(f"Unknown URL type {unknown}, url={url!r}")
