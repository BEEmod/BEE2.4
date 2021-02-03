"""Parse Markdown and display it in Tkinter widgets.

This produces a stream of values, which are fed into richTextBox to display.
"""
from enum import Enum
from itertools import count

import mistletoe
from mistletoe import block_token as btok
from mistletoe import span_token as stok
import srctools.logger

from typing import (
    Iterable, Iterator, Union, List, Tuple, Optional, Any, Dict,
    NamedTuple, Set,
)


LOGGER = srctools.logger.get_logger(__name__)
Token = Union[stok.SpanToken, btok.BlockToken]


class TAG(Enum):
    """Marker used to indicate when tags start/end."""
    START = 0
    END = 1


class BlockTags(Enum):
    """The various kinds of blocks that can happen."""
    # Paragraphs of regular text or other stuff we can insert.
    # The data is a list of TextSegment.
    TEXT = 'text'
    # An image, data is the file path.
    IMAGE = 'image'


class TextSegment(NamedTuple):
    """Each section added in text blocks."""
    text: str  # The text to show
    tags: Tuple[str, ...]  # Tags
    url: Optional[str]  # If set, the text should be given this URL as a callback.



UL_START = '\u2022 '
OL_START = '{}. '
_HR = [
    TextSegment('\n', (), None),
    TextSegment('\n', ('hrule', ), None),
    TextSegment('\n', (), None),
]


class MarkdownData:
    """The output of the conversion, a set of tags and link references for callbacks.

    Blocks are a list of two-tuples - each is a Block type, and data for it.
    """
    __slots__ = ['blocks']
    def __init__(
        self,
        blocks: Iterable[Tuple[BlockTags, Union[List[TextSegment], str]]] = (),
    ) -> None:
        self.blocks = list(blocks)

    def __bool__(self) -> bool:
        """Empty data is false."""
        return bool(self.blocks)

    def copy(self) -> 'MarkdownData':
        """Create and return a duplicate of this object."""
        return MarkdownData(self.blocks)

    __copy__ = copy


class TKRenderer(mistletoe.BaseRenderer):
    """Extension needed to extract our list from the tree.
    """
    def __init__(self) -> None:
        # The lists we're currently generating.
        # If none it's bulleted, otherwise it's the current count.
        self._list_stack: List[Optional[int]] = []
        super().__init__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._list_stack.clear()

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
        blocks: List[Tuple[BlockTags, Union[Tuple[TextSegment, ...], str]]] = []
        # Merge together adjacent text blocks.
        last_text: Optional[List[TextSegment]] = None
        for child in token.children:
            for block_type, block_data in self.render(child).blocks:
                if last_text is not None and block_type is BlockTags.TEXT:
                    last_text.extend(block_data)
                    continue
                blocks.append((block_type, block_data))
                if block_type is BlockTags.TEXT:
                    last_text = block_data
                else:
                    last_text = None

        return MarkdownData(blocks)

    def _with_tag(self, token: Token, *tags: str, url: str=None) -> MarkdownData:
        added_tags = set(tags)
        data = self.render_inner(token)
        for block_type, block_data in data.blocks:
            if block_type is BlockTags.TEXT:
                block_data[:] = [
                    TextSegment(seg.text, tuple(added_tags.union(seg.tags)), url or seg.url)
                    for seg in block_data
                ]
        return data

    def _text(self, text: str, *tags: str, url: str=None) -> MarkdownData:
        """Construct data containing a single text section."""
        return MarkdownData([
            (BlockTags.TEXT, [TextSegment(text, tags, url)])
        ])

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
        return self.render_inner(token)

    def render_escape_sequence(self, token: stok.EscapeSequence) -> MarkdownData:
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child.content)

    def render_image(self, token: stok.Image) -> MarkdownData:
        return MarkdownData([
            (BlockTags.IMAGE, token.src)
        ])

    def render_inline_code(self, token: stok.InlineCode) -> MarkdownData:
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child.content, 'code')

    def render_line_break(self, token: stok.LineBreak) -> MarkdownData:
        return self._text('' if token.soft else '\n')

    def render_link(self, token: stok.Link) -> MarkdownData:
        return self._with_tag(token, url=token.target)

    def render_list(self, token: btok.List) -> MarkdownData:
        self._list_stack.append(token.start)
        try:
            return self._with_tag(token, 'indent')
        finally:
            self._list_stack.pop()

    def render_list_item(self, token: btok.ListItem) -> MarkdownData:
        count = self._list_stack[-1]
        if count is None:
            prefix = UL_START
        else:
            prefix = OL_START.format(count)
            self._list_stack[-1] += 1

        result = join(self._text(prefix), self.render_inner(token))
        # The content is likely a paragraph, strip the extra line break.
        if result.blocks and result.blocks[-1][0] is BlockTags.TEXT:
            last_segs = result.blocks[-1][1]
            if last_segs and last_segs[-1].text.endswith('\n\n'):
                seg = last_segs[-1]
                last_segs[-1] = TextSegment(seg.text[:-1], seg.tags, seg.url)
        return result

    def render_paragraph(self, token: btok.Paragraph) -> MarkdownData:
        return join(self.render_inner(token), self._text('\n\n'))

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
        return MarkdownData([(BlockTags.TEXT, _HR.copy())])

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


def convert(text: str) -> MarkdownData:
    """Convert markdown syntax into data ready to be passed to richTextBox."""
    with _RENDERER:
        return _RENDERER.render(mistletoe.Document(text))


def join(*args: MarkdownData) -> MarkdownData:
    """Join several text blocks together.

    This merges together blocks, reassigning link callbacks as needed.
    """
    if len(args) == 1:
        # We only have one block, just copy and return.
        return MarkdownData(args[0].blocks.copy())

    blocks: List[Tuple[BlockTags, Union[List[TextSegment, str]]]] = []
    last_text: Optional[List[TextSegment]] = None

    for child in args:
        for block_type, block_data in child.blocks:
            if last_text is not None and block_type is BlockTags.TEXT:
                last_text.extend(block_data)
                continue
            blocks.append((block_type, block_data))
            if block_type is BlockTags.TEXT:
                last_text = block_data
            else:
                last_text = None

    return MarkdownData(blocks)
