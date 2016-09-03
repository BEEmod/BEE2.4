import tkinter
from tkinter.constants import *
from tkinter.font import Font as tkFont, nametofont
from tkinter.messagebox import askokcancel

import webbrowser

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

        self.link_commands = {}  # tag-id -> command

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
        self.tag_config(
            "link",
            underline=1,
            foreground='blue',
        )

        # We can't change cursors locally for tags, so add a binding which
        # sets the widget property.
        self.tag_bind(
            "link",
            "<Enter>",
            lambda e: self.configure(cursor=utils.CURSORS['link']),
        )
        self.tag_bind(
            "link",
            "<Leave>",
            lambda e: self.configure(cursor=utils.CURSORS['regular']),
        )

        self['state'] = "disabled"

    def insert(*args, **kwargs):
        raise TypeError('richTextBox should not have text inserted directly.')

    def set_text(self, text_data):
        """Write the rich-text into the textbox.

        text_data should either be a string, or the data returned from
        tkMarkdown.convert().
        """

        # Remove all previous link commands
        for tag, (command_id, func) in self.link_commands.items():
            self.tag_unbind(tag, '<Button-1>', funcid=command_id)
        self.link_commands.clear()

        self['state'] = "normal"
        self.delete(1.0, END)

        if isinstance(text_data, str):
            super().insert("end", text_data)
            return

        if text_data.tags:
            super().insert('end', *text_data.tags)

        for url, link_id in text_data.links.items():
            func = self.make_link_callback(url)
            self.link_commands[link_id] = self.tag_bind(
                link_id,
                '<Button-1>',
                self.make_link_callback(url),
            ), func

        self['state'] = "disabled"

    def make_link_callback(self, url):
        """Create a link callback for the given URL."""

        def callback(e):
            if askokcancel(
                title='BEE2 - Open URL?',
                message='Open "{}" in the default browser?'.format(url),
                master=self,
            ):
                webbrowser.open(url)
        return callback
