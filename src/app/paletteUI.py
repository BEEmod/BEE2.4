"""Handles the UI required for saving and loading palettes."""
from __future__ import annotations
from typing import Callable
from uuid import UUID

import tkinter as tk
from tkinter import ttk, messagebox

import BEE2_config
from app.paletteLoader import Palette
from app import tk_tools, paletteLoader
from localisation import gettext

import srctools.logger

LOGGER = srctools.logger.get_logger(__name__)


class PaletteUI:
    """UI for selecting palettes."""
    def __init__(
        self, f: tk.Frame, menu: tk.Menu,
        *,
        cmd_clear: Callable[[], None],
        cmd_shuffle: Callable[[], None],
        get_items: Callable[[], list[tuple[str, int]]],
    ) -> None:
        """Initialises the palette pane.

        The paramters are used to communicate with the item list:
        - cmd_clear and cmd_shuffle are called to do those actions to the list.
        - pal_get_items is called to retrieve the current list of selected items.
        - cmd_save_btn_state is the .state() method on the save button.
        """
        self.palettes: dict[UUID, Palette] = {
            pal.uuid: pal
            for pal in paletteLoader.load_palettes()
        }

        try:
            self.selected_uuid = UUID(hex=BEE2_config.GEN_OPTS.get_val('Last_Selected', 'palette_uuid', ''))
        except ValueError:
            self.selected_uuid = paletteLoader.UUID_PORTAL2

        f.rowconfigure(1, weight=1)
        f.columnconfigure(0, weight=1)
        self.var_save_settings = tk.BooleanVar(value=BEE2_config.GEN_OPTS.get_bool('General', 'palette_save_settings'))
        self.var_pal_select = tk.StringVar(value=self.selected_uuid.hex)
        self.get_items = get_items
        # Overwritten to configure the save state button.
        self.save_btn_state = lambda s: None

        ttk.Button(
            f,
            text=gettext('Clear Palette'),
            command=cmd_clear,
        ).grid(row=0, sticky="EW")

        self.ui_treeview = ttk.Treeview(f, show='tree', selectmode='browse')
        self.ui_treeview.grid(row=1, sticky="NSEW")

        # def set_pal_listbox(e=None):
        #     global selectedPalette
        #     cur_selection = listbox.curselection()
        #     if cur_selection:  # Might be blank if none selected
        #         selectedPalette = int(cur_selection[0])
        #         selectedPalette_radio.set(selectedPalette)
        #
        #         # Actually set palette..
        #         set_palette()
        #     else:
        #         listbox.selection_set(selectedPalette, selectedPalette)
        #
        # listbox.bind("<<ListboxSelect>>", set_pal_listbox)

        # Set the selected state when hovered, so users can see which is
        # selected.
        # listbox.selection_set(0)

        scrollbar = tk_tools.HidingScroll(
            f,
            orient='vertical',
            command=self.ui_treeview.yview_scroll,
        )
        scrollbar.grid(row=1, column=1, sticky="NS")
        self.ui_treeview['yscrollcommand'] = scrollbar

        self.ui_remove = ttk.Button(
            f,
            text=gettext('Delete Palette'),
            command=self.event_remove,
        )
        self.ui_remove.grid(row=2, sticky="EW")

        if tk_tools.USE_SIZEGRIP:
            ttk.Sizegrip(f).grid(row=2, column=1)

        self.ui_menu = menu
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
        self.ui_menu_palettes_index = menu.index('end')

        # refresh_pal_ui() adds the palette menu options here.

    @property
    def selected(self) -> Palette:
        """Retrieve the currently selected palette."""
        try:
            return self.palettes[self.selected_uuid]
        except KeyError:
            LOGGER.warning('No such palette with ID {}', self.selected_uuid)
            return self.palettes[paletteLoader.UUID_PORTAL2]

    def update_state(self) -> None:
        """Update the UI to show correct state."""
        if self.selected.prevent_overwrite:
            self.ui_remove.state(('disabled',))
            self.save_btn_state(('disabled',))
            self.ui_menu.entryconfigure(self.ui_menu_delete_index, state='disabled')
            self.ui_menu.entryconfigure(self.ui_menu_save_ind, state='disabled')
        else:
            self.ui_remove.state(('!disabled',))
            self.save_btn_state(('!disabled',))
            self.ui_menu.entryconfigure(self.ui_menu_delete_index, state='normal')
            self.ui_menu.entryconfigure(self.ui_menu_save_ind, state='normal')

    def event_save_settings_changed(self) -> None:
        """Save the state of this button."""
        BEE2_config.GEN_OPTS['General']['palette_save_settings'] = srctools.bool_as_int(self.var_save_settings.get())

    def event_remove(self) -> None:
        """Remove the currently selected palette."""

    def event_save(self) -> None:
        """Save the current palette over the original name."""
        if self.selected.prevent_overwrite:
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
        while True:
            name = tk_tools.prompt(gettext("BEE2 - Save Palette"), gettext("Enter a name:"))
            if name is None:
                # Cancelled...
                return
            elif paletteLoader.check_exists(name):
                if messagebox.askyesno(
                    icon=messagebox.QUESTION,
                    title='BEE2',
                    message=gettext('This palette already exists. Overwrite?'),
                ):
                    break
            else:
                break
        pal = Palette(name, self.get_items())
        while pal.uuid in self.palettes:  # Should be impossible.
            pal.uuid = paletteLoader.uuid4()
        self.palettes[pal.uuid] = pal
        pal.save()
        self.update_state()


# def set_pal_radio() -> None:
#     global selected
#     pal_uuid = selected_var.get()
#     try:
#         pal = palettes[UUID(hex=pal_uuid)]
#     except KeyError:
#         LOGGER.warning('Unknown palette UUID {}', pal_uuid)
#         return
#
#     set_treeview_selection()
#     set_palette()
#
#
# def set_treeview_selection(e=None) -> None:
#     """Select the currently chosen palette in the treeview."""
#     UI['palette'].selection_clear(0, len(paletteLoader.pal_list))
#     UI['palette'].selection_set(selectedPalette)
