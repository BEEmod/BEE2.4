import tkinter
from tkinter.constants import *
from tkinter.font import Font as tkFont, nametofont

import utils

LOGGER = utils.getLogger(__name__)


class tkRichText(tkinter.Text):
    """A version of the TK Text widget which allows using special formatting."""
    def __init__(self, parent, width=10, height=4, font="TkDefaultFont"):
        self.font = nametofont(font)
        self.bold_font = self.font.copy()
        self.italic_font = self.font.copy()

        self.bold_font['weight'] = 'bold'
        self.italic_font['slant'] = 'italic'

        super().__init__(
            parent,
            width=width,
            height=height,
            wrap="word",
            font=self.font,
        )
        self.tag_config(
            "underline",
            underline=1,
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
            "invert",
            background='black',
            foreground='white',
        )
        self.tag_config(
            "indent",
            # Indent the first line slightly, but indent the following
            # lines more to line up with the text.
            lmargin1="10",
            lmargin2="25",
        )
        self.tag_config(
            "hrule",
            relief="sunken",
            borderwidth=1,
            # This makes the line-height very short.
            font=tkFont(size=1),
        )
        self['state'] = "disabled"

    def insert(*args, **kwargs):
        raise TypeError('richTextBox should not have text inserted directly.')

    def set_text(self, desc):
        """Write the rich-text into the textbox."""
        self['state'] = "normal"
        self.delete(1.0, END)

        if isinstance(desc, str):
            super().insert("end", desc)
        else:
            desc = list(desc)
            LOGGER.info('Text data: {}', desc)
            for text, tag in desc:
                super().insert("end", text, tag)

            self['state'] = "disabled"
