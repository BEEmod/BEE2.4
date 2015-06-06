from tkinter import *  # ui library
from tkinter import ttk  # themed ui components that match the OS
from tkinter import messagebox  # simple, standard modal dialogs
from tk_root import TK_ROOT
from functools import partial as func_partial
import itertools
import operator

from query_dialogs import ask_string
from itemPropWin import PROP_TYPES
from BEE2_config import ConfigFile, GEN_OPTS

import sound as snd
from loadScreen import main_loader as loader
import paletteLoader
import img
import utils

from SubPane import SubPane
from selectorWin import selWin, Item as selWinItem
import voiceEditor
import contextWin
import gameMan
import StyleVarPane
import CompilerPane

# Holds the TK Toplevels, frames, widgets and menus
windows = {}
frames = {}
UI = {}
menus = {}

pal_picked = []  # array of the picker icons
pal_items = []  # array of the "all items" icons
pal_picked_fake = []  # Labels used for the empty palette positions
pal_items_fake = []  # Labels for empty picker positions


FILTER_CATS = ('author', 'package', 'tags')
FilterBoxes = {}  # the various checkboxes for the filters
FilterBoxes_all = {}
FilterVars = {}  # The variables for the checkboxes
FilterVars_all = {}

ItemsBG = "#CDD0CE"  # Colour of the main background to match the menu image


selected_style = "BEE2_CLEAN"
selectedPalette = 0
# fake value the menu radio buttons set
selectedPalette_radio = IntVar(value=0)

muted = IntVar(value=0)  # Is the sound fx muted?
show_wip_items = IntVar(value=0)

# All the stuff we've loaded in
item_list = {}
skyboxes = {}
voices = {}
styles = {}
musics = {}
elevators = {}

item_opts = ConfigFile('item_configs.cfg')
# A config file which remembers changed property options, chosen
# versions, etc


class Item:
    """Represents an item that can appear on the list."""
    __slots__ = [
        'ver_list',
        'selected_ver',
        'item',
        'def_data',
        'data',
        'num_sub',
        'authors',
        'tags',
        'id',
        'pak_id',
        'pak_name',
        'names',
        'is_dep',
        'is_wip',
        'url',
        'can_group',
        ]

    def __init__(self, item):
        self.ver_list = sorted(item.versions.keys())

        self.selected_ver = item_opts.get_val(item.id, 'sel_version', item.def_ver['id'])
        if self.selected_ver not in item.versions:
            self.selected_ver = self.def_ver['id']

        self.item = item
        self.def_data = self.item.def_ver['def_style']
        # These pieces of data are constant, only from the first style.
        self.num_sub = sum(
            1 for _ in
            self.def_data['editor'].find_all(
                "Editor",
                "Subtype",
                "Palette",
                )
            )
        self.authors = self.def_data['auth']
        self.tags = self.def_data['tags']

        self.load_data()

        self.id = item.id
        self.pak_id = item.pak_id
        self.pak_name = item.pak_name
        self.set_properties(self.get_properties())

    def load_data(self):
        """Load data from the item."""
        version = self.item.versions[self.selected_ver]
        self.data = version['styles'].get(
            selected_style,
            self.def_data,
            )
        self.names = [
            gameMan.translate(prop['name', ''])
            for prop in
            self.data['editor'].find_all("Editor", "Subtype")
            if prop['Palette', None] is not None
        ]
        self.is_dep = version['is_dep']
        self.is_wip = version['is_wip']
        self.url = self.data['url']

        # This checks to see if all the data is present to enable
        # grouped items
        self.can_group = ('all' in self.data['icons'] and
                          self.data['all_name'] is not None and
                          self.data['all_icon'] is not None)

    def get_icon(self, subKey, allow_single=False, single_num=1):
        """Get an icon for the given subkey.

        If allow_single is true, the grouping icon can be returned
        instead if only one item is on the palette.
        Drag-icons have different rules for what counts as 'single', so
        they use the single_num parameter to control the output.
        """
        icons = self.data['icons']
        num_picked = sum(
            1 for item in
            pal_picked if
            item.id == self.id
            )
        if allow_single and self.can_group and num_picked <= single_num:
            # If only 1 copy of this item is on the palette, use the
            # special icon
            return img.icon(icons['all'])
        else:
            return img.icon(icons[str(subKey)])

    def properties(self):
        """Iterate through all properties for this item."""
        for part in self.data['editor'].find_all("Properties"):
            for prop in part:
                yield prop.name

    def get_properties(self):
        """Return a dictionary of properties and the current value for them.

        """
        result = {}
        for part in self.data['editor'].find_all("Properties"):
            for prop in part:
                name = prop.name
                # PROP_TYPES is a dict holding all the modifiable properties.
                if name not in result and name in PROP_TYPES:
                    result[name] = item_opts.get_val(
                        self.id,
                        'PROP_' + name,
                        prop["DefaultValue", ''],
                        )
        return result

    def set_properties(self, props):
        """Apply the properties to the item."""
        for prop, value in props.items():
            for def_prop in self.data['editor'].find_all(
                    "Properties",
                    prop,
                    'DefaultValue',
                    ):
                def_prop.value = str(value)
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
        vers = []
        for ver_id in self.ver_list:
            ver = self.item.versions[ver_id]
            name = ver['name']

            if ver['is_dep']:
                name = '[DEP] ' + name

            if ver['is_wip']:
                # We always display the currently selected version, so
                # it's possible to deselect it.
                if ver_id != self.selected_ver and not show_wip_items.get():
                    continue
                name = '[WIP] ' + name
            vers.append(name)
        return self.ver_list, vers

    def export(self):
        """Generate the editoritems and vbsp_config data for this item.

        """
        self.load_data()

        # Build a dictionary of this item's palette positions,
        # if any exist.
        palette_items = {
            item.subKey: item
            for item in pal_picked
            if item.id == self.id
        }

        new_editor = self.data['editor'].copy()

        new_editor['type'] = self.id # Set the item ID to match our item
        # This allows the folders to be reused for different items if needed.

        for index, editor_section in enumerate(
                new_editor.find_all("Editor", "Subtype")):
            # For each subtype, see if it's on the palette
            for editor_sec_index, pal_section in enumerate(
                    editor_section):
                # We need to manually loop so we get the index of the palette
                # property block in the section
                if pal_section.name == "palette":
                    if index in palette_items:
                        if len(palette_items) == 1:
                            # Switch to the 'Grouped' icon
                            if self.data['all_name'] is not None:
                                pal_section['Tooltip'] = self.data['all_name']
                            if self.data['all_icon'] is not None:
                                pal_section['Image'] = self.data['all_icon']
                        pal_section['Position'] = (
                            str(palette_items[index].pre_x) + " " +
                            str(palette_items[index].pre_y) + " 0"
                            )
                    else:
                        del editor_section[editor_sec_index]
                        break

        return new_editor, self.data['editor_extra'], self.data['vbsp']


class PalItem(Label):
    """The icon and associated data for a single subitem."""
    def __init__(self, frame, item, sub, is_pre):
        """Create a label to show an item onscreen."""
        super().__init__(
            frame,
            font=("Courier", 24, "bold"),
            foreground='red',
            )
        self.item = item
        self.subKey = sub
        self.id = item.id
        # Toggled according to filter settings
        self.visible = True
        # Used to distinguish between picker and palette items
        self.is_pre = is_pre
        self.needs_unlock = item.item.needs_unlock
        self.load_data()
        self.bind("<Button-3>", contextWin.open_event)
        self.bind("<Button-1>", drag_start)
        self.bind("<Shift-Button-1>", drag_fast)
        self.bind("<Enter>", self.rollover)
        self.bind("<Leave>", self.rollout)

    def rollover(self, _):
        set_disp_name(self)
        self.lift()
        self['relief'] = 'ridge'

    def rollout(self, _):
        clear_disp_name()
        self['relief'] = 'flat'

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

    def load_data(self):
        """Refresh our icon and name.

        Call whenever the style changes, so the icons update.
        """
        self.img = self.item.get_icon(self.subKey, self.is_pre)
        self.name = gameMan.translate(self.item.names[self.subKey])
        self['image'] = self.img
        # Put a large D over the item if it's deprecated.
        if self.item.is_dep:
            self['text'] = 'OLD'
            self['compound'] = 'center'
        else:
            self['compound'] = 'none'
            self['text'] = None

    def clear(self):
        """Remove any items matching ourselves from the palette.

        This prevents adding two copies.
        """
        found = False
        for item in pal_picked[:]:
            # remove the item off of the palette if it's on there, this
            # lets you delete items and prevents having the same item twice.
            if self == item:
                item.kill()
                found = True
        return found

    def kill(self):
        """Hide and destroy this widget."""
        if self in pal_picked:
            pal_picked.remove(self)
        self.place_forget()
        self.destroy()

    def on_pal(self):
        """Determine if this item is on the palette."""
        for item in pal_picked:
            if self == item:
                return True
        return False

    def __eq__(self, other):
        """Two items are equal if they have the same item and sub-item index.

        """
        return self.id == other.id and self.subKey == other.subKey

    def copy(self, frame):
        return PalItem(frame, self.item, self.subKey, self.is_pre)

    def __repr__(self):
        return '<' + str(self.id) + ":" + str(self.subKey) + '>'


def quit_application():
    """Do a last-minute save of our config files, and quit the app."""
    GEN_OPTS['win_state']['main_window_x'] = str(TK_ROOT.winfo_rootx())
    GEN_OPTS['win_state']['main_window_y'] = str(TK_ROOT.winfo_rooty())

    GEN_OPTS.save_check()
    item_opts.save_check()
    CompilerPane.COMPILE_CFG.save_check()
    # Destroy the TK windows
    TK_ROOT.destroy()
    exit(0)


def set_mute():
    """Apply the muted setting based on the variable."""
    snd.muted = (muted.get() == 1)
    GEN_OPTS['General']['mute_sounds'] = str(muted.get())


def load_palette(data):
    """Import in all defined palettes."""
    global palettes
    palettes = data


def load_settings(settings):
    """Load options from the general config file."""
    global GEN_OPTS
    GEN_OPTS = settings

    show_wip_items.set(GEN_OPTS.get_bool(
        'General',
        'show_wip_items',
        False
        ))

    muted.set(GEN_OPTS.get_bool(
        'General',
        'mute_sounds',
        False,
        ))
    set_mute()
    try:
        selectedPalette_radio.set(int(GEN_OPTS['Last_Selected']['palette']))
    except (KeyError, ValueError):
        pass  # It'll be set to the first palette by default, and then saved
    GEN_OPTS.has_changed = False


def load_packages(data):
    """Import in the list of items and styles from the packages.

    A lot of our other data is initialised here too.
    This must be called before initMain() can run.
    """
    global skybox_win, voice_win, music_win, style_win, elev_win
    global item_list, filter_data
    global selected_style

    filter_data = {
        'package': {},
        'author': {},
        'tags': {},
    }

    for item in data['Item']:
        it = Item(item)
        item_list[it.id] = it
        for tag in it.tags:
            if tag.casefold() not in filter_data['tags']:
                filter_data['tags'][tag.casefold()] = tag
        for auth in it.authors:
            if auth.casefold() not in filter_data['author']:
                filter_data['author'][auth.casefold()] = auth
        if it.pak_id not in filter_data['package']:
            filter_data['package'][it.pak_id] = it.pak_name
        loader.step("IMG")

    StyleVarPane.add_vars(data['StyleVar'])

    sky_list = []
    voice_list = []
    style_list = []
    music_list = []
    elev_list = []

    # These don't need special-casing, and act the same.
    obj_types = [
        (sky_list, skyboxes, 'Skybox'),
        (voice_list, voices, 'QuotePack'),
        (style_list, styles, 'Style'),
        (music_list, musics, 'Music'),
        (elev_list, elevators, 'Elevator'),
        ]
    for sel_list, obj_list, name in obj_types:
        # Extract the display properties out of the object, and create
        # a SelectorWin item to display with.
        for obj in sorted(data[name], key=operator.attrgetter('name')):
            sel_list.append(selWinItem(
                obj.id,
                obj.short_name,
                long_name=obj.name,
                icon=obj.icon,
                authors=obj.auth,
                desc=obj.desc,
            ))
            obj_list[obj.id] = obj
            # Every item has an image
            loader.step("IMG")

    def win_callback(style_id, win_name):
        """Callback for the selector windows.

        This saves into the config file the last selected item.
        """
        if style_id is None:
            style_id = '<NONE>'
        GEN_OPTS['Last_Selected'][win_name] = style_id
        suggested_refresh()

    def voice_callback(style_id):
        """Special callback for the voice selector window.

        The configuration button is disabled whin no music is selected.
        """
        try:
            if style_id is None:
                style_id = '<NONE>'
                UI['conf_voice'].state(['disabled'])
                UI['conf_voice']['image'] = img.png('icons/gear_disabled')
            else:
                UI['conf_voice'].state(['!disabled'])
                UI['conf_voice']['image'] = img.png('icons/gear')
        except KeyError:
            # When first initialising, conf_voice won't exist!
            pass
        GEN_OPTS['Last_Selected']['Voice'] = style_id
        suggested_refresh()

    skybox_win = selWin(
        TK_ROOT,
        sky_list,
        title='Select Skyboxes',
        has_none=False,
        callback=win_callback,
        callback_params=['Skybox'],
        )

    voice_win = selWin(
        TK_ROOT,
        voice_list,
        title='Select Additional Voice Lines',
        has_none=True,
        none_desc='Add no extra voice lines.',
        callback=voice_callback,
        )

    music_win = selWin(
        TK_ROOT,
        music_list,
        title='Select Background Music',
        has_none=True,
        none_desc='Add no music to the map at all.',
        callback=win_callback,
        callback_params=['Music'],
        )

    style_win = selWin(
        TK_ROOT,
        style_list,
        title='Select Style',
        has_none=False,
        has_def=False,
        )

    elev_win = selWin(
        TK_ROOT,
        elev_list,
        title='Select Elevator Video',
        has_none=True,
        has_def=True,
        none_desc='Chose a random video.',
        callback=win_callback,
        callback_params=['Elevator'],
    )

    last_style = GEN_OPTS.get_val('Last_Selected', 'Style', 'BEE2_CLEAN')
    if last_style in style_win:
        style_win.sel_item_id(last_style)
        selected_style = last_style
    else:
        selected_style = 'BEE2_CLEAN'
        style_win.sel_item_id('BEE2_CLEAN')

    obj_types = [
        (voice_win, 'Voice'),
        (music_win, 'Music'),
        (skybox_win, 'Skybox'),
        (elev_win, 'Elevator'),
        ]
    for (sel_win, opt_name), default in zip(
            obj_types,
            styles[selected_style].suggested,
            ):
        sel_win.sel_item_id(
            GEN_OPTS.get_val('Last_Selected', opt_name, default)
        )


def suggested_refresh():
    """Enable or disable the suggestion setting button."""
    if 'suggested_style' in UI:
        if (
                voice_win.is_suggested() and
                music_win.is_suggested() and
                skybox_win.is_suggested() and
                elev_win.is_suggested()
                ):
            UI['suggested_style'].state(['disabled'])
        else:
            UI['suggested_style'].state(['!disabled'])


def refresh_pal_ui():
    """Update the UI to show the correct palettes."""
    palettes.sort(key=str)  # sort by name
    UI['palette'].delete(0, END)
    for i, pal in enumerate(palettes):
        UI['palette'].insert(i, pal.name)

    for ind in range(menus['pal'].index(END), 0, -1):
        # Delete all the old radiobuttons
        # Iterate backward to ensure indexes stay the same.
        if menus['pal'].type(ind) == RADIOBUTTON:
            menus['pal'].delete(ind)
    # Add a set of options to pick the palette into the menu system
    for val, pal in enumerate(palettes):
        menus['pal'].add_radiobutton(
            label=pal.name,
            variable=selectedPalette_radio,
            value=val,
            command=set_pal_radio,
            )
    if len(palettes) < 2:
        UI['pal_remove'].state(('disabled',))
        menus['pal'].entryconfigure(1, state=DISABLED)
    else:
        UI['pal_remove'].state(('!disabled',))
        menus['pal'].entryconfigure(1, state=NORMAL)


def export_editoritems(_=None):
    """Export the selected Items and Style into the chosen game."""

    # Convert IntVar to boolean, and only export values in the selected style
    style_vals = StyleVarPane.tk_vars
    chosen_style = styles[selected_style]
    style_vars = {
        var.id: (style_vals[var.id].get() == 1)
        for var in
        StyleVarPane.var_list
        if var.applies_to_style(chosen_style)
    }

    for var_id, _, __ in StyleVarPane.styleOptions:
        style_vars[var_id] = style_vals[var_id].get() == 1

    gameMan.selected_game.export(
        chosen_style,
        item_list,
        music=musics.get(music_win.chosen_id, None),
        skybox=skyboxes.get(skybox_win.chosen_id, None),
        voice=voices.get(voice_win.chosen_id, None),
        elevator=elevators.get(elev_win.chosen_id, None),
        style_vars=style_vars,
        )
    messagebox.showinfo(
        'BEEMOD2',
        message='Selected Items and Style successfully exported!',
        )

    if not GEN_OPTS.get_bool('General', 'preserve_BEE2_resource_dir', False):
        print('Copying resources...')
        gameMan.selected_game.refresh_cache()
        print('Done!')

    for pal in palettes[:]:
        if pal.name == '<Last Export>':
            palettes.remove(pal)
    new_pal = paletteLoader.Palette(
        '<Last Export>',
        [(it.id, it.subKey) for it in pal_picked],
        options={},
        filename='LAST_EXPORT.zip',
        )

    # Save the configs since we're writing to disk anyway.
    GEN_OPTS.save_check()
    item_opts.save_check()

    # Since last_export is a zip, users won't be able to overwrite it
    # normally!
    palettes.append(new_pal)
    new_pal.save(allow_overwrite=True)
    refresh_pal_ui()


def set_disp_name(item, _=None):
    UI['pre_disp_name'].configure(text='Item: '+item.name)


def clear_disp_name(_=None):
    UI['pre_disp_name'].configure(text='')


def conv_screen_to_grid(x, y):
    """Returns the location of the item hovered over on the preview pane."""
    return (
        (x-UI['pre_bg_img'].winfo_rootx()-8) // 65,
        (y-UI['pre_bg_img'].winfo_rooty()-32) // 65,
    )


def drag_start(e):
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
        UI['drag_lbl']['image'] = drag_win.drag_item.item.get_icon(
            drag_win.drag_item.subKey,
            allow_single=False,
            )
    else:
        drag_win.from_pal = False
        UI['drag_lbl']['image'] = drag_win.drag_item.item.get_icon(
            drag_win.drag_item.subKey,
            allow_single=True,
            single_num=0,
            )
    drag_win.deiconify()
    drag_win.lift(TK_ROOT)
    # grab makes this window the only one to receive mouse events, so
    # it is guaranteed that it'll drop when the mouse is released.
    drag_win.grab_set_global()
    # NOTE: _global means no other programs can interact, make sure
    # it's released eventually or you won't be able to quit!
    drag_move(e)  # move to correct position
    drag_win.bind("<B1-Motion>", drag_move)
    UI['pre_sel_line'].lift()


def drag_stop(e):
    """User released the mouse button, complete the drag."""
    drag_win = windows['drag_win']
    drag_win.withdraw()
    drag_win.unbind("<B1-Motion>")
    drag_win.grab_release()
    clear_disp_name()
    UI['pre_sel_line'].place_forget()
    snd.fx('config')

    pos_x, pos_y = conv_screen_to_grid(e.x_root, e.y_root)
    ind = pos_x+pos_y*4

    # this prevents a single click on the picker from clearing items
    # off the palette
    if drag_win.passed_over_pal:
        # is the cursor over the preview pane?
        if 0 <= pos_x < 4:
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
    set_disp_name(drag_win.drag_item)
    drag_win.geometry('+'+str(e.x_root-32)+'+'+str(e.y_root-32))
    pos_x, pos_y = conv_screen_to_grid(e.x_root, e.y_root)
    if 0 <= pos_x < 4 and 0 <= pos_y < 8:
        drag_win.configure(cursor='plus')
        UI['pre_sel_line'].place(x=pos_x*65+3, y=pos_y*65+33)
        if not drag_win.passed_over_pal:
            # If we've passed over the palette, replace identical items
            # with movement icons to indicate they will move to the new location
            for item in pal_picked:
                if item == drag_win.drag_item:
                    # We haven't removed the original, so we don't need the
                    # special label for this.
                    # The group item refresh will return this if nothing
                    # changes.
                    item['image'] = img.png('BEE2/item_moving')
                    break

        drag_win.passed_over_pal = True
    else:
        if drag_win.from_pal and drag_win.passed_over_pal:
            drag_win.configure(cursor='x_cursor')
        else:
            drag_win.configure(cursor='no')
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
        print('flowing')
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


def set_pal_listbox_selection(_=None):
    """Select the currently chosen palette in the listbox."""
    UI['palette'].selection_clear(0, len(palettes))
    UI['palette'].selection_set(selectedPalette)


def set_palette(_=None):
    """Select a palette."""
    GEN_OPTS['Last_Selected']['palette'] = str(selectedPalette)
    pal_clear()
    menus['pal'].entryconfigure(
        1,
        label='Delete Palette "'
        + palettes[selectedPalette].name
        + '"',
        )
    for item, sub in palettes[selectedPalette].pos:
        if item in item_list.keys():
            pal_picked.append(PalItem(
                frames['preview'],
                item_list[item],
                sub,
                is_pre=True
                ))
        else:
            print('Unknown item "' + item + '"!')
    flow_preview()


def pal_clear():
    """Empty the palette."""
    for item in pal_picked:
        item.kill()
    pal_picked.clear()
    flow_preview()


def pal_save_as(_=None):
    name = ""
    while True:
        name = ask_string(
            "BEE2 - Save Palette",
            "Enter a name:",
            )
        if name is None:
            return False
        # Check for non-basic characters
        elif not utils.is_plain_text(name):
            messagebox.showinfo(
                icon=messagebox.ERROR,
                title='BEE2',
                message='Please only use basic characters in palette '
                        'names.',
                parent=TK_ROOT,
                )
        else:
            break
    paletteLoader.save_pal(pal_picked, name)
    refresh_pal_ui()


def pal_save(_=None):
    pal = palettes[selectedPalette]
    pal.pos = [(it.id, it.subKey) for it in pal_picked]
    pal.save(allow_overwrite=True)  # overwrite it
    refresh_pal_ui()


def pal_remove():
    global selectedPalette
    if len(palettes) >= 2:
        pal = palettes[selectedPalette]
        if messagebox.askyesno(
                title='BEE2',
                message='Are you sure you want to delete "'
                        + pal.name + '"?',
                parent=TK_ROOT,
                ):
            pal.delete_from_disk()
            del palettes[selectedPalette]
            selectedPalette -= 1
            selectedPalette_radio.set(selectedPalette)
            refresh_pal_ui()


def update_filters():
    # First update the 'all' checkboxes to make half-selected if not
    # fully selected.
    for cat in FILTER_CATS:  # do for each
        no_alt = True
        all_vars = iter(FilterVars[cat].values())

        # Pull the first one to get the compare value, this will check
        # if they are all the same
        value = next(all_vars).get()
        for var in all_vars:
            if var.get() != value:
                # force it to be true so when clicked it'll blank out
                # all the checkboxes
                FilterVars_all[cat].set(True)
                # make it the half-selected state, since they don't
                # match
                FilterBoxes_all[cat].state(['alternate'])
                no_alt = False
                break
        if no_alt:  # no alternate if they are all the same
            FilterBoxes_all[cat].state(['!alternate'])
            FilterVars_all[cat].set(value)
    show_wip = show_wip_items.get()
    style_unlocked = StyleVarPane.tk_vars['UnlockDefault'].get() == 1
    for item in pal_items:
        item.visible = (
            # Items are hidden if it's a wip item and the option is
            # deselected
            (show_wip or not item.item.is_wip)
            # Visible if any of the author and tag checkboxes are checked
            and any(
                FilterVars['author'][auth.casefold()].get()
                for auth in item.item.authors
                )
            and any(
                FilterVars['tags'][tag.casefold()].get()
                for tag in item.item.tags
                )
            # The package is selected
            and FilterVars['package'][item.item.pak_id].get()
            # Items like the elevator that need the unlocked stylevar
            and (not item.needs_unlock or style_unlocked)
            )
    flow_picker()


# UI functions, each accepts the parent frame to place everything in.
# initMainWind generates the main frames that hold all the panes to
# make it easy to move them around if needed


def init_palette(f):
    """Initialises the palette pane.

    This lists all saved palettes and lets users choose from the list.
    """
    f.rowconfigure(1, weight=1)
    f.columnconfigure(0, weight=1)

    ttk.Button(
        f,
        text='Clear Palette',
        command=pal_clear,
        ).grid(row=0, sticky="EW")

    UI['palette'] = Listbox(f, width=10)
    UI['palette'].grid(row=1, sticky="NSEW")

    def set_pal_listbox(_=None):
        global selectedPalette
        selectedPalette = int(UI['palette'].curselection()[0])
        selectedPalette_radio.set(selectedPalette)
        set_palette()
    UI['palette'].bind("<<ListboxSelect>>", set_pal_listbox)
    UI['palette'].bind("<Enter>", set_pal_listbox_selection)
    # Set the selected state when hovered, so users can see which is
    # selected.
    UI['palette'].selection_set(0)

    pal_scroll = ttk.Scrollbar(f, orient=VERTICAL, command=UI['palette'].yview)
    pal_scroll.grid(row=1, column=1, sticky="NS")
    UI['palette']['yscrollcommand'] = pal_scroll.set

    UI['pal_remove'] = ttk.Button(f, text='Delete Palette', command=pal_remove)
    UI['pal_remove'].grid(row=2, sticky="EW")

    ttk.Sizegrip(f).grid(row=2, column=1)


def init_option(f):
    """Initialise the options pane."""
    f.columnconfigure(0, weight=1)
    ttk.Button(
        f,
        text="Save Palette...",
        command=pal_save,
        ).grid(row=0, sticky="EW", padx=5)
    ttk.Button(
        f,
        text="Save Palette As...",
        command=pal_save_as,
        ).grid(row=1, sticky="EW", padx=5)
    ttk.Button(
        f,
        text="Export...",
        command=export_editoritems,
        ).grid(row=2, sticky="EW", padx=5, pady=(0, 10))

    props = ttk.LabelFrame(f, text="Properties", width="50")
    props.columnconfigure(1, weight=1)
    props.grid(row=3, sticky="EW")

    def suggested_style_set():
        """Set music, skybox, voices, etc to the settings defined for a style.

        """
        sugg = styles[selected_style].suggested
        win_types = (voice_win, music_win, skybox_win, elev_win)
        for win, sugg_val in zip(win_types, sugg):
            win.sel_item_id(sugg_val)
        UI['suggested_style'].state(['disabled'])

    UI['suggested_style'] = ttk.Button(
        props,
        # '\u2193' is the downward arrow symbol.
        text="\u2193 Use Suggested \u2193",
        command=suggested_style_set,
        )
    UI['suggested_style'].grid(row=1, column=1, columnspan=2, sticky="EW")

    def configure_voice():
        """Open the voiceEditor window to configure a Quote Pack."""
        chosen = voices.get(voice_win.chosen_id, None)
        if chosen is not None:
            voiceEditor.show(chosen)
    for ind, name in enumerate([
            "Style",
            None,
            "Music",
            "Voice",
            "Skybox",
            "Elev Vid",
            ]):
        if name is None:
            # This is the "Suggested" button!
            continue
        ttk.Label(props, text=name+': ').grid(row=ind)

    voice_frame = ttk.Frame(props)
    voice_frame.columnconfigure(1, weight=1)
    UI['conf_voice'] = ttk.Button(
        voice_frame,
        image=img.png('icons/gear'),
        command=configure_voice,
        width=8,
        )
    UI['conf_voice'].grid(row=0, column=0, sticky='NS')

    # Make all the selector window textboxes
    style_win.widget(props).grid(row=0, column=1, sticky='EW')
    music_win.widget(props).grid(row=2, column=1, sticky='EW')
    voice_frame.grid(row=3, column=1, sticky='EW')
    skybox_win.widget(props).grid(row=4, column=1, sticky='EW')
    elev_win.widget(props).grid(row=5, column=1, sticky='EW')
    voice_win.widget(voice_frame).grid(row=0, column=1, sticky='EW')

    ttk.Sizegrip(
        props,
        cursor='sb_h_double_arrow',
        ).grid(
            row=2,
            column=5,
            rowspan=2,
            sticky="NS",
            )


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
    global pal_picked_fake
    UI['pre_bg_img'] = Label(
        f,
        bg=ItemsBG,
        image=img.png('BEE2/menu'),
        )
    UI['pre_bg_img'].grid(row=0, column=0)

    UI['pre_disp_name'] = ttk.Label(
        f,
        text="Item: Button",
        style='BG.TLabel',
        )
    UI['pre_disp_name'].place(x=10, y=552)

    UI['pre_sel_line'] = Label(
        f,
        bg="#F0F0F0",
        image=img.png('BEE2/sel_bar'),
        borderwidth=0,
        relief="solid",
        )
    blank = img.png('BEE2/blank')
    pal_picked_fake = [
        ttk.Label(
            frames['preview'],
            image=blank,
            )
        for _ in range(32)
        ]

    UI['pre_moving'] = ttk.Label(
        f,
        image=img.png('BEE2/item_moving')
    )

    flow_preview()


def init_picker(f):
    global frmScroll, pal_canvas
    ttk.Label(
        f,
        text="All Items: ",
        anchor="center",
        ).grid(
            row=0,
            column=0,
            sticky="EW",
            )
    cframe = ttk.Frame(
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

    scroll = ttk.Scrollbar(cframe, orient=VERTICAL, command=pal_canvas.yview)
    scroll.grid(column=1, row=0, sticky="NS")
    pal_canvas['yscrollcommand'] = scroll.set

    # add another frame inside to place labels on
    frmScroll = ttk.Frame(pal_canvas)
    pal_canvas.create_window(1, 1, window=frmScroll, anchor="nw")
    for item in item_list.values():
        for i in range(0, item.num_sub):
            pal_items.append(PalItem(frmScroll, item, sub=i, is_pre=False))
    f.bind("<Configure>", flow_picker)


def flow_picker(_=None):
    """Update the picker box so all items are positioned corrctly.

    Should be run (e arg is ignored) whenever the items change, or the
    window changes shape.
    """
    frmScroll.update_idletasks()
    frmScroll['width'] = pal_canvas.winfo_width()
    if frames['filter'].expanded:
        # Offset the icons so they aren't covered by the filter popup
        offset = max(
            (
                frames['filter_expanded'].winfo_height()
                - pal_canvas.winfo_rooty()
                + frames['filter_expanded'].winfo_rooty()
                + 10
            ), 0)
    else:
        offset = 0
    width = (pal_canvas.winfo_width()-10) // 65
    if width < 1:
        width = 1  # we got way too small, prevent division by zero
    vis_items = [it for it in pal_items if it.visible]
    num_items = len(vis_items)
    for i, item in enumerate(vis_items):
        item.is_pre = False
        item.place(
            x=((i % width) * 65 + 1),
            y=((i // width) * 65 + offset + 1),
            )

    for item in (it for it in pal_items if not it.visible):
        item.place_forget()
    height = (num_items//width + 1)*65 + offset + 2
    pal_canvas['scrollregion'] = (
        0,
        0,
        width*65,
        height,
        )
    frmScroll['height'] = height

    # this adds extra blank items on the end to finish the grid nicely.
    blank_img = img.png('BEE2/blank')

    for i in range(width):
        if i not in pal_items_fake:
            pal_items_fake.append(ttk.Label(frmScroll, image=blank_img))
        if (num_items % width) <= i < width:  # if this space is empty
            pal_items_fake[i].place(
                x=((i % width)*65 + 1),
                y=(num_items // width)*65 + offset + 1,
            )

    for item in pal_items_fake[width:]:
        item.place_forget()


def init_filter_col(cat, f):
    FilterBoxes[cat] = {}
    FilterVars[cat] = {}
    FilterVars_all[cat] = IntVar(value=1)

    def filter_all_callback(col):
        """Sets all items in a category to true/false.

        """
        val = FilterVars_all[col].get()
        for i in FilterVars[col]:
            FilterVars[col][i].set(val)
        update_filters()

    FilterBoxes_all[cat] = ttk.Checkbutton(
        f,
        text='All',
        onvalue=1,
        offvalue=0,
        # We pass along the name of the category, so the function can
        # figure out what to change.
        command=func_partial(filter_all_callback, cat),
        variable=FilterVars_all[cat],
        )

    FilterBoxes_all[cat].grid(
        row=1,
        column=0,
        sticky=W,
        )

    for ind, (filt_id, name) in enumerate(sorted(
            filter_data[cat].items(),
            key=operator.itemgetter(1),
            )):
        FilterVars[cat][filt_id] = IntVar(value=1)
        FilterBoxes[cat][filt_id] = ttk.Checkbutton(
            f,
            text=name,
            command=update_filters,
            variable=FilterVars[cat][filt_id],
            )
        FilterBoxes[cat][filt_id]['variable'] = FilterVars[cat][filt_id]
        FilterBoxes[cat][filt_id].grid(
            row=ind+2,
            column=0,
            sticky=W,
            padx=(4, 0),
            )
        if ind == 0:
            FilterBoxes_all[cat].first_var = FilterVars[cat][filt_id]


def init_filter(f):
    ttk.Label(
        f,
        text="Filters:",
        anchor="center",
        ).grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="EW",
            )
    f.columnconfigure(0, weight=1)
    f.columnconfigure(1, weight=1)
    f.columnconfigure(2, weight=1)
    f2 = ttk.Frame(f)
    frames['filter_expanded'] = f2
    # Not added to window, we add it below the others to expand the
    # lists

    def expand(_):
        frames['filter_expanded'].grid(row=2, column=0, columnspan=3)
        frames['filter']['borderwidth'] = 4
        frames['filter'].expanded = True
        snd.fx('expand')
        flow_picker()

    def contract(_):
        frames['filter_expanded'].grid_remove()
        frames['filter']['borderwidth'] = 0
        frames['filter'].expanded = False
        snd.fx('contract')
        flow_picker()

    f.bind("<Enter>", expand)
    f.bind("<Leave>", contract)

    auth = ttk.Labelframe(f2, text="Authors")
    auth.grid(row=2, column=0, sticky="NS")
    pack = ttk.Labelframe(f2, text="Packages")
    pack.grid(row=2, column=1, sticky="NS")
    tags = ttk.Labelframe(f2, text="Tags")
    tags.grid(row=2, column=2, sticky="NS")
    init_filter_col('author', auth)
    init_filter_col('package', pack)
    init_filter_col('tags', tags)


def init_drag_icon():
    drag_win = Toplevel(TK_ROOT)
    # this prevents stuff like the title bar, normal borders etc from
    # appearing in this window.
    drag_win.overrideredirect(1)
    drag_win.resizable(False, False)
    drag_win.withdraw()
    drag_win.transient(master=TK_ROOT)
    drag_win.withdraw()  # starts hidden
    drag_win.bind("<ButtonRelease-1>", drag_stop)
    UI['drag_lbl'] = Label(
        drag_win,
        image=img.png('BEE2/blank'),
        )
    UI['drag_lbl'].grid(row=0, column=0)
    windows['drag_win'] = drag_win

    drag_win.passed_over_pal = False  # has the cursor passed over the palette
    drag_win.from_pal = False  # are we dragging a palette item?
    drag_win.drag_item = None  # the item currently being moved


def set_game(game):
    """Callback for when the game is changed.

    This updates the title bar to match, and saves it into the config.
    """
    TK_ROOT.title('BEEMOD {} - {}'.format(utils.BEE_VERSION, game.name))
    GEN_OPTS['Last_Selected']['game'] = game.name


def init_menu_bar(win):
    bar = Menu(win)
    win['menu'] = bar
    # Suppress ability to make each menu a separate window - weird old
    # TK behaviour
    win.option_add('*tearOff', False)

    # Name is used to make this the special 'BEE2' menu item on Mac
    menus['file'] = Menu(bar, name='apple')
    file_menu = menus['file']
    bar.add_cascade(menu=file_menu, label='File')

    file_menu.add_command(
        label="Export",
        command=export_editoritems,
        accelerator='Ctrl-E',
        )
    win.bind_all('<Control-e>', export_editoritems)

    file_menu.add_command(
        label="Add Game",
        command=gameMan.add_game,
    )
    file_menu.add_command(
        label="Remove Selected Game",
        command=gameMan.remove_game,
        )
    file_menu.add_separator()
    file_menu.add_command(
        label="Quit",
        command=quit_application,
        )
    file_menu.add_separator()

    # Add a set of options to pick the game into the menu system
    gameMan.add_menu_opts(menus['file'], callback=set_game)
    gameMan.game_menu = menus['file']

    menus['pal'] = Menu(bar)
    pal_menu = menus['pal']
    bar.add_cascade(menu=pal_menu, label='Palette')
    pal_menu.add_command(
        label='Clear',
        command=pal_clear,
        )
    pal_menu.add_command(
        label='Delete Palette',
        command=pal_remove,
        )
    pal_menu.add_command(
        label='Save Palette',
        command=pal_save,
        accelerator='Ctrl-S',
        )
    pal_menu.add_command(
        label='Save Palette As...',
        command=pal_save_as,
        accelerator='Ctrl-Shift-S'
        )
    pal_menu.add_separator()

    # refresh_pal_ui() adds the palette menu options here.

    win.bind_all('<Control-s>', pal_save)
    win.bind_all('<Control-Shift-s>', pal_save_as)

    menus['tools'] = Menu(bar)
    bar.add_cascade(menu=menus['tools'], label='Options')
    if snd.initiallised:
        menus['tools'].add_checkbutton(
            label="Mute Sounds",
            variable=muted,
            command=set_mute,
            )
    menus['tools'].add_checkbutton(
        label='Show Work In Progress Items',
        variable=show_wip_items,
        )

    menus['help'] = Menu(bar, name='help')  # Name for Mac-specific stuff
    bar.add_cascade(menu=menus['help'], label='Help')
    menus['help'].add_command(label='About')  # Authors etc


def init_windows():
    """Initialise all windows and panes.

    """
    init_menu_bar(TK_ROOT)
    TK_ROOT.maxsize(
        width=TK_ROOT.winfo_screenwidth(),
        height=TK_ROOT.winfo_screenheight(),
        )
    TK_ROOT.protocol("WM_DELETE_WINDOW", quit_application)
    TK_ROOT.iconbitmap('../BEE2.ico')  # set the window icon

    ui_bg = Frame(TK_ROOT, bg=ItemsBG)
    ui_bg.grid(row=0, column=0, sticky='NSEW')
    TK_ROOT.columnconfigure(0, weight=1)
    TK_ROOT.rowconfigure(0, weight=1)
    ui_bg.rowconfigure(0, weight=1)
    StyleVarPane.update_filter = update_filters

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
    frames['filter'] = ttk.Frame(
        picker_split_frame,
        padding=5,
        borderwidth=0,
        relief="raised",
        )
    frames['filter'].place(x=0, y=0, relwidth=1)
    frames['filter'].expanded = False
    init_filter(frames['filter'])
    loader.step('UI')

    frames['picker'] = ttk.Frame(
        picker_split_frame,
        padding=(5, 40, 5, 5),
        borderwidth=4,
        relief="raised",
        )
    frames['picker'].grid(row=0, column=0, sticky="NSEW")
    picker_split_frame.rowconfigure(0, weight=1)
    picker_split_frame.columnconfigure(0, weight=1)
    init_picker(frames['picker'])
    loader.step('UI')

    frames['filter'].lift()

    frames['toolMenu'] = Frame(
        frames['preview'],
        bg=ItemsBG,
        width=192,
        height=26,
        borderwidth=0,
        )
    frames['toolMenu'].place(x=73, y=2)

    windows['pal'] = SubPane(
        TK_ROOT,
        options=GEN_OPTS,
        title='Palettes',
        name='pal',
        resize_x=True,
        resize_y=True,
        tool_frame=frames['toolMenu'],
        tool_img=img.png('icons/win_palette'),
        tool_col=0,
    )
    init_palette(windows['pal'])
    loader.step('UI')

    windows['opt'] = SubPane(
        TK_ROOT,
        options=GEN_OPTS,
        title='Export Options',
        name='opt',
        resize_x=True,
        tool_frame=frames['toolMenu'],
        tool_img=img.png('icons/win_options'),
        tool_col=1,
    )
    init_option(windows['opt'])
    loader.step('UI')

    StyleVarPane.make_pane(frames['toolMenu'])
    loader.step('UI')

    CompilerPane.make_pane(frames['toolMenu'])
    loader.step('UI')

    # make scrollbar work globally
    TK_ROOT.bind(
        "<MouseWheel>",
        lambda e: pal_canvas.yview_scroll(int(-1*(e.delta/120)), "units"),
        )
    # needed for linux
    TK_ROOT.bind(
        "<Button-4>",
        lambda e: pal_canvas.yview_scroll(1, "units"),
        )
    TK_ROOT.bind(
        "<Button-5>",
        lambda e: pal_canvas.yview_scroll(-1, "units"),
        )

    StyleVarPane.window.bind(
        "<MouseWheel>",
        lambda e: UI['style_can'].yview_scroll(int(-1*(e.delta/120)), "units"),
        )
    StyleVarPane.window.bind(
        "<Button-4>",
        lambda e: UI['style_can'].yview_scroll(1, "units"),
        )
    StyleVarPane.window.bind(
        "<Button-5>",
        lambda e: UI['style_can'].yview_scroll(-1, "units"),
        )

    # When clicking on any window hide the context window
    TK_ROOT.bind("<Button-1>", contextWin.hide_context)
    StyleVarPane.window.bind("<Button-1>", contextWin.hide_context)
    windows['opt'].bind("<Button-1>", contextWin.hide_context)
    windows['pal'].bind("<Button-1>", contextWin.hide_context)

    voiceEditor.init_widgets()
    contextWin.init_widgets()
    init_drag_icon()
    loader.step('UI')

    TK_ROOT.deiconify()  # show it once we've loaded everything

    TK_ROOT.update_idletasks()
    StyleVarPane.window.update_idletasks()
    CompilerPane.window.update_idletasks()
    windows['opt'].update_idletasks()
    windows['pal'].update_idletasks()

    TK_ROOT.after(50, set_pal_listbox_selection)
    # This needs some time for the listbox to appear first
    set_palette()

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

    # Default positions for sub-panes
    xpos = min(
        TK_ROOT.winfo_screenwidth()
        - StyleVarPane.window.winfo_reqwidth(),

        TK_ROOT.winfo_rootx()
        + TK_ROOT.winfo_reqwidth()
        + 25
        )
    windows['pal'].move(
        x=(TK_ROOT.winfo_rootx() - windows['pal'].winfo_reqwidth() - 50),
        y=(TK_ROOT.winfo_rooty() - 50),
        height=TK_ROOT.winfo_reqheight() + 25)
    windows['opt'].move(
        x=xpos,
        y=TK_ROOT.winfo_rooty()-40,
        width=StyleVarPane.window.winfo_reqwidth())
    StyleVarPane.window.move(
        x=xpos,
        y=TK_ROOT.winfo_rooty() + windows['opt'].winfo_reqheight() + 25)

    # Load from config file
    StyleVarPane.window.load_conf()
    CompilerPane.window.load_conf()
    windows['opt'].load_conf()
    windows['pal'].load_conf()

    TK_ROOT.bind("<Configure>", contextWin.follow_main, add='+')
    refresh_pal_ui()

    def style_select_callback(style_id):
        """Callback whenever a new style is chosen."""
        global selected_style
        selected_style = style_id
        GEN_OPTS['Last_Selected']['Style'] = style_id

        style_obj = styles[selected_style]

        for item in itertools.chain(item_list.values(), pal_picked, pal_items):
            item.load_data()  # Refresh everything

        # Disable this if the style doesn't have elevators
        elev_win.readonly = not style_obj.has_video

        CompilerPane.set_corr_values('sp_entry', style_obj.corridor_names)
        CompilerPane.set_corr_values('sp_exit', style_obj.corridor_names)
        CompilerPane.set_corr_values('coop', style_obj.corridor_names)

        sugg = style_obj.suggested
        win_types = (voice_win, music_win, skybox_win, elev_win)
        for win, sugg_val in zip(win_types, sugg):
            win.set_suggested(sugg_val)
        suggested_refresh()
        StyleVarPane.refresh(style_obj)

    style_win.callback = style_select_callback
    style_select_callback(style_win.chosen_id)

    set_palette()

event_loop = TK_ROOT.mainloop