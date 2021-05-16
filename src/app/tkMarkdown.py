"""Parse Markdown and display it in Tkinter widgets.

This produces a stream of values, which are fed into richTextBox to display.
"""
import mistletoe
from mistletoe import block_token as btok
from mistletoe import span_token as stok
import srctools.logger
import urllib.parse

from typing import Optional, Union, Iterable, List, Tuple, NamedTuple, Sequence

import utils
from app.img import Handle as ImgHandle

LOGGER = srctools.logger.get_logger(__name__)
# Mistletoe toke types.
Token = Union[stok.SpanToken, btok.BlockToken]


class TextSegment(NamedTuple):
    """Each section added in text blocks."""
    text: str  # The text to show
    tags: Tuple[str, ...]  # Tags
    url: Optional[str]  # If set, the text should be given this URL as a callback.


class Image(NamedTuple):
    """An image."""
    handle: ImgHandle

# The kinds of data contained in MarkdownData
Block = Union[TextSegment, Image]

_HR = [
    TextSegment('\n', (), None),
    TextSegment('\n', ('hrule', ), None),
    TextSegment('\n', (), None),
]


class MarkdownData:
    """The output of the conversion, a set of tags and link references for callbacks.

    Blocks are a list of data.
    """
    __slots__ = ['blocks']
    blocks: Sequence[Block]  # External users shouldn't modify directly.
    def __init__(
        self,
        blocks: Iterable[Block] = (),
    ) -> None:
        self.blocks = list(blocks)

    def __bool__(self) -> bool:
        """Empty data is false."""
        return bool(self.blocks)

    def copy(self) -> 'MarkdownData':
        """Create and return a duplicate of this object."""
        return MarkdownData(self.blocks)

    @classmethod
    def text(cls, text: str, *tags: str, url: Optional[str] = None) -> 'MarkdownData':
        """Construct data with a single text segment."""
        return cls([TextSegment(text, tags, url)])

    __copy__ = copy


class TKRenderer(mistletoe.BaseRenderer):
    """Extension needed to extract our list from the tree.
    """
    def __init__(self) -> None:
        # The lists we're currently generating.
        # If none it's bulleted, otherwise it's the current count.
        self._list_stack: List[Optional[int]] = []
        self.package: Optional[str] = None
        super().__init__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._list_stack.clear()
        self.package = None

    def render(self, token: btok.BlockToken) -> MarkdownData:
        return super().render(token)

    def render_inner(self, token: Token) -> MarkdownData:
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
        blocks: List[Block] = []
        # Merge together adjacent text segments.
        for child in token.children:
            for data in self.render(child).blocks:
                if isinstance(data, TextSegment) and blocks and isinstance(blocks[-1], TextSegment):
                    last = blocks[-1]
                    if last.tags == data.tags and last.url == data.url:
                        blocks[-1] = TextSegment(last.text + data.text, last.tags, last.url)
                        continue
                blocks.append(data)

        return MarkdownData(blocks)

    def _with_tag(self, token: Token, *tags: str, url: str=None) -> MarkdownData:
        added_tags = set(tags)
        result = self.render_inner(token)
        for i, data in enumerate(result.blocks):
            if isinstance(data, TextSegment):
                result.blocks[i] = TextSegment(data.text, tuple(added_tags.union(data.tags)), url or data.url)
        return result

    def _text(self, text: str, *tags: str, url: str=None) -> MarkdownData:
        """Construct data containing a single text section."""
        return MarkdownData([TextSegment(text, tags, url)])

    def render_auto_link(self, token: stok.AutoLink) -> MarkdownData:
        """An automatic link - the child is a single raw token."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child.content, 'link', url=token.target)

    def render_block_code(self, token: btok.BlockCode) -> MarkdownData:
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child.content, 'codeblock')

    def render_document(self, token: btok.Document) -> MarkdownData:
        """Render the outermost document."""
        self.footnotes.update(token.footnotes)
        result = self.render_inner(token)
        if not result.blocks:
            return result

        # Strip newlines from the start and end.
        first = result.blocks[0]
        if isinstance(first, TextSegment) and first.text.startswith('\n'):
            result.blocks[0] = TextSegment(first.text.lstrip('\n'), first.tags, first.url)

        last = result.blocks[-1]
        if isinstance(last, TextSegment) and last.text.endswith('\n'):
            result.blocks[-1] = TextSegment(last.text.rstrip('\n'), last.tags, last.url)
        return result

    def render_escape_sequence(self, token: stok.EscapeSequence) -> MarkdownData:
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child.content)

    def render_image(self, token: stok.Image) -> MarkdownData:
        """Embed an image into a file."""
        uri = utils.PackagePath.parse(urllib.parse.unquote(token.src), self.package)
        return MarkdownData([Image(ImgHandle.parse_uri(uri))])

    def render_inline_code(self, token: stok.InlineCode) -> MarkdownData:
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child.content, 'code')

    def render_line_break(self, token: stok.LineBreak) -> MarkdownData:
        if token.soft:
            return MarkdownData([])
        else:
            return self._text('\n')

    def render_link(self, token: stok.Link) -> MarkdownData:
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
            prefix = '\N{bullet} '  # Bullet char.
        else:
            prefix = f'{count}. '
            self._list_stack[-1] += 1

        result = join(
            self._text(prefix, 'list_start'),
            self._with_tag(token, 'list'),
        )

        return result

    def render_paragraph(self, token: btok.Paragraph) -> MarkdownData:
        if self._list_stack:  # Collapse together.
            return join(self.render_inner(token), self._text('\n'))
        else:
            return join(self._text('\n'), self.render_inner(token), self._text('\n'))

    def render_raw_text(self, token: stok.RawText) -> MarkdownData:
        return self._text(token.content)

    def render_table(self, token: btok.Table) -> MarkdownData:
        """We don't support tables."""
        # TODO?
        return self._text('<Tables not supported>')

    def render_table_cell(self, token: btok.TableCell) -> MarkdownData:
        return self._text('<Tables not supported>')

    def render_table_row(self, token: btok.TableRow) -> MarkdownData:
        return self._text('<Tables not supported>')

    def render_thematic_break(self, token: btok.ThematicBreak) -> MarkdownData:
        """Render a horizontal rule."""
        return MarkdownData(_HR.copy())

    def render_heading(self, token: btok.Heading) -> MarkdownData:
        return self._with_tag(token, f'heading_{token.level}')

    def render_quote(self, token: btok.Quote) -> MarkdownData:
        return self._with_tag(token, 'indent')

    def render_strikethrough(self, token: stok.Strikethrough) -> MarkdownData:
        return self._with_tag(token, 'strikethrough')

    def render_strong(self, token: stok.Strong) -> MarkdownData:
        return self._with_tag(token, 'bold')

    def render_emphasis(self, token: stok.Emphasis) -> MarkdownData:
        return self._with_tag(token, 'italic')

_RENDERER = TKRenderer()


def convert(text: str, package: Optional[str]) -> MarkdownData:
    """Convert markdown syntax into data ready to be passed to richTextBox.

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

    blocks: List[Block] = []

    for child in args:
        for data in child.blocks:
            if isinstance(data, TextSegment) and blocks and isinstance(blocks[-1], TextSegment):
                if blocks[-1].tags == data.tags and blocks[-1].url == data.url:
                    blocks[-1] = TextSegment(blocks[-1].text + data.text, blocks[-1].tags, blocks[-1].url)
                    continue
            blocks.append(data)

    return MarkdownData(blocks)
