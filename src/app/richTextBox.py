import tkinter
from tkinter.constants import *
from tkinter.font import Font as tkFont, nametofont
from tkinter.messagebox import askokcancel

from typing import Union, Tuple, Dict, Callable
import webbrowser

from app import tkMarkdown
from app.tkMarkdown import TextTag
from app.tk_tools import Cursors
from localisation import gettext
import srctools.logger

LOGGER = srctools.logger.get_logger(__name__)


class tkRichText(tkinter.Text):
    """A version of the TK Text widget which allows using special formatting."""
    def __init__(
        self,
        parent: tkinter.Misc,
        width: int = 10, height: int = 4,
        font: Union[str, tkFont] = "TkDefaultFont",
        **kargs,
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
        self._link_commands: Dict[str, Tuple[str, str]] = {}

        super().__init__(
            parent,
            width=width,
            height=height,
            wrap="word",
            font=self.font,
            # We only want the I-beam cursor over text.
            cursor=Cursors.REGULAR,
            **kargs,
        )

        self.heading_font = {}
        cur_size: float = self.font['size']
        for size in range(6, 0, -1):
            self.heading_font[size] = font = self.font.copy()
            cur_size /= 0.8735
            font.configure(weight='bold', size=round(cur_size))
            self.tag_config(TextTag.HEADINGS[size], font=font)

        self.tag_config(TextTag.UNDERLINE, underline=True)
        self.tag_config(TextTag.BOLD, font=self.bold_font)
        self.tag_config(TextTag.ITALIC, font=self.italic_font)
        self.tag_config(TextTag.STRIKETHROUGH, overstrike=True)
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

    def insert(self, *args, **kwargs) -> None:
        """Inserting directly is disallowed."""
        raise TypeError('richTextBox should not have text inserted directly.')

    # noinspection PyUnresolvedReferences
    # noinspection PyProtectedMember
    def set_text(self, text_data: Union[str, tkMarkdown.MarkdownData]) -> None:
        """Write the rich-text into the textbox.

        text_data should either be a string, or the data returned from
        tkMarkdown.convert().
        """

        # Remove all previous link commands
        for cmd_tag, cmd_id in self._link_commands.values():
            self.tag_unbind(cmd_tag, '<Button-1>', funcid=cmd_id)
        self._link_commands.clear()

        self['state'] = "normal"
        self.delete(1.0, END)

        # Basic mode, insert just blocks of text.
        if isinstance(text_data, str):
            super().insert("end", text_data)
            return

        segment: tkMarkdown.TextSegment
        for i, block in enumerate(text_data.blocks):
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
                    tags = block.tags + (cmd_tag, TextTag.LINK)
                else:
                    tags = block.tags
                # Strip newlines from the beginning and end of the textbox.
                text = block.text
                if i == 0:
                    text = text.lstrip('\n')
                elif i + 1 == len(text_data.blocks):
                    text = text.rstrip('\n')
                super().insert('end', text, tags)
            elif isinstance(block, tkMarkdown.Image):
                super().insert('end', '\n')
                # TODO: Setup apply to handle this?
                block.handle._force_loaded = True
                self.image_create('end', image=block.handle._load_tk())
                super().insert('end', '\n')
            else:
                raise ValueError('Unknown block {!r}?'.format(block))

        self['state'] = "disabled"

    def make_link_callback(self, url: str) -> Callable[[tkinter.Event], None]:
        """Create a link callback for the given URL."""

        def callback(e):
            if askokcancel(
                title='BEE2 - Open URL?',
                message=gettext('Open "{}" in the default browser?').format(url),
                parent=self,
            ):
                webbrowser.open(url)
        return callback
