"""Main UI module, brings everything together."""
from tkinter import *  # ui library
from tkinter import ttk  # themed ui components that match the OS
from tkinter import messagebox  # simple, standard modal dialogs
import itertools
import operator
import random
import math

from srctools import Property
from app import music_conf, TK_ROOT
from app.itemPropWin import PROP_TYPES
from BEE2_config import ConfigFile, GEN_OPTS
from app.selector_win import selWin, Item as selWinItem, AttrDef as SelAttr
from loadScreen import main_loader as loader
import srctools.logger
from app import sound as snd
import BEE2_config
from app import paletteLoader
import packages
from app import img
from app import itemconfig
import utils
import consts
from app import (
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
    helpMenu,
    backup as backup_win,
    tooltip,
    signage_ui,
)

from typing import List, Dict, Tuple, Optional, Set, Iterator


LOGGER = srctools.logger.get_logger(__name__)

# Holds the TK Toplevels, frames, widgets and menus
windows = {}
frames = {}
UI = {}
menus = {}

# Items chosen for the palette.
pal_picked = []   # type: List[PalItem]
# Array of the "all items" icons
pal_items = []  # type: List[PalItem]
# Labels used for the empty palette positions
pal_picked_fake = []  # type: List[ttk.Label]
# Labels for empty picker positions
pal_items_fake = []  # type: List[ttk.Label]
# The current filtering state.
cur_filter: Optional[Set[Tuple[str, int]]] = None

ItemsBG = "#CDD0CE"  # Colour of the main background to match the menu image

# Icon shown while items are being moved elsewhere.
ICO_MOVING = img.Handle.builtin('BEE2/item_moving', 64, 64)
ICO_GEAR = img.Handle.sprite('icons/gear', 10, 10)
ICO_GEAR_DIS = img.Handle.sprite('icons/gear_disabled', 10, 10)
IMG_BLANK = img.Handle.color(img.PETI_ITEM_BG, 64, 64)

selected_style = "BEE2_CLEAN"
selectedPalette = 0
# fake value the menu radio buttons set
selectedPalette_radio = IntVar(value=0)
# Variable used for export button (changes to include game name)
EXPORT_CMD_VAR = StringVar(value=_('Export...'))
# If set, save settings into the palette in addition to items.
var_pal_save_settings = BooleanVar(value=True)

# Maps item IDs to our wrapper for the object.
item_list = {}  # type: Dict[str, Item]

item_opts = ConfigFile('item_configs.cfg')
# A config file which remembers changed property options, chosen
# versions, etc

# "Wheel of Dharma" / white sun, close enough and should be
# in most fonts.
CHR_GEAR = '☼ '


class Item:
    """Represents an item that can appear on the list."""
    __slots__ = [
        'ver_list',
        'selected_ver',
        'item',
        'def_data',
        'data',
        'visual_subtypes',
        'authors',
        'id',
        'pak_id',
        'pak_name',
        'names',
        'url',
        ]

    def __init__(self, item: packages.Item) -> None:
        self.ver_list = sorted(item.versions.keys())

        self.selected_ver = item_opts.get_val(
            item.id,
            'sel_version',
            item.def_ver.id,
        )
        # If the last-selected value doesn't exist, fallback to the default.
        if self.selected_ver not in item.versions:
            LOGGER.warning('Version ID {} is not valid for item {}', self.selected_ver, item.id)
            self.selected_ver = item.def_ver.id

        self.item = item
        self.def_data = self.item.def_ver.def_style
        # The indexes of subtypes that are actually visible.
        self.visual_subtypes = [
            ind
            for ind, sub in enumerate(self.def_data.editor.subtypes)
            if sub.pal_name or sub.pal_icon
        ]
        if not self.visual_subtypes:
            # We need at least one subtype, otherwise something's wrong
            # with the file.
            raise Exception('Item {} has no visible subtypes!'.format(item.id))

        self.authors = self.def_data.authors
        self.id = item.id
        self.pak_id = item.pak_id
        self.pak_name = item.pak_name

        self.load_data()

    def load_data(self) -> None:
        """Load data from the item."""
        version = self.item.versions[self.selected_ver]
        self.data = version.styles.get(
            selected_style,
            self.def_data,
        )
        self.url = self.data.url

    def get_tags(self, subtype: int) -> Iterator[str]:
        """Return all the search keywords for this item/subtype."""
        yield self.pak_name
        yield from self.data.tags
        yield from self.data.authors
        try:
            yield gameMan.translate(self.data.editor.subtypes[subtype].name)
        except IndexError:
            LOGGER.warning(
                'No subtype number {} for {} in {} style!',
                subtype, self.id, selected_style,
            )

    def get_icon(self, subKey, allow_single=False, single_num=1) -> img.Handle:
        """Get an icon for the given subkey.

        If allow_single is true, the grouping icon can be returned
        instead if only one item is on the palette.
        Drag-icons have different rules for what counts as 'single', so
        they use the single_num parameter to control the output.
        """
        icons = self.data.icons
        num_picked = sum(
            1 for item in
            pal_picked if
            item.id == self.id
            )
        if allow_single and self.data.can_group() and num_picked <= single_num:
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
            self.pak_id, str(subtype.pal_icon)
        ), 64, 64)

    def properties(self):
        """Iterate through all properties for this item."""
        for prop_name, prop in self.data.editor.properties.items():
            if prop.allow_user_default:
                yield prop_name

    def get_properties(self):
        """Return a dictionary of properties and the current value for them.

        """
        result = {}
        for prop_name, prop in self.data.editor.properties.items():
            if not prop.allow_user_default:
                continue

            # PROP_TYPES is a dict holding all the modifiable properties.
            if prop_name in PROP_TYPES:
                result[prop_name] = item_opts.get_val(
                    self.id,
                    'PROP_' + prop_name,
                    prop.export(),
                )
            else:
                LOGGER.warning(
                    'Unknown property "{}" in {}',
                    prop_name,
                    self.id,
                )
        return result

    def set_properties(self, props):
        """Apply the properties to the item."""
        for prop, value in props.items():
            item_opts[self.id]['PROP_' + prop] = str(value)

    def refresh_subitems(self):
        """Call load_data() on all our subitems, so they reload icons and names.

        """
        for refresh_cmd, subitem_list in [
                (flow_preview, pal_picked),
                (flow_picker, pal_items),
                ]:
            for item in subitem_list:
                if item.id == self.id:
                    item.load_data()
            refresh_cmd()

    def change_version(self, version):
        item_opts[self.id]['sel_version'] = version
        self.selected_ver = version
        self.load_data()
        self.refresh_subitems()

    def get_version_names(self):
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


class PalItem(Label):
    """The icon and associated data for a single subitem."""
    def __init__(self, frame, item: Item, sub: int, is_pre):
        """Create a label to show an item onscreen."""
        super().__init__(frame)
        self.item = item
        self.subKey = sub
        self.id = item.id
        # Used to distinguish between picker and palette items
        self.is_pre = is_pre
        self.needs_unlock = item.item.needs_unlock
        self.load_data()

        self.bind(tk_tools.EVENTS['LEFT'], drag_start)
        self.bind(tk_tools.EVENTS['LEFT_SHIFT'], drag_fast)
        self.bind("<Enter>", self.rollover)
        self.bind("<Leave>", self.rollout)

        self.info_btn = Label(
            self,
            relief='ridge',
            width=12,
            height=12,
        )
        img.apply(self.info_btn, ICO_GEAR)

        click_func = contextWin.open_event(self)
        tk_tools.bind_rightclick(self, click_func)

        @tk_tools.bind_leftclick(self.info_btn)
        def info_button_click(e):
            click_func(e)
            # Cancel the event sequence, so it doesn't travel up to the main
            # window and hide the window again.
            return 'break'

        # Rightclick does the same as the icon.
        tk_tools.bind_rightclick(self.info_btn, click_func)

    def rollover(self, _):
        """Show the name of a subitem and info button when moused over."""
        set_disp_name(self)
        self.lift()
        self['relief'] = 'ridge'
        padding = 2 if utils.WIN else 0
        self.info_btn.place(
            x=self.winfo_width() - padding,
            y=self.winfo_height() - padding,
            anchor=SE,
        )

    def rollout(self, _):
        """Reset the item name display and hide the info button when the mouse leaves."""
        clear_disp_name()
        self['relief'] = 'flat'
        self.info_btn.place_forget()

    def change_subtype(self, ind):
        """Change the subtype of this icon.

        This removes duplicates from the palette if needed.
        """
        for item in pal_picked[:]:
            if item.id == self.id and item.subKey == ind:
                item.kill()
        self.subKey = ind
        self.load_data()
        self.master.update()  # Update the frame
        flow_preview()

    def open_menu_at_sub(self, ind):
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
        self.img = self.item.get_icon(self.subKey, self.is_pre)
        try:
            self.name = gameMan.translate(self.item.data.editor.subtypes[self.subKey].name)
        except IndexError:
            LOGGER.warning(
                'Item <{}> in <{}> style has mismatched subtype count!',
                self.id, selected_style,
            )
            self.name = '??'
        img.apply(self, self.img)

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
        if self in pal_picked:
            pal_picked.remove(self)
        self.place_forget()
        self.destroy()

    def on_pal(self) -> bool:
        """Determine if this item is on the palette."""
        for item in pal_picked:
            if self.id == item.id and self.subKey == item.subKey:
                return True
        return False

    def copy(self, frame):
        return PalItem(frame, self.item, self.subKey, self.is_pre)

    def __repr__(self):
        return '<' + str(self.id) + ":" + str(self.subKey) + '>'


def quit_application() -> None:
    """Do a last-minute save of our config files, and quit the app."""
    import sys, logging

    LOGGER.info('Shutting down application.')

    # If our window isn't actually visible, this is set to nonsense -
    # ignore those values.
    if TK_ROOT.winfo_viewable():
        GEN_OPTS['win_state']['main_window_x'] = str(TK_ROOT.winfo_rootx())
        GEN_OPTS['win_state']['main_window_y'] = str(TK_ROOT.winfo_rooty())

    BEE2_config.write_settings()
    GEN_OPTS.save_check()
    item_opts.save_check()
    CompilerPane.COMPILE_CFG.save_check()
    gameMan.save()

    # Destroy the TK windows, finalise logging, then quit.
    logging.shutdown()
    TK_ROOT.quit()
    sys.exit(0)

gameMan.quit_application = quit_application


def load_settings():
    """Load options from the general config file."""
    global selectedPalette
    try:
        selectedPalette = GEN_OPTS.get_int('Last_Selected', 'palette')
    except (KeyError, ValueError):
        pass  # It'll be set to the first palette by default, and then saved
    selectedPalette_radio.set(selectedPalette)

    optionWindow.load()


@BEE2_config.option_handler('LastSelected')
def save_load_selector_win(props: Property=None):
    """Save and load options on the selector window."""
    sel_win = [
        ('Style', style_win),
        ('Skybox', skybox_win),
        ('Voice', voice_win),
        ('Elevator', elev_win),
    ]
    for channel, win in music_conf.WINDOWS.items():
        sel_win.append(('Music_' + channel.name.title(), win))

    # Saving
    if props is None:
        props = Property('', [])
        for win_name, win in sel_win:
            props.append(Property(win_name, win.chosen_id or '<NONE>'))
        return props

    # Loading
    for win_name, win in sel_win:
        try:
            win.sel_item_id(props[win_name])
        except IndexError:
            pass


def load_packages() -> None:
    """Import in the list of items and styles from the packages.

    A lot of our other data is initialised here too.
    This must be called before initMain() can run.
    """
    global skybox_win, voice_win, style_win, elev_win
    global selected_style

    for item in packages.Item.all():
        item_list[item.id] = Item(item)

    StyleVarPane.add_vars(packages.StyleVar.all(), packages.Style.all())

    sky_list   = []  # type: List[selWinItem]
    voice_list = []  # type: List[selWinItem]
    style_list = []  # type: List[selWinItem]
    elev_list  = []  # type: List[selWinItem]

    # These don't need special-casing, and act the same.
    # The attrs are a map from selectorWin attributes, to the attribute on
    # the object.
    obj_types = [
        (sky_list, packages.Skybox.all(), {
            '3D': 'config',  # Check if it has a config
            'COLOR': 'fog_color',
        }),
        (voice_list, packages.QuotePack.all(), {
            'CHAR': 'chars',
            'MONITOR': 'studio',
            'TURRET': 'turret_hate',
        }),
        (style_list, packages.Style.all(), {
            'VID': 'has_video',
        }),
        (elev_list, packages.Elevator.all(), {
            'ORIENT': 'has_orient',
        }),
    ]

    for sel_list, obj_list, attrs in obj_types:
        attr_commands = [
            # cache the operator.attrgetter funcs
            (key, operator.attrgetter(value))
            for key, value in attrs.items()
        ]
        # Extract the display properties out of the object, and create
        # a SelectorWin item to display with.
        for obj in sorted(obj_list, key=operator.attrgetter('selitem_data.name')):
            sel_list.append(selWinItem.from_data(
                obj.id,
                obj.selitem_data,
                attrs={
                    key: func(obj)
                    for key, func in
                    attr_commands
                }
            ))

    music_conf.load_selitems()

    def win_callback(style_id, win_name):
        """Callback for the selector windows.

        This just refreshes if the 'apply selection' option is enabled.
        """
        suggested_refresh()

    def voice_callback(voice_id):
        """Special callback for the voice selector window.

        The configuration button is disabled when no music is selected.
        """
        # This might be open, so force-close it to ensure it isn't corrupt...
        voiceEditor.save()
        try:
            if voice_id is None:
                UI['conf_voice'].state(['disabled'])
                img.apply(UI['conf_voice'], ICO_GEAR_DIS)
            else:
                UI['conf_voice'].state(['!disabled'])
                img.apply(UI['conf_voice'], ICO_GEAR)
        except KeyError:
            # When first initialising, conf_voice won't exist!
            pass
        suggested_refresh()

    skybox_win = selWin(
        TK_ROOT,
        sky_list,
        title=_('Select Skyboxes'),
        desc=_('The skybox decides what the area outside the chamber is like.'
               ' It chooses the colour of sky (seen in some items), the style'
               ' of bottomless pit (if present), as well as color of "fog" '
               '(seen in larger chambers).'),
        has_none=False,
        callback=win_callback,
        callback_params=['Skybox'],
        attributes=[
            SelAttr.bool('3D', _('3D Skybox'), False),
            SelAttr.color('COLOR', _('Fog Color')),
        ],
    )

    voice_win = selWin(
        TK_ROOT,
        voice_list,
        title=_('Select Additional Voice Lines'),
        desc=_('Voice lines choose which extra voices play as the player enters'
               ' or exits a chamber. They are chosen based on which items are'
               ' present in the map. The additional "Multiverse" Cave lines'
               ' are controlled separately in Style Properties.'),
        has_none=True,
        none_desc=_('Add no extra voice lines, only Multiverse Cave if enabled.'),
        none_attrs={
            'CHAR': [_('<Multiverse Cave only>')],
        },
        callback=voice_callback,
        attributes=[
            SelAttr.list('CHAR', _('Characters'), ['??']),
            SelAttr.bool('TURRET', _('Turret Shoot Monitor'), False),
            SelAttr.bool('MONITOR', _('Monitor Visuals'), False),
        ],
    )

    style_win = selWin(
        TK_ROOT,
        style_list,
        title=_('Select Style'),
        desc=_('The Style controls many aspects of the map. It decides the '
               'materials used for walls, the appearance of entrances and '
               'exits, the design for most items as well as other settings.\n\n'
               'The style broadly defines the time period a chamber is set in.'),
        has_none=False,
        has_def=False,
        # Selecting items changes much of the gui - don't allow when other
        # things are open..
        modal=True,
        # callback set in the main initialisation function..
        attributes=[
            SelAttr.bool('VID', _('Elevator Videos'), default=True),
        ]
    )

    elev_win = selWin(
        TK_ROOT,
        elev_list,
        title=_('Select Elevator Video'),
        desc=_('Set the video played on the video screens in modern Aperture '
               'elevator rooms. Not all styles feature these. If set to '
               '"None", a random video will be selected each time the map is '
               'played, like in the default PeTI.'),
        readonly_desc=_('This style does not have a elevator video screen.'),
        has_none=True,
        has_def=True,
        none_icon=img.Handle.builtin('BEE2/random', 96, 96),
        none_name=_('Random'),
        none_desc=_('Choose a random video.'),
        callback=win_callback,
        callback_params=['Elevator'],
        attributes=[
            SelAttr.bool('ORIENT', _('Multiple Orientations')),
        ]
    )

    # Defaults, which will be reset at the end.
    selected_style = 'BEE2_CLEAN'
    style_win.sel_item_id('BEE2_CLEAN')

    voice_win.sel_suggested()
    skybox_win.sel_suggested()
    elev_win.sel_suggested()
    for win in music_conf.WINDOWS.values():
        win.sel_suggested()


def current_style() -> packages.Style:
    """Return the currently selected style."""
    return packages.Style.by_id(selected_style)


def reposition_panes() -> None:
    """Position all the panes in the default places around the main window."""
    comp_win = CompilerPane.window
    style_win = StyleVarPane.window
    opt_win = windows['opt']
    pal_win = windows['pal']
    # The x-pos of the right side of the main window
    xpos = min(
        TK_ROOT.winfo_screenwidth()
        - style_win.winfo_reqwidth(),

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
        width=style_win.winfo_reqwidth())
    style_win.move(
        x=xpos,
        y=TK_ROOT.winfo_rooty() + opt_win.winfo_reqheight() + 25)


def reset_panes():
    reposition_panes()
    windows['pal'].save_conf()
    windows['opt'].save_conf()
    StyleVarPane.window.save_conf()
    CompilerPane.window.save_conf()


def suggested_refresh():
    """Enable or disable the suggestion setting button."""
    if 'suggested_style' in UI:
        windows = [
            voice_win,
            skybox_win,
            elev_win,
        ]
        windows.extend(music_conf.WINDOWS.values())
        if all(win.is_suggested() for win in windows):
            UI['suggested_style'].state(['disabled'])
        else:
            UI['suggested_style'].state(['!disabled'])


def refresh_pal_ui() -> None:
    """Update the UI to show the correct palettes."""
    global selectedPalette
    cur_palette = paletteLoader.pal_list[selectedPalette]
    paletteLoader.pal_list.sort(key=str)  # sort by name
    selectedPalette = paletteLoader.pal_list.index(cur_palette)

    listbox = UI['palette']  # type: Listbox
    listbox.delete(0, END)

    for i, pal in enumerate(paletteLoader.pal_list):
        if pal.settings is not None:
            listbox.insert(i, CHR_GEAR + pal.name)
        else:
            listbox.insert(i, pal.name)

        if pal.prevent_overwrite:
            listbox.itemconfig(
                i,
                foreground='grey',
                background=tk_tools.LISTBOX_BG_COLOR,
                selectbackground=tk_tools.LISTBOX_BG_SEL_COLOR,
            )
        else:
            listbox.itemconfig(
                i,
                foreground='black',
                background=tk_tools.LISTBOX_BG_COLOR,
                selectbackground=tk_tools.LISTBOX_BG_SEL_COLOR,
            )

    if len(paletteLoader.pal_list) < 2 or cur_palette.prevent_overwrite:
        UI['pal_remove'].state(('disabled',))
        UI['pal_save'].state(('disabled', ))  # Save As only.
        menus['pal'].entryconfigure(menus['pal_delete_ind'], state=DISABLED)
        menus['pal'].entryconfigure(menus['pal_save_ind'], state=DISABLED)
    else:
        UI['pal_remove'].state(('!disabled',))
        UI['pal_save'].state(('!disabled', ))
        menus['pal'].entryconfigure(menus['pal_delete_ind'], state=NORMAL)
        menus['pal'].entryconfigure(menus['pal_save_ind'], state=NORMAL)

    for ind in range(menus['pal'].index(END), 0, -1):
        # Delete all the old radiobuttons
        # Iterate backward to ensure indexes stay the same.
        if menus['pal'].type(ind) == RADIOBUTTON:
            menus['pal'].delete(ind)
    # Add a set of options to pick the palette into the menu system
    for val, pal in enumerate(paletteLoader.pal_list):
        menus['pal'].add_radiobutton(
            label=(
                pal.name if pal.settings is None
                else CHR_GEAR + pal.name
            ),
            variable=selectedPalette_radio,
            value=val,
            command=set_pal_radio,
            )
    selectedPalette_radio.set(selectedPalette)


def export_editoritems(e=None):
    """Export the selected Items and Style into the chosen game."""

    # Convert IntVar to boolean, and only export values in the selected style
    style_vals = StyleVarPane.tk_vars
    chosen_style = current_style()
    style_vars = {
        var.id: (style_vals[var.id].get() == 1)
        for var in
        StyleVarPane.VAR_LIST
        if var.applies_to_style(chosen_style)
    }

    # Add all of the special/hardcoded style vars
    for var in StyleVarPane.styleOptions:
        style_vars[var.id] = style_vals[var.id].get() == 1

    # The chosen items on the palette
    pal_data = [(it.id, it.subKey) for it in pal_picked]

    item_versions = {
        it_id: item.selected_ver
        for it_id, item in
        item_list.items()
    }

    item_properties = {
        it_id: {
            key[5:]: value
            for key, value in
            section.items() if
            key.startswith('prop_')
        }
        for it_id, section in
        item_opts.items()
    }

    success, vpk_success = gameMan.selected_game.export(
        style=chosen_style,
        selected_objects={
            # Specify the 'chosen item' for each object type
            packages.Music: music_conf.export_data(),
            packages.Skybox: skybox_win.chosen_id,
            packages.QuotePack: voice_win.chosen_id,
            packages.Elevator: elev_win.chosen_id,

            packages.Item: (pal_data, item_versions, item_properties),
            packages.StyleVar: style_vars,
            packages.Signage: signage_ui.export_data(),

            # The others don't have one, so it defaults to None.
        },
        should_refresh=not GEN_OPTS.get_bool(
            'General',
            'preserve_BEE2_resource_dir',
            False,
        )
    )

    if not success:
        return

    export_filename = 'LAST_EXPORT' + paletteLoader.PAL_EXT

    for pal in paletteLoader.pal_list[:]:
        if pal.filename == export_filename:
            paletteLoader.pal_list.remove(pal)

    new_pal = paletteLoader.Palette(
        '??',
        pal_data,
        # This makes it lookup the translated name
        # instead of using a configured one.
        trans_name='LAST_EXPORT',
        # Use a specific filename - this replaces existing files.
        filename=export_filename,
        # And prevent overwrite
        prevent_overwrite=True,
        )
    paletteLoader.pal_list.append(new_pal)
    new_pal.save(ignore_readonly=True)

    # Save the configs since we're writing to disk lots anyway.
    GEN_OPTS.save_check()
    item_opts.save_check()
    BEE2_config.write_settings()

    message = _('Selected Items and Style successfully exported!')
    if not vpk_success:
        message += _(
            '\n\nWarning: VPK files were not exported, quit Portal 2 and '
            'Hammer to ensure editor wall previews are changed.'
        )

    chosen_action = optionWindow.AfterExport(optionWindow.AFTER_EXPORT_ACTION.get())
    want_launch = optionWindow.LAUNCH_AFTER_EXPORT.get()

    if want_launch or chosen_action is not optionWindow.AfterExport.NORMAL:
        do_action = messagebox.askyesno(
            'BEEMOD2',
            message + optionWindow.AFTER_EXPORT_TEXT[chosen_action, want_launch],
            parent=TK_ROOT,
        )
    else:  # No action to do, so just show an OK.
        messagebox.showinfo('BEEMOD2', message, parent=TK_ROOT)
        do_action = False

    # Do the desired action - if quit, we don't bother to update UI.
    if do_action:
        # Launch first so quitting doesn't affect this.
        if want_launch:
            gameMan.selected_game.launch()

        if chosen_action is optionWindow.AfterExport.NORMAL:
            pass
        elif chosen_action is optionWindow.AfterExport.MINIMISE:
            TK_ROOT.iconify()
        elif chosen_action is optionWindow.AfterExport.QUIT:
            quit_application()
            # We never return from this.
        else:
            raise ValueError('Unknown action "{}"'.format(chosen_action))

    # Select the last_export palette, so reloading loads this item selection.
    paletteLoader.pal_list.sort(key=str)
    selectedPalette_radio.set(paletteLoader.pal_list.index(new_pal))
    set_pal_radio()

    # Re-set this, so we clear the '*' on buttons if extracting cache.
    set_game(gameMan.selected_game)

    refresh_pal_ui()


def set_disp_name(item, e=None) -> None:
    UI['pre_disp_name'].configure(text=item.name)


def clear_disp_name(e=None) -> None:
    UI['pre_disp_name'].configure(text='')


def conv_screen_to_grid(x: float, y: float) -> Tuple[int, int]:
    """Returns the location of the item hovered over on the preview pane."""
    return (
        (x-UI['pre_bg_img'].winfo_rootx()-8) // 65,
        (y-UI['pre_bg_img'].winfo_rooty()-32) // 65,
    )


def drag_start(e: Event) -> None:
    """Start dragging a palette item."""
    drag_win = windows['drag_win']
    drag_win.drag_item = e.widget
    set_disp_name(drag_win.drag_item)
    snd.fx('config')
    drag_win.passed_over_pal = False
    if drag_win.drag_item.is_pre:  # is the cursor over the preview pane?
        drag_win.drag_item.kill()
        UI['pre_moving'].place(
            x=drag_win.drag_item.pre_x*65 + 4,
            y=drag_win.drag_item.pre_y*65 + 32,
        )
        drag_win.from_pal = True

        for item in pal_picked:
            if item.id == drag_win.drag_item.id:
                item.load_data()

        # When dragging off, switch to the single-only icon
        img.apply(UI['drag_lbl'], drag_win.drag_item.item.get_icon(
            drag_win.drag_item.subKey,
            allow_single=False,
        ))
    else:
        drag_win.from_pal = False
        img.apply(UI['drag_lbl'], drag_win.drag_item.item.get_icon(
            drag_win.drag_item.subKey,
            allow_single=True,
            single_num=0,
        ))
    drag_win.deiconify()
    drag_win.lift(TK_ROOT)
    # grab makes this window the only one to receive mouse events, so
    # it is guaranteed that it'll drop when the mouse is released.
    drag_win.grab_set_global()
    # NOTE: _global means no other programs can interact, make sure
    # it's released eventually or you won't be able to quit!
    drag_move(e)  # move to correct position
    drag_win.bind(tk_tools.EVENTS['LEFT_MOVE'], drag_move)
    UI['pre_sel_line'].lift()


def drag_stop(e) -> None:
    """User released the mouse button, complete the drag."""
    drag_win = windows['drag_win']

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


def drag_move(e):
    """Update the position of dragged items as they move around."""
    drag_win = windows['drag_win']

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
                    img.apply(item, ICO_MOVING)
                    break

        drag_win.passed_over_pal = True
    else:
        if drag_win.from_pal and drag_win.passed_over_pal:
            drag_win['cursor'] = tk_tools.Cursors.DESTROY_ITEM
        else:
            drag_win['cursor'] = tk_tools.Cursors.INVALID_DRAG
        UI['pre_sel_line'].place_forget()


def drag_fast(e):
    """Implement shift-clicking.

     When shift-clicking, an item will be immediately moved to the
     palette or deleted from it.
    """
    pos_x, pos_y = conv_screen_to_grid(e.x_root, e.y_root)
    e.widget.clear()
    # Is the cursor over the preview pane?
    if 0 <= pos_x < 4:
        snd.fx('delete')
        flow_picker()
    else:  # over the picker
        if len(pal_picked) < 32:  # can't copy if there isn't room
            snd.fx('config')
            new_item = e.widget.copy(frames['preview'])
            new_item.is_pre = True
            pal_picked.append(new_item)
        else:
            snd.fx('error')
    flow_preview()


def set_pal_radio():
    global selectedPalette
    selectedPalette = selectedPalette_radio.get()
    set_pal_listbox_selection()
    set_palette()


def set_pal_listbox_selection(e=None):
    """Select the currently chosen palette in the listbox."""
    UI['palette'].selection_clear(0, len(paletteLoader.pal_list))
    UI['palette'].selection_set(selectedPalette)


def set_palette(e=None):
    """Select a palette."""
    global selectedPalette
    if selectedPalette >= len(paletteLoader.pal_list) or selectedPalette < 0:
        LOGGER.warning('Invalid palette index!')
        selectedPalette = 0

    chosen_pal = paletteLoader.pal_list[selectedPalette]

    GEN_OPTS['Last_Selected']['palette'] = str(selectedPalette)
    pal_clear()
    menus['pal'].entryconfigure(
        1,
        label=_('Delete Palette "{}"').format(chosen_pal.name),
    )
    for item, sub in chosen_pal.pos:
        try:
            item_group = item_list[item]
        except KeyError:
            LOGGER.warning('Unknown item "{}"! for palette', item)
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
        BEE2_config.apply_settings(chosen_pal.settings)

    if len(paletteLoader.pal_list) < 2 or paletteLoader.pal_list[selectedPalette].prevent_overwrite:
        UI['pal_remove'].state(('disabled',))
        UI['pal_save'].state(('disabled', ))  # Save As only.
        menus['pal'].entryconfigure(menus['pal_delete_ind'], state=DISABLED)
        menus['pal'].entryconfigure(menus['pal_save_ind'], state=DISABLED)
    else:
        UI['pal_remove'].state(('!disabled',))
        UI['pal_save'].state(('!disabled', ))
        menus['pal'].entryconfigure(menus['pal_delete_ind'], state=NORMAL)
        menus['pal'].entryconfigure(menus['pal_save_ind'], state=NORMAL)

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


def pal_save_as(e: Event=None) -> None:
    """Save the palette with a new name."""
    while True:
        name = tk_tools.prompt(
            _("BEE2 - Save Palette"),
            _("Enter a name:"),
        )
        if name is None:
            # Cancelled...
            return
        elif paletteLoader.check_exists(name):
            if messagebox.askyesno(
                icon=messagebox.QUESTION,
                title='BEE2',
                message=_('This palette already exists. Overwrite?'),
            ):
                break
        else:
            break
    paletteLoader.save_pal(
        [(it.id, it.subKey) for it in pal_picked],
        name,
        var_pal_save_settings.get(),
    )
    refresh_pal_ui()


def pal_save(e=None) -> None:
    """Save the current palette over the original name."""
    pal = paletteLoader.pal_list[selectedPalette]
    if pal.prevent_overwrite:
        pal_save_as()
    else:
        paletteLoader.save_pal(
            [(it.id, it.subKey) for it in pal_picked],
            pal.name,
            var_pal_save_settings.get(),
        )
        refresh_pal_ui()


def pal_remove() -> None:
    global selectedPalette
    pal = paletteLoader.pal_list[selectedPalette]
    # Don't delete if there's only 1, or it's readonly.
    if len(paletteLoader.pal_list) < 2 or pal.prevent_overwrite:
        return

    if messagebox.askyesno(
        title='BEE2',
        message=_('Are you sure you want to delete "{}"?').format(
            pal.name,
        ),
        parent=TK_ROOT,
    ):
        pal.delete_from_disk()
        del paletteLoader.pal_list[selectedPalette]
        selectedPalette -= 1
        selectedPalette_radio.set(selectedPalette)
        refresh_pal_ui()
        set_palette()


# UI functions, each accepts the parent frame to place everything in.
# initMainWind generates the main frames that hold all the panes to
# make it easy to move them around if needed


def init_palette(f) -> None:
    """Initialises the palette pane.

    This lists all saved palettes and lets users choose from the list.
    """
    f.rowconfigure(1, weight=1)
    f.columnconfigure(0, weight=1)

    ttk.Button(
        f,
        text=_('Clear Palette'),
        command=pal_clear,
        ).grid(row=0, sticky="EW")

    UI['palette'] = listbox = Listbox(f, width=10)
    listbox.grid(row=1, sticky="NSEW")

    def set_pal_listbox(e=None):
        global selectedPalette
        cur_selection = listbox.curselection()
        if cur_selection:  # Might be blank if none selected
            selectedPalette = int(cur_selection[0])
            selectedPalette_radio.set(selectedPalette)

            # Actually set palette..
            set_palette()
        else:
            listbox.selection_set(selectedPalette, selectedPalette)

    listbox.bind("<<ListboxSelect>>", set_pal_listbox)
    listbox.bind("<Enter>", set_pal_listbox_selection)

    # Set the selected state when hovered, so users can see which is
    # selected.
    listbox.selection_set(0)

    pal_scroll = tk_tools.HidingScroll(
        f,
        orient=VERTICAL,
        command=listbox.yview,
    )
    pal_scroll.grid(row=1, column=1, sticky="NS")
    UI['palette']['yscrollcommand'] = pal_scroll.set

    UI['pal_remove'] = ttk.Button(
        f,
        text=_('Delete Palette'),
        command=pal_remove,
    )
    UI['pal_remove'].grid(row=2, sticky="EW")

    if tk_tools.USE_SIZEGRIP:
        ttk.Sizegrip(f).grid(row=2, column=1)


def init_option(pane: SubPane) -> None:
    """Initialise the options pane."""
    pane.columnconfigure(0, weight=1)
    pane.rowconfigure(0, weight=1)

    frame = ttk.Frame(pane)
    frame.grid(row=0, column=0, sticky=NSEW)
    frame.columnconfigure(0, weight=1)

    UI['pal_save'] = ttk.Button(
        frame,
        text=_("Save Palette..."),
        command=pal_save,
    )
    UI['pal_save'].grid(row=0, sticky="EW", padx=5)
    ttk.Button(
        frame,
        text=_("Save Palette As..."),
        command=pal_save_as,
    ).grid(row=1, sticky="EW", padx=5)

    def save_settings_changed() -> None:
        GEN_OPTS['General'][
            'palette_save_settings'
        ] = srctools.bool_as_int(var_pal_save_settings.get())

    ttk.Checkbutton(
        frame,
        text=_('Save Settings in Palettes'),
        variable=var_pal_save_settings,
        command=save_settings_changed,
    ).grid(row=2, sticky="EW", padx=5)
    var_pal_save_settings.set(GEN_OPTS.get_bool('General', 'palette_save_settings'))

    ttk.Separator(frame, orient='horizontal').grid(row=3, sticky="EW")

    ttk.Button(
        frame,
        textvariable=EXPORT_CMD_VAR,
        command=export_editoritems,
    ).grid(row=4, sticky="EW", padx=5)

    props = ttk.Frame(frame, width="50")
    props.columnconfigure(1, weight=1)
    props.grid(row=5, sticky="EW")

    music_frame = ttk.Labelframe(props, text=_('Music: '))
    music_win = music_conf.make_widgets(music_frame, pane)

    def suggested_style_set():
        """Set music, skybox, voices, etc to the settings defined for a style.

        """
        sugg = current_style().suggested
        win_types = (voice_win, music_win, skybox_win, elev_win)
        for win, sugg_val in zip(win_types, sugg):
            win.sel_item_id(sugg_val)
        UI['suggested_style'].state(['disabled'])

    def suggested_style_mousein(_):
        """When mousing over the button, show the suggested items."""
        for win in (voice_win, music_win, skybox_win, elev_win):
            win.rollover_suggest()

    def suggested_style_mouseout(_):
        """Return text to the normal value on mouseout."""
        for win in (voice_win, music_win, skybox_win, elev_win):
            win.set_disp()

    UI['suggested_style'] = ttk.Button(
        props,
        # '\u2193' is the downward arrow symbol.
        text=_("{arr} Use Suggested {arr}").format(arr='\u2193'),
        command=suggested_style_set,
        )
    UI['suggested_style'].grid(row=1, column=1, columnspan=2, sticky="EW", padx=0)
    UI['suggested_style'].bind('<Enter>', suggested_style_mousein)
    UI['suggested_style'].bind('<Leave>', suggested_style_mouseout)

    def configure_voice():
        """Open the voiceEditor window to configure a Quote Pack."""
        try:
            chosen_voice = packages.QuotePack.by_id(voice_win.chosen_id)
        except KeyError:
            pass
        else:
            voiceEditor.show(chosen_voice)
    for ind, name in enumerate([
            _("Style: "),
            None,
            _("Voice: "),
            _("Skybox: "),
            _("Elev Vid: "),
            ]):
        if name is None:
            # This is the "Suggested" button!
            continue
        ttk.Label(props, text=name).grid(row=ind)

    voice_frame = ttk.Frame(props)
    voice_frame.columnconfigure(1, weight=1)
    UI['conf_voice'] = ttk.Button(
        voice_frame,
        command=configure_voice,
        width=8,
        )
    UI['conf_voice'].grid(row=0, column=0, sticky='NS')
    img.apply(UI['conf_voice'], ICO_GEAR_DIS)
    tooltip.add_tooltip(
        UI['conf_voice'],
        _('Enable or disable particular voice lines, to prevent them from '
          'being added.'),
    )
    
    if utils.WIN:
        # On windows, the buttons get inset on the left a bit. Inset everything
        # else to adjust.
        left_pad = (1, 0)
    else:
        left_pad = 0

    # Make all the selector window textboxes
    style_win.widget(props).grid(row=0, column=1, sticky='EW', padx=left_pad)
    # row=1: Suggested.
    voice_frame.grid(row=2, column=1, sticky='EW')
    skybox_win.widget(props).grid(row=3, column=1, sticky='EW', padx=left_pad)
    elev_win.widget(props).grid(row=4, column=1, sticky='EW', padx=left_pad)
    music_frame.grid(row=5, column=0, sticky='EW', columnspan=2)

    voice_win.widget(voice_frame).grid(row=0, column=1, sticky='EW', padx=left_pad)

    if tk_tools.USE_SIZEGRIP:
        sizegrip = ttk.Sizegrip(props, cursor=tk_tools.Cursors.STRETCH_HORIZ)
        sizegrip.grid(row=2, column=5, rowspan=2, sticky="NS")


def flow_preview():
    """Position all the preview icons based on the array.

    Run to refresh if items are moved around.
    """
    for i, item in enumerate(pal_picked):
        # these can be referred to to figure out where it is
        item.pre_x = i % 4
        item.pre_y = i // 4
        item.place(x=(i % 4*65 + 4), y=(i // 4*65 + 32))
        # Check to see if this should use the single-icon
        item.load_data()
        item.lift()

    item_count = len(pal_picked)
    for ind, fake in enumerate(pal_picked_fake):
        if ind < item_count:
            fake.place_forget()
        else:
            fake.place(x=(ind % 4*65+4), y=(ind//4*65+32))
            fake.lift()
    UI['pre_sel_line'].lift()


def init_preview(f):
    """Generate the preview pane.

     This shows the items that will export to the palette.
    """
    UI['pre_bg_img'] = Label(f, bg=ItemsBG)
    UI['pre_bg_img'].grid(row=0, column=0)
    img.apply(UI['pre_bg_img'], img.Handle.builtin('BEE2/menu', 271, 563))

    UI['pre_disp_name'] = ttk.Label(
        f,
        text="",
        style='BG.TLabel',
        )
    UI['pre_disp_name'].place(x=10, y=552)

    UI['pre_sel_line'] = Label(
        f,
        bg="#F0F0F0",
        borderwidth=0,
        relief="solid",
        )
    img.apply(UI['pre_sel_line'], img.Handle.builtin('BEE2/sel_bar', 4, 64))
    pal_picked_fake.extend([
        img.apply(ttk.Label(frames['preview']), IMG_BLANK)
        for _ in range(32)
    ])

    UI['pre_moving'] = ttk.Label(f)
    img.apply(UI['pre_moving'], ICO_MOVING)

    flow_preview()


def init_picker(f):
    global frmScroll, pal_canvas
    ttk.Label(
        f,
        text=_("All Items: "),
        anchor="center",
    ).grid(
        row=0,
        column=0,
        sticky="EW",
    )
    UI['picker_frame'] = cframe = ttk.Frame(
        f,
        borderwidth=4,
        relief="sunken",
        )
    cframe.grid(row=1, column=0, sticky="NSEW")
    f.rowconfigure(1, weight=1)
    f.columnconfigure(0, weight=1)

    pal_canvas = Canvas(cframe)
    # need to use a canvas to allow scrolling
    pal_canvas.grid(row=0, column=0, sticky="NSEW")
    cframe.rowconfigure(0, weight=1)
    cframe.columnconfigure(0, weight=1)

    scroll = tk_tools.HidingScroll(
        cframe,
        orient=VERTICAL,
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
        for i, subtype in enumerate(item.data.editor.subtypes):
            if subtype.pal_icon or subtype.pal_name:
                pal_items.append(PalItem(frmScroll, item, sub=i, is_pre=False))

    f.bind("<Configure>", flow_picker)


def flow_picker(e=None):
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
    for item in pal_items:
        if item.needs_unlock and not mandatory_unlocked:
            visible = False
        elif cur_filter is None:
            visible = True
        else:
            visible = (item.item.id, item.subKey) in cur_filter

        if visible:
            item.is_pre = False
            item.place(
                x=((i % width) * 65 + 1),
                y=((i // width) * 65 + 1),
                )
            i += 1
        else:
            item.place_forget()

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
        if i not in pal_items_fake:
            pal_items_fake.append(img.apply(ttk.Label(frmScroll), IMG_BLANK))
        pal_items_fake[i].place(x=((i + last_row) % width)*65 + 1, y=y)

    for item in pal_items_fake[extra_items:]:
        item.place_forget()


def init_drag_icon() -> None:
    drag_win = Toplevel(TK_ROOT)
    # this prevents stuff like the title bar, normal borders etc from
    # appearing in this window.
    drag_win.overrideredirect(True)
    drag_win.resizable(False, False)
    drag_win.withdraw()
    drag_win.transient(master=TK_ROOT)
    drag_win.withdraw()  # starts hidden
    drag_win.bind(tk_tools.EVENTS['LEFT_RELEASE'], drag_stop)
    UI['drag_lbl'] = Label(drag_win)
    img.apply(UI['drag_lbl'], IMG_BLANK)
    UI['drag_lbl'].grid(row=0, column=0)
    windows['drag_win'] = drag_win

    drag_win.passed_over_pal = False  # has the cursor passed over the palette
    drag_win.from_pal = False  # are we dragging a palette item?
    drag_win.drag_item = None  # the item currently being moved


def set_game(game: 'gameMan.Game'):
    """Callback for when the game is changed.

    This updates the title bar to match, and saves it into the config.
    """
    TK_ROOT.title('BEEMOD {} - {}'.format(utils.BEE_VERSION, game.name))
    GEN_OPTS['Last_Selected']['game'] = game.name
    text = _('Export to "{}"...').format(game.name)

    if game.cache_invalid():
        # Mark that it needs extractions
        text += ' *'

    menus['file'].entryconfigure(
        menus['file'].export_btn_index,
        label=text,
    )
    EXPORT_CMD_VAR.set(text)


def init_menu_bar(win: Toplevel) -> Menu:
    """Create the top menu bar.

    This returns the View menu, for later population.
    """
    bar = Menu(win)
    # Suppress ability to make each menu a separate window - weird old
    # TK behaviour
    win.option_add('*tearOff', '0')
    if utils.MAC:
        # Name is used to make this the special 'BEE2' menu item
        file_menu = menus['file'] = Menu(bar, name='apple')
    else:
        file_menu = menus['file'] = Menu(bar)

    bar.add_cascade(menu=file_menu, label=_('File'))

    # Assign the bar as the main window's menu.
    # Must be done after creating the apple menu.
    win['menu'] = bar

    file_menu.add_command(
        label=_("Export"),
        command=export_editoritems,
        accelerator=tk_tools.ACCEL_EXPORT,
    )
    file_menu.export_btn_index = 0  # Change this if the menu is reordered

    file_menu.add_command(
        label=_("Add Game"),
        command=gameMan.add_game,
    )
    file_menu.add_command(
        label=_("Uninstall from Selected Game"),
        command=gameMan.remove_game,
        )
    file_menu.add_command(
        label=_("Backup/Restore Puzzles..."),
        command=backup_win.show_window,
    )
    file_menu.add_command(
        label=_("Manage Packages..."),
        command=packageMan.show,
    )
    file_menu.add_separator()
    file_menu.add_command(
        label=_("Options"),
        command=optionWindow.show,
    )
    if not utils.MAC:
        file_menu.add_command(
            label=_("Quit"),
            command=quit_application,
            )
    file_menu.add_separator()
    # Add a set of options to pick the game into the menu system
    gameMan.add_menu_opts(menus['file'], callback=set_game)
    gameMan.game_menu = menus['file']

    pal_menu = menus['pal'] = Menu(bar)
    # Menu name
    bar.add_cascade(menu=pal_menu, label=_('Palette'))
    pal_menu.add_command(
        label=_('Clear'),
        command=pal_clear,
        )
    pal_menu.add_command(
        # Placeholder..
        label=_('Delete Palette'),  # This name is overwritten later
        command=pal_remove,
        )
    menus['pal_delete_ind'] = pal_menu.index('end')
    pal_menu.add_command(
        label=_('Fill Palette'),
        command=pal_shuffle,
    )

    pal_menu.add_separator()

    pal_menu.add_checkbutton(
        label=_('Save Settings in Palettes'),
        variable=var_pal_save_settings,
    )

    pal_menu.add_separator()

    pal_menu.add_command(
        label=_('Save Palette'),
        command=pal_save,
        accelerator=tk_tools.ACCEL_SAVE,
    )
    menus['pal_save_ind'] = pal_menu.index('end')
    pal_menu.add_command(
        label=_('Save Palette As...'),
        command=pal_save_as,
        accelerator=tk_tools.ACCEL_SAVE_AS,
    )

    pal_menu.add_separator()

    # refresh_pal_ui() adds the palette menu options here.

    view_menu = Menu(bar)
    bar.add_cascade(menu=view_menu, label=_('View'))

    win.bind_all(tk_tools.KEY_SAVE, pal_save)
    win.bind_all(tk_tools.KEY_SAVE_AS, pal_save_as)
    win.bind_all(tk_tools.KEY_EXPORT, export_editoritems)

    helpMenu.make_help_menu(bar)

    return view_menu


def init_windows() -> None:
    """Initialise all windows and panes.

    """
    view_menu = init_menu_bar(TK_ROOT)
    TK_ROOT.maxsize(
        width=TK_ROOT.winfo_screenwidth(),
        height=TK_ROOT.winfo_screenheight(),
        )
    TK_ROOT.protocol("WM_DELETE_WINDOW", quit_application)

    if utils.MAC:
        # OS X has a special quit menu item.
        TK_ROOT.createcommand('tk::mac::Quit', quit_application)

    ui_bg = Frame(TK_ROOT, bg=ItemsBG)
    ui_bg.grid(row=0, column=0, sticky='NSEW')
    TK_ROOT.columnconfigure(0, weight=1)
    TK_ROOT.rowconfigure(0, weight=1)
    ui_bg.rowconfigure(0, weight=1)

    style = ttk.Style()
    # Custom button style with correct background
    # Custom label style with correct background
    style.configure('BG.TButton', background=ItemsBG)
    style.configure('Preview.TLabel', background='#F4F5F5')

    frames['preview'] = Frame(ui_bg, bg=ItemsBG)
    frames['preview'].grid(
        row=0,
        column=3,
        sticky="NW",
        padx=(2, 5),
        pady=5,
    )
    init_preview(frames['preview'])
    frames['preview'].update_idletasks()
    TK_ROOT.minsize(
        width=frames['preview'].winfo_reqwidth()+200,
        height=frames['preview'].winfo_reqheight()+5,
    )  # Prevent making the window smaller than the preview pane

    loader.step('UI')

    ttk.Separator(
        ui_bg,
        orient=VERTICAL,
    ).grid(
        row=0,
        column=4,
        sticky="NS",
        padx=10,
        pady=10,
    )

    picker_split_frame = Frame(ui_bg, bg=ItemsBG)
    picker_split_frame.grid(row=0, column=5, sticky="NSEW", padx=5, pady=5)
    ui_bg.columnconfigure(5, weight=1)

    # This will sit on top of the palette section, spanning from left
    # to right
    search_frame = ttk.Frame(
        picker_split_frame,
        padding=5,
        borderwidth=0,
        relief="raised",
    )
    search_frame.grid(row=0, column=0, sticky='ew')

    def update_filter(new_filter: Optional[Set[Tuple[str, int]]]) -> None:
        """Refresh filtered items whenever it's changed."""
        global cur_filter
        cur_filter = new_filter
        flow_picker()

    item_search.init(search_frame, update_filter)

    loader.step('UI')

    frames['picker'] = ttk.Frame(
        picker_split_frame,
        padding=5,
        borderwidth=4,
        relief="raised",
    )
    frames['picker'].grid(row=1, column=0, sticky="NSEW")
    picker_split_frame.rowconfigure(1, weight=1)
    picker_split_frame.columnconfigure(0, weight=1)
    init_picker(frames['picker'])

    loader.step('UI')

    frames['toolMenu'] = Frame(
        frames['preview'],
        bg=ItemsBG,
        width=192,
        height=26,
        borderwidth=0,
        )
    frames['toolMenu'].place(x=73, y=2)

    windows['pal'] = SubPane.SubPane(
        TK_ROOT,
        title=_('Palettes'),
        name='pal',
        menu_bar=view_menu,
        resize_x=True,
        resize_y=True,
        tool_frame=frames['toolMenu'],
        tool_img='icons/win_palette',
        tool_col=1,
    )

    pal_frame = ttk.Frame(windows['pal'])
    pal_frame.grid(row=0, column=0, sticky='NSEW')
    windows['pal'].columnconfigure(0, weight=1)
    windows['pal'].rowconfigure(0, weight=1)

    init_palette(pal_frame)

    loader.step('UI')

    packageMan.make_window()

    loader.step('UI')

    windows['opt'] = SubPane.SubPane(
        TK_ROOT,
        title=_('Export Options'),
        name='opt',
        menu_bar=view_menu,
        resize_x=True,
        tool_frame=frames['toolMenu'],
        tool_img='icons/win_options',
        tool_col=2,
    )
    init_option(windows['opt'])

    loader.step('UI')

    StyleVarPane.make_pane(frames['toolMenu'], view_menu, flow_picker)

    loader.step('UI')

    CompilerPane.make_pane(frames['toolMenu'], view_menu)

    loader.step('UI')

    UI['shuffle_pal'] = SubPane.make_tool_button(
        frame=frames['toolMenu'],
        img='icons/shuffle_pal',
        command=pal_shuffle,
    )
    UI['shuffle_pal'].grid(
        row=0,
        column=0,
        padx=((2, 10) if utils.MAC else (2, 20)),
    )
    tooltip.add_tooltip(
        UI['shuffle_pal'],
        _('Fill empty spots in the palette with random items.'),
    )

    # Make scrollbar work globally
    tk_tools.add_mousewheel(pal_canvas, TK_ROOT)

    # When clicking on any window hide the context window
    tk_tools.bind_leftclick(TK_ROOT, contextWin.hide_context)
    tk_tools.bind_leftclick(StyleVarPane.window, contextWin.hide_context)
    tk_tools.bind_leftclick(CompilerPane.window, contextWin.hide_context)
    tk_tools.bind_leftclick(windows['opt'], contextWin.hide_context)
    tk_tools.bind_leftclick(windows['pal'], contextWin.hide_context)

    backup_win.init_toplevel()
    loader.step('UI')
    voiceEditor.init_widgets()
    loader.step('UI')
    contextWin.init_widgets()
    loader.step('UI')
    optionWindow.init_widgets()
    loader.step('UI')
    init_drag_icon()
    loader.step('UI')

    optionWindow.reset_all_win = reset_panes

    # Load to properly apply config settings, then save to ensure
    # the file has any defaults applied.
    optionWindow.load()
    optionWindow.save()

    TK_ROOT.deiconify()  # show it once we've loaded everything
    windows['pal'].deiconify()
    windows['opt'].deiconify()
    StyleVarPane.window.deiconify()
    CompilerPane.window.deiconify()

    if utils.MAC:
        TK_ROOT.lift()  # Raise to the top of the stack

    TK_ROOT.update_idletasks()
    StyleVarPane.window.update_idletasks()
    CompilerPane.window.update_idletasks()
    windows['opt'].update_idletasks()
    windows['pal'].update_idletasks()

    TK_ROOT.after(50, set_pal_listbox_selection)
    # This needs some time for the listbox to appear first

    # Position windows according to remembered settings:
    try:
        start_x = int(GEN_OPTS['win_state']['main_window_x'])
        start_y = int(GEN_OPTS['win_state']['main_window_y'])
    except (ValueError, KeyError):
        # We don't have a config, position the window ourselves
        # move the main window if needed to allow room for palette
        if TK_ROOT.winfo_rootx() < windows['pal'].winfo_reqwidth() + 50:
            TK_ROOT.geometry(
                '+' + str(windows['pal'].winfo_reqwidth() + 50) +
                '+' + str(TK_ROOT.winfo_rooty())
                )
        else:
            TK_ROOT.geometry(
                '+' + str(TK_ROOT.winfo_rootx()) +
                '+' + str(TK_ROOT.winfo_rooty())
                )
    else:
        start_x, start_y = utils.adjust_inside_screen(
            start_x,
            start_y,
            win=TK_ROOT,
            )
        TK_ROOT.geometry('+' + str(start_x) + '+' + str(start_y))
    TK_ROOT.update_idletasks()

    # First move to default positions, then load the config.
    # If the config is valid, this will move them to user-defined
    # positions.
    reposition_panes()
    StyleVarPane.window.load_conf()
    CompilerPane.window.load_conf()
    windows['opt'].load_conf()
    windows['pal'].load_conf()

    def style_select_callback(style_id: str) -> None:
        """Callback whenever a new style is chosen."""
        global selected_style
        selected_style = style_id

        style_obj = current_style()

        for item in itertools.chain(item_list.values(), pal_picked, pal_items):
            item.load_data()  # Refresh everything

        # Update variant selectors on the itemconfig pane
        for func in itemconfig.ITEM_VARIANT_LOAD:
            func()

        # Disable this if the style doesn't have elevators
        elev_win.readonly = not style_obj.has_video

        signage_ui.style_changed(style_obj)
        item_search.rebuild_database()
        CompilerPane.set_corridors(style_obj.corridors)

        sugg = style_obj.suggested
        win_types = (
            voice_win,
            music_conf.WINDOWS[consts.MusicChannel.BASE],
            skybox_win,
            elev_win,
        )
        for win, sugg_val in zip(win_types, sugg):
            win.set_suggested(sugg_val)
        suggested_refresh()
        StyleVarPane.refresh(style_obj)

    style_win.callback = style_select_callback
    style_select_callback(style_win.chosen_id)
    img.start_loading()
    set_palette()
    # Set_palette needs to run first, so it can fix invalid palette indexes.
    BEE2_config.read_settings()
    refresh_pal_ui()
