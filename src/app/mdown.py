"""Holds objects which cache the result of parsing markdown data.

Tkinter and WX most efficiently work with different result formats, so this flexibly handles either.
"""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from typing import ClassVar, cast

import attrs

from transtoken import TransToken, TransTokenSource
import utils


__all__ = ['MarkdownData', 'BaseRenderer']


@attrs.define
class MarkdownData:
    """The encapsulated data.

    The package must be passed to allow using images in the document. None should only be
    used for app-defined strings where we know that can't occur.
    """
    # TODO: if dev mode, parse this immediately to check syntax.
    #       If token is untranslated, also parse immediately.
    source: TransToken
    package: utils.ObjectID | None

    _result: object = attrs.field(init=False, default=None)
    _cache_hash: int = attrs.field(init=False, default=-1)

    def __add__(self, other: MarkdownData) -> MarkdownData:
        """Join multiple pieces of data together."""
        return JoinedData([self, other])

    def iter_tokens(self, desc: str) -> Iterator[TransTokenSource]:
        """Iterate tokens contained in this data."""
        yield self.source, desc

    # An empty set of data.
    BLANK: ClassVar[MarkdownData] = cast('MarkdownData', ...)


MarkdownData.BLANK = MarkdownData(TransToken.BLANK, None)  # type: ignore


@attrs.define(init=False)
class JoinedData(MarkdownData):
    """Markdown data composed of concatenated segments."""
    children: list[MarkdownData]

    def __init__(self, children: list[MarkdownData]) -> None:
        self._result = None
        self._cache_hash = -1
        self.children = children

        # Source/package is not relevant, but set it for completeness.
        self.source = TransToken.BLANK
        self.package = None

    def iter_tokens(self, desc: str) -> Iterator[TransTokenSource]:
        """Iterate tokens contained in this data."""
        for child in self.children:
            yield from child.iter_tokens(desc)

    def __add__(self, other: MarkdownData) -> MarkdownData:
        """Join two pieces of data together, more efficiently."""
        if isinstance(other, JoinedData):
            return JoinedData(self.children + other.children)
        return JoinedData([*self.children, other])

    def __radd__(self, other: MarkdownData) -> MarkdownData:
        """Join two pieces of data together, more efficiently."""
        if isinstance(other, JoinedData):
            return JoinedData(other.children + self.children)
        return JoinedData([other, *self.children])


class BaseRenderer[ResultT]:
    """The implementation of the renderer, should only be used by the UI libraries themselves."""
    _result_type: type[ResultT]

    def __init__(self, res_type: type[ResultT]) -> None:
        """This must be given the type results will produce."""
        self._result_type = res_type

    @abstractmethod
    def _convert(self, text: str, package: utils.ObjectID | None) -> ResultT:
        """Should be overridden to do the conversion."""
        raise NotImplementedError

    @abstractmethod
    def _join(self, children: list[ResultT]) -> ResultT:
        """Return the concatenated form of several results."""
        raise NotImplementedError

    # noinspection PyProtectedMember
    def convert(self, data: MarkdownData) -> ResultT:
        """Run a conversion, or return a cached result if unchanged."""
        if isinstance(data, JoinedData):
            # Convert recursively, then join.
            return self._join([self.convert(child) for child in data.children])

        text = str(data.source)
        if hash(text) != data._cache_hash:
            data._result = self._convert(text, data.package)
            data._cache_hash = hash(text)
        assert isinstance(data._result, self._result_type)
        return data._result
