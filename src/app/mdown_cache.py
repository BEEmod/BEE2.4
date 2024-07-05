"""Holds objects which cache the result of parsing markdown data.

Tkinter and WX most efficiently work with different result formats, so this flexibly handles either.
"""
from typing import Protocol

import attrs
import trio

from transtoken import TransToken
import utils


__all__ = ['Converter', 'MarkdownData', 'BaseRenderer']


@attrs.define
class MarkdownData:
    """The encapsulated data."""
    source: TransToken
    package: utils.ObjectID | None
    _result: object = attrs.field(init=False, default=None)
    _cache_hash: int = attrs.field(init=False, default=-1)


class Converter(Protocol):
    """Function that can be called to convert a TransToken."""
    def __call__(self, text: TransToken, /, package: utils.ObjectID | None) -> MarkdownData:
        """Convert Markdown syntax into data ready to be passed to a textbox.

        The package must be passed to allow using images in the document. None should only be
        used for app-defined strings where we know that can't occur.
        """


class BaseRenderer[ResultT]:
    """The implementation of the renderer, should only be used by the UI libraries themselves."""
    _result_type: type[ResultT]

    def __init__(self, res_type: type[ResultT], nursery: trio.Nursery, ) -> None:
        """This must be created with a nursery to render in and given the type results will produce."""
        self.nursery = nursery
        self._result_type = res_type

    def _convert(self, text: str) -> ResultT:
        """Should be overridden to do the conversion."""
        raise NotImplementedError

    def __call__(self, text: TransToken, /, package: utils.ObjectID | None) -> MarkdownData:
        """Produce encapsulated markdown data.

        The package must be passed to allow using images in the document. None should only be
        used for app-defined strings where we know that can't occur.
        """
        # TODO: if dev mode, parse this immediately to check syntax. If token is untranslated,
        # also parse immediately.
        return MarkdownData(text, package)

    # noinspection PyProtectedMember
    async def convert(self, data: MarkdownData) -> ResultT:
        """Run a conversion, or return a cached result if unchanged."""
        text = str(data.source)
        if hash(text) != data._cache_hash:
            data._result = self._convert(text)
            data._cache_hash = hash(text)
        assert isinstance(data._result, self._result_type)
        return data._result
