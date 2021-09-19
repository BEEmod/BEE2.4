"""Handles the UI required for saving and loading palettes."""
from __future__ import annotations
from typing import Callable
from uuid import UUID

import tkinter as tk
from tkinter import ttk, messagebox

import BEE2_config
from app.paletteLoader import Palette, UUID_PORTAL2, UUID_EXPORT
from app import tk_tools, paletteLoader, TK_ROOT, img
from localisation import gettext

import srctools.logger

LOGGER = srctools.logger.get_logger(__name__)
# "Wheel of Dharma" / white sun, close enough and should be in most fonts.
CHR_GEAR = '☼ '
TREE_TAG_GROUPS = 'pal_group'
TREE_TAG_PALETTES = 'palette'
ICO_GEAR = img.Handle.sprite('icons/gear', 10, 10)


class PaletteUI:
    """UI for selecting palettes."""
    def __init__(
        self, f: tk.Frame, menu: tk.Menu,
        *,
        cmd_clear: Callable[[], None],
        cmd_shuffle: Callable[[], None],
        get_items: Callable[[], list[tuple[str, int]]],
        set_items: Callable[[Palette], None],
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

        try:
            self.selected_uuid = UUID(hex=BEE2_config.GEN_OPTS.get_val('Last_Selected', 'palette_uuid', ''))
        except ValueError:
            self.selected_uuid = UUID_PORTAL2

        f.rowconfigure(1, weight=1)
        f.columnconfigure(0, weight=1)
        self.var_save_settings = tk.BooleanVar(value=BEE2_config.GEN_OPTS.get_bool('General', 'palette_save_settings'))
        self.var_pal_select = tk.StringVar(value=self.selected_uuid.hex)
        self.get_items = get_items
        self.set_items = set_items
        # Overwritten to configure the save state button.
        self.save_btn_state = lambda s: None

        ttk.Button(
            f,
            text=gettext('Clear Palette'),
            command=cmd_clear,
        ).grid(row=0, sticky="EW")

        self.ui_treeview = treeview = ttk.Treeview(f, show='tree', selectmode='browse')
        self.ui_treeview.grid(row=1, sticky="NSEW")
        self.ui_treeview.tag_bind(TREE_TAG_PALETTES, '<ButtonPress>', self.event_select_tree)
        # Avoid re-registering the double-lambda, just do it here.
        evtid_group_select = self.ui_treeview.register(self.event_group_select_tree)
        self.ui_treeview.tag_bind(TREE_TAG_GROUPS, '<ButtonPress>', lambda e: treeview.tk.call('after', 'idle', evtid_group_select))

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

        menu.add_command(
            label=gettext('Change Palette Group...'),
            command=self.event_change_group,
        )
        self.ui_menu_regroup_index = menu.index('end')

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
        self.ui_menu_save_ind = menu.index('end')
        menu.add_command(
            label=gettext('Save Palette As...'),
            command=self.event_save_as,
            accelerator=tk_tools.ACCEL_SAVE_AS,
        )

        menu.add_separator()
        self.ui_menu_palettes_index = menu.index('end') + 1

        # refresh_pal_ui() adds the palette menu options here.

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
                grp_menu.add_radiobutton(
                    label=CHR_GEAR + pal.name if pal.settings is not None else pal.name,
                    value=pal.uuid.hex,
                    command=self.event_select_menu,
                    variable=self.var_pal_select,
                )
                pal_id = 'pal_' + pal.uuid.hex
                if pal_id in existing:
                    existing.remove(pal_id)
                    self.ui_treeview.move(pal_id, grp_tree, 99999)
                    self.ui_treeview.item(
                        pal_id,
                        text=pal.name,
                        image=ICO_GEAR.get_tk() if pal.settings is not None else '',
                    )
                else:  # New
                    self.ui_treeview.insert(
                        grp_tree, 'end',
                        text=pal.name,
                        iid='pal_' + pal.uuid.hex,
                        image=ICO_GEAR.get_tk() if pal.settings is not None else '',
                        tags=TREE_TAG_PALETTES,
                    )
        # Finally strip any ones which were removed.
        if existing:
            self.ui_treeview.delete(*existing)

        self.ui_menu.entryconfigure(
            self.ui_menu_delete_index,
            label=gettext('Delete Palette "{}"').format(self.selected.name),
        )
        if self.selected.readonly:
            self.ui_remove.state(('disabled',))
            self.save_btn_state(('disabled',))
            self.ui_menu.entryconfigure(self.ui_menu_delete_index, state='disabled')
            self.ui_menu.entryconfigure(self.ui_menu_regroup_index, state='disabled')
            self.ui_menu.entryconfigure(self.ui_menu_save_ind, state='disabled')
        else:
            self.ui_remove.state(('!disabled',))
            self.save_btn_state(('!disabled',))
            self.ui_menu.entryconfigure(self.ui_menu_delete_index, state='normal')
            self.ui_menu.entryconfigure(self.ui_menu_regroup_index, state='normal')
            self.ui_menu.entryconfigure(self.ui_menu_save_ind, state='normal')

    def event_save_settings_changed(self) -> None:
        """Save the state of this button."""
        BEE2_config.GEN_OPTS['General']['palette_save_settings'] = srctools.bool_as_int(self.var_save_settings.get())

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
        self.set_items(self.selected)

    def event_save(self) -> None:
        """Save the current palette over the original name."""
        if self.selected.readonly:
            self.event_save_as()
            return
        else:
            self.selected.pos = self.get_items()
            if self.var_save_settings.get():
                self.selected.settings = BEE2_config.get_curr_settings(is_palette=True)
            else:
                self.selected.settings = None
            self.selected.save()
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
        pal.save()
        self.palettes[pal.uuid] = pal
        self.select_palette(pal.uuid)
        self.update_state()

    def select_palette(self, uuid: UUID) -> None:
        """Select a new palette, and update state. This does not update items/settings!"""
        pal = self.palettes[uuid]
        self.selected_uuid = uuid
        BEE2_config.GEN_OPTS['Last_Selected']['palette_uuid'] = uuid.hex

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

    def event_select_menu(self) -> None:
        """Called when the menu buttons are clicked."""
        uuid_hex = self.var_pal_select.get()
        self.select_palette(UUID(hex=uuid_hex))
        self.ui_treeview.selection_set('pal_' + uuid_hex)
        self.ui_treeview.see('pal_' + uuid_hex)
        self.set_items(self.selected)
        self.update_state()

    def event_select_tree(self, evt: tk.Event) -> None:
        """Called when palettes are selected on the treeview."""
        # We're called just before it actually changes, so look up by the cursor pos.
        uuid_hex = self.ui_treeview.identify('item', evt.x, evt.y)[4:]
        self.var_pal_select.set(uuid_hex)
        self.select_palette(UUID(hex=uuid_hex))
        self.set_items(self.selected)
        self.update_state()

    def event_group_select_tree(self) -> None:
        """When a group item is selected on the tree, reselect the palette."""
        self.ui_treeview.selection_set('pal_' + self.selected.uuid.hex)
