"""Handles the UI required for saving and loading palettes."""
from __future__ import annotations
from typing import Awaitable, Callable
from uuid import UUID

from srctools.dmx import Element
from tkinter import ttk, messagebox
import tkinter as tk

from srctools import Property
import srctools.logger
import attrs

from app.paletteLoader import Palette, UUID_PORTAL2, UUID_EXPORT, UUID_BLANK
from app import background_run, tk_tools, paletteLoader, config, TK_ROOT, img, BEE2
from localisation import gettext


LOGGER = srctools.logger.get_logger(__name__)
TREE_TAG_GROUPS = 'pal_group'
TREE_TAG_PALETTES = 'palette'
ICO_GEAR = img.Handle.sprite('icons/gear', 10, 10)

# Re-export paletteLoader values for convenience.
__all__ = [
    'PaletteUI', 'Palette', 'UUID', 'UUID_EXPORT', 'UUID_PORTAL2', 'UUID_BLANK',
]


@config.register('Palette', palette_stores=False)
@attrs.frozen
class PaletteState(config.Data):
    """Data related to palettes which is restored next run.

    Since we don't store in the palette, we don't need to register the UI callback.
    """
    selected: UUID = UUID_PORTAL2
    save_settings: bool = False

    @classmethod
    def parse_legacy(cls, conf: Property) -> dict[str, PaletteState]:
        """Convert the legacy config options to the new format."""
        # These are all in the GEN_OPTS config.
        try:
            selected_uuid = UUID(hex=config.LEGACY_CONF.get_val('Last_Selected', 'palette_uuid', ''))
        except ValueError:
            selected_uuid = UUID_PORTAL2

        return {'': cls(
            selected_uuid,
            config.LEGACY_CONF.get_bool('General', 'palette_save_settings'),
        )}

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> PaletteState:
        """Parse Keyvalues data."""
        assert version == 1
        try:
            uuid = UUID(hex=data['selected'])
        except (LookupError, ValueError):
            uuid = UUID_PORTAL2
        return PaletteState(uuid, data.bool('save_settings', False))

    def export_kv1(self) -> Property:
        """Export to a property block."""
        return Property('', [
            Property('selected', self.selected.hex),
            Property('save_settings', srctools.bool_as_int(self.save_settings)),
        ])

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> PaletteState:
        """Parse DMX data."""
        try:
            uuid = UUID(bytes=data['selected'].val_bytes)
        except (LookupError, ValueError):
            uuid = UUID_PORTAL2
        return PaletteState(
            uuid,
            data['save_settings'].val_bool,
        )

    def export_dmx(self) -> Element:
        """Export to a DMX."""
        elem = Element('Palette', 'DMElement')
        elem['selected'] = self.selected.bytes
        elem['save_settings'] = self.save_settings
        return elem


class PaletteUI:
    """UI for selecting palettes."""
    def __init__(
        self, f: tk.Frame, menu: tk.Menu,
        *,
        cmd_clear: Callable[[], None],
        cmd_shuffle: Callable[[], None],
        get_items: Callable[[], list[tuple[str, int]]],
        set_items: Callable[[Palette], Awaitable[None]],
    ) -> None:
        """Initialises the palette pane.

        The parameters are used to communicate with the item list:
        - cmd_clear and cmd_shuffle are called to do those actions to the list.
        - pal_get_items is called to retrieve the current list of selected items.
        - cmd_save_btn_state is the .state() method on the save button.
        - cmd_set_items is called to apply a palette to the list of items.
        """
        self.palettes: dict[UUID, Palette] = {
            pal.uuid: pal
            for pal in paletteLoader.load_palettes()
        }
        prev_state = config.get_cur_conf(PaletteState, default=PaletteState())
        self.selected_uuid = prev_state.selected
        self.var_save_settings = tk.BooleanVar(value=prev_state.save_settings)
        self.var_pal_select = tk.StringVar(value=self.selected_uuid.hex)
        self.get_items = get_items
        self.set_items = set_items
        # Overwritten to configure the save state button.
        self.save_btn_state = lambda s: None

        f.rowconfigure(1, weight=1)
        f.columnconfigure(0, weight=1)
        ttk.Button(
            f,
            text=gettext('Clear Palette'),
            command=cmd_clear,
        ).grid(row=0, sticky="EW")

        self.ui_treeview = treeview = ttk.Treeview(f, show='tree', selectmode='browse')
        self.ui_treeview.grid(row=1, sticky="NSEW")
        # We need to delay this a frame, so the selection completes.
        self.ui_treeview.tag_bind(
            TREE_TAG_PALETTES, '<ButtonPress>',
            lambda e: background_run(self.event_select_tree),
        )

        # Avoid re-registering the double-lambda, just do it here.
        # This makes clicking the groups return selection to the palette.
        evtid_reselect = self.ui_treeview.register(self.treeview_reselect)
        self.ui_treeview.tag_bind(TREE_TAG_GROUPS, '<ButtonPress>', lambda e: treeview.tk.call('after', 'idle', evtid_reselect))

        # And ensure when focus returns we reselect, in case it deselects.
        f.winfo_toplevel().bind('<FocusIn>', lambda e: self.treeview_reselect(), add=True)

        scrollbar = tk_tools.HidingScroll(
            f,
            orient='vertical',
            command=self.ui_treeview.yview,
        )
        scrollbar.grid(row=1, column=1, sticky="NS")
        self.ui_treeview['yscrollcommand'] = scrollbar.set

        self.ui_remove = ttk.Button(
            f,
            text=gettext('Delete Palette'),
            command=self.event_remove,
        )
        self.ui_remove.grid(row=2, sticky="EW")

        if tk_tools.USE_SIZEGRIP:
            ttk.Sizegrip(f).grid(row=2, column=1)

        self.ui_menu = menu
        self.ui_group_menus: dict[str, tk.Menu] = {}
        self.ui_group_treeids: dict[str, str] = {}
        menu.add_command(
            label=gettext('Clear'),
            command=cmd_clear,
        )
        menu.add_command(
            # Placeholder..
            label=gettext('Delete Palette'),  # This name is overwritten later
            command=self.event_remove,
        )
        self.ui_menu_delete_index = menu.index('end')
        self.ui_menu_indexes = [self.ui_menu_delete_index]

        menu.add_command(
            label=gettext('Change Palette Group...'),
            command=self.event_change_group,
        )
        self.ui_menu_indexes.append(menu.index('end'))

        menu.add_command(
            label=gettext('Rename Palette...'),
            command=self.event_rename,
        )
        self.ui_menu_indexes.append(menu.index('end'))

        menu.add_command(
            label=gettext('Fill Palette'),
            command=cmd_shuffle,
        )

        menu.add_separator()

        menu.add_checkbutton(
            label=gettext('Save Settings in Palettes'),
            variable=self.var_save_settings,
        )

        menu.add_separator()

        menu.add_command(
            label=gettext('Save Palette'),
            command=self.event_save,
            accelerator=tk_tools.ACCEL_SAVE,
        )
        self.ui_menu_indexes.append(menu.index('end'))
        menu.add_command(
            label=gettext('Save Palette As...'),
            command=self.event_save_as,
            accelerator=tk_tools.ACCEL_SAVE_AS,
        )

        menu.add_separator()
        self.ui_menu_palettes_index = menu.index('end') + 1
        self.update_state()

    @property
    def selected(self) -> Palette:
        """Retrieve the currently selected palette."""
        try:
            return self.palettes[self.selected_uuid]
        except KeyError:
            LOGGER.warning('No such palette with ID {}', self.selected_uuid)
            return self.palettes[UUID_PORTAL2]

    def update_state(self) -> None:
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
            groups.setdefault(pal.group, []).append(pal)

        for group, palettes in sorted(groups.items(), key=lambda t: (t[0] != paletteLoader.GROUP_BUILTIN, t[0])):
            if group == paletteLoader.GROUP_BUILTIN:
                group = gettext('Builtin / Readonly')  # i18n: Palette group title.
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
            for pal in sorted(palettes, key=lambda p: p.name):
                gear_img = ICO_GEAR.get_tk() if pal.settings is not None else ''
                grp_menu.add_radiobutton(
                    label=pal.name,
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
                        text=pal.name,
                        image=gear_img,
                    )
                else:  # New
                    self.ui_treeview.insert(
                        grp_tree, 'end',
                        text=pal.name,
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

        self.ui_menu.entryconfigure(
            self.ui_menu_delete_index,
            label=gettext('Delete Palette "{}"').format(self.selected.name),
        )
        if self.selected.readonly:
            self.ui_remove.state(('disabled',))
            self.save_btn_state(('disabled',))
            for ind in self.ui_menu_indexes:
                self.ui_menu.entryconfigure(ind, state='disabled')
        else:
            self.ui_remove.state(('!disabled',))
            self.save_btn_state(('!disabled',))
            for ind in self.ui_menu_indexes:
                self.ui_menu.entryconfigure(ind, state='normal')

    def make_option_checkbox(self, frame: tk.Misc) -> ttk.Checkbutton:
        """Create a checkbutton configured to control the save palette in settings option."""
        return ttk.Checkbutton(
            frame,
            text=gettext('Save Settings in Palettes'),
            variable=self.var_save_settings,
            command=self._store_configuration,
        )

    def _store_configuration(self) -> None:
        """Save the state of the palette to the config."""
        config.store_conf(PaletteState(self.selected_uuid, self.var_save_settings.get()))

    def event_remove(self) -> None:
        """Remove the currently selected palette."""
        pal = self.selected
        if not pal.readonly and messagebox.askyesno(
            title='BEE2',
            message=gettext('Are you sure you want to delete "{}"?').format(pal.name),
            parent=TK_ROOT,
        ):
            pal.delete_from_disk()
            del self.palettes[pal.uuid]
        self.select_palette(paletteLoader.UUID_PORTAL2)
        background_run(self.set_items, self.selected)

    def event_save(self) -> None:
        """Save the current palette over the original name."""
        if self.selected.readonly:
            self.event_save_as()
            return
        else:
            self.selected.pos = self.get_items()
            if self.var_save_settings.get():
                self.selected.settings = config.get_pal_conf()
            else:
                self.selected.settings = None
            self.selected.save(ignore_readonly=True)
        self.update_state()

    def event_save_as(self) -> None:
        """Save the palette with a new name."""
        name = tk_tools.prompt(gettext("BEE2 - Save Palette"), gettext("Enter a name:"))
        if name is None:
            # Cancelled...
            return
        pal = Palette(name, self.get_items())
        while pal.uuid in self.palettes:  # Should be impossible.
            pal.uuid = paletteLoader.uuid4()

        if self.var_save_settings.get():
            pal.settings = config.get_pal_conf()

        pal.save()
        self.palettes[pal.uuid] = pal
        self.select_palette(pal.uuid)
        self.update_state()

    def event_rename(self) -> None:
        """Rename an existing palette."""
        if self.selected.readonly:
            return
        name = tk_tools.prompt(gettext("BEE2 - Save Palette"), gettext("Enter a name:"))
        if name is None:
            # Cancelled...
            return
        self.selected.name = name
        self.update_state()

    def select_palette(self, uuid: UUID) -> None:
        """Select a new palette. This does not update items/settings!"""
        if uuid in self.palettes:
            self.selected_uuid = uuid
            self._store_configuration()
        else:
            LOGGER.warning('Unknown UUID {}!', uuid.hex)

    def event_change_group(self) -> None:
        """Change the group of a palette."""
        if self.selected.readonly:
            return
        res = tk_tools.prompt(
            gettext("BEE2 - Change Palette Group"),
            gettext('Enter the name of the group for this palette, or "" to ungroup.'),
            validator=lambda x: x,
        )
        if res is not None:
            self.selected.group = res.strip('<>')
            self.selected.save()
            self.update_state()

    async def event_select_menu(self) -> None:
        """Called when the menu buttons are clicked."""
        uuid_hex = self.var_pal_select.get()
        self.select_palette(UUID(hex=uuid_hex))
        await self.set_items(self.selected)
        self.update_state()

    async def event_select_tree(self) -> None:
        """Called when palettes are selected on the treeview."""
        try:
            uuid_hex = self.ui_treeview.selection()[0][4:]
        except IndexError:  # No selection, exit.
            return
        self.var_pal_select.set(uuid_hex)
        self.select_palette(UUID(hex=uuid_hex))
        await self.set_items(self.selected)
        self.update_state()

    def treeview_reselect(self) -> None:
        """When a group item is selected on the tree, reselect the palette."""
        # This could be called before all the items are added to the UI.
        uuid_hex = 'pal_' + self.selected.uuid.hex
        if self.ui_treeview.exists(uuid_hex):
            self.ui_treeview.selection_set(uuid_hex)
