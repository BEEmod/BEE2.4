"""Main UI module, brings everything together."""
from typing import List, Type, Dict, Tuple, Optional, Set, Iterator, Callable, TypedDict, Union
import tkinter as tk
from tkinter import ttk
import itertools
import operator
import random
import functools
import math

import srctools.logger
import attrs
import trio
from typing_extensions import assert_never

import exporting
from app import EdgeTrigger, TK_ROOT, background_run, background_start, quit_app
from BEE2_config import GEN_OPTS
from app.dialogs import Dialogs
from loadScreen import MAIN_UI as LOAD_UI
import packages
from packages.item import ItemVariant, InheritKind
import utils
from config.filters import FilterConf
from config.gen_opts import GenOptions, AfterExport
from config.last_sel import LastSelected
from config.windows import WindowState
from config.item_defaults import ItemDefault
import config
from transtoken import TransToken
from app import (
    img,
    itemconfig,
    sound as snd,
    tk_tools,
    SubPane,
    voiceEditor,
    contextWin,
    gameMan,
    packageMan,
    StyleVarPane,
    CompilerPane,
    item_search,
    optionWindow,
    backup as backup_win,
    tooltip,
    signage_ui,
    paletteUI,
    music_conf,
)
from app.selector_win import SelectorWin, Item as selWinItem, AttrDef as SelAttr
from app.menu_bar import MenuBar
from ui_tk.corridor_selector import TkSelector
from ui_tk.dialogs import DIALOG
from ui_tk.img import TKImages, TK_IMG
from ui_tk import wid_transtoken


LOGGER = srctools.logger.get_logger(__name__)

# These panes and a dict mapping object type to them.
skybox_win: 'SelectorWin[[]]'
voice_win: 'SelectorWin[[]]'
style_win: 'SelectorWin[[]]'
elev_win: 'SelectorWin[[]]'
suggest_windows: Dict[Type[packages.PakObject], 'SelectorWin[...]'] = {}

# Items chosen for the palette.
pal_picked: List['PalItem'] = []
# Array of the "all items" icons
pal_items: List['PalItem'] = []
# Labels used for the empty palette positions
pal_picked_fake: List[ttk.Label] = []
# Labels for empty picker positions
pal_items_fake: List[ttk.Label] = []
# The current filtering state.
cur_filter: Optional[Set[Tuple[str, int]]] = None

ItemsBG = "#CDD0CE"  # Colour of the main background to match the menu image

# Icon shown while items are being moved elsewhere.
ICO_MOVING = img.Handle.builtin('BEE2/item_moving', 64, 64)
ICO_GEAR = img.Handle.sprite('icons/gear', 10, 10)
ICO_GEAR_DIS = img.Handle.sprite('icons/gear_disabled', 10, 10)
IMG_BLANK = img.Handle.background(64, 64)

selected_style: utils.ObjectID = packages.CLEAN_STYLE

# Maps item IDs to our wrapper for the object.
item_list: Dict[str, 'Item'] = {}

# Piles of global widgets, should be made local...
frmScroll: ttk.Frame  # Frame holding the item list.
pal_canvas: tk.Canvas  # Canvas for the item list to scroll.


TRANS_EXPORTED = TransToken.ui('Selected Items and Style successfully exported!')
TRANS_EXPORTED_TITLE = TransToken.ui('BEE2 - Export Complete')
TRANS_MAIN_TITLE = TransToken.ui('BEEMOD {version} - {game}')
TRANS_ERROR = TransToken.untranslated('???')


class DragWin(tk.Toplevel):
    """Todo: use dragdrop module instead."""
    passed_over_pal: bool  # Has the cursor passed over the palette
    from_pal: bool  # Are we dragging a palette item?
    drag_item: Optional['PalItem']  # The item currently being moved


class _WindowsDict(TypedDict, total=False):
    """TODO: Remove."""
    drag_win: DragWin
    opt: SubPane.SubPane
    pal: SubPane.SubPane


class _FramesDict(TypedDict, total=False):
    """TODO: Remove."""
    picker: ttk.Frame
    preview: tk.Frame
    toolMenu: tk.Frame


class _UIDict(TypedDict, total=False):
    """TODO: Remove."""
    conf_voice: ttk.Button
    pal_export: ttk.Button
    suggested_style: ttk.Button
    drag_lbl: ttk.Label
    pre_bg_img: tk.Label
    pre_disp_name: ttk.Label
    pre_moving: ttk.Label
    pre_sel_line: tk.Label
    picker_frame: ttk.Frame


# Holds the TK Toplevels, frames, widgets and menus
windows: _WindowsDict = {}
frames: _FramesDict = {}
UI: _UIDict = {}


class Item:
    """Represents an item that can appear on the list."""
    __slots__ = [
        'ver_list',
        'item',
        'def_data',
        'data',
        'inherit_kind',
        'visual_subtypes',
        'id',
        'pak_id',
        'pak_name',
        'names',
        ]
    data: ItemVariant
    inherit_kind: InheritKind

    def __init__(self, item: packages.Item) -> None:
        self.ver_list = sorted(item.versions.keys())

        self.item = item
        self.def_data = item.def_ver.def_style
        # The indexes of subtypes that are actually visible.
        self.visual_subtypes = [
            ind
            for ind, sub in enumerate(self.def_data.editor.subtypes)
            if sub.pal_name or sub.pal_icon
        ]

        self.id = item.id
        self.pak_id = item.pak_id
        self.pak_name = item.pak_name

        self.load_data()

    def selected_version(self) -> packages.item.Version:
        """Fetch the selected version for this item."""
        conf = config.APP.get_cur_conf(ItemDefault, self.id, ItemDefault())
        try:
            return self.item.versions[conf.version]
        except KeyError:
            LOGGER.warning('Version ID {} is not valid for item {}', conf.version, self.item.id)
            config.APP.store_conf(attrs.evolve(conf, version=self.item.def_ver.id), self.id)
            return self.item.def_ver

    def load_data(self) -> None:
        """Reload data from the item."""
        version = self.selected_version()
        self.data = version.styles.get(selected_style, self.def_data)
        self.inherit_kind = version.inherit_kind.get(selected_style, InheritKind.UNSTYLED)

    def get_tags(self, subtype: int) -> Iterator[str]:
        """Return all the search keywords for this item/subtype."""
        yield self.pak_name
        yield from self.data.tags
        yield from self.data.authors
        try:
            name = self.data.editor.subtypes[subtype].name
        except IndexError:
            LOGGER.warning(
                'No subtype number {} for {} in {} style!',
                subtype, self.id, selected_style,
            )
        else:  # Include both the original and translated versions.
            if not name.is_game:
                yield name.token
            yield str(name)

    def get_icon(self, subKey: int, allow_single: bool = False, single_num: int = 1) -> img.Handle:
        """Get an icon for the given subkey.

        If allow_single is true, the grouping icon can be returned
        instead if only one item is on the palette.
        Drag-icons have different rules for what counts as 'single', so
        they use the single_num parameter to control the output.
        """
        num_picked = sum(
            item.id == self.id
            for item in pal_picked
        )
        return self.get_raw_icon(subKey, allow_single and num_picked <= single_num)

    def get_raw_icon(self, sub_key: int, use_grouping: bool) -> img.Handle:
        """Get an icon for the given subkey, directly indicating if it should be grouped."""
        icon = self._get_raw_icon(sub_key, use_grouping)
        if self.item.unstyled or not config.APP.get_cur_conf(GenOptions).visualise_inheritance:
            return icon
        if self.inherit_kind is not InheritKind.DEFINED:
            icon = icon.overlay_text(self.inherit_kind.value.title(), 12)
        return icon

    def _get_raw_icon(self, subKey: int, use_grouping: bool) -> img.Handle:
        """Get the raw icon, which may be overlaid if required."""
        icons = self.data.icons
        if use_grouping and self.data.can_group():
            # If only 1 copy of this item is on the palette, use the
            # special icon
            try:
                return icons['all']
            except KeyError:
                return img.Handle.file(utils.PackagePath(
                    self.pak_id, str(self.data.all_icon)
                ), 64, 64)

        try:
            return icons[str(subKey)]
        except KeyError:
            # Read from editoritems.
            pass
        try:
            subtype = self.data.editor.subtypes[subKey]
        except IndexError:
            LOGGER.warning(
                'No subtype number {} for {} in {} style!',
                subKey, self.id, selected_style,
            )
            return img.Handle.error(64, 64)
        if subtype.pal_icon is None:
            LOGGER.warning(
                'No palette icon for {} subtype {} in {} style!',
                self.id, subKey, selected_style,
            )
            return img.Handle.error(64, 64)

        return img.Handle.file(utils.PackagePath(
            self.data.pak_id, str(subtype.pal_icon)
        ), 64, 64)

    def refresh_subitems(self) -> None:
        """Call load_data() on all our subitems, so they reload icons and names."""
        for item in pal_picked:
            if item.id == self.id:
                item.load_data()
        flow_preview()
        for item in pal_items:
            if item.id == self.id:
                item.load_data()
        background_run(flow_picker, config.APP.get_cur_conf(FilterConf))

    def change_version(self, version: str) -> None:
        """Set the version of this item."""
        old_conf = config.APP.get_cur_conf(ItemDefault, self.id, ItemDefault())
        config.APP.store_conf(attrs.evolve(old_conf, version=version), self.id)
        self.load_data()
        self.refresh_subitems()

    def get_version_names(self) -> Tuple[List[str], List[str]]:
        """Get a list of the names and corresponding IDs for the item."""
        # item folders are reused, so we can find duplicates.
        style_obj_ids = {
            id(self.item.versions[ver_id].styles[selected_style])
            for ver_id in self.ver_list
        }
        versions = self.ver_list
        if len(style_obj_ids) == 1:
            # All the variants are the same, so we effectively have one
            # variant. Disable the version display.
            versions = self.ver_list[:1]

        return versions, [
            self.item.versions[ver_id].name
            for ver_id in versions
        ]


class PalItem:
    """The icon and associated data for a single subitem."""
    def __init__(self, frame: tk.Misc, item: Item, sub: int, is_pre: bool) -> None:
        """Create a label to show an item onscreen."""
        self.item = item
        self.subKey = sub
        self.id = item.id
        # Used to distinguish between picker and palette items
        self.is_pre = is_pre
        self.needs_unlock = item.item.needs_unlock

        # Location this item was present at previously when dragging it.
        self.pre_x = self.pre_y = -1

        self.label = lbl = tk.Label(frame)

        lbl.bind(tk_tools.EVENTS['LEFT'], functools.partial(drag_start, self))
        lbl.bind(tk_tools.EVENTS['LEFT_SHIFT'], functools.partial(drag_fast, self))
        lbl.bind("<Enter>", self.rollover)
        lbl.bind("<Leave>", self.rollout)

        self.info_btn = tk.Label(
            lbl,
            relief='ridge',
            width=12,
            height=12,
        )
        TK_IMG.apply(self.info_btn, ICO_GEAR)

        click_func = contextWin.open_event(self)
        tk_tools.bind_rightclick(lbl, click_func)

        @tk_tools.bind_leftclick(self.info_btn)
        def info_button_click(e: tk.Event[tk.Misc]) -> object:
            """When clicked, show the context window."""
            click_func(e)
            # Cancel the event sequence, so it doesn't travel up to the main
            # window and hide the window again.
            return 'break'

        # Right-click does the same as the icon.
        tk_tools.bind_rightclick(self.info_btn, click_func)

    def __del__(self) -> None:
        """When destroyed, clean up the label."""
        try:
            self.label.destroy()
        except AttributeError:
            pass

    @property
    def name(self) -> TransToken:
        """Get the current name for this subtype."""
        try:
            return self.item.data.editor.subtypes[self.subKey].name
        except IndexError:
            LOGGER.warning(
                'Item <{}> in <{}> style has mismatched subtype count!',
                self.id, selected_style,
            )
            return TRANS_ERROR

    def rollover(self, _: tk.Event) -> None:
        """Show the name of a subitem and info button when moused over."""
        set_disp_name(self)
        self.label.lift()
        self.label['relief'] = 'ridge'
        padding = 2 if utils.WIN else 0
        self.info_btn.place(
            x=self.label.winfo_width() - padding,
            y=self.label.winfo_height() - padding,
            anchor='se',
        )

    def rollout(self, _: tk.Event) -> None:
        """Reset the item name display and hide the info button when the mouse leaves."""
        clear_disp_name()
        self.label['relief'] = 'flat'
        self.info_btn.place_forget()

    def change_subtype(self, ind: int) -> None:
        """Change the subtype of this icon.

        This removes duplicates from the palette if needed.
        """
        for item in pal_picked[:]:
            if item.id == self.id and item.subKey == ind:
                item.kill()
        self.subKey = ind
        self.load_data()
        self.label.master.update()  # Update the frame
        flow_preview()

    def open_menu_at_sub(self, ind: int) -> None:
        """Make the contextWin open itself at the indicated subitem.

        """
        if self.is_pre:
            items_list = pal_picked[:]
        else:
            items_list = []
        # Open on the palette, but also open on the item picker if needed
        for item in itertools.chain(items_list, pal_items):
            if item.id == self.id and item.subKey == ind:
                contextWin.show_prop(item, warp_cursor=True)
                break

    def load_data(self) -> None:
        """Refresh our icon and name.

        Call whenever the style changes, so the icons update.
        """
        if self.is_pre:
            TK_IMG.apply(self.label, self.item.get_icon(self.subKey, True))
        else:
            TK_IMG.apply(self.label, self.item.get_raw_icon(
                self.subKey,
                config.APP.get_cur_conf(FilterConf, default=FilterConf()).compress,
            ))

    def clear(self) -> bool:
        """Remove any items matching ourselves from the palette.

        This prevents adding two copies.
        """
        found = False
        for item in pal_picked[:]:
            # remove the item off of the palette if it's on there, this
            # lets you delete items and prevents having the same item twice.
            if self.id == item.id and self.subKey == item.subKey:
                item.kill()
                found = True
        return found

    def kill(self) -> None:
        """Hide and destroy this widget."""
        for i, item in enumerate(pal_picked):
            if item is self:
                del pal_picked[i]
                break
        self.label.place_forget()

    def on_pal(self) -> bool:
        """Determine if this item is on the palette."""
        for item in pal_picked:
            if self.id == item.id and self.subKey == item.subKey:
                return True
        return False

    def copy(self, frame: tk.Misc) -> 'PalItem':
        return PalItem(frame, self.item, self.subKey, self.is_pre)

    def __repr__(self) -> str:
        return f'<{self.id}:{self.subKey}>'


async def load_packages(packset: packages.PackagesSet, tk_img: TKImages) -> None:
    """Import in the list of items and styles from the packages.

    A lot of our other data is initialised here too.
    This must be called before initMain() can run.
    """
    global skybox_win, voice_win, style_win, elev_win

    for item in packset.all_obj(packages.Item):
        item_list[item.id] = Item(item)

    sky_list: List[selWinItem] = []
    voice_list: List[selWinItem] = []
    style_list: List[selWinItem] = []
    elev_list: List[selWinItem] = []

    # These don't need special-casing, and act the same.
    # The attrs are a map from selectorWin attributes, to the attribute on
    # the object.
    obj_types = [
        (sky_list, packages.Skybox, {
            '3D': 'config',  # Check if it has a config
            'COLOR': 'fog_color',
        }),
        (style_list, packages.Style, {
            'VID': 'has_video',
        }),
        (elev_list, packages.Elevator, {
            'ORIENT': 'has_orient',
        }),
    ]

    for sel_list, obj_type, sel_attrs in obj_types:
        # Extract the display properties out of the object, and create
        # a SelectorWin item to display with.
        for obj in sorted(packset.all_obj(obj_type), key=operator.attrgetter('selitem_data.name.token')):
            sel_list.append(selWinItem.from_data(
                obj.id,
                obj.selitem_data,
                attrs={
                    key: getattr(obj, attr_name)
                    for key, attr_name in
                    sel_attrs.items()
                }
            ))

    voice: packages.QuotePack
    for voice in sorted(packset.all_obj(packages.QuotePack), key=operator.attrgetter('selitem_data.name.token')):
        voice_list.append(selWinItem.from_data(
            voice.id,
            voice.selitem_data,
            attrs={
                'CHAR': voice.data.chars or {'???'},
                'MONITOR': voice.data.monitor is not None,
                'TURRET': voice.data.monitor is not None and voice.data.monitor.turret_hate,
            }
        ))

    def win_callback(sel_id: Optional[str]) -> None:
        """Callback for the selector windows.

        This just refreshes if the 'apply selection' option is enabled.
        """
        suggested_refresh()

    def voice_callback(voice_id: Optional[str]) -> None:
        """Special callback for the voice selector window.

        The configuration button is disabled when no music is selected.
        """
        # This might be open, so force-close it to ensure it isn't corrupt...
        voiceEditor.save()
        try:
            if voice_id is None:
                UI['conf_voice'].state(['disabled'])
                tk_img.apply(UI['conf_voice'], ICO_GEAR_DIS)
            else:
                UI['conf_voice'].state(['!disabled'])
                tk_img.apply(UI['conf_voice'], ICO_GEAR)
        except KeyError:
            # When first initialising, conf_voice won't exist!
            pass
        suggested_refresh()

    # Defaults match Clean Style, if not found it uses the first item.
    skybox_win = await background_start(functools.partial(
        SelectorWin.create,
        TK_ROOT,
        sky_list,
        save_id='skyboxes',
        title=TransToken.ui('Select Skyboxes'),
        desc=TransToken.ui(
            'The skybox decides what the area outside the chamber is like. It chooses the colour '
            'of sky (seen in some items), the style of bottomless pit (if present), as well as '
            'color of "fog" (seen in larger chambers).'
        ),
        default_id='BEE2_CLEAN',
        has_none=False,
        callback=win_callback,
        attributes=[
            SelAttr.bool('3D', TransToken.ui('3D Skybox'), False),
            SelAttr.color('COLOR', TransToken.ui('Fog Color')),
        ],
    ))

    voice_win = await background_start(functools.partial(
        SelectorWin.create,
        TK_ROOT,
        voice_list,
        save_id='voicelines',
        title=TransToken.ui('Select Additional Voice Lines'),
        desc=TransToken.ui(
            'Voice lines choose which extra voices play as the player enters or exits a chamber. '
            'They are chosen based on which items are present in the map. The additional '
            '"Multiverse" Cave lines are controlled separately in Style Properties.'
        ),
        has_none=True,
        default_id='BEE2_GLADOS_CLEAN',
        none_desc=TransToken.ui('Add no extra voice lines, only Multiverse Cave if enabled.'),
        none_attrs={
            'CHAR': [TransToken.ui('<Multiverse Cave only>')],
        },
        callback=voice_callback,
        attributes=[
            SelAttr.list_and('CHAR', TransToken.ui('Characters'), ['??']),
            SelAttr.bool('TURRET', TransToken.ui('Turret Shoot Monitor'), False),
            SelAttr.bool('MONITOR', TransToken.ui('Monitor Visuals'), False),
        ],
    ))

    style_win = await background_start(functools.partial(
        SelectorWin.create,
        TK_ROOT,
        style_list,
        save_id='styles',
        default_id='BEE2_CLEAN',
        title=TransToken.ui('Select Style'),
        desc=TransToken.ui(
            'The Style controls many aspects of the map. It decides the materials used for walls, '
            'the appearance of entrances and exits, the design for most items as well as other '
            'settings.\n\nThe style broadly defines the time period a chamber is set in.'
        ),
        has_none=False,
        has_def=False,
        # Selecting items changes much of the gui - don't allow when other
        # things are open...
        modal=True,
        # callback set in the main initialisation function...
        attributes=[
            SelAttr.bool('VID', TransToken.ui('Elevator Videos'), default=True),
        ]
    ))

    elev_win = await background_start(functools.partial(
        SelectorWin.create,
        TK_ROOT,
        elev_list,
        save_id='elevators',
        title=TransToken.ui('Select Elevator Video'),
        desc=TransToken.ui(
            'Set the video played on the video screens in modern Aperture elevator rooms. Not all '
            'styles feature these. If set to "None", a random video will be selected each time the '
            'map is played, like in the default PeTI.'
        ),
        readonly_desc=TransToken.ui('This style does not have a elevator video screen.'),
        # i18n: Text when elevators are not present in the style.
        readonly_override=TransToken.ui('<Not Present>'),
        has_none=True,
        has_def=True,
        none_icon=img.Handle.builtin('BEE2/random', 96, 96),
        none_name=TransToken.ui('Random'),
        none_desc=TransToken.ui('Choose a random video.'),
        callback=win_callback,
        attributes=[
            SelAttr.bool('ORIENT', TransToken.ui('Multiple Orientations')),
        ]
    ))

    suggest_windows[packages.QuotePack] = voice_win
    suggest_windows[packages.Skybox] = skybox_win
    suggest_windows[packages.Elevator] = elev_win


def current_style() -> packages.Style:
    """Return the currently selected style."""
    return packages.get_loaded_packages().obj_by_id(packages.Style, selected_style)


def reposition_panes() -> None:
    """Position all the panes in the default places around the main window."""
    comp_win = CompilerPane.window
    opt_win = windows['opt']
    pal_win = windows['pal']
    # The x-pos of the right side of the main window
    xpos = min(
        TK_ROOT.winfo_screenwidth()
        - itemconfig.window.winfo_reqwidth(),

        TK_ROOT.winfo_rootx()
        + TK_ROOT.winfo_reqwidth()
        + 25
        )
    # The x-pos for the palette and compiler panes
    pal_x = TK_ROOT.winfo_rootx() - comp_win.winfo_reqwidth() - 25
    pal_win.move(
        x=pal_x,
        y=(TK_ROOT.winfo_rooty() - 50),
        height=max(
            TK_ROOT.winfo_reqheight() -
            comp_win.winfo_reqheight() -
            25,
            30,
        ),
        width=comp_win.winfo_reqwidth(),
    )
    comp_win.move(
        x=pal_x,
        y=pal_win.winfo_rooty() + pal_win.winfo_reqheight(),
    )
    opt_win.move(
        x=xpos,
        y=TK_ROOT.winfo_rooty()-40,
        width=itemconfig.window.winfo_reqwidth(),
    )
    itemconfig.window.move(
        x=xpos,
        y=TK_ROOT.winfo_rooty() + opt_win.winfo_reqheight() + 25,
    )


def reset_panes() -> None:
    """Reset the position of all panes."""
    reposition_panes()
    windows['pal'].save_conf()
    windows['opt'].save_conf()
    itemconfig.window.save_conf()
    CompilerPane.window.save_conf()


def suggested_refresh() -> None:
    """Enable or disable the suggestion setting button."""
    if 'suggested_style' in UI:
        windows: list[SelectorWin[...]] = [
            voice_win, skybox_win, elev_win,
            *music_conf.WINDOWS.values(),
        ]
        if all(win.is_suggested() for win in windows):
            UI['suggested_style'].state(['disabled'])
        else:
            UI['suggested_style'].state(['!disabled'])


async def export_editoritems(pal_ui: paletteUI.PaletteUI, bar: MenuBar, dialog: Dialogs) -> None:
    """Export the selected Items and Style into the chosen game."""
    # Disable, so you can't double-export.
    UI['pal_export'].state(('disabled',))
    bar.set_export_allowed(False)
    try:
        await tk_tools.wait_eventloop()
        # Convert IntVar to boolean, and only export values in the selected style
        chosen_style = current_style()

        # The chosen items on the palette.
        pal_data: paletteUI.ItemPos = {
            pos: (it.id, it.subKey)
            for pos, it in zip(paletteUI.COORDS, pal_picked)
        }
        # Group palette data by each item ID, so it can easily determine which items are actually
        # on the palette at all.
        pal_by_item: Dict[str, Dict[int, Tuple[int, int]]] = {}
        for pos, (item_id, subkey) in pal_data.items():
            pal_by_item.setdefault(item_id.casefold(), {})[subkey] = pos

        conf = config.APP.get_cur_conf(config.gen_opts.GenOptions)
        packset = packages.get_loaded_packages()

        result = await exporting.export(
            gameMan.selected_game,
            packset,
            style=chosen_style,
            selected_objects={
                # Specify the 'chosen item' for each object type
                packages.Music: music_conf.export_data(packset),
                packages.Skybox: skybox_win.chosen_id,
                packages.QuotePack: voice_win.chosen_id,
                packages.Elevator: elev_win.chosen_id,

                packages.Item: pal_by_item,
                packages.StyleVar: StyleVarPane.export_data(chosen_style),
                packages.Signage: signage_ui.export_data(),
            },
            should_refresh=not conf.preserve_resources,
        )

        if result is result.FAILED:
            return

        try:
            last_export = pal_ui.palettes[paletteUI.UUID_EXPORT]
        except KeyError:
            last_export = pal_ui.palettes[paletteUI.UUID_EXPORT] = paletteUI.Palette(
                '',
                pal_data,
                # This makes it lookup the translated name
                # instead of using a configured one.
                trans_name='LAST_EXPORT',
                uuid=paletteUI.UUID_EXPORT,
                readonly=True,
            )
        else:
            last_export.items = pal_data
        last_export.save(ignore_readonly=True)

        # Save the configs since we're writing to disk lots anyway.
        GEN_OPTS.save_check()
        config.APP.write_file()

        if conf.launch_after_export or conf.after_export is not config.gen_opts.AfterExport.NORMAL:
            do_action = await dialog.ask_yes_no(
                optionWindow.AFTER_EXPORT_TEXT[
                    conf.after_export, conf.launch_after_export,
                ].format(msg=TRANS_EXPORTED),
                title=TRANS_EXPORTED_TITLE,
            )
        else:  # No action to do, so just show an OK.
            await dialog.show_info(TRANS_EXPORTED, title=TRANS_EXPORTED_TITLE)
            do_action = False

        # Do the desired action - if quit, we don't bother to update UI.
        if do_action:
            # Launch first so quitting doesn't affect this.
            if conf.launch_after_export:
                gameMan.selected_game.launch()

            if conf.after_export is AfterExport.NORMAL:
                pass
            elif conf.after_export is AfterExport.MINIMISE:
                TK_ROOT.iconify()
            elif conf.after_export is AfterExport.QUIT:
                quit_app()
                return
            else:
                assert_never(conf.after_export)

        # Select the last_export palette, so reloading loads this item selection.
        # But leave it at the current palette, if it's unmodified.
        if pal_ui.selected.items != pal_data:
            pal_ui.select_palette(paletteUI.UUID_EXPORT, False)
            pal_ui.update_state()

        # Re-fire this, so we clear the '*' on buttons if extracting cache.
        await gameMan.ON_GAME_CHANGED(gameMan.selected_game)
    finally:
        UI['pal_export'].state(('!disabled',))
        bar.set_export_allowed(True)


def set_disp_name(item: PalItem, e: object = None) -> None:
    """Callback to display the name of the item."""
    wid_transtoken.set_text(UI['pre_disp_name'], item.name)


def clear_disp_name(e: object = None) -> None:
    """Callback to reset the item name."""
    wid_transtoken.set_text(UI['pre_disp_name'], TransToken.BLANK)


def conv_screen_to_grid(x: float, y: float) -> Tuple[int, int]:
    """Returns the location of the item hovered over on the preview pane."""
    return (
        round(x-UI['pre_bg_img'].winfo_rootx()-8) // 65,
        round(y-UI['pre_bg_img'].winfo_rooty()-32) // 65,
    )


def drag_start(drag_item: PalItem, e: tk.Event[tk.Misc]) -> None:
    """Start dragging a palette item."""
    drag_win = windows['drag_win']
    drag_win.drag_item = drag_item
    set_disp_name(drag_item)
    snd.fx('config')
    drag_win.passed_over_pal = False
    if drag_item.is_pre:  # is the cursor over the preview pane?
        drag_item.kill()
        UI['pre_moving'].place(
            x=drag_item.pre_x*65 + 4,
            y=drag_item.pre_y*65 + 32,
        )
        drag_win.from_pal = True

        for item in pal_picked:
            if item.id == drag_win.drag_item.id:
                item.load_data()

        # When dragging off, switch to the single-only icon
        TK_IMG.apply(UI['drag_lbl'], drag_item.item.get_icon(
            drag_item.subKey,
            allow_single=False,
        ))
    else:
        drag_win.from_pal = False
        TK_IMG.apply(UI['drag_lbl'], drag_item.item.get_icon(
            drag_item.subKey,
            allow_single=True,
            single_num=0,
        ))
    drag_win.deiconify()
    drag_win.lift()
    # grab makes this window the only one to receive mouse events, so
    # it is guaranteed that it'll drop when the mouse is released.
    drag_win.grab_set_global()
    # NOTE: _global means no other programs can interact, make sure
    # it's released eventually or you won't be able to quit!
    drag_move(e)  # move to correct position
    drag_win.bind(tk_tools.EVENTS['LEFT_MOVE'], drag_move)
    UI['pre_sel_line'].lift()


def drag_stop(e: tk.Event[tk.Misc]) -> None:
    """User released the mouse button, complete the drag."""
    drag_win: DragWin = windows['drag_win']

    if drag_win.drag_item is None:
        # We aren't dragging, ignore the event.
        return

    drag_win.withdraw()
    drag_win.unbind("<B1-Motion>")
    drag_win.grab_release()
    clear_disp_name()
    UI['pre_sel_line'].place_forget()
    UI['pre_moving'].place_forget()
    snd.fx('config')

    pos_x, pos_y = conv_screen_to_grid(e.x_root, e.y_root)
    ind = pos_x + pos_y * 4

    # this prevents a single click on the picker from clearing items
    # off the palette
    if drag_win.passed_over_pal:
        # is the cursor over the preview pane?
        if 0 <= pos_x < 4 and 0 <= pos_y < 8:
            drag_win.drag_item.clear()  # wipe duplicates off the palette first
            new_item = drag_win.drag_item.copy(frames['preview'])
            new_item.is_pre = True
            if ind >= len(pal_picked):
                pal_picked.append(new_item)
            else:
                pal_picked.insert(ind, new_item)
            # delete the item - it's fallen off the palette
            if len(pal_picked) > 32:
                pal_picked.pop().kill()
        else:  # drop the item
            if drag_win.from_pal:
                # Only remove if we started on the palette
                drag_win.drag_item.clear()
            snd.fx('delete')

        flow_preview()  # always refresh
    drag_win.drag_item = None


def drag_move(e: tk.Event[tk.Misc]) -> None:
    """Update the position of dragged items as they move around."""
    drag_win: DragWin = windows['drag_win']

    if drag_win.drag_item is None:
        # We aren't dragging, ignore the event.
        return

    set_disp_name(drag_win.drag_item)
    drag_win.geometry('+'+str(e.x_root-32)+'+'+str(e.y_root-32))
    pos_x, pos_y = conv_screen_to_grid(e.x_root, e.y_root)
    if 0 <= pos_x < 4 and 0 <= pos_y < 8:
        drag_win['cursor'] = tk_tools.Cursors.MOVE_ITEM
        UI['pre_sel_line'].place(x=pos_x*65+3, y=pos_y*65+33)
        if not drag_win.passed_over_pal:
            # If we've passed over the palette, replace identical items
            # with movement icons to indicate they will move to the new location
            for item in pal_picked:
                if item.id == drag_win.drag_item.id and item.subKey == drag_win.drag_item.subKey:
                    # We haven't removed the original, so we don't need the
                    # special label for this.
                    # The group item refresh will return this if nothing
                    # changes.
                    TK_IMG.apply(item.label, ICO_MOVING)
                    break

        drag_win.passed_over_pal = True
    else:
        if drag_win.from_pal and drag_win.passed_over_pal:
            drag_win['cursor'] = tk_tools.Cursors.DESTROY_ITEM
        else:
            drag_win['cursor'] = tk_tools.Cursors.INVALID_DRAG
        UI['pre_sel_line'].place_forget()


def drag_fast(drag_item: PalItem, e: tk.Event[tk.Misc]) -> None:
    """Implement shift-clicking.

     When shift-clicking, an item will be immediately moved to the
     palette or deleted from it.
    """
    pos_x, pos_y = conv_screen_to_grid(e.x_root, e.y_root)
    drag_item.clear()
    # Is the cursor over the preview pane?
    if 0 <= pos_x < 4:
        snd.fx('delete')
    else:  # over the picker
        if len(pal_picked) < 32:  # can't copy if there isn't room
            snd.fx('config')
            new_item = drag_item.copy(frames['preview'])
            new_item.is_pre = True
            pal_picked.append(new_item)
        else:
            snd.fx('error')
    flow_preview()


async def set_palette(chosen_pal: paletteUI.Palette) -> None:
    """Select a palette."""
    pal_clear()
    for coord in paletteUI.COORDS:
        try:
            item, sub = chosen_pal.items[coord]
        except KeyError:
            break  # TODO: Handle gaps.
        try:
            item_group = item_list[item]
        except KeyError:
            LOGGER.warning('Unknown item "{}" for palette!', item)
            continue

        if sub not in item_group.visual_subtypes:
            LOGGER.warning(
                'Palette had incorrect subtype {} for "{}"! Valid subtypes: {}!',
                item, sub, item_group.visual_subtypes,
            )
            continue

        pal_picked.append(PalItem(
            frames['preview'],
            item_list[item],
            sub,
            is_pre=True,
        ))

    if chosen_pal.settings is not None:
        LOGGER.info('Settings: {}', chosen_pal.settings)
        await config.APP.apply_multi(chosen_pal.settings)

    flow_preview()


def pal_clear() -> None:
    """Empty the palette."""
    for item in pal_picked[:]:
        item.kill()
    flow_preview()


def pal_shuffle() -> None:
    """Set the palette to a list of random items."""
    mandatory_unlocked = StyleVarPane.mandatory_unlocked()

    if len(pal_picked) == 32:
        return

    palette_set = {
        item.id
        for item in pal_picked
    }

    # Use a set to eliminate duplicates.
    shuff_items = list({
        item.id
        # Only consider items not already on the palette,
        # obey the mandatory item lock and filters.
        for item in pal_items
        if item.id not in palette_set
        if mandatory_unlocked or not item.needs_unlock
        if cur_filter is None or (item.id, item.subKey) in cur_filter
        if item_list[item.id].visual_subtypes  # Check there's actually sub-items to show.
    })

    random.shuffle(shuff_items)

    for item_id in shuff_items[:32-len(pal_picked)]:
        item = item_list[item_id]
        pal_picked.append(PalItem(
            frames['preview'],
            item,
            # Pick a random available palette icon.
            sub=random.choice(item.visual_subtypes),
            is_pre=True,
        ))
    flow_preview()


async def init_option(
    pane: SubPane.SubPane,
    tk_img: TKImages,
    export: Callable[[], object],
    corridor: TkSelector,
) -> None:
    """Initialise the export options pane."""
    pane.columnconfigure(0, weight=1)
    pane.rowconfigure(0, weight=1)

    frame = ttk.Frame(pane)
    frame.grid(row=0, column=0, sticky='nsew')
    frame.columnconfigure(0, weight=1)

    UI['pal_export'] = ttk.Button(frame, command=export)
    UI['pal_export'].state(('disabled',))
    UI['pal_export'].grid(row=4, sticky="EW", padx=5)

    async def game_changed(game: gameMan.Game) -> None:
        """When the game changes, update this button."""
        wid_transtoken.set_text(UI['pal_export'], game.get_export_text())

    await gameMan.ON_GAME_CHANGED.register_and_prime(game_changed)

    props = ttk.Frame(frame, width="50")
    props.columnconfigure(1, weight=1)
    props.grid(row=5, sticky="EW")

    music_frame = ttk.Labelframe(props)
    wid_transtoken.set_text(music_frame, TransToken.ui('Music: '))

    async with trio.open_nursery() as nursery:
        nursery.start_soon(music_conf.make_widgets, packages.get_loaded_packages(), music_frame, pane)
    suggest_windows[packages.Music] = music_conf.WINDOWS[music_conf.MusicChannel.BASE]

    def suggested_style_set() -> None:
        """Set music, skybox, voices, etc to the settings defined for a style."""
        has_suggest = False
        for win in suggest_windows.values():
            win.sel_suggested()
            if win.can_suggest():
                has_suggest = True
        UI['suggested_style'].state(('!disabled', ) if has_suggest else ('disabled', ))

    def suggested_style_mousein(_: tk.Event[tk.Misc]) -> None:
        """When mousing over the button, show the suggested items."""
        for win in suggest_windows.values():
            win.rollover_suggest()

    def suggested_style_mouseout(_: tk.Event[tk.Misc]) -> None:
        """Return text to the normal value on mouseout."""
        for win in suggest_windows.values():
            win.set_disp()

    UI['suggested_style'] = sugg_btn =  ttk.Button(props, command=suggested_style_set)
    # '\u2193' is the downward arrow symbol.
    wid_transtoken.set_text(sugg_btn, TransToken.ui(
        "{down_arrow} Use Suggested {down_arrow}"
    ).format(down_arrow='\u2193'))
    sugg_btn.grid(row=1, column=1, columnspan=2, sticky="EW", padx=0)
    sugg_btn.bind('<Enter>', suggested_style_mousein)
    sugg_btn.bind('<Leave>', suggested_style_mouseout)

    def configure_voice() -> None:
        """Open the voiceEditor window to configure a Quote Pack."""
        try:
            chosen_voice = packages.get_loaded_packages().obj_by_id(packages.QuotePack, voice_win.chosen_id)
        except KeyError:
            pass
        else:
            voiceEditor.show(tk_img, chosen_voice)
    for ind, name in enumerate([
            TransToken.ui("Style: "),
            None,
            TransToken.ui("Voice: "),
            TransToken.ui("Skybox: "),
            TransToken.ui("Elev Vid: "),
            TransToken.ui("Corridor: "),
            ]):
        if name is None:
            # This is the "Suggested" button!
            continue
        wid_transtoken.set_text(ttk.Label(props), name).grid(row=ind)

    voice_frame = ttk.Frame(props)
    voice_frame.columnconfigure(1, weight=1)
    UI['conf_voice'] = ttk.Button(
        voice_frame,
        command=configure_voice,
        width=8,
    )
    UI['conf_voice'].grid(row=0, column=0, sticky='NS')
    tk_img.apply(UI['conf_voice'], ICO_GEAR_DIS)
    tooltip.add_tooltip(
        UI['conf_voice'],
        TransToken.ui('Enable or disable particular voice lines, to prevent them from being added.'),
    )

    if utils.WIN:
        # On Windows, the buttons get inset on the left a bit. Inset everything
        # else to adjust.
        left_pad = (1, 0)
    else:
        left_pad = (0, 0)

    # Make all the selector window textboxes
    (await style_win.widget(props)).grid(row=0, column=1, sticky='EW', padx=left_pad)
    # row=1: Suggested.
    voice_frame.grid(row=2, column=1, sticky='EW')
    (await skybox_win.widget(props)).grid(row=3, column=1, sticky='EW', padx=left_pad)
    (await elev_win.widget(props)).grid(row=4, column=1, sticky='EW', padx=left_pad)
    wid_transtoken.set_text(
        ttk.Button(props, command=lambda: background_run(corridor.show)),
        TransToken.ui('Select'),
    ).grid(row=5, column=1, sticky='EW')
    music_frame.grid(row=6, column=0, sticky='EW', columnspan=2)
    (await voice_win.widget(voice_frame)).grid(row=0, column=1, sticky='EW', padx=left_pad)

    if tk_tools.USE_SIZEGRIP:
        sizegrip = ttk.Sizegrip(props, cursor=tk_tools.Cursors.STRETCH_HORIZ)
        sizegrip.grid(row=2, column=5, rowspan=2, sticky="NS")


def flow_preview() -> None:
    """Position all the preview icons based on the array.

    Run to refresh if items are moved around.
    """
    for i, item in enumerate(pal_picked):
        # These can be used to figure out where it is
        item.pre_x = i % 4
        item.pre_y = i // 4
        item.label.place(x=(i % 4*65 + 4), y=(i // 4*65 + 32))
        # Check to see if this should use the single-icon
        item.load_data()
        item.label.lift()

    item_count = len(pal_picked)
    for ind, fake in enumerate(pal_picked_fake):
        if ind < item_count:
            fake.place_forget()
        else:
            fake.place(x=(ind % 4*65+4), y=(ind//4*65+32))
            fake.lift()
    UI['pre_sel_line'].lift()


def init_preview(tk_img: TKImages, f: Union[tk.Frame, ttk.Frame]) -> None:
    """Generate the preview pane.

     This shows the items that will export to the palette.
    """
    UI['pre_bg_img'] = tk.Label(f, bg=ItemsBG)
    UI['pre_bg_img'].grid(row=0, column=0)
    tk_img.apply(UI['pre_bg_img'], img.Handle.builtin('BEE2/menu', 271, 573))

    UI['pre_disp_name'] = ttk.Label(
        f,
        text="",
        style='BG.TLabel',
        )
    UI['pre_disp_name'].place(x=10, y=554)

    UI['pre_sel_line'] = tk.Label(
        f,
        bg="#F0F0F0",
        borderwidth=0,
        relief="solid",
        )
    tk_img.apply(UI['pre_sel_line'], img.Handle.builtin('BEE2/sel_bar', 4, 64))
    pal_picked_fake.extend([
        tk_img.apply(ttk.Label(frames['preview']), IMG_BLANK)
        for _ in range(32)
    ])

    UI['pre_moving'] = ttk.Label(f)
    tk_img.apply(UI['pre_moving'], ICO_MOVING)

    flow_preview()


async def init_picker(f: Union[tk.Frame, ttk.Frame]) -> None:
    """Construct the frame holding all the items."""
    global frmScroll, pal_canvas
    wid_transtoken.set_text(
        ttk.Label(f, anchor="center"),
        TransToken.ui("All Items: "),
    ).grid(row=0, column=0, sticky="EW")
    UI['picker_frame'] = cframe = ttk.Frame(f, borderwidth=4, relief="sunken")
    cframe.grid(row=1, column=0, sticky="NSEW")
    f.rowconfigure(1, weight=1)
    f.columnconfigure(0, weight=1)

    pal_canvas = tk.Canvas(cframe)
    # need to use a canvas to allow scrolling
    pal_canvas.grid(row=0, column=0, sticky="NSEW")
    cframe.rowconfigure(0, weight=1)
    cframe.columnconfigure(0, weight=1)

    scroll = tk_tools.HidingScroll(
        cframe,
        orient=tk.VERTICAL,
        command=pal_canvas.yview,
    )
    scroll.grid(column=1, row=0, sticky="NS")
    pal_canvas['yscrollcommand'] = scroll.set

    # add another frame inside to place labels on
    frmScroll = ttk.Frame(pal_canvas)
    pal_canvas.create_window(1, 1, window=frmScroll, anchor="nw")

    # Create the items in the palette.
    # Sort by item ID, and then group by package ID.
    # Reverse sort packages so 'Valve' appears at the top..
    items = sorted(item_list.values(), key=operator.attrgetter('id'))
    items.sort(key=operator.attrgetter('pak_id'), reverse=True)

    for item in items:
        await trio.sleep(0)
        for i, subtype in enumerate(item.data.editor.subtypes):
            if subtype.pal_icon or subtype.pal_name:
                pal_items.append(PalItem(frmScroll, item, sub=i, is_pre=False))

    f.bind("<Configure>", lambda e: background_run(
        flow_picker,
        config.APP.get_cur_conf(FilterConf, default=FilterConf()),
    ))
    await config.APP.set_and_run_ui_callback(FilterConf, flow_picker)


async def flow_picker(filter_conf: FilterConf) -> None:
    """Update the picker box so all items are positioned corrctly.

    Should be run (e arg is ignored) whenever the items change, or the
    window changes shape.
    """
    frmScroll.update_idletasks()
    frmScroll['width'] = pal_canvas.winfo_width()
    mandatory_unlocked = StyleVarPane.mandatory_unlocked()

    width = (pal_canvas.winfo_width() - 10) // 65
    if width < 1:
        width = 1  # we got way too small, prevent division by zero

    i = 0
    # If cur_filter is None, it's blank and so show all of them.
    for item in pal_items:
        if item.needs_unlock and not mandatory_unlocked:
            visible = False
        elif filter_conf.compress:
            # Show if this is the first, and any in this item are visible.
            # Visual subtypes should not be empty if we're here, but if so just hide.
            if item.item.visual_subtypes and item.subKey == item.item.visual_subtypes[0]:
                visible = any(
                    (item.item.id, subKey) in cur_filter
                    for subKey in item.item.visual_subtypes
                ) if cur_filter is not None else True
            else:
                visible = False
        else:
            # Uncompressed, check each individually.
            visible = cur_filter is None or (item.item.id, item.subKey) in cur_filter

        if visible:
            item.is_pre = False
            item.load_data()
            item.label.place(
                x=((i % width) * 65 + 1),
                y=((i // width) * 65 + 1),
                )
            i += 1
        else:
            item.label.place_forget()

    num_items = i

    height = int(math.ceil(num_items / width)) * 65 + 2
    pal_canvas['scrollregion'] = (0, 0, width * 65, height)
    frmScroll['height'] = height

    # Now, add extra blank items on the end to finish the grid nicely.
    # pal_items_fake allows us to recycle existing icons.
    last_row = num_items % width
    # Special case, don't add a full row if it's exactly the right count.
    extra_items = (width - last_row) if last_row != 0 else 0

    y = (num_items // width)*65 + 1
    for i in range(extra_items):
        if i >= len(pal_items_fake):
            pal_items_fake.append(TK_IMG.apply(ttk.Label(frmScroll), IMG_BLANK))
        pal_items_fake[i].place(x=((i + last_row) % width)*65 + 1, y=y)

    for item in pal_items_fake[extra_items:]:
        item.place_forget()


def init_drag_icon() -> None:
    """Create the window for rendering held items."""
    drag_win = DragWin(TK_ROOT, name='pal_drag')
    # this prevents stuff like the title bar, normal borders etc from
    # appearing in this window.
    drag_win.overrideredirect(True)
    drag_win.resizable(False, False)
    if utils.LINUX:
        drag_win.wm_attributes('-type', 'dnd')
    drag_win.transient(master=TK_ROOT)
    drag_win.withdraw()  # starts hidden
    drag_win.bind(tk_tools.EVENTS['LEFT_RELEASE'], drag_stop)
    UI['drag_lbl'] = ttk.Label(drag_win)
    TK_IMG.apply(UI['drag_lbl'], IMG_BLANK)
    UI['drag_lbl'].grid(row=0, column=0)
    windows['drag_win'] = drag_win

    drag_win.passed_over_pal = False
    drag_win.from_pal = False
    drag_win.drag_item = None


async def set_game(game: 'gameMan.Game') -> None:
    """Callback for when the game is changed.

    This updates the title bar to match, and saves it into the config.
    """
    wid_transtoken.set_win_title(TK_ROOT, TRANS_MAIN_TITLE.format(version=utils.BEE_VERSION, game=game.name))
    config.APP.store_conf(LastSelected(game.name), 'game')


def refresh_palette_icons() -> None:
    """Refresh all displayed palette icons."""
    for pal_item in itertools.chain(pal_picked, pal_items):
        pal_item.load_data()


async def init_windows(tk_img: TKImages) -> None:
    """Initialise all windows and panes.

    """
    def export() -> None:
        """Export the palette, passing the required UI objects."""
        background_run(export_editoritems, pal_ui, menu_bar, DIALOG)

    menu_bar = MenuBar(TK_ROOT, tk_img=tk_img, export=export)
    TK_ROOT.maxsize(
        width=TK_ROOT.winfo_screenwidth(),
        height=TK_ROOT.winfo_screenheight(),
    )
    gameMan.ON_GAME_CHANGED.register(set_game)
    # Initialise the above and the menu bar.
    await gameMan.ON_GAME_CHANGED(gameMan.selected_game)

    ui_bg = tk.Frame(TK_ROOT, bg=ItemsBG, name='bg')
    ui_bg.grid(row=0, column=0, sticky='NSEW')
    TK_ROOT.columnconfigure(0, weight=1)
    TK_ROOT.rowconfigure(0, weight=1)
    ui_bg.rowconfigure(0, weight=1)

    style = ttk.Style()
    # Custom button style with correct background
    # Custom label style with correct background
    style.configure('BG.TButton', background=ItemsBG)
    style.configure('Preview.TLabel', background='#F4F5F5')

    frames['preview'] = tk.Frame(ui_bg, bg=ItemsBG, name='preview')
    frames['preview'].grid(
        row=0, column=3,
        sticky="NW",
        padx=(2, 5), pady=5,
    )
    init_preview(tk_img, frames['preview'])
    frames['preview'].update_idletasks()
    TK_ROOT.minsize(
        width=frames['preview'].winfo_reqwidth()+200,
        height=frames['preview'].winfo_reqheight()+5,
    )  # Prevent making the window smaller than the preview pane

    await trio.sleep(0)
    await LOAD_UI.step('preview')

    ttk.Separator(ui_bg, orient='vertical').grid(
        row=0, column=4,
        sticky="NS",
        padx=10, pady=10,
    )

    picker_split_frame = tk.Frame(ui_bg, bg=ItemsBG, name='picker_split')
    picker_split_frame.grid(row=0, column=5, sticky="NSEW", padx=5, pady=5)
    ui_bg.columnconfigure(5, weight=1)

    # This will sit on top of the palette section, spanning from left
    # to right
    search_frame = ttk.Frame(
        picker_split_frame,
        name='searchbar',
        padding=5,
        borderwidth=0,
        relief="raised",
    )
    search_frame.grid(row=0, column=0, sticky='ew')

    def update_filter(new_filter: Optional[Set[Tuple[str, int]]]) -> None:
        """Refresh filtered items whenever it's changed."""
        global cur_filter
        cur_filter = new_filter
        background_run(flow_picker, config.APP.get_cur_conf(FilterConf))

    item_search.init(search_frame, update_filter)

    await LOAD_UI.step('filter')

    frames['picker'] = ttk.Frame(
        picker_split_frame,
        name='picker',
        padding=5,
        borderwidth=4,
        relief="raised",
    )
    frames['picker'].grid(row=1, column=0, sticky="NSEW")
    picker_split_frame.rowconfigure(1, weight=1)
    picker_split_frame.columnconfigure(0, weight=1)
    await init_picker(frames['picker'])

    await LOAD_UI.step('picker')

    frames['toolMenu'] = tk.Frame(
        frames['preview'],
        name='toolbar',
        bg=ItemsBG,
        width=192,
        height=26,
        borderwidth=0,
        )
    frames['toolMenu'].place(x=73, y=2)

    windows['pal'] = SubPane.SubPane(
        TK_ROOT, tk_img,
        title=TransToken.ui('Palettes'),
        name='pal',
        menu_bar=menu_bar.view_menu,
        resize_x=True,
        resize_y=True,
        tool_frame=frames['toolMenu'],
        tool_img='icons/win_palette',
        tool_col=10,
    )

    pal_frame = ttk.Frame(windows['pal'], name='pal_frame')
    pal_frame.grid(row=0, column=0, sticky='NSEW')
    windows['pal'].columnconfigure(0, weight=1)
    windows['pal'].rowconfigure(0, weight=1)

    pal_ui = paletteUI.PaletteUI(
        pal_frame, menu_bar.pal_menu,
        tk_img=tk_img,
        cmd_clear=pal_clear,
        cmd_shuffle=pal_shuffle,
        get_items=lambda: {
            pos: (it.id, it.subKey)
            for pos, it in zip(paletteUI.COORDS, pal_picked)
        },
        set_items=set_palette,
    )

    TK_ROOT.bind_all(tk_tools.KEY_SAVE, lambda e: pal_ui.event_save(DIALOG))
    TK_ROOT.bind_all(tk_tools.KEY_SAVE_AS, lambda e: pal_ui.event_save_as(DIALOG))
    TK_ROOT.bind_all(tk_tools.KEY_EXPORT, lambda e: background_run(export_editoritems, pal_ui, menu_bar, DIALOG))

    await LOAD_UI.step('palette')

    packageMan.make_window()

    await LOAD_UI.step('packageman')

    windows['opt'] = SubPane.SubPane(
        TK_ROOT, tk_img,
        title=TransToken.ui('Export Options'),
        name='opt',
        menu_bar=menu_bar.view_menu,
        resize_x=True,
        tool_frame=frames['toolMenu'],
        tool_img='icons/win_options',
        tool_col=11,
    )
    async with trio.open_nursery() as nurs:
        corridor = TkSelector(packages.get_loaded_packages(), tk_img)
        nurs.start_soon(init_option, windows['opt'], tk_img, export, corridor)
    async with trio.open_nursery() as nurs:
        nurs.start_soon(corridor.refresh)
    await LOAD_UI.step('options')

    signage_trigger: EdgeTrigger[()] = EdgeTrigger()
    background_run(signage_ui.init_widgets, tk_img, signage_trigger)

    async with trio.open_nursery() as nurs:
        nurs.start_soon(
            background_start, itemconfig.make_pane,
            frames['toolMenu'], menu_bar.view_menu, tk_img, signage_trigger,
        )
    await LOAD_UI.step('itemvar')

    async with trio.open_nursery() as nurs:
        nurs.start_soon(CompilerPane.make_pane, frames['toolMenu'], tk_img, menu_bar.view_menu)
    await LOAD_UI.step('compiler')

    btn_clear = SubPane.make_tool_button(
        frames['toolMenu'], tk_img,
        img='icons/clear_pal',
        command=pal_clear,
    )
    btn_clear.grid(row=0, column=0, padx=2)
    tooltip.add_tooltip(
        btn_clear,
        TransToken.ui('Remove all items from the palette.'),
    )

    btn_shuffle = SubPane.make_tool_button(
        frames['toolMenu'], tk_img,
        img='icons/shuffle_pal',
        command=pal_shuffle,
    )
    btn_shuffle.grid(
        row=0,
        column=1,
        padx=((2, 5) if utils.MAC else (2, 10)),
    )
    tooltip.add_tooltip(
        btn_shuffle,
        TransToken.ui('Fill empty spots in the palette with random items.'),
    )

    # Make scrollbar work globally
    tk_tools.add_mousewheel(pal_canvas, TK_ROOT)

    # When clicking on any window hide the context window
    hide_ctx_win = contextWin.hide_context
    tk_tools.bind_leftclick(TK_ROOT, hide_ctx_win)
    tk_tools.bind_leftclick(itemconfig.window, hide_ctx_win)
    tk_tools.bind_leftclick(CompilerPane.window, hide_ctx_win)
    tk_tools.bind_leftclick(corridor.win, hide_ctx_win)
    tk_tools.bind_leftclick(windows['opt'], hide_ctx_win)
    tk_tools.bind_leftclick(windows['pal'], hide_ctx_win)

    await trio.sleep(0)
    backup_win.init_toplevel(tk_img)
    await LOAD_UI.step('backup')
    voiceEditor.init_widgets()
    await LOAD_UI.step('voiceline')
    await background_start(contextWin.init_widgets, tk_img, signage_trigger)
    await LOAD_UI.step('contextwin')
    await optionWindow.init_widgets(
        unhide_palettes=pal_ui.reset_hidden_palettes,
        reset_all_win=reset_panes,
    )
    await LOAD_UI.step('optionwindow')
    init_drag_icon()
    await LOAD_UI.step('drag_icon')
    await trio.sleep(0)

    # Load to properly apply config settings, then save to ensure
    # the file has any defaults applied.
    optionWindow.load()
    optionWindow.save()

    TK_ROOT.deiconify()  # show it once we've loaded everything
    windows['pal'].deiconify()
    windows['opt'].deiconify()
    itemconfig.window.deiconify()
    CompilerPane.window.deiconify()

    if utils.MAC:
        TK_ROOT.lift()  # Raise to the top of the stack

    await trio.sleep(0.1)

    # Position windows according to remembered settings:
    try:
        main_win_state = config.APP.get_cur_conf(WindowState, 'main_window')
    except KeyError:
        # We don't have a config, position the window ourselves
        # move the main window if needed to allow room for palette
        if TK_ROOT.winfo_rootx() < windows['pal'].winfo_reqwidth() + 50:
            TK_ROOT.geometry(
                f'+{windows["pal"].winfo_reqwidth() + 50}+{TK_ROOT.winfo_rooty()}'
            )
        else:
            TK_ROOT.geometry(f'+{TK_ROOT.winfo_rootx()}+{TK_ROOT.winfo_rooty()}')
    else:
        start_x, start_y = tk_tools.adjust_inside_screen(
            main_win_state.x, main_win_state.y,
            win=TK_ROOT,
        )
        TK_ROOT.geometry(f'+{start_x}+{start_y}')
    await tk_tools.wait_eventloop()

    # First move to default positions, then load the config.
    # If the config is valid, this will move them to user-defined
    # positions.
    reposition_panes()
    itemconfig.window.load_conf()
    CompilerPane.window.load_conf()
    windows['opt'].load_conf()
    windows['pal'].load_conf()

    async def enable_export() -> None:
        """Enable exporting only after all packages are loaded."""
        packset = packages.get_loaded_packages()
        for cls in packages.OBJ_TYPES.values():
            await packset.ready(cls).wait()
        UI['pal_export'].state(('!disabled',))
        menu_bar.set_export_allowed(True)

    background_run(enable_export)

    def style_select_callback(style_id: Optional[str]) -> None:
        """Callback whenever a new style is chosen."""
        packset = packages.get_loaded_packages()
        global selected_style
        if style_id is None:
            LOGGER.warning('Style ID is None??')
            style_win.sel_item(style_win.item_list[0])
            style_win.set_disp()
            style_id = style_win.item_list[0].name

        selected_style = utils.obj_id(style_id)

        style_obj = current_style()
        for item in item_list.values():
            item.load_data()
        refresh_palette_icons()

        if contextWin.is_visible():
            contextWin.show_prop(contextWin.selected_sub_item)

        # Update variant selectors on the itemconfig pane
        for item_id, func in itemconfig.ITEM_VARIANT_LOAD:
            func()

        # Disable this if the style doesn't have elevators
        elev_win.readonly = not style_obj.has_video

        signage_ui.style_changed(utils.obj_id(style_obj.id))
        item_search.rebuild_database()

        for sugg_cls, win in suggest_windows.items():
            win.set_suggested(style_obj.suggested[sugg_cls])
        suggested_refresh()
        StyleVarPane.refresh(packset, style_obj)
        corridor.load_corridors(packset)
        background_run(corridor.refresh)

    style_win.callback = style_select_callback
    style_select_callback(style_win.chosen_id)
    await set_palette(pal_ui.selected)
    pal_ui.update_state()
