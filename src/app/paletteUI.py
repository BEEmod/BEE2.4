"""Handles the UI required for saving and loading palettes."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk
from uuid import UUID, uuid4

from srctools import EmptyMapping
import srctools.logger
import trio

from app import background_run, img, paletteLoader
from app.dialogs import Dialogs
from app.item_picker import ItemPickerBase
from app.paletteLoader import (
    COORDS, HORIZ, VERT, HorizInd, ItemPos, Palette, VertInd,
)
from config.palette import PaletteState
from consts import PALETTE_FORCE_SHOWN, UUID_BLANK, UUID_EXPORT, UUID_PORTAL2
from transtoken import CURRENT_LANG, TransToken
from ui_tk import tk_tools
from ui_tk.img import TKImages, TkImg
from ui_tk.wid_transtoken import set_menu_text, set_text
from utils import not_none
import config
import trio_util


LOGGER = srctools.logger.get_logger(__name__)
TREE_TAG_GROUPS = 'pal_group'
TREE_TAG_PALETTES = 'palette'
ICO_GEAR = img.Handle.sprite('icons/gear', 10, 10)

# Re-export paletteLoader values for convenience.
__all__ = [
    'PaletteUI',
    'Palette', 'ItemPos', 'VertInd', 'HorizInd', 'VERT', 'HORIZ', 'COORDS',
    'UUID', 'UUID_EXPORT', 'UUID_PORTAL2', 'UUID_BLANK',
]
TRANS_DELETE = TransToken.ui("Delete")
TRANS_HIDE = TransToken.ui("Hide")
TRANS_DELETE_NAMED = TransToken.ui('Delete Palette "{name}"')
TRANS_HIDE_NAMED = TransToken.ui('Hide Palette "{name}"')
TRANS_ENTER_NAME = TransToken.ui("Enter a name:")
TRANS_SHOULD_DELETE = TransToken.ui('Are you sure you want to delete "{palette}"?')
TRANS_BUILTIN = TransToken.ui('Builtin / Readonly')  # i18n: Palette group title.
TRANS_TITLE_SAVE = TransToken.ui("BEE2 - Save Palette")
TRANS_TITLE_DELETE = TransToken.ui('BEE2 - Delete Palette')
TRANS_TITLE_CHANGE_GROUP = TransToken.ui("BEE2 - Change Palette Group")


class PaletteUI:
    """UI for selecting palettes."""
    palettes: dict[UUID, Palette]
    selected_uuid: UUID
    hidden_defaults: set[UUID]
    var_save_settings: tk.BooleanVar
    var_pal_select: tk.StringVar

    ui_btn_save: ttk.Button
    ui_remove: ttk.Button
    ui_treeview: ttk.Treeview
    tk_img: TKImages
    ui_menu: tk.Menu
    ui_group_menus: dict[str, tk.Menu]
    ui_group_treeids: dict[str, str]
    ui_readonly_indexes: list[int]
    ui_menu_palettes_index: int

    def __init__(
        self, f: ttk.Frame, menu: tk.Menu, item_picker: ItemPickerBase,
        *,
        tk_img: TKImages,
        dialog_menu: Dialogs,
        dialog_window: Dialogs,
    ) -> None:
        """Initialises the palette pane."""
        self.palettes: dict[UUID, Palette] = {
            pal.uuid: pal
            for pal in paletteLoader.load_palettes()
        }
        prev_state = config.APP.get_cur_conf(PaletteState)
        self.selected_uuid = prev_state.selected
        self.hidden_defaults = set(prev_state.hidden_defaults)
        self.var_save_settings = tk.BooleanVar(value=prev_state.save_settings)
        self.var_pal_select = tk.StringVar(value=self.selected_uuid.hex)
        self.picker = item_picker

        f.rowconfigure(2, weight=1)
        f.columnconfigure(0, weight=1)

        btn_bar = ttk.Frame(f)
        btn_bar.grid(row=0, column=0, columnspan=2, sticky='EW', padx=5)
        btn_bar.columnconfigure(0, weight=1)
        btn_bar.columnconfigure(1, weight=1)
        btn_bar.columnconfigure(2, weight=1)

        self.ui_btn_save = set_text(
            ttk.Button(btn_bar, command=lambda: background_run(self.event_save, dialog_window)),
            TransToken.ui("Save"),
        )
        self.ui_btn_save.grid(row=0, column=0, sticky="EW")

        set_text(
            ttk.Button(btn_bar, command=lambda: background_run(self.event_save_as, dialog_window)),
            TransToken.ui("Save As"),
        ).grid(row=0, column=1, sticky="EW")

        self.ui_remove = set_text(
            ttk.Button(btn_bar, command=lambda: background_run(self.event_remove, dialog_window)),
            TransToken.ui("Delete"),
        )
        self.ui_remove.grid(row=0, column=2, sticky="EW")

        self.ui_treeview = treeview = ttk.Treeview(f, show='tree', selectmode='browse')
        self.ui_treeview.grid(row=2, column=0, sticky="NSEW")
        # We need to delay this a frame, so the selection completes.
        self.ui_treeview.tag_bind(
            TREE_TAG_PALETTES, '<ButtonPress>',
            lambda e: background_run(self.event_select_tree),
        )

        check_save_settings = ttk.Checkbutton(
            f,
            variable=self.var_save_settings,
            command=self._store_configuration,
        )
        set_text(check_save_settings, TransToken.ui('Save Settings in Palettes'))
        check_save_settings.grid(row=3, column=0, sticky="EW", padx=5)

        self.tk_img = tk_img

        # Avoid re-registering the double-lambda, just do it here.
        # This makes clicking the groups return selection to the palette.
        evtid_reselect = self.ui_treeview.register(self.treeview_reselect)
        self.ui_treeview.tag_bind(
            TREE_TAG_GROUPS, '<ButtonPress>',
            lambda e: treeview.tk.call('after', 'idle', evtid_reselect),
        )

        # And ensure when focus returns we reselect, in case it deselects.
        f.winfo_toplevel().bind('<FocusIn>', lambda e: self.treeview_reselect(), add=True)

        scrollbar = tk_tools.HidingScroll(
            f,
            orient='vertical',
            command=self.ui_treeview.yview,
        )
        scrollbar.grid(row=2, column=1, sticky="NS")
        self.ui_treeview['yscrollcommand'] = scrollbar.set

        if tk_tools.USE_SIZEGRIP:
            ttk.Sizegrip(f).grid(row=3, column=1)

        self.ui_menu = menu
        self.ui_group_menus = {}
        self.ui_group_treeids = {}
        # Set this event to trigger a reload.
        self.is_dirty = trio.Event()

        menu.add_command(
            command=lambda: background_run(self.event_save, dialog_menu),
            accelerator=tk_tools.ACCEL_SAVE,
        )
        set_menu_text(menu, TransToken.ui('Save Palette'))
        self.ui_readonly_indexes = [not_none(menu.index('end'))]

        menu.add_command(
            command=lambda: background_run(self.event_save_as, dialog_menu),
            accelerator=tk_tools.ACCEL_SAVE_AS,
        )
        set_menu_text(menu, TransToken.ui('Save Palette As...'))

        menu.add_command(
            label='Delete Palette',  # This name is overwritten later
            command=lambda: background_run(self.event_remove, dialog_menu),
        )
        self.ui_menu_delete_index = not_none(menu.index('end'))

        menu.add_command(command=lambda: background_run(self.event_change_group, dialog_menu))
        set_menu_text(menu, TransToken.ui('Change Palette Group...'))
        self.ui_readonly_indexes.append(not_none(menu.index('end')))

        menu.add_command(command=lambda: background_run(self.event_rename, dialog_menu))
        set_menu_text(menu, TransToken.ui('Rename Palette...'))
        self.ui_readonly_indexes.append(not_none(menu.index('end')))

        menu.add_separator()

        menu.add_checkbutton(variable=self.var_save_settings)
        set_menu_text(menu, TransToken.ui('Save Settings in Palettes'))

        menu.add_separator()

        menu.add_command(command=item_picker.clear_palette)
        set_menu_text(menu, TransToken.ui('Clear'))

        menu.add_command(command=item_picker.fill_palette)
        set_menu_text(menu, TransToken.ui('Fill Palette'))

        menu.add_separator()

        self.ui_menu_palettes_index = not_none(menu.index('end')) + 1

    @property
    def selected(self) -> Palette:
        """Retrieve the currently selected palette."""
        try:
            return self.palettes[self.selected_uuid]
        except KeyError:
            LOGGER.warning('No such palette with ID {}', self.selected_uuid)
            return self.palettes[UUID_PORTAL2]

    async def update_task(self) -> None:
        """Whenever a change occurs, update all the UI."""
        while True:
            self.is_dirty = trio.Event()
            await trio_util.wait_any(
                CURRENT_LANG.wait_transition,
                self.is_dirty.wait,
            )
            self._update_state()

    def _update_state(self) -> None:
        """Update the UI to show correct state."""

        # Clear out all the current data.
        for grp_menu in self.ui_group_menus.values():
            grp_menu.delete(0, 'end')
        self.ui_menu.delete(self.ui_menu_palettes_index, 'end')

        # Detach all groups + children, and get a list of existing ones.
        existing: set[str] = set()
        for group_id in self.ui_group_treeids.values():
            existing.update(self.ui_treeview.get_children(group_id))
            self.ui_treeview.detach(group_id)
        for pal_id in self.ui_treeview.get_children(''):
            if pal_id.startswith('pal_'):
                self.ui_treeview.delete(pal_id)

        groups: dict[str, list[Palette]] = {}
        for pal in self.palettes.values():
            if pal is self.selected or pal.uuid not in self.hidden_defaults:
                groups.setdefault(pal.group, []).append(pal)

        for group, palettes in sorted(groups.items(), key=lambda t: (t[0] != paletteLoader.GROUP_BUILTIN, t[0])):
            if group == paletteLoader.GROUP_BUILTIN:
                group = str(TRANS_BUILTIN)
            if group:
                try:
                    grp_menu = self.ui_group_menus[group]
                except KeyError:
                    grp_menu = self.ui_group_menus[group] = tk.Menu(self.ui_menu)
                self.ui_menu.add_cascade(label=group, menu=grp_menu)

                try:
                    grp_tree = self.ui_group_treeids[group]
                except KeyError:
                    grp_tree = self.ui_group_treeids[group] = self.ui_treeview.insert(
                        '', 'end',
                        text=group,
                        open=True,
                        tags=TREE_TAG_GROUPS,
                    )
                else:
                    self.ui_treeview.move(grp_tree, '', 9999)
            else:  # '', directly add.
                grp_menu = self.ui_menu
                grp_tree = ''  # Root.
            for pal in sorted(palettes, key=lambda p: str(p.name)):
                gear_img: TkImg | str = self.tk_img.sync_load(ICO_GEAR) if pal.settings is not None else ''
                grp_menu.add_radiobutton(
                    label=str(pal.name),
                    value=pal.uuid.hex,
                    # If we remake the palette menus inside this event handler, it tries
                    # to select the old menu item (likely), so a crash occurs. Delay until
                    # another frame.
                    command=lambda: background_run(self.event_select_menu),
                    variable=self.var_pal_select,
                    image=gear_img,
                    compound='left',
                )
                pal_id = 'pal_' + pal.uuid.hex
                if pal_id in existing:
                    existing.remove(pal_id)
                    self.ui_treeview.move(pal_id, grp_tree, 99999)
                    self.ui_treeview.item(
                        pal_id,
                        text=str(pal.name),
                        image=gear_img,
                    )
                else:  # New
                    self.ui_treeview.insert(
                        grp_tree, 'end',
                        text=str(pal.name),
                        iid='pal_' + pal.uuid.hex,
                        image=gear_img,
                        tags=TREE_TAG_PALETTES,
                    )
        # Finally, strip any ones which were removed.
        if existing:
            self.ui_treeview.delete(*existing)

        # Select the currently selected UUID.
        self.ui_treeview.selection_set('pal_' + self.selected.uuid.hex)
        self.ui_treeview.see('pal_' + self.selected.uuid.hex)

        if self.selected.readonly:
            self.ui_menu.entryconfigure(
                self.ui_menu_delete_index,
                label=TRANS_HIDE_NAMED.format(name=self.selected.name),
            )
            set_text(self.ui_remove, TRANS_HIDE)

            self.ui_btn_save.state(('disabled',))
            for ind in self.ui_readonly_indexes:
                self.ui_menu.entryconfigure(ind, state='disabled')
        else:
            self.ui_menu.entryconfigure(
                self.ui_menu_delete_index,
                label=TRANS_DELETE_NAMED.format(name=self.selected.name),
            )
            set_text(self.ui_remove, TRANS_DELETE)

            self.ui_btn_save.state(('!disabled',))
            for ind in self.ui_readonly_indexes:
                self.ui_menu.entryconfigure(ind, state='normal')

        if self.selected.uuid in PALETTE_FORCE_SHOWN:
            self.ui_remove.state(('disabled',))
            self.ui_menu.entryconfigure(self.ui_menu_delete_index, state='disabled')
        else:
            self.ui_remove.state(('!disabled',))
            self.ui_menu.entryconfigure(self.ui_menu_delete_index, state='normal')

    def _store_configuration(self) -> None:
        """Save the state of the palette to the config."""
        config.APP.store_conf(PaletteState(
            self.selected_uuid,
            self.var_save_settings.get(),
            frozenset(self.hidden_defaults),
        ))

    def reset_hidden_palettes(self) -> None:
        """Clear all hidden palettes, and save."""
        self.hidden_defaults.clear()
        self._store_configuration()
        self.is_dirty.set()

    async def event_remove(self, dialogs: Dialogs) -> None:
        """Remove the currently selected palette."""
        pal = self.selected
        if pal.readonly:
            if pal.uuid in PALETTE_FORCE_SHOWN:
                return  # Disallowed.
            self.hidden_defaults.add(pal.uuid)
        elif await dialogs.ask_yes_no(
            title=TRANS_TITLE_DELETE,
            message=TRANS_SHOULD_DELETE.format(palette=pal.name),
        ):
            pal.delete_from_disk()
            del self.palettes[pal.uuid]
        else:
            return  # Cancelled
        self.select_palette(UUID_PORTAL2, False)
        self.is_dirty.set()

    async def event_save(self, dialogs: Dialogs) -> None:
        """Save the current palette over the original name."""
        if self.selected.readonly:
            await self.event_save_as(dialogs)
            return
        else:
            self.selected.items = self.picker.get_items()
            if self.var_save_settings.get():
                self.selected.settings = config.APP.get_full_conf(config.PALETTE)
            else:
                self.selected.settings = None
            self.selected.save(ignore_readonly=True)
        self.is_dirty.set()

    async def event_save_as(self, dialogs: Dialogs) -> None:
        """Save the palette with a new name."""
        name = await dialogs.prompt(title=TRANS_TITLE_SAVE, message=TRANS_ENTER_NAME)
        if name is None:
            # Cancelled...
            return
        pal = Palette(name, self.picker.get_items())
        while pal.uuid in self.palettes:  # Should never occur, but check anyway.
            pal.uuid = uuid4()

        if self.var_save_settings.get():
            pal.settings = config.APP.get_full_conf(config.PALETTE)

        pal.save()
        self.palettes[pal.uuid] = pal
        self.select_palette(pal.uuid, False)
        self.is_dirty.set()

    async def event_rename(self, dialogs: Dialogs) -> None:
        """Rename an existing palette."""
        if self.selected.readonly:
            return
        name = await dialogs.prompt(title=TRANS_TITLE_SAVE, message=TRANS_ENTER_NAME)
        if name is None:
            # Cancelled...
            return
        self.selected.name = TransToken.untranslated(name)
        self.is_dirty.set()

    def select_palette(self, uuid: UUID, set_save_settings: bool) -> None:
        """Select a new palette.

        This does not update items/settings! It does override the "save settings" checkbox
        to match the palette optionally, though.
        """
        try:
            pal = self.palettes[uuid]
        except KeyError:
            LOGGER.warning('Unknown UUID {}!', uuid.hex)
        else:
            self.selected_uuid = uuid
            if set_save_settings and not pal.readonly:
                # Propagate the save-settings option to the palette, so saving does the same thing.
                self.var_save_settings.set(pal.settings is not None)
            self._store_configuration()

    async def event_change_group(self, dialogs: Dialogs) -> None:
        """Change the group of a palette."""
        if self.selected.readonly:
            return
        res = await dialogs.prompt(
            title=TRANS_TITLE_CHANGE_GROUP,
            message=TransToken.ui('Enter the name of the group for this palette, or "" to ungroup.'),
            validator=lambda x: x,
        )
        if res is not None:
            self.selected.group = res.strip('<>')
            self.selected.save()
            self.is_dirty.set()

    async def event_select_menu(self) -> None:
        """Called when the menu buttons are clicked."""
        uuid_hex = self.var_pal_select.get()
        self.select_palette(UUID(hex=uuid_hex), True)
        self.picker.set_items(self.selected.items)
        self.is_dirty.set()

    async def event_select_tree(self) -> None:
        """Called when palettes are selected on the treeview."""
        try:
            uuid_hex = self.ui_treeview.selection()[0][4:]
        except IndexError:  # No selection, exit.
            return
        self.var_pal_select.set(uuid_hex)
        self.select_palette(UUID(hex=uuid_hex), True)
        self.picker.set_items(self.selected.items)
        self.is_dirty.set()

    def treeview_reselect(self) -> None:
        """When a group item is selected on the tree, reselect the palette."""
        # This could be called before all the items are added to the UI.
        uuid_hex = 'pal_' + self.selected.uuid.hex
        if self.ui_treeview.exists(uuid_hex):
            self.ui_treeview.selection_set(uuid_hex)
