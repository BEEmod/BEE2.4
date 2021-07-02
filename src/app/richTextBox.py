import tkinter
from tkinter.constants import *
from tkinter.font import Font as tkFont, nametofont
from tkinter.messagebox import askokcancel

from typing import Union, Tuple, Dict, Callable
import webbrowser

from app import tkMarkdown
from app.tk_tools import Cursors
import utils
import srctools.logger

LOGGER = srctools.logger.get_logger(__name__)


class tkRichText(tkinter.Text):
    """A version of the TK Text widget which allows using special formatting."""
    def __init__(self, parent, width=10, height=4, font="TkDefaultFont"):
        # Setup all our configuration for inserting text.
        self.font = nametofont(font)
        self.bold_font = self.font.copy()
        self.italic_font = self.font.copy()

        self.bold_font['weight'] = 'bold'
        self.italic_font['slant'] = 'italic'

        # URL -> tag name and callback ID.
        self._link_commands: Dict[str, Tuple[str, int]] = {}

        super().__init__(
            parent,
            width=width,
            height=height,
            wrap="word",
            font=self.font,
            # We only want the I-beam cursor over text.
            cursor=Cursors.REGULAR,
        )

        self.heading_font = {}
        cur_size = self.font['size']
        for size in range(6, 0, -1):
            self.heading_font[size] = font = self.font.copy()
            cur_size /= 0.8735
            font.configure(weight='bold', size=round(cur_size))
            self.tag_config(
                'heading_{}'.format(size),
                font=font,
            )

        self.tag_config(
            "underline",
            underline=True,
        )
        self.tag_config(
            "bold",
            font=self.bold_font,
        )
        self.tag_config(
            "italic",
            font=self.italic_font,
        )
        self.tag_config(
            "strikethrough",
            overstrike=True,
        )
        self.tag_config(
            "invert",
            background='black',
            foreground='white',
        )
        self.tag_config(
            "code",
            font='TkFixedFont',
        )
        self.tag_config(
            "indent",
            # Indent the first line slightly, but indent the following
            # lines more to line up with the text.
            lmargin1="10",
            lmargin2="25",
        )
        # Indent the first line slightly, but indent the following
        # lines more to line up with the text.
        self.tag_config(
            "list_start",
            lmargin1="10",
            lmargin2="25",
        )
        self.tag_config(
            "list",
            lmargin1="25",
            lmargin2="25",
        )
        self.tag_config(
            "hrule",
            relief="sunken",
            borderwidth=1,
            # This makes the line-height very short.
            font=tkFont(size=1),
        )
        self.tag_config(
            "link",
            underline=True,
            foreground='blue',
        )

        # We can't change cursors locally for tags, so add a binding which
        # sets the widget property.
        self.tag_bind(
            "link",
            "<Enter>",
            lambda e: self.configure(cursor=Cursors.LINK),
        )
        self.tag_bind(
            "link",
            "<Leave>",
            lambda e: self.configure(cursor=Cursors.REGULAR),
        )

        self['state'] = "disabled"

    def insert(*args, **kwargs) -> None:
        """Inserting directly is disallowed."""
        raise TypeError('richTextBox should not have text inserted directly.')

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
        for block in text_data.blocks:
            if isinstance(block, tkMarkdown.TextSegment):
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
                    tags = block.tags + (cmd_tag, 'link')
                else:
                    tags = block.tags
                super().insert('end', block.text, tags)
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
                message=_('Open "{}" in the default browser?').format(url),
                parent=self,
            ):
                webbrowser.open(url)
        return callback
