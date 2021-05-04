"""Help menu and associated dialogs."""
from enum import Enum
from typing import NamedTuple, Dict

from tkinter import ttk
import tkinter as tk
import webbrowser
import functools


from app.richTextBox import tkRichText
from app import tkMarkdown, tk_tools, sound, img, TK_ROOT
import utils

# For version info
import PIL
import platform
import mistletoe


class ResIcon(Enum):
    """Icons to show on the menu list."""
    NONE = ''
    GITHUB = 'menu_github'
    BEE2 = 'menu_bee2'
    APERTURE = 'ap_black'
    BUGS = 'menu_github'
    DISCORD = 'menu_discord'
    MUSIC_CHANGER = 'menu_music_changer'

    PORTAL2 = 'menu_p2'
    TAG = 'menu_tag'
    TWTM = 'menu_twtm'
    MEL = 'menu_mel'

SEPERATOR = object()

BEE2_REPO = 'https://github.com/BEEmod/BEE2.4/'
BEE2_ITEMS_REPO = 'https://github.com/BEEmod/BEE2-items/'
DISCORD_SERVER = 'https://discord.gg/EvC8Fku'
MUSIC_CHANGER = 'https://beemmc.boards.net/'


def steam_url(name):
    """Return the URL to open the given game in Steam."""
    return 'steam://store/' + utils.STEAM_IDS[name]


WebResource = NamedTuple('WebResource', [
    ('name', str),
    ('url', str),
    ('icon', ResIcon),
])
Res = WebResource

WEB_RESOURCES = [
    Res(_('Wiki...'), BEE2_ITEMS_REPO + 'wiki/', ResIcon.BEE2),
    Res(
        _('Original Items...'),
        'https://developer.valvesoftware.com/wiki/Category:Portal_2_Puzzle_Maker',
        ResIcon.PORTAL2,
    ),
    # i18n: The chat program.
    Res(_('Discord Server...'), DISCORD_SERVER, ResIcon.DISCORD),
    Res(_("aerond's Music Changer..."), MUSIC_CHANGER, ResIcon.MUSIC_CHANGER),
    SEPERATOR,
    Res(_('Application Repository...'), BEE2_REPO, ResIcon.GITHUB),
    Res(_('Items Repository...'), BEE2_ITEMS_REPO, ResIcon.GITHUB),
    SEPERATOR,
    Res(_('Submit Application Bugs...'), BEE2_REPO + 'issues/new', ResIcon.BUGS),
    Res(_('Submit Item Bugs...'), BEE2_ITEMS_REPO + 'issues/new', ResIcon.BUGS),
    SEPERATOR,
    Res(_('Portal 2'), steam_url('PORTAL2'), ResIcon.PORTAL2),
    Res(_('Aperture Tag'), steam_url('TAG'), ResIcon.TAG),
    Res(_('Portal Stories: Mel'), steam_url('MEL'), ResIcon.MEL),
    Res(_('Thinking With Time Machine'), steam_url('TWTM'), ResIcon.TWTM),
]
del Res, steam_url

# language=Markdown
CREDITS_TEXT = '''\
Used software / libraries in the BEE2.4:

* [pyglet {pyglet_ver}][pyglet] by Alex Holkner and Contributors
* [Pillow {pil_ver}][pillow] by Alex Clark and Contributors
* [noise (2008-12-15)][perlin_noise] by Casey Duncan
* [mistletoe {mstle_ver}][mistletoe] by Mi Yu and Contributors
* [marisa-trie][marisa] by Susumu Yata and Contributors
* [TKinter {tk_ver}/TTK {ttk_ver}/Tcl {tcl_ver}][tcl]
* [Python {py_ver}][python]

[pyglet]: https://bitbucket.org/pyglet/pyglet/wiki/Home
[avbin]: https://avbin.github.io/AVbin/Home/Home.html
[pillow]: http://pillow.readthedocs.io
[perlin_noise]: https://github.com/caseman/noise
[squish]: https://github.com/svn2github/libsquish
[mistletoe]: https://github.com/miyuchina/mistletoe
[marisa]: https://github.com/s-yata/marisa-trie
[tcl]: https://tcl.tk/
[python]: https://www.python.org/

-----

# Pyglet license:

Copyright (c) 2006-2008 Alex Holkner
All rights reserved.
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
 * Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
 * Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in
   the documentation and/or other materials provided with the
   distribution.
 * Neither the name of pyglet nor the names of its
   contributors may be used to endorse or promote products
   derived from this software without specific prior written
   permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

--------

# Mistletoe license:
Copyright 2017 Mi Yu

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

--------

# Noise license:
Copyright (c) 2008, Casey Duncan (casey dot duncan at gmail dot com)

Licence:

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

-------

# Marisa-trie

Copyright (c) marisa-trie authors and contributors, 2012-2016

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is furnished
to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR
A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE
OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

------

# Libmarisa

libmarisa and its command line tools are dual-licensed under the BSD 2-clause license and the LGPL.

#### The BSD 2-clause license

Copyright (c) 2010-2016, Susumu Yata
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

- Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
- Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

--------

# Libsquish

Copyright (c) 2006 Simon Brown                          si@sjbrown.co.uk

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the 
"Software"), to	deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to 
permit persons to whom the Software is furnished to do so, subject to 
the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF 
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY 
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, 
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE 
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

'''.format(
    # Inject the running Python version.
    py_ver=platform.python_version(),
    tk_ver=tk.TkVersion,
    tcl_ver=tk.TclVersion,
    ttk_ver=ttk.__version__,
    pyglet_ver=sound.pyglet_version,
    mstle_ver=mistletoe.__version__,
    pil_ver=PIL.__version__,
).replace('\n', '  \n')  # Add two spaces to keep line breaks


class Dialog(tk.Toplevel):
    """Show a dialog with a message."""
    def __init__(self, title: str, text: str):
        super().__init__(TK_ROOT)
        self.withdraw()
        self.title(title)
        self.transient(master=TK_ROOT)
        self.resizable(width=True, height=True)
        self.text = text
        tk_tools.set_window_icon(self)

        # Hide when the exit button is pressed, or Escape
        # on the keyboard.
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.bind("<Escape>", self.withdraw)

        frame = tk.Frame(self, background='white')
        frame.grid(row=0, column=0, sticky='nsew')
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.textbox = tkRichText(frame, width=80, height=24)
        self.textbox.configure(background='white', relief='flat')
        self.textbox.grid(row=0, column=0, sticky='nsew')
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        scrollbox = tk_tools.HidingScroll(
            frame,
            orient='vertical',
            command=self.textbox.yview,
        )
        scrollbox.grid(row=0, column=1, sticky='ns')
        self.textbox['yscrollcommand'] = scrollbox.set

        ttk.Button(
            frame,
            text=_('Close'),
            command=self.withdraw,
        ).grid(
            row=1, column=0,
        )

    def show(self, e=None):
        # The first time we're shown, decode the text.
        # That way we don't need to do it on startup.
        if self.text is not None:
            parsed_text = tkMarkdown.convert(self.text, package=None)
            self.textbox.set_text(parsed_text)
            self.text = None

        self.deiconify()
        self.update_idletasks()
        utils.center_win(self, TK_ROOT)


def make_help_menu(parent: tk.Menu):
    """Create the application 'Help' menu."""
    # Using this name displays this correctly in OS X
    help = tk.Menu(parent, name='help')

    parent.add_cascade(menu=help, label=_('Help'))

    icons: Dict[ResIcon, img.Handle] = {
        icon: img.Handle.sprite('icons/' + icon.value, 16, 16)
        for icon in ResIcon
        if icon is not ResIcon.NONE
    }
    icons[ResIcon.NONE] = img.Handle.blank(16, 16)

    credits = Dialog(
        title=_('BEE2 Credits'),
        text=CREDITS_TEXT,
    )

    for res in WEB_RESOURCES:
        if res is SEPERATOR:
            help.add_separator()
        else:
            help.add_command(
                label=res.name,
                command=functools.partial(webbrowser.open, res.url),
                compound='left',
                image=icons[res.icon].get_tk(),
            )

    help.add_separator()
    help.add_command(
        label=_('Credits...'),
        command=credits.show,
    )
