"""Implements UI for selecting corridors."""
from tkinter import ttk
import tkinter as tk
from enum import Enum
from typing import Dict, List

from srctools import Property
from srctools.dmx import Element, Attribute as DMAttr, ValueType as DMXValue
import srctools.logger
import attrs
import trio

import packages
from app import TK_ROOT, config, dragdrop, img, sound, tk_tools
from app.richTextBox import tkRichText
from localisation import gettext
from packages import corridor
import consts
import utils


LOGGER = srctools.logger.get_logger(__name__)
WIDTH = 96 + (32 if utils.MAC else 16)
HEIGHT = 64 + 51


class RandMode(Enum):
    """Kind of randomisation to use."""
    SINGLE = 'single'
    EDITOR = 'editor'  # 4 or 7, depending on editor instance count.
    ALL = 'all'  # Use all regardless.


@config.register('Corridor', uses_id=True)
@attrs.frozen
class CorridorConf(config.Data):
    """The current configuration for a corridor."""
    selected: List[str] = attrs.Factory(list)
    random: RandMode = RandMode.EDITOR

    @staticmethod
    def get_id(
        style: str,
        mode: corridor.GameMode,
        direction: corridor.Direction,
        orient: corridor.CorrOrient,
    ) -> str:
        """Given the style and kind of corridor, return the ID for config lookup."""
        return f'{style.casefold()}:{mode.value}_{direction.value}_{orient.value}'

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'CorridorConf':
        """Parse from KeyValues1 configs."""
        assert version == 1, version
        corr = [
            prop.value
            for prop in data.find_children('selected')
        ]
        try:
            rand = RandMode(data['random', 'editor'])
        except ValueError:
            rand = RandMode.EDITOR

        return CorridorConf(corr, rand)

    def export_kv1(self) -> Property:
        """Serialise to a Keyvalues1 config."""
        return Property('Corridor', [
            Property('random', self.random.value),
            Property('Selected', [
                Property('Corridor', corr)
                for corr in self.selected
            ])
        ])

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'CorridorConf':
        """Parse from DMX configs."""
        assert version == 1, version
        try:
            rand = RandMode(data['random'].val_str)
        except (KeyError, TypeError, ValueError):
            rand = RandMode.EDITOR
        try:
            corr = list(data['selected'].iter_str())
        except KeyError:
            corr = []

        return CorridorConf(corr, rand)

    def export_dmx(self) -> Element:
        """Serialise to DMX configs."""
        elem = Element('Corridor', 'DMEConfig')
        elem['random'] = self.random.value
        elem['selected'] = selected = DMAttr.array('selected', DMXValue.STR)
        selected.extend(self.selected)
        return elem
class Selector:
    """Corridor selection UI."""
    win: tk.Toplevel
    dragdrop: dragdrop.Manager[corridor.Corridor]

    # Current corridor on the right side.
    wid_image: ttk.Label
    wid_title: ttk.Label
    wid_desc: tkRichText

    def __init__(self) -> None:
        self.win = tk.Toplevel(TK_ROOT)
        self.win.wm_protocol("WM_DELETE_WINDOW", self.hide)

        self.win.rowconfigure(0, weight=1)
        self.win.columnconfigure(0, weight=1)

        frm_left = ttk.Frame(self.win, relief="sunken")
        frm_left.rowconfigure(0, weight=1)
        frm_left.columnconfigure(0, weight=1)
        frm_left.grid(row=0, column=0, sticky='nsew')

        frm_right = ttk.Frame(self.win)
        frm_right.columnconfigure(0, weight=1)
        frm_right.grid(row=0, column=1, sticky='ns')

        self.wid_image = ttk.Label(frm_right)
        self.wid_image.grid(row=0, column=0, sticky='ew')
        img.apply(self.wid_image, img.Handle.builtin('BEE2/corr_generic', 256, 192))

        self.wid_title = ttk.Label(frm_right, text='Corridor')
        self.wid_title.grid(row=1, column=0, sticky='ew')

        self.wid_desc = tkRichText(frm_right)
        self.wid_desc.grid(row=2, column=0, sticky='nsew')
        frm_right.rowconfigure(2, weight=1)

        ttk.Button(frm_right, text=gettext('Close'), command=self.hide).grid(row=3, column=0)

        update = self.update

        button_frm = ttk.Frame(frm_left)
        button_frm.grid(row=0, column=0, columnspan=3)
        self.btn_mode = tk_tools.EnumButton(
            button_frm,
            (corridor.GameMode.SP, gettext('SP')),
            (corridor.GameMode.COOP, gettext('Coop')),
            callback=update,
        )
        self.btn_direction = tk_tools.EnumButton(
            button_frm,
            (corridor.Direction.ENTRY, gettext('Entry')),
            (corridor.Direction.EXIT, gettext('Exit')),
            callback=update,
        )
        self.btn_orient = tk_tools.EnumButton(
            button_frm,
            (corridor.CorrOrient.FLAT, gettext('Flat')),
            (corridor.CorrOrient.UP, gettext('Upward')),
            (corridor.CorrOrient.DN, gettext('Downward')),
            callback=update,
        )
        self.btn_mode.frame.grid(row=0, column=0, padx=8)
        self.btn_direction.frame.grid(row=0, column=1, padx=8)
        self.btn_orient.frame.grid(row=0, column=2, padx=8)

        self.dragdrop = drop = dragdrop.Manager(self.win, size=(WIDTH, HEIGHT))
        self.selected = [
            drop.slot_target(frm_left)
            for _ in range(7)
        ]

    def show(self) -> None:
        """Display the window."""
        self.dragdrop.load_icons()
        self.win.deiconify()

    def hide(self) -> None:
        """Hide the window."""
        self.win.withdraw()
        self.dragdrop.unload_icons()

    async def update(self, _) -> None:
        """Called to reposition the corridors."""
        LOGGER.info(
            'Mode: {}, Dir: {}, Orient: {}',
            self.btn_mode.current, self.btn_direction.current, self.btn_orient.current,
        )


async def test() -> None:
    from app import background_run
    background_run(img.init, {})
    background_run(sound.sound_task)

    test_sel = Selector()
    config.read_settings()
    test_sel.show()
    with trio.CancelScope() as scope:
        test_sel.win.wm_protocol('WM_DELETE_WINDOW', scope.cancel)
        await trio.sleep_forever()
