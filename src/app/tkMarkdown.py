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

# These tags if present simply add a TK tag.
SIMPLE_TAGS = {
    'u': 'underline',
    'strong': 'bold',
    'em': 'italic',
    # Blockquotes become white-on-black text
    'blockquote': 'invert',
    'li': 'indent',

    # The parser will already split these into their own line,
    # add paragraphs - we just increase font size.
    'h1': 'heading_1',
    'h2': 'heading_2',
    'h3': 'heading_3',
    'h4': 'heading_4',
    'h5': 'heading_5',
    'h6': 'heading_6',
}

UL_START = '\u2022 '
OL_START = '{}. '

LINK_TAG_START = 'link_callback_'
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


def iter_elemtext(
    elem: XMLElement,
    parent_path: Iterable[XMLElement]=(),
) -> Iterator[Tuple[List[XMLElement], Union[str, TAG]]]:
    """Flatten out an elementTree into the text parts.

    Yields path, text tuples. path is a list of the parent elements for the
    text. Text is either the text itself, with '' for < />-style tags, or
    TAG.START/END to match the beginning and end of tag blocks.
    """
    path = list(parent_path) + [elem]

    yield path, TAG.START

    if elem.text is None:
        yield path, ''
    else:
        yield path, elem.text.replace('\n', '')

    for child in elem:
        yield from iter_elemtext(child, path)

    yield path, TAG.END

    # Text after this element..
    # Do not return if we are the root element - "</div>\n"
    if elem.tail is not None and parent_path:
        yield parent_path, elem.tail.replace('\n', '')


def parse_html(element: XMLElement):
    """Translate markdown HTML into TK tags.

    This returns lists of alternating text and tags, matching the arguments for
    Text widgets.
    This also returns a tag: url dict for the embedded hyperlinks.
    """
    ol_nums = []
    links = {}
    link_counter = count(start=1)
    force_return = False

    blocks = []
    cur_text_block = []

    def finish_text_block():
        """Copy the cur_text_block into blocks ready for another type."""
        if cur_text_block:
            blocks.append((BlockTags.TEXT, tuple(cur_text_block)))
            cur_text_block.clear()

    for path, text in iter_elemtext(element, parent_path=[]):
        last = path[-1]

        if last.tag == 'div':
            continue  # This wraps around the entire block..

        # We need to insert a return after <p> or <br>, but only if
        # the next block is empty.
        if force_return:
            force_return = False
            cur_text_block.append('\n')
            cur_text_block.append(())

        # Line breaks at <br> or at the end of <p> blocks.
        # <br> emits a START, '', and END - we only want to output for one
        # of those.
        if last.tag in ('br', 'p') and text is TAG.END:
            cur_text_block.append('\n')
            cur_text_block.append(())
            continue

        # Insert the number or bullet
        if last.tag == 'li' and text is TAG.START:
            list_type = path[-2].tag
            if list_type == 'ul':
                cur_text_block.append(UL_START)
                cur_text_block.append(('list_start', 'indent'))
            elif list_type == 'ol':
                ol_nums[-1] += 1
                cur_text_block.append(OL_START.format(ol_nums[-1]))
                cur_text_block.append(('list_start', 'indent'))

        if last.tag == 'hr' and text == '':
            cur_text_block.extend((
                '\n', (),
                '\n', ('hrule', ),
                '\n', (),
            ))

        if last.tag == 'li' and text is TAG.END:
            cur_text_block.append('\n')
            cur_text_block.append(('indent', ))

        if last.tag == 'ol':
            # Set and reset the counter appropriately..
            if text is TAG.START:
                ol_nums.append(0)
            if text is TAG.END:
                ol_nums.pop()

        if last.tag == 'img' and not text:
            # Add the image - it's own block type.
            finish_text_block()
            blocks.append((BlockTags.IMAGE, last.attrib['src']))

        if isinstance(text, TAG) or not text:
            # Don't output these internal values.
            continue

        tk_tags = set()
        for tag in {elem.tag for elem in path}:
            # Simple tags are things like strong, u - no additional value.
            if tag in SIMPLE_TAGS:
                to_add = SIMPLE_TAGS[tag]
                if isinstance(to_add, str):
                    tk_tags.add(to_add)
                else:
                    tk_tags.update(to_add)
            if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                force_return = True

        # Handle links.
        for elem in path:
            if elem.tag != 'a':
                continue
            try:
                url = elem.attrib['href']
            except KeyError:
                continue  # We don't handle anchor a-tags.
            try:
                url_id = links[url]
            except KeyError:
                url_id = links[url] = LINK_TAG_START + str(next(link_counter))
            tk_tags.add('link')  # For formatting
            tk_tags.add(url_id)  # For the click-callback.

        cur_text_block.append(text)
        cur_text_block.append(tuple(tk_tags))

    # Finish our last block.
    finish_text_block()

    return blocks, links


class TKRenderer(mistletoe.BaseRenderer):
    """Extension needed to extract our list from the tree.
    """
    def __init__(self) -> None:
        super().__init__()

        x = {
            'Strong':         self.render_strong,
            'Emphasis':       self.render_emphasis,
            'InlineCode':     self.render_inline_code,
            'RawText':        self.render_raw_text,
            'Strikethrough':  self.render_strikethrough,
            'Image':          self.render_image,
            'Link':           self.render_link,
            'AutoLink':       self.render_auto_link,
            'EscapeSequence': self.render_escape_sequence,
            'Heading':        self.render_heading,
            'SetextHeading':  self.render_heading,
            'Quote':          self.render_quote,
            'Paragraph':      self.render_paragraph,
            'CodeFence':      self.render_block_code,
            'BlockCode':      self.render_block_code,
            'List':           self.render_list,
            'ListItem':       self.render_list_item,
            'Table':          self.render_table,
            'TableRow':       self.render_table_row,
            'TableCell':      self.render_table_cell,
            'ThematicBreak':  self.render_thematic_break,
            'LineBreak':      self.render_line_break,
            'Document':       self.render_document,
        }

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
        return MarkdownData([
            (BlockTags.TEXT, [TextSegment(text, tags, url)])
        ])

    def render_auto_link(self, token: stok.AutoLink) -> MarkdownData:
        """An automatic link - the child is a single raw token."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child, 'link', url=token.target)

    def render_block_code(self, token: MistleToken) -> MarkdownData:

    def render_document(self, token: btok.Document) -> MarkdownData:
        """Render the outermost document."""
        self.footnotes.update(token.footnotes)
        return self.render_inner(token)

    def render_emphasis(self, token: stok.Emphasis) -> MarkdownData:
        return self._text(token.content, 'italic')

    def render_escape_sequence(self, token: stok.EscapeSequence) -> MarkdownData:
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child.content)

    def render_heading(self, token: btok.Heading) -> MarkdownData:
        return self._with_tag(token.children, f'heading_{token.level}')

    def render_image(self, token: stok.Image) -> MarkdownData:
        return MarkdownData([
            (BlockTags.IMAGE, token.src)
        ])

    def render_inline_code(self, token: stok.InlineCode) -> MarkdownData:
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return self._text(child.content, 'code')

    def render_line_break(self, token: stok.LineBreak) -> MarkdownData:
        return self._text('\n')

    def render_link(self, token: stok.Link) -> MarkdownData:
        return self._with_tag(token.content, url=token.target)

    def render_list(self, token: btok.BlockToken) -> MarkdownData:
        return self.render_inner(token)

    def render_list_item(self, token: MistleToken) -> MarkdownData:

    def render_paragraph(self, token: MistleToken) -> MarkdownData:

    def render_quote(self, token: MistleToken) -> MarkdownData:

    def render_raw_text(self, token: MistleToken) -> MarkdownData:

    def render_strikethrough(self, token: MistleToken) -> MarkdownData:

    def render_strong(self, token: MistleToken) -> MarkdownData:

    def render_table(self, token: MistleToken) -> MarkdownData:

    def render_table_cell(self, token: MistleToken) -> MarkdownData:

    def render_table_row(self, token: MistleToken) -> MarkdownData:

    def render_thematic_break(self, token: MistleToken) -> MarkdownData:

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
