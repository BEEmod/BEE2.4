import tkinter
from tkinter.constants import *
from tkinter.font import Font as tkFont, nametofont

import utils

LOGGER = utils.getLogger(__name__)

FORMAT_TYPES = {
    # format string, tag
    'line': ('{}\n', None),
    'under': ('{}\n', 'underline'),
    'bold': ('{}\n', 'bold'),
    'italic': ('{}\n', 'italic'),
    'bullet': ('\u2022 {}\n', 'indent'),
    'list': ('{i}. {}\n', 'indent'),
    'break': ('\n', None),
    'rule': (' \n', 'hrule'),
    'invert': ('{}\n', 'invert')
    # Horizontal rules are created by applying a tag to a
    # space + newline (which affects the whole line)
    # It decreases the text size (to shrink it vertically),
    # and gives a border.
}


class tkRichText(tkinter.Text):
    """A version of the TK Text widget which allows using special formatting.

    The format for the text is a list of tuples, where each tuple is (type, text).
    Types:
     - "line" : standard line, with carriage return after.
     - "bold" : bolded text, with carriage return
     - "bullet" : indented with a bullet at the beginning
     - "list" : indented with "1. " at the beginning, the number increasing
     - "break" : A carriage return. This ignores the text part.
     - "rule" : A horizontal line. This ignores the text part.
     - "invert": White-on-black text.
    """
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
            list_ind = 1
            for line_type, value in desc:
                try:
                    form, tag = FORMAT_TYPES[line_type.casefold()]
                except KeyError:
                    LOGGER.warning('Unknown description type "{}"!', line_type)
                    continue

                super().insert("end", form.format(value, i=list_ind), tag)

                if '{i}' in form:
                    # Increment the list index if used.
                    list_ind += 1
            # delete the trailing newline
            self.delete(self.index(END) + "-1char", "end")

        self['state'] = "disabled"
