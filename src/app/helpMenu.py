"""Help menu and associated dialogs.

All the URLs we have available here are not directly listed. Instead, we download a file from the
GitHub repo, which ensures we're able to change them retroactively if the old URL becomes dead for
whatever reason.
"""
import io
import urllib.request, urllib.error
from enum import Enum
from typing import Any, Callable, Dict, cast
from tkinter import ttk
import tkinter as tk
import webbrowser
import functools

from srctools.dmx import Element, NULL
import attrs
import srctools.logger
import trio.to_thread

from app.richTextBox import tkRichText
from app import tkMarkdown, tk_tools, sound, img, TK_ROOT, background_run
from localisation import TransToken

# For version info
import PIL
import platform
import mistletoe
import pygtrie


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


@attrs.frozen
class WebResource:
    """Definition for the links in the help menu."""
    name: TransToken
    url_key: str
    icon: ResIcon


LOGGER = srctools.logger.get_logger(__name__)
DB_LOCATION = 'https://raw.githubusercontent.com/BEEmod/BEE2.4/master/help_urls.dmx'
url_data: Element = NULL

# This produces a '-------' instead.
SEPERATOR = WebResource(TransToken.untranslated(''), '', ResIcon.NONE)

Res: Callable[[TransToken, str, ResIcon], WebResource] = cast(Any, WebResource)
WEB_RESOURCES = [
    Res(TransToken.ui('Wiki...'), 'wiki_bee2', ResIcon.BEE2),
    Res(TransToken.ui('Original Items...'), "wiki_peti", ResIcon.PORTAL2),
    # i18n: The chat program.
    Res(TransToken.ui('Discord Server...'), "discord_bee2", ResIcon.DISCORD),
    Res(TransToken.ui("aerond's Music Changer..."), "music_changer", ResIcon.MUSIC_CHANGER),
    Res(TransToken.ui('Purchase Portal 2'), "store_portal2", ResIcon.PORTAL2),
    SEPERATOR,
    Res(TransToken.ui('Application Repository...'), "repo_bee2", ResIcon.GITHUB),
    Res(TransToken.ui('Items Repository...'), "repo_items", ResIcon.GITHUB),
    Res(TransToken.ui('Music Repository...'), "repo_music", ResIcon.GITHUB),
    SEPERATOR,
    Res(TransToken.ui('Submit Application Bugs...'), "issues_app", ResIcon.BUGS),
    Res(TransToken.ui('Submit Item Bugs...'), "issues_items", ResIcon.BUGS),
    Res(TransToken.ui('Submit Music Bugs...'), "issues_music", ResIcon.BUGS),
]
del Res

# language=Markdown
CREDITS_TEXT = '''\
Used software / libraries in the BEE2.4:

* [srctools][srctools] `v{srctools_ver}` by TeamSpen210
* [pyglet][pyglet] `{pyglet_ver}` by Alex Holkner and Contributors
* [Pillow][pillow] `{pil_ver}` by Alex Clark and Contributors
* [noise][perlin_noise] `(2008-12-15)` by Casey Duncan
* [mistletoe][mistletoe] `{mstle_ver}` by Mi Yu and Contributors
* [pygtrie][pygtrie] `{pygtrie_ver}` by Michal Nazarewicz
* [TKinter][tcl] /[Tcl][tcl] `{tk_ver}`
* [Python][python] `{py_ver}`
* [FFmpeg][ffmpeg] licensed under the [LGPLv2.1](http://www.gnu.org/licenses/old-licenses/lgpl-2.1.html). Binaries are built via [sudo-nautilus][ffmpeg-bin].

[pyglet]: https://pyglet.org/
[avbin]: https://avbin.github.io/AVbin/Home/Home.html
[pillow]: http://pillow.readthedocs.io
[perlin_noise]: https://github.com/caseman/noise
[squish]: https://github.com/svn2github/libsquish
[mistletoe]: https://github.com/miyuchina/mistletoe
[pygtrie]: https://github.com/mina86/pygtrie
[tcl]: https://tcl.tk/
[python]: https://www.python.org/
[FFmpeg]: https://ffmpeg.org/
[ffmpeg-bin]: https://github.com/sudo-nautilus/FFmpeg-Builds-Win32
[srctools]: https://github.com/TeamSpen210/srctools

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

# pygtrie


                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

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
    tk_ver=TK_ROOT.tk.call('info', 'patchlevel'),
    pyglet_ver=sound.pyglet_version,
    mstle_ver=mistletoe.__version__,
    pygtrie_ver=pygtrie.__version__,
    pil_ver=PIL.__version__,
    srctools_ver=srctools.__version__,
).replace('\n', '  \n')  # Add two spaces to keep line breaks


class Dialog(tk.Toplevel):
    """Show a dialog with a message."""
    def __init__(self, title: TransToken, text: str):
        super().__init__(TK_ROOT)
        self.withdraw()
        title.apply_title(self)
        self.transient(master=TK_ROOT)
        self.resizable(width=True, height=True)
        self.text = text
        tk_tools.set_window_icon(self)

        # Hide when the exit button is pressed, or Escape
        # on the keyboard.
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.bind("<Escape>", lambda e: self.withdraw())

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

        TransToken.ui('Close').apply(
            ttk.Button(frame, command=self.withdraw)
        ).grid(row=1, column=0)

    async def show(self) -> None:
        """Display the help dialog."""
        # The first time we're shown, decode the text.
        # That way we don't need to do it on startup.
        if self.text is not None:
            parsed_text = tkMarkdown.convert(self.text, package=None)
            self.textbox.set_text(parsed_text)
            self.text = None

        self.deiconify()
        await tk_tools.wait_eventloop()
        tk_tools.center_win(self, TK_ROOT)


def load_database() -> Element:
    """Download the database."""
    LOGGER.info('Downloading help URLs...')
    with urllib.request.urlopen(DB_LOCATION) as response:
        # Read the whole thing, it's tiny and DMX needs to seek.
        data = response.read()
    elem, fmt_name, fmt_ver = Element.parse(io.BytesIO(data), unicode=True)
    if fmt_name != 'bee_urls' or fmt_ver != 1:
        raise ValueError(f'Unknown version {fmt_name!r} v{fmt_ver}!')
    return elem


async def open_url(url_key: str) -> None:
    """Load the URL file if required, then open that URL."""
    global url_data
    if url_data is NULL:
        try:
            url_data = await trio.to_thread.run_sync(load_database)
        except urllib.error.URLError as exc:
            LOGGER.error('Failed to download help url file:', exc_info=exc)
            tk_tools.showerror(
                TransToken.ui('BEEMOD2 - Failed to open URL'),
                TransToken.ui('Failed to download list of URLs. Help menu links will not function. Check your Internet?'),
            )
            return
        except (IOError, ValueError) as exc:
            LOGGER.error('Failed to parse help url file:', exc_info=exc)
            tk_tools.showerror(
                TransToken.ui('BEEMOD2 - Failed to open URL'),
                TransToken.ui('Failed to parse help menu URLs file. Help menu links will not function.'),
            )
            return
        LOGGER.debug('Help URLs:\n{}', '\n'.join([
            f'- {attr.name}: {"[...]" if attr.is_array else repr(attr.val_str)}'
            for attr in url_data.values()
        ]))
    # Got and cached URL data, now lookup.
    try:
        url = url_data[url_key].val_str
    except KeyError:
        LOGGER.warning('Invalid URL key "{}"!', url_key)
    else:
        if tk_tools.askyesno(
            TransToken.ui('BEEMOD 2 - Open URL'),
            TransToken.ui('Do you wish to open the following URL?\n{url}').format(url=url),
        ):
            webbrowser.open(url)


def make_help_menu(parent: tk.Menu) -> None:
    """Create the application 'Help' menu."""
    # Using this name displays this correctly in OS X
    help_menu = tk.Menu(parent, name='help')

    parent.add_cascade(menu=help_menu)
    TransToken.ui('Help').apply_menu(parent)

    icons: Dict[ResIcon, img.Handle] = {
        icon: img.Handle.sprite('icons/' + icon.value, 16, 16)
        for icon in ResIcon
        if icon is not ResIcon.NONE
    }
    icons[ResIcon.NONE] = img.Handle.blank(16, 16)

    credit_window = Dialog(title=TransToken.ui('BEE2 Credits'), text=CREDITS_TEXT)

    for res in WEB_RESOURCES:
        if res is SEPERATOR:
            help_menu.add_separator()
        else:
            help_menu.add_command(
                command=functools.partial(background_run, open_url, res.url_key),
                compound='left',
                image=icons[res.icon].get_tk(),
            )
            res.name.apply_menu(help_menu)

    help_menu.add_separator()
    help_menu.add_command(command=functools.partial(background_run, credit_window.show))
    TransToken.ui('Credits...').apply_menu(help_menu)
