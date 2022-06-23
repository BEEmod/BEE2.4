"""Parse Markdown and display it in Tkinter widgets.

This produces a stream of values, which are fed into richTextBox to display.
"""
from __future__ import annotations
from typing import Type, Sequence
import urllib.parse
import types
import enum

import attrs
from mistletoe import block_token as btok, span_token as stok
import mistletoe
import srctools.logger

from app.img import Handle as ImgHandle
import utils

LOGGER = srctools.logger.get_logger(__name__)


class TextTag(str, enum.Enum):
    """Tags used in text segments."""
    H1 = 'heading_1'
    H2 = 'heading_2'
    H3 = 'heading_3'
    H4 = 'heading_4'
    H5 = 'heading_5'
    H6 = 'heading_6'

    UNDERLINE = 'underline'
    BOLD = 'bold'
    ITALIC = 'italic'
    CODE = 'code'
    STRIKETHROUGH = 'strikethrough'
    INVERT = 'invert'
    INDENT = 'indent'
    LIST_START = 'list_start'
    LIST = 'list'
    HRULE = 'hrule'
    LINK = 'link'

    HEADINGS: dict[int, TextTag]

# Assign outside class, so it's not an enum member.
TextTag.HEADINGS = {
    int(tag.name[-1]): tag
    for tag in TextTag
    if tag.value.startswith('heading_')
}


class Block:
    """The kinds of data contained in MarkdownData."""


@attrs.frozen
class TextSegment(Block):
    """Each section added in text blocks."""
    text: str  # The text to show
    tags: tuple[TextTag, ...]  # Tags
    url: str | None  # If set, the text should be given this URL as a callback.


@attrs.define
class Image(Block):
    """An image."""
    handle: ImgHandle


_HR = [
    TextSegment('\n', (), None),
    TextSegment('\n', ('hrule', ), None),
    TextSegment('\n', (), None),
]
# Unicode bullet characters, in order of use.
BULLETS = [
    '\N{bullet} ',  # Regular bullet
    '\u25E6 ',  # White/hollow bullet
    '- ',  # Dash
    '\u2023 ',  # Triangular bullet
]


@attrs.define
class MarkdownData:
    """The output of the conversion, a set of tags and link references for callbacks.

    Blocks are a list of data.
    """
    # External users shouldn't modify directly, so make it readonly.
    blocks: Sequence[Block] = attrs.field(factory=[].copy)

    def __bool__(self) -> bool:
        """Empty data is false."""
        return bool(self.blocks)

    def copy(self) -> MarkdownData:
        """Create and return a duplicate of this object."""
        return MarkdownData(list(self.blocks))

    @classmethod
    def text(cls, text: str, *tags: TextTag, url: str | None = None) -> MarkdownData:
        """Construct data with a single text segment."""
        return cls([TextSegment(text, tags, url)])

    __copy__ = copy


class TKRenderer(mistletoe.BaseRenderer):
    """Extension needed to extract our list from the tree.
    """
    def __init__(self) -> None:
        # The lists we're currently generating.
        # If none it's bulleted, otherwise it's the current count.
        self._list_stack: list[int | None] = []
        self.package: str | None = None
        super().__init__()

    def __exit__(self, exc_type: Type[BaseException], exc_val: BaseException, exc_tb: types.TracebackType) -> None:
        self._list_stack.clear()
        self.package = None

    def render(self, token: btok.BlockToken) -> MarkdownData:
        """Indicate the correct types for this."""
        return super().render(token)

    def render_inner(self, token: stok.SpanToken | btok.BlockToken) -> MarkdownData:
        """
        Recursively renders child tokens. Joins the rendered
        strings with no space in between.

        If newlines / spaces are needed between tokens, add them
        in their respective templates, or override this function
        in the renderer subclass, so that whitespace won't seem to
        appear magically for anyone reading your program.

        Arguments:
            token: a branch node who has children attribute.
        """
        blocks: list[Block] = []
        # Merge together adjacent text segments.
        for child in token.children:
            for data in self.render(child).blocks:
                if isinstance(data, TextSegment) and blocks:
                    last = blocks[-1]
                    if isinstance(last, TextSegment):
                        if last.tags == data.tags and last.url == data.url:
                            blocks[-1] = TextSegment(last.text + data.text, last.tags, last.url)
                            continue
                blocks.append(data)

        return MarkdownData(blocks)

    def _with_tag(self, token: stok.SpanToken | btok.BlockToken, *tags: TextTag, url: str=None) -> MarkdownData:
        added_tags = set(tags)
        result = self.render_inner(token)
        for i, data in enumerate(result.blocks):
            if isinstance(data, TextSegment):
                new_seg = TextSegment(data.text, tuple(added_tags.union(data.tags)), url or data.url)
                result.blocks[i] = new_seg  # type: ignore  # Readonly to users.
        return result

    def render_auto_link(self, token: stok.AutoLink) -> MarkdownData:
        """An automatic link - the child is a single raw token."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return MarkdownData.text(child.content, TextTag.LINK, url=token.target)

    def render_block_code(self, token: btok.BlockCode) -> MarkdownData:
        """Render full code blocks."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        # TODO: Code block.
        return MarkdownData.text(child.content, TextTag.CODE)

    def render_document(self, token: btok.Document) -> MarkdownData:
        """Render the outermost document."""
        self.footnotes.update(token.footnotes)
        result = self.render_inner(token)
        if not result.blocks:
            return result

        return result

    def render_escape_sequence(self, token: stok.EscapeSequence) -> MarkdownData:
        """Render backslash escaped text."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return MarkdownData.text(child.content)

    def render_image(self, token: stok.Image) -> MarkdownData:
        """Embed an image into a file."""
        uri = utils.PackagePath.parse(urllib.parse.unquote(token.src), self.package)
        return MarkdownData([Image(ImgHandle.parse_uri(uri))])

    def render_inline_code(self, token: stok.InlineCode) -> MarkdownData:
        """Render inline code segments."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return MarkdownData.text(child.content, TextTag.CODE)

    def render_line_break(self, token: stok.LineBreak) -> MarkdownData:
        if token.soft:
            return MarkdownData([])
        else:
            return MarkdownData.text('\n')

    def render_link(self, token: stok.Link) -> MarkdownData:
        """Render links."""
        return self._with_tag(token, url=token.target)

    def render_list(self, token: btok.List) -> MarkdownData:
        """The wrapping around a list, specifying the type and start number."""
        self._list_stack.append(token.start)
        try:
            return self.render_inner(token)
        finally:
            self._list_stack.pop()

    def render_list_item(self, token: btok.ListItem) -> MarkdownData:
        """The individual items in a list."""
        count = self._list_stack[-1]
        if count is None:
            # Bullet list, make nested ones use different characters.
            nesting = self._list_stack.count(None) - 1
            prefix = BULLETS[nesting % len(BULLETS)]
        else:
            prefix = f'{count}. '
            self._list_stack[-1] += 1

        result = join(
            MarkdownData.text(prefix, TextTag.LIST_START),
            self._with_tag(token, TextTag.LIST),
        )

        return result

    def render_paragraph(self, token: btok.Paragraph) -> MarkdownData:
        if self._list_stack:  # Collapse together.
            return join(self.render_inner(token), MarkdownData.text('\n'))
        else:
            return join(MarkdownData.text('\n'), self.render_inner(token), MarkdownData.text('\n'))

    def render_raw_text(self, token: stok.RawText) -> MarkdownData:
        return MarkdownData.text(token.content)

    def render_table(self, token: btok.Table) -> MarkdownData:
        """We don't support tables."""
        # TODO?
        return MarkdownData.text('<Tables not supported>')

    def render_table_cell(self, token: btok.TableCell) -> MarkdownData:
        """Unimplemented table cells."""
        return MarkdownData.text('<Tables not supported>')

    def render_table_row(self, token: btok.TableRow) -> MarkdownData:
        """Unimplemented table rows."""
        return MarkdownData.text('<Tables not supported>')

    def render_thematic_break(self, token: btok.ThematicBreak) -> MarkdownData:
        """Render a horizontal rule."""
        return MarkdownData(_HR.copy())

    def render_heading(self, token: btok.Heading) -> MarkdownData:
        """Render a level 1-6 heading."""
        return self._with_tag(token, TextTag.HEADINGS[token.level])

    def render_quote(self, token: btok.Quote) -> MarkdownData:
        """Render blockquotes."""
        return self._with_tag(token, TextTag.INDENT)

    def render_strikethrough(self, token: stok.Strikethrough) -> MarkdownData:
        """Render strikethroughed text."""
        return self._with_tag(token, TextTag.STRIKETHROUGH)

    def render_strong(self, token: stok.Strong) -> MarkdownData:
        """Render <strong> tags, with bold fonts."""
        return self._with_tag(token, TextTag.BOLD)

    def render_emphasis(self, token: stok.Emphasis) -> MarkdownData:
        """Render <em> tags, with italic fonts."""
        return self._with_tag(token, TextTag.ITALIC)

_RENDERER = TKRenderer()


def convert(text: str, package: str | None) -> MarkdownData:
    """Convert Markdown syntax into data ready to be passed to richTextBox.

    The package must be passed to allow using images in the document.
    """
    with _RENDERER:
        _RENDERER.package = package
        return _RENDERER.render(mistletoe.Document(text))


def join(*args: MarkdownData) -> MarkdownData:
    """Join several text blocks together.

    This merges together blocks, reassigning link callbacks as needed.
    """
    if len(args) == 1:
        # We only have one block, just copy and return.
        return MarkdownData(args[0].blocks)

    blocks: list[Block] = []

    for child in args:
        for data in child.blocks:
            # We also want to combine text segments next to each other.
            if isinstance(data, TextSegment) and blocks:
                last = blocks[-1]
                if isinstance(last, TextSegment) and last.tags == data.tags and last.url == data.url:
                    blocks[-1] = TextSegment(last.text + data.text, last.tags, last.url)
                    continue
            blocks.append(data)

    return MarkdownData(blocks)
