"""Parse Markdown and display it in Tkinter widgets."""
from __future__ import annotations
from typing import Never, Final, cast
from tkinter.font import Font as tkFont, nametofont
from tkinter.messagebox import askokcancel
import tkinter

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar
import urllib.parse
import itertools
import enum
import webbrowser

from mistletoe import block_token as btok, span_token as stok, base_renderer
from mistletoe.token import Token
import mistletoe
import attrs
import srctools.logger

from app import tkMarkdown
from app.img import Handle as ImgHandle
from transtoken import TransToken, TransTokenSource
from ui_tk.tk_tools import Cursors
from ui_tk.img import TK_IMG
import utils

LOGGER = srctools.logger.get_logger(__name__)
TRANS_WEBBROWSER = TransToken.ui('Open "{url}" in the default browser?')


def iter_firstlast[T](iterable: Iterable[T]) -> Iterator[tuple[bool, T, bool]]:
    """Iterate over anything, tracking if the value is the first or last one."""
    it = iter(iterable)
    try:
        first = next(it)
    except StopIteration:
        return  # Empty.

    try:
        prev = next(it)
    except StopIteration:
        # Only one, special case.
        yield True, first, True
        return
    # We now know there's at least two values,
    yield True, first, False

    while True:
        try:
            current = next(it)
        except StopIteration:
            yield False, prev, True
            break
        yield False, prev, False
        prev = current


class TextTag(enum.StrEnum):
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
    IMAGE = 'image'

    def __str__(self) -> str:
        """Pass to tkinter as the value."""
        return self.value


TAG_HEADINGS: Mapping[int, TextTag] = {
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
    tags: tuple[TextTag, ...] = ()  # Tags
    url: str | None = None  # If set, the text should be given this URL as a callback.


@attrs.define
class Image(Block):
    """An image."""
    handle: ImgHandle


_HR = [
    TextSegment('\n', (), None),
    TextSegment('\n', (TextTag.HRULE, ), None),
    TextSegment('\n', (), None),
]
# Unicode bullet characters, in order of use.
BULLETS = [
    '\N{bullet} ',  # Regular bullet
    '\u25E6 ',  # White/hollow bullet
    '- ',  # Dash
    '\u2023 ',  # Triangular bullet
]


class MarkdownData:
    """Protocol for objects holding Markdown data."""
    def __iter__(self) -> Iterator[Block]:
        return iter(())

    def __bool__(self) -> bool:
        """Check if this is non-empty."""
        return False

    @staticmethod
    def text(text: str, *tags: TextTag, url: str | None = None) -> SingleMarkdown:
        """Construct data with a single text segment."""
        return SingleMarkdown([TextSegment(text, tags, url)])

    # An empty set of data.
    BLANK: Final[MarkdownData] = cast('MarkdownData', ...)


MarkdownData.BLANK = MarkdownData()  # type: ignore


@attrs.define
class TranslatedMarkdown(MarkdownData):
    """Markdown data parsed out of translated sources."""
    source: TransToken
    package: utils.ObjectID | None
    _blocks: Sequence[Block] = attrs.Factory(list)
    _cache_hash: int = -1

    def __bool__(self) -> bool:
        """Check if this is non-empty."""
        return bool(self.source)

    def __iter__(self) -> Iterator[Block]:
        """Convert if necessary, then return the blocks."""
        text = str(self.source)
        if hash(text) != self._cache_hash:
            self._blocks = list(_convert(text, self.package))
            self._cache_hash = hash(text)
        return iter(self._blocks)


@attrs.define
class SingleMarkdown(MarkdownData):
    """The output of the conversion, a set of tags and link references for callbacks.

    Blocks are a list of data.
    """
    # External users shouldn't modify directly, so make it readonly.
    blocks: Sequence[Block] = attrs.field(factory=[].copy)

    def __iter__(self) -> Iterator[Block]:
        return iter(self.blocks)

    def __bool__(self) -> bool:
        """Empty data is false."""
        return bool(self.blocks)


@attrs.define
class JoinedMarkdown(MarkdownData):
    """Multiple blocks of data which has been joined together."""
    children: list[MarkdownData]

    def __iter__(self) -> Iterator[Block]:
        """Recursively iterate children."""
        return itertools.chain.from_iterable(self.children)


@attrs.define
class RenderState:
    """The data needed to convert tokens.

    Since the TKRenderer is shared, we need this to prevent storing state on that.
    """
    package: utils.ObjectID | None
    # The lists we're currently generating.
    # If none it's bulleted, otherwise it's the current count.
    list_stack: list[int | None] = attrs.Factory(list)


no_state = RenderState(None)
state = ContextVar('tk_markdown_state', default=no_state)

if not hasattr(base_renderer.BaseRenderer, '__class_getitem__'):
    # Patch in generic support.
    base_renderer.BaseRenderer.__class_getitem__ = lambda item: base_renderer.BaseRenderer  # type: ignore


class TKRenderer(base_renderer.BaseRenderer[SingleMarkdown]):
    """Extension needed to extract our list from the tree.
    """
    def render(self, token: Token) -> SingleMarkdown:
        """Check that the state has been fetched."""
        assert state.get() is not no_state
        result = super().render(token)
        assert isinstance(result, SingleMarkdown)
        return result

    def render_inner(self, token: Token) -> SingleMarkdown:
        """Recursively renders child tokens.

        We merge together adjacient segments, to tidy up the block list.
        """
        blocks: list[Block] = []
        if not hasattr(token, 'children'):
            result = super().render_inner(token)
            assert isinstance(result, SingleMarkdown)
            return result
        child: Token

        # Merge together adjacent text segments
        for child in token.children:
            for data in self.render(child):
                if isinstance(data, TextSegment) and blocks:
                    last = blocks[-1]
                    if isinstance(last, TextSegment):
                        if last.tags == data.tags and last.url == data.url:
                            blocks[-1] = TextSegment(last.text + data.text, last.tags, last.url)
                            continue
                blocks.append(data)

        return SingleMarkdown(blocks)

    def _with_tag(
        self,
        token: stok.SpanToken | btok.BlockToken,
        *tags: TextTag,
        url: str | None = None,
    ) -> SingleMarkdown:
        added_tags = set(tags)
        result = self.render_inner(token)
        for i, data in enumerate(result):
            if isinstance(data, TextSegment):
                new_seg = TextSegment(data.text, tuple(added_tags.union(data.tags)), url or data.url)
                result.blocks[i] = new_seg  # type: ignore  # Readonly to users.
        return result

    def render_auto_link(self, token: stok.AutoLink) -> SingleMarkdown:
        """An automatic link - the child is a single raw token."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return MarkdownData.text(child.content, TextTag.LINK, url=token.target)

    def render_block_code(self, token: btok.BlockCode) -> SingleMarkdown:
        """Render full code blocks."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        # TODO: Code block.
        return MarkdownData.text(child.content, TextTag.CODE)

    def render_document(self, token: btok.Document) -> SingleMarkdown:
        """Render the outermost document."""
        self.footnotes.update(token.footnotes)
        return self.render_inner(token)

    def render_escape_sequence(self, token: stok.EscapeSequence) -> SingleMarkdown:
        """Render backslash escaped text."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return SingleMarkdown.text(child.content)

    def render_image(self, token: stok.Image) -> SingleMarkdown:
        """Embed an image into a file."""
        package = state.get().package
        if package is None:
            raise ValueError("Image used, but no package supplied!")
        uri = utils.PackagePath.parse(urllib.parse.unquote(token.src), package)
        return SingleMarkdown([Image(ImgHandle.parse_uri(uri))])

    def render_inline_code(self, token: stok.InlineCode) -> SingleMarkdown:
        """Render inline code segments."""
        [child] = token.children
        assert isinstance(child, stok.RawText)
        return MarkdownData.text(child.content, TextTag.CODE)

    def render_line_break(self, token: stok.LineBreak) -> SingleMarkdown:
        """Render a newline."""
        if token.soft:
            return SingleMarkdown([])
        else:
            return MarkdownData.text('\n')

    def render_link(self, token: stok.Link) -> SingleMarkdown:
        """Render links."""
        return self._with_tag(token, url=token.target)

    def render_list(self, token: btok.List) -> SingleMarkdown:
        """The wrapping around a list, specifying the type and start number."""
        stack = state.get().list_stack
        stack.append(token.start)
        try:
            return self.render_inner(token)
        finally:
            stack.pop()

    def render_list_item(self, token: btok.ListItem) -> SingleMarkdown:
        """The individual items in a list."""
        stack = state.get().list_stack
        count = stack[-1]
        if count is None:
            # Bullet list, make nested ones use different characters.
            nesting = stack.count(None) - 1
            prefix = BULLETS[nesting % len(BULLETS)]
        else:
            prefix = f'{count}. '
            stack[-1] = count + 1

        return _merge(
            MarkdownData.text(prefix, TextTag.LIST_START),
            self._with_tag(token, TextTag.LIST),
        )

    def render_paragraph(self, token: btok.Paragraph) -> SingleMarkdown:
        """Render a text paragraph."""
        if state.get().list_stack:  # Collapse together.
            return _merge(self.render_inner(token), MarkdownData.text('\n'))
        else:
            return _merge(MarkdownData.text('\n'), self.render_inner(token), MarkdownData.text('\n'))

    def render_raw_text(self, token: stok.RawText) -> SingleMarkdown:
        """Render raw text."""
        return MarkdownData.text(token.content)

    def render_table(self, token: btok.Table) -> SingleMarkdown:
        """We don't support tables."""
        # TODO?
        return MarkdownData.text('<Tables not supported>')

    def render_table_cell(self, token: btok.TableCell) -> SingleMarkdown:
        """Unimplemented table cells."""
        return MarkdownData.text('<Tables not supported>')

    def render_table_row(self, token: btok.TableRow) -> SingleMarkdown:
        """Unimplemented table rows."""
        return MarkdownData.text('<Tables not supported>')

    def render_thematic_break(self, token: btok.ThematicBreak) -> SingleMarkdown:
        """Render a horizontal rule."""
        return SingleMarkdown(_HR.copy())

    def render_heading(self, token: btok.Heading) -> SingleMarkdown:
        """Render a level 1-6 heading."""
        return self._with_tag(token, TAG_HEADINGS[token.level])

    def render_quote(self, token: btok.Quote) -> SingleMarkdown:
        """Render blockquotes."""
        return self._with_tag(token, TextTag.INDENT)

    def render_strikethrough(self, token: stok.Strikethrough) -> SingleMarkdown:
        """Render strikethroughed text."""
        return self._with_tag(token, TextTag.STRIKETHROUGH)

    def render_strong(self, token: stok.Strong) -> SingleMarkdown:
        """Render <strong> tags, with bold fonts."""
        return self._with_tag(token, TextTag.BOLD)

    def render_emphasis(self, token: stok.Emphasis) -> SingleMarkdown:
        """Render <em> tags, with italic fonts."""
        return self._with_tag(token, TextTag.ITALIC)


_RENDERER = TKRenderer()


def _merge(*blocks: SingleMarkdown) -> SingleMarkdown:
    """Merge single markdown blocks together."""
    result: list[Block] = []
    for seg in blocks:
        result.extend(seg.blocks)
    return SingleMarkdown(result)


def _convert(text: str, package: utils.ObjectID | None) -> SingleMarkdown:
    """Actually convert markdown data."""
    tok = state.set(RenderState(package))
    with _RENDERER:
        try:
            return _RENDERER.render(mistletoe.Document(text))
        finally:
            state.reset(tok)


def convert(text: TransToken, package: utils.ObjectID | None) -> MarkdownData:
    """Convert Markdown syntax into data ready to be passed to richTextBox.

    The package must be passed to allow using images in the document. None should only be
    used for app-defined strings where we know that can't occur.
    """
    # If untranslated, it'll never change so convert to blocks and discard the source.
    if text.is_untranslated:
        return _convert(str(text), package)
    # Otherwise, keep the source, don't change later.
    return TranslatedMarkdown(text, package)


def join(*args: MarkdownData) -> MarkdownData:
    """Merge several mardown blocks together."""
    # This preserves the originals, so they can be translated separately.
    return JoinedMarkdown(list(args))


def iter_tokens(data: MarkdownData, source: str) -> Iterator[TransTokenSource]:
    """Yield all tokens present in this data block."""
    if isinstance(data, TranslatedMarkdown):
        yield (data.source, source)
    elif isinstance(data, JoinedMarkdown):
        for child in data.children:
            yield from iter_tokens(child, source)


class RichText(tkinter.Text):
    """A version of the TK Text widget which allows using special formatting."""
    def __init__(
        self,
        parent: tkinter.Misc,
        *,
        name: str,
        width: int = 10, height: int = 4,
        font: str | tkFont = "TkDefaultFont",
    ) -> None:
        # Setup all our configuration for inserting text.
        if isinstance(font, str):
            font = nametofont(font)
        self.font = font
        self.bold_font = self.font.copy()
        self.italic_font = self.font.copy()

        self.bold_font['weight'] = 'bold'
        self.italic_font['slant'] = 'italic'

        # URL -> tag name and callback ID.
        self._link_commands: dict[str, tuple[str, str]] = {}

        super().__init__(
            parent,
            name=name,
            width=width,
            height=height,
            wrap="word",
            font=self.font,
            # We only want the I-beam cursor over text.
            cursor=Cursors.REGULAR,
            # If required, add more keyword arguments here.
        )

        self.heading_font = {}
        cur_size: float = self.font['size']
        for size in range(6, 0, -1):
            self.heading_font[size] = font = self.font.copy()
            cur_size /= 0.8735
            font.configure(weight='bold', size=round(cur_size))
            self.tag_config(TAG_HEADINGS[size], font=font)

        self.tag_config(TextTag.UNDERLINE, underline=True)
        self.tag_config(TextTag.BOLD, font=self.bold_font)
        self.tag_config(TextTag.ITALIC, font=self.italic_font)
        self.tag_config(TextTag.STRIKETHROUGH, overstrike=True)
        self.tag_config(TextTag.IMAGE, justify='center')
        self.tag_config(
            TextTag.INVERT,
            background='black',
            foreground='white',
        )
        self.tag_config(TextTag.CODE, font='TkFixedFont')
        self.tag_config(
            TextTag.INDENT,
            # Indent the first line slightly, but indent the following
            # lines more to line up with the text.
            lmargin1="10",
            lmargin2="25",
        )
        # Indent the first line slightly, but indent the following
        # lines more to line up with the text.
        self.tag_config(
            TextTag.LIST_START,
            lmargin1="10",
            lmargin2="25",
        )
        self.tag_config(
            TextTag.LIST,
            lmargin1="25",
            lmargin2="25",
        )
        self.tag_config(
            TextTag.HRULE,
            relief="sunken",
            borderwidth=1,
            # This makes the line-height very short.
            font=tkFont(size=1),
        )
        self.tag_config(
            TextTag.LINK,
            underline=True,
            foreground='blue',
        )

        # We can't change cursors locally for tags, so add a binding which
        # sets the widget property.
        self.tag_bind(
            TextTag.LINK,
            "<Enter>",
            lambda e: self.__setitem__('cursor', Cursors.LINK),
        )
        self.tag_bind(
            TextTag.LINK,
            "<Leave>",
            lambda e: self.__setitem__('cursor', Cursors.REGULAR),
        )

        self['state'] = "disabled"

    def insert(self, *args: Never, **kwargs: Never) -> None:  # type: ignore[override]
        """Inserting directly is disallowed."""
        raise TypeError('richTextBox should not have text inserted directly.')

    # noinspection PyUnresolvedReferences
    # noinspection PyProtectedMember
    def set_text(self, text_data: str | tkMarkdown.MarkdownData) -> None:
        """Write the rich-text into the textbox.

        text_data should either be a string, or the data returned from
        tkMarkdown.convert().
        """
        # Remove all previous link commands
        for cmd_tag, cmd_id in self._link_commands.values():
            self.tag_unbind(cmd_tag, '<Button-1>', funcid=cmd_id)
        self._link_commands.clear()

        self['state'] = "normal"
        try:
            TK_IMG.textwid_clear(self)
            self.delete(1.0, 'end')

            # Basic mode, insert just blocks of text.
            if isinstance(text_data, str):
                super().insert("end", text_data)
                return

            for is_first, block, is_last in iter_firstlast(text_data):
                if isinstance(block, tkMarkdown.TextSegment):
                    tags: tuple[str, ...]
                    if block.url:
                        try:
                            cmd_tag, _ = self._link_commands[block.url]
                        except KeyError:
                            cmd_tag = f'link_cb_{len(self._link_commands)}'
                            cmd_id = self.tag_bind(
                                cmd_tag,
                                '<Button-1>',
                                self.make_link_callback(block.url),
                            )
                            self._link_commands[block.url] = cmd_tag, cmd_id
                        tags = (*block.tags, cmd_tag, TextTag.LINK)
                    else:
                        tags = block.tags
                    # Strip newlines from the beginning and end of the textbox.
                    text = block.text
                    if is_first:
                        text = text.lstrip('\n')
                    if is_last:
                        text = text.rstrip('\n')
                    super().insert('end', text, tags)
                elif isinstance(block, tkMarkdown.Image):
                    super().insert('end', '\n')
                    img_pos = TK_IMG.textwid_add(self, 'end', block.handle)
                    super().tag_add(TextTag.IMAGE, img_pos)
                    super().insert('end', '\n')

                else:
                    raise ValueError(f'Unknown block {block!r}?')
        finally:
            self['state'] = "disabled"

    def make_link_callback(self, url: str) -> Callable[[tkinter.Event[tkinter.Text]], None]:
        """Create a link callback for the given URL."""
        def callback(e: tkinter.Event[tkinter.Text]) -> None:
            """The callback function."""
            if askokcancel(
                title='BEE2 - Open URL?',
                message=str(TRANS_WEBBROWSER.format(url=url)),
                parent=self,
            ):
                webbrowser.open(url)
        return callback
