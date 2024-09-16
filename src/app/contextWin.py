"""
The rightclick pane which shows item descriptions,and allows changing
various item properties.
- init() creates all the required widgets, and is called with the root window.
- showProps() shows the screen.
- hideProps() hides the screen.
- open_event is the TK callback version of showProps(), which gets the
  clicked widget from the event
"""
from __future__ import annotations

from contextlib import aclosing
from enum import Enum
import webbrowser

from trio_util import AsyncValue
from srctools.logger import get_logger
import trio

from . import sound, img, DEV_MODE
from async_util import EdgeTrigger
from .dragdrop import Slot
from .item_picker import ItemPickerBase
from .item_properties import PropertyWindow
from .mdown import MarkdownData
from .dialogs import Dialogs
from consts import DefaultItems
from .paletteLoader import Coord
from packages.item import Item, ItemVariant, SubItemRef, Version
from packages.signage import ITEM_ID as SIGNAGE_ITEM_ID
import packages

from editoritems import Handle as RotHandle, SubType, Surface, ItemClass
from editoritems_props import prop_timer_delay
from transtoken import TransToken


LOGGER = get_logger(__name__)

SUBITEM_POS = {
    # Positions of subitems depending on the number of subitems that exist
    # This way they appear nicely centered on the list
    1: (-1, -1,  0, -1, -1),  # __0__
    2: (-1,  0, -1,  1, -1),  # _0_0_
    3: (-1,  0,  1,  2, -1),  # _000_
    4: (+0,  1, -1,  2,  3),  # 00_00
    5: (+0,  1,  2,  3,  4),  # 00000
}

ROT_TYPES: dict[RotHandle, str] = {
    #  Image names that correspond to editoritems values
    RotHandle.NONE:     "rot_0",
    RotHandle.QUAD:     "rot_4",
    RotHandle.CENT_OFF: "rot_5",
    RotHandle.DUAL_OFF: "rot_6",
    RotHandle.QUAD_OFF: "rot_8",
    RotHandle.FREE_ROT: "rot_36",
    RotHandle.FAITH:    "rot_catapult",
}


class SPR(Enum):
    """The slots for property-indicating sprites. The value is the column."""
    INPUT = 0
    OUTPUT = 1
    ROTATION = 2
    COLLISION = 3
    FACING = 4


SPRITE_TOOL = {
    # The tooltips associated with each sprite.
    'rot_0': TransToken.ui('This item may not be rotated.'),
    'rot_4': TransToken.ui('This item can be pointed in 4 directions.'),
    'rot_5': TransToken.ui('This item can be positioned on the sides and center.'),
    'rot_6': TransToken.ui('This item can be centered in two directions, plus on the sides.'),
    'rot_8': TransToken.ui('This item can be placed like light strips.'),
    'rot_36': TransToken.ui('This item can be rotated on the floor to face 360 degrees.'),
    'rot_catapult': TransToken.ui('This item is positioned using a catapult trajectory.'),
    'rot_paint': TransToken.ui('This item positions the dropper to hit target locations.'),

    'in_none': TransToken.ui('This item does not accept any inputs.'),
    'in_norm': TransToken.ui('This item accepts inputs.'),
    'in_dual': TransToken.ui('This item has two input types (A and B), using the Input A and B items.'),

    'out_none': TransToken.ui('This item does not output.'),
    'out_norm': TransToken.ui('This item has an output.'),
    'out_tim': TransToken.ui('This item has a timed output.'),

    'space_none': TransToken.ui('This item does not take up any space inside walls.'),
    'space_embed': TransToken.ui('This item takes space inside the wall.'),

    'surf_none': TransToken.ui('This item cannot be placed anywhere...'),
    'surf_ceil': TransToken.ui('This item can only be attached to ceilings.'),
    'surf_floor': TransToken.ui('This item can only be placed on the floor.'),
    'surf_floor_ceil': TransToken.ui('This item can be placed on floors and ceilings.'),
    'surf_wall': TransToken.ui('This item can be placed on walls only.'),
    'surf_wall_ceil': TransToken.ui('This item can be attached to walls and ceilings.'),
    'surf_wall_floor': TransToken.ui('This item can be placed on floors and walls.'),
    'surf_wall_floor_ceil': TransToken.ui('This item can be placed in any orientation.'),
}
IMG_ALPHA: img.Handle = img.Handle.blank(64, 64)
# Special case tooltips
TRANS_TOOL_TBEAM = TransToken.ui('Excursion Funnels accept a on/off input and a directional input.')
TRANS_TOOL_CUBE = TransToken.ui(
    '{generic_rot} However when this is set to Reflection Cube, this item can instead rotated on '
    'the floor to face 360 degrees.'
)
TRANS_TOOL_FIZZOUT = TransToken.ui(
    'This fizzler has an output. Due to an editor bug, this cannot be used directly. Instead '
    'the Fizzler Output Relay item should be placed on top of this fizzler.'
)
TRANS_TOOL_FIZZOUT_TIMED = TransToken.ui(
    'This fizzler has a timed output. Due to an editor bug, this cannot be used directly. Instead '
    'the Fizzler Output Relay item should be placed on top of this fizzler.'
)
TRANS_NO_VERSIONS = TransToken.ui('No Alternate Versions')
TRANS_ENT_COUNT = TransToken.ui(
    'The number of entities used for this item. The Source engine '
    'limits this to 2048 in total. This provides a guide to how many of '
    'these items can be placed in a map at once.'
)


def pos_for_item(item: Item, ind: int) -> int | None:
    """Get the index the specified subitem is located at."""
    positions = SUBITEM_POS[len(item.visual_subtypes)]
    for pos, sub in enumerate(positions):
        if sub != -1 and ind == item.visual_subtypes[sub]:
            return pos
    else:
        return None


def ind_for_pos(item: Item, pos: int) -> int | None:
    """Return the subtype index for the specified position."""
    ind = SUBITEM_POS[len(item.visual_subtypes)][pos]
    if ind == -1:
        return None
    else:
        return item.visual_subtypes[ind]


def get_description(
    global_last: bool,
    glob_desc: MarkdownData,
    style_desc: MarkdownData,
) -> MarkdownData:
    """Join together the general and style description for an item."""
    if glob_desc and style_desc:
        if global_last:
            return style_desc + glob_desc
        else:
            return glob_desc + style_desc
    elif glob_desc:
        return glob_desc
    elif style_desc:
        return style_desc
    else:
        return MarkdownData.BLANK  # No description


class ContextWinBase:
    """Shared logic for item context windows.

    TargetT: The widget representing palette icons.
    """
    # If we are open, info about the selected widget.
    selected: SubItemRef | None
    selected_slot: Slot[SubItemRef] | None  # The slot we're opening on.
    selected_pal_pos: Coord | None  # Palette position, if from there. Allows changing version.

    dialog: Dialogs
    picker: ItemPickerBase
    # If set, the item properties window is open and suppressing us.
    props_open: bool

    moreinfo_url: AsyncValue[str | None]
    moreinfo_trigger: EdgeTrigger[str]
    defaults_trigger: EdgeTrigger[()]

    def __init__(self, item_picker: ItemPickerBase, dialog: Dialogs) -> None:
        self.selected = None
        self.selected_slot = None
        self.selected_pal_pos = None
        self.dialog = dialog
        self.picker = item_picker
        self.props_open = False
        self.packset = packages.PackagesSet()

        # The current URL in the more-info button, if available.
        self.moreinfo_url = AsyncValue(None)
        self.moreinfo_trigger = EdgeTrigger()
        # Triggered to open the change-defaults button.
        self.defaults_trigger = EdgeTrigger()

    @property
    def is_visible(self) -> bool:
        """We are visible if a selected item is defined."""
        return self.selected is not None and not self.props_open

    async def init_widgets(
        self,
        signage_trigger: EdgeTrigger[()],
        *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
    ) -> None:
        """Initialise all the window components."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self.ui_task, signage_trigger)
            nursery.start_soon(self._moreinfo_task)
            nursery.start_soon(self._packset_changed_task)
            nursery.start_soon(self.picker.open_contextwin_task, self.show_prop)
            task_status.started()

    async def _packset_changed_task(self) -> None:
        """Whenever packages change, force-close."""
        async with aclosing(packages.LOADED.eventual_values()) as agen:
            async for self.packset in agen:
                self.hide_context()
                await trio.lowlevel.checkpoint()

    def get_current(self) -> tuple[
        packages.PakRef[packages.Style],
        Item, Version, ItemVariant, SubType,
    ]:
        """Fetch the tree representing the selected subtype."""
        assert self.selected is not None
        item = self.selected.item.resolve(self.packset)
        if item is None:
            raise LookupError
        version = item.selected_version()
        style_ref = self.picker.cur_style()
        try:
            variant = version.styles[style_ref.id]
        except KeyError:
            LOGGER.warning('No {} style for {}!', style_ref, self.selected)
            variant = version.def_style
        try:
            subtype = variant.editor.subtypes[self.selected.subtype]
        except KeyError:
            LOGGER.warning('No subtype {} in style {}!', self.selected, style_ref)
            first = item.visual_subtypes[0]
            self.selected = self.selected.with_subtype(first)
            subtype = variant.editor.subtypes[first]

        return style_ref, item, version, variant, subtype

    def load_item_data(self) -> None:
        """Refresh the window to use the selected item's data."""
        if self.selected is None:
            return
        try:
            style_ref, item, version, variant, subtype = self.get_current()
        except LookupError:  # Not defined?
            return
        item_id = self.selected.item.id

        sel_pos = pos_for_item(item, self.selected.subtype)
        for ind, pos in enumerate(SUBITEM_POS[len(item.visual_subtypes)]):
            if pos == -1:
                icon = IMG_ALPHA
            else:
                icon = item.get_icon(style_ref, item.visual_subtypes[pos])
            self.ui_set_props_icon(ind, icon, ind == sel_pos)

        desc = get_description(
            global_last=item.glob_desc_last,
            glob_desc=item.glob_desc,
            style_desc=variant.desc,
        )
        # Dump out the instances used in this item.
        if DEV_MODE.value:
            desc += variant.instance_desc()

        self.ui_set_props_main(
            name=subtype.name,
            authors=TransToken.list_and(
                map(TransToken.untranslated, variant.authors), sort=True,
            ),
            desc=desc,
            ent_count=variant.ent_count or '??',
        )

        if DEV_MODE.value:
            source = variant.source.replace("from", "\nfrom")
            self.ui_set_debug_itemid(f'{source}\n-> {self.selected}')
        else:
            self.ui_set_debug_itemid('')

        self.ui_set_defaults_enabled(PropertyWindow.can_edit(variant.editor))

        if self.selected.item == SIGNAGE_ITEM_ID:
            self.ui_show_sign_config()
        else:
            self.ui_show_variants(item)

        self.moreinfo_url.value = variant.url
        has_timer = any(prop.kind is prop_timer_delay for prop in variant.editor.properties.values())

        if variant.editor.has_prim_input():
            if variant.editor.has_sec_input():
                self.set_sprite(SPR.INPUT, 'in_dual')
                # Real funnels work slightly differently.
                if item_id == DefaultItems.funnel.id:
                    self.ui_set_sprite_tool(SPR.INPUT, TRANS_TOOL_TBEAM)
            else:
                self.set_sprite(SPR.INPUT, 'in_norm')
        else:
            self.set_sprite(SPR.INPUT, 'in_none')

        if variant.editor.has_output():
            if has_timer:
                self.set_sprite(SPR.OUTPUT, 'out_tim')
                # Mention the Fizzler Output Relay here.
                if variant.editor.cls is ItemClass.FIZZLER:
                    self.ui_set_sprite_tool(SPR.OUTPUT, TRANS_TOOL_FIZZOUT_TIMED)
            else:
                self.set_sprite(SPR.OUTPUT, 'out_norm')
                if variant.editor.cls is ItemClass.FIZZLER:
                    self.ui_set_sprite_tool(SPR.OUTPUT, TRANS_TOOL_FIZZOUT)
        else:
            self.set_sprite(SPR.OUTPUT, 'out_none')

        self.set_sprite(SPR.ROTATION, ROT_TYPES[variant.editor.handle])

        if variant.editor.embed_voxels:
            self.set_sprite(SPR.COLLISION, 'space_embed')
        else:
            self.set_sprite(SPR.COLLISION, 'space_none')

        face_spr = "surf"
        if Surface.WALL not in variant.editor.invalid_surf:
            face_spr += "_wall"
        if Surface.FLOOR not in variant.editor.invalid_surf:
            face_spr += "_floor"
        if Surface.CEIL not in variant.editor.invalid_surf:
            face_spr += "_ceil"
        if face_spr == "surf":
            # This doesn't seem right - this item won't be placeable at all...
            LOGGER.warning(
                "Item <{}> disallows all orientations. Is this right?",
                self.selected.item,
            )
            face_spr += "_none"

        self.set_sprite(SPR.FACING, face_spr)

        # Now some special overrides for certain classes.
        if item_id == DefaultItems.cube.id:
            # Cubes - they should show info for the dropper.
            self.set_sprite(SPR.FACING, 'surf_ceil')
            self.set_sprite(SPR.INPUT, 'in_norm')
            self.set_sprite(SPR.COLLISION, 'space_embed')
            self.set_sprite(SPR.OUTPUT, 'out_none')
            # This can have 2 handles - the specified one, overridden to 36 on reflection cubes.
            # Concatenate the two definitions.
            self.ui_set_sprite_tool(SPR.ROTATION, TRANS_TOOL_CUBE.format(
                generic_rot=SPRITE_TOOL[ROT_TYPES[variant.editor.handle]]
            ))

        if variant.editor.cls is ItemClass.GEL:
            # Reflection or normal gel...
            self.set_sprite(SPR.FACING, 'surf_wall_ceil')
            self.set_sprite(SPR.INPUT, 'in_norm')
            self.set_sprite(SPR.COLLISION, 'space_none')
            self.set_sprite(SPR.OUTPUT, 'out_none')
            self.set_sprite(SPR.ROTATION, 'rot_paint')
        elif variant.editor.cls is ItemClass.TRACK_PLATFORM:
            # Track platform - always embeds into the floor.
            self.set_sprite(SPR.COLLISION, 'space_embed')

        real_conn_item = variant.editor
        if item_id == DefaultItems.cube.id or item_id == DefaultItems.gel_splat.id:
            # The connections are on the dropper.
            try:
                [real_conn_item] = variant.editor_extra
            except ValueError:
                # Moved elsewhere?
                pass

        if DEV_MODE.value and real_conn_item.conn_config is not None:
            # Override tooltips with the raw information.
            blurb = real_conn_item.conn_config.get_input_blurb()
            if real_conn_item.force_input:
                # Strip to remove \n if blurb is empty.
                blurb = ('Input force-enabled!\n' + blurb).strip()
            self.ui_set_sprite_tool(SPR.INPUT, TransToken.untranslated(blurb))

            blurb = real_conn_item.conn_config.get_output_blurb()
            if real_conn_item.force_output:
                blurb = ('Output force-enabled!\n' + blurb).strip()
            self.ui_set_sprite_tool(SPR.OUTPUT, TransToken.untranslated(blurb))

    def hide_context(self, e: object = None) -> None:
        """Hide the properties window, if it's open."""
        if self.is_visible:
            self.ui_hide_window()
            sound.fx('contract')
            self.selected = self.selected_slot = self.selected_pal_pos = None

    def show_prop(
        self,
        slot: Slot[SubItemRef],
        pal_pos: Coord | None,
        warp_cursor: bool = False,
    ) -> None:
        """Show the properties window for an item in a slot.

        - widget should be the widget that represents the item.
        - If warp_cursor is true, the cursor will be moved relative to this window so that
          it stays on top of the selected subitem.
        - If from the palette, pal_pos is the position.
        """
        if warp_cursor and self.is_visible:
            offset = self.ui_get_cursor_offset()
        else:
            offset = None
        self.selected = slot.contents
        if self.selected is None:
            LOGGER.warning('Selected empty slot?')
            self.hide_context()
            return
        # Check to see if it's actually a valid item too.
        if self.selected.item.resolve(self.packset) is None:
            LOGGER.info('Item not defined, nothing to show.')
            self.hide_context()
            return

        self.selected_slot = slot
        self.selected_pal_pos = pal_pos

        x, y = slot.get_coords()
        self.ui_show_window(x, y)
        self.adjust_position()

        if offset is not None:
            self.ui_set_cursor_offset(offset)
        self.load_item_data()

    async def _moreinfo_task(self) -> None:
        """Task to handle clicking on the 'more info' URL."""
        while True:
            url = await self.moreinfo_trigger.wait()

            try:
                webbrowser.open_new_tab(url)
            except webbrowser.Error:
                if await self.dialog.ask_yes_no(
                    title=TransToken.ui("BEE2 - Error"),
                    message=TransToken.ui(
                        'Failed to open a web browser. Do you wish for the URL '
                        'to be copied to the clipboard instead?'
                    ),
                    icon=self.dialog.ERROR,
                    detail=f'"{url}"',
                ):
                    LOGGER.info("Saving {} to clipboard!", url)
                    self.ui_set_clipboard(url)
            # Either the web browser or the messagebox could cause the
            # properties to move behind the main window, so hide it
            # so that it doesn't appear there.
            self.hide_context()

    def set_sprite(self, pos: SPR, sprite: str) -> None:
        """Set one of the property sprites to a value, with the default context menu."""
        self.ui_set_sprite_img(pos, img.Handle.sprite('icons/' + sprite, 32, 32))
        self.ui_set_sprite_tool(pos, SPRITE_TOOL[sprite])

    def sub_sel(self, pos: int, e: object = None) -> None:
        """Change the currently-selected sub-item."""
        if self.selected is None or self.selected_slot is None:
            return
        item = self.selected.item.resolve(packages.get_loaded_packages())
        if item is None:
            return
        ind = ind_for_pos(item, pos)
        # Can only change the subitem on the preview window
        if self.selected_pal_pos is not None and ind is not None:
            sound.fx('config')
            ref = self.selected.with_subtype(ind)
            if self.picker.change_pal_subtype(self.selected_slot, ref):
                # Redisplay the window to refresh data and move it to match
                self.show_prop(self.selected_slot, self.selected_pal_pos, warp_cursor=True)

    def sub_open(self, pos: int, e: object = None) -> None:
        """Move the context window to apply to the given item."""
        assert self.selected is not None
        item = self.selected.item.resolve(packages.get_loaded_packages())
        if item is not None:
            ind = ind_for_pos(item, pos)
            if ind is not None:
                sound.fx('expand')
                slot, pal_pos = self.picker.find_matching_slot(
                    self.selected.with_subtype(ind),
                    check_palette=self.selected_pal_pos is not None,
                )
                if slot is not None:
                    self.show_prop(slot, pal_pos)

    def adjust_position(self, e: object = None) -> None:
        """Move the properties window onto the selected item.

        We call this constantly, so the property window will not go outside
        the screen, and snap back to the item when the main window returns.
        """
        if not self.is_visible or self.selected is None or self.selected_slot is None:
            return
        if (item := self.selected.item.resolve(packages.get_loaded_packages())) is None:
            return
        if (pos := pos_for_item(item, self.selected.subtype)) is None:
            return

        # Calculate the pixel offset between the window and the subitem in
        # the properties dialog, and shift if needed to keep it inside the
        # window
        targ_x, targ_y = self.selected_slot.get_coords()
        icon_x, icon_y = self.ui_get_icon_offset(pos)

        self.ui_show_window(targ_x - icon_x, targ_y - icon_y)

    async def ui_task(self, signage_trigger: EdgeTrigger[()]) -> None:
        """Run logic to update the UI."""
        raise NotImplementedError

    def ui_set_sprite_img(self, sprite: SPR, icon: img.Handle) -> None:
        """Set the image for a connection sprite."""
        raise NotImplementedError

    def ui_set_sprite_tool(self, sprite: SPR, tool: TransToken) -> None:
        """Set the tooltip for a connection sprite."""
        raise NotImplementedError

    def ui_set_props_main(
        self,
        name: TransToken,
        authors: TransToken,
        desc: MarkdownData,
        ent_count: str,
    ) -> None:
        """Set the main set of widgets for properties."""
        raise NotImplementedError

    def ui_set_props_icon(self, ind: int, icon: img.Handle, selected: bool) -> None:
        """Set the palette icon in the menu."""
        raise NotImplementedError

    def ui_set_debug_itemid(self, itemid: str) -> None:
        """Set the debug item ID, or hide it if blank."""
        raise NotImplementedError

    def ui_get_icon_offset(self, ind: int) -> tuple[int, int]:
        """Get the offset of this palette icon widget."""
        raise NotImplementedError

    def ui_hide_window(self) -> None:
        """Hide the window."""
        raise NotImplementedError

    def ui_show_window(self, x: int, y: int) -> None:
        """Show the window, at the specified position."""
        raise NotImplementedError

    def ui_get_cursor_offset(self) -> tuple[int, int]:
        """Fetch the offset of the cursor relative to the window, for restoring when it moves."""
        raise NotImplementedError

    def ui_set_cursor_offset(self, offset: tuple[int, int]) -> None:
        """Apply the offset, after the window has moved."""
        raise NotImplementedError

    def ui_set_clipboard(self, text: str) -> None:
        """Add the specified text to the clipboard."""
        raise NotImplementedError

    def ui_show_sign_config(self) -> None:
        """Show the special signage-configure button."""
        raise NotImplementedError

    def ui_show_variants(self, item: Item) -> None:
        """Show the variants combo-box, and configure it."""
        raise NotImplementedError

    def ui_set_defaults_enabled(self, enable: bool) -> None:
        """Set whether the Change Defaults button is enabled."""
        raise NotImplementedError
