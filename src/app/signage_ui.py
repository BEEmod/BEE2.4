"""Configures which signs are defined for the Signage item."""
from __future__ import annotations
from typing import Any, Final, Generic, TypeVar
from typing_extensions import TypeAliasType, TypeGuard

from collections.abc import Sequence, Iterator
from datetime import timedelta

import srctools.logger
import trio
import trio_util

from app import EdgeTrigger, dragdrop, img
from config.signage import DEFAULT_IDS, Layout
from packages import Signage, Style, PakRef
import packages
from transtoken import TransToken
import config
import utils


LOGGER = srctools.logger.get_logger(__name__)
SignRef = TypeAliasType("SignRef", PakRef[Signage])
DragManT_co = TypeVar('DragManT_co', bound=dragdrop.ManagerBase[SignRef, Any], covariant=True)
ParentT = TypeVar('ParentT')


# The valid timer indexes for signs.
SIGN_IND: Sequence[int] = range(3, 31)
IMG_ERROR: Final[img.Handle] = img.Handle.error(64, 64)
IMG_BLANK: Final[img.Handle] = img.Handle.background(64, 64)

TRANS_SIGN_NAME: Final = TransToken.ui('Signage: {name}')
TRANS_UNKNOWN_SIGN: Final = TransToken.ui('Unknown Signage: {id}')
TRANS_TITLE: Final = TransToken.ui('Configure Signage')
TRANS_SELECTED: Final = TransToken.ui('Selected')


def is_full(value: SignRef | None) -> TypeGuard[SignRef]:
    """Predicate for valid contents."""
    return value is not None


def export_data() -> list[tuple[str, utils.ObjectID]]:
    """Returns selected items, for Signage.export() to use."""
    conf: Layout = config.APP.get_cur_conf(Layout, default=Layout())
    return [
        (str(ind), sign_id)
        for ind in SIGN_IND
        if (sign_id := conf.signs.get(ind, '')) != ''
    ]


def get_icon(sign: Signage, style: Style) -> img.Handle:
    """Get the icon currently in use for a sign."""
    for potential_style in style.bases:
        try:
            return sign.styles[potential_style.reference()].icon
        except KeyError:
            pass
    LOGGER.warning(
        'No valid <{}> style for "{}" signage!',
        style.id,
        sign.id,
    )
    try:
        return sign.styles[PakRef(Style, packages.CLEAN_STYLE)].icon
    except KeyError:
        return IMG_ERROR


class SignageUIBase(Generic[DragManT_co]):
    """Common implementation of the signage chooser."""
    _slots: dict[int, dragdrop.Slot[SignRef]]
    _cur_style_id: PakRef[Style]

    def __init__(self, drag_man: DragManT_co) -> None:
        """Create the chooser."""
        self.drag_man = drag_man
        self.visible = False
        self._close_event = trio.Event()
        self._slots = {}
        self._cur_style_id = PakRef(Style, packages.CLEAN_STYLE)

    async def apply_config(self, data: Layout) -> None:
        """Apply saved signage info to the UI."""
        for timer in SIGN_IND:
            try:
                slot = self._slots[timer]
            except KeyError:
                LOGGER.warning('Invalid timer value {}!', timer)
                continue

            value = data.signs.get(timer, '')
            if value != "":
                slot.contents = PakRef(Signage, value)
            else:
                slot.contents = None

    def style_changed(self, new_style_id: utils.ObjectID) -> None:
        """Update the icons for the selected signage."""
        self._cur_style_id = PakRef(Style, new_style_id)
        if self.visible:
            self.drag_man.load_icons()

    def _get_drag_info(self, ref: SignRef) -> dragdrop.DragInfo:
        """Get the icon for displaying this sign."""
        packset = packages.get_loaded_packages()
        style = self._cur_style_id.resolve(packset)
        if style is None:
            return dragdrop.DragInfo(IMG_ERROR)

        sign = ref.resolve(packages.get_loaded_packages())
        if sign is None:
            LOGGER.warning('No signage with id "{}"!', ref.id)
            return dragdrop.DragInfo(IMG_ERROR)
        return dragdrop.DragInfo(get_icon(sign, style))

    def _evt_on_closed(self) -> None:
        """Trigger a close."""
        # Late binding!
        self._close_event.set()

    async def task(self, trigger: EdgeTrigger[()]) -> None:
        """Handles opening/closing the UI."""
        await config.APP.set_and_run_ui_callback(Layout, self.apply_config)

        # Alternate between showing and hiding.
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._hovering_task)

            while True:
                await trigger.wait()
                self.drag_man.load_icons()
                self.visible = True
                self.ui_win_show()

                await self._close_event.wait()
                self._close_event = trio.Event()

                # Store off the configured signage.
                config.APP.store_conf(Layout({
                    timer: slt.contents.id if slt.contents is not None else ''
                    for timer, slt in self._slots.items()
                }))
                self.ui_win_hide()
                self.drag_man.unload_icons()
                self.visible = False
                self.ui_set_preview_name(TransToken.BLANK)
                self.ui_set_preview_img(IMG_BLANK, IMG_BLANK)

    def _create_slots(
        self: SignageUIBase[dragdrop.ManagerBase[SignRef, ParentT]],
        parent_chosen: ParentT,
        parent_all: ParentT,
    ) -> Iterator[tuple[int, int, dragdrop.Slot[SignRef]]]:
        """Create all the slots for the signage."""
        load_packset = packages.get_loaded_packages()
        for i in SIGN_IND:
            self._slots[i] = slot = self.drag_man.slot_target(
                parent_chosen,
                label=TransToken.untranslated('{delta:ms}').format(delta=timedelta(seconds=i)),
            )
            row, col = divmod(i-3, 4)
            yield row, col, slot

            prev_id = DEFAULT_IDS.get(i, '')
            if prev_id != "":
                slot.contents = PakRef(Signage, prev_id)

        # TODO: Dynamically refresh this.
        for sign in sorted(load_packset.all_obj(Signage), key=lambda s: s.name):
            if not sign.hidden:
                slot = self.drag_man.slot_source(parent_all)
                slot.contents = PakRef(Signage, utils.obj_id(sign.id))

    async def _hovering_task(self) -> None:
        """Show the signage when hovered, then toggle."""
        while True:
            hover_sign_ref = await self.drag_man.hovered_item.wait_value(is_full)
            packset = packages.get_loaded_packages()

            hover_sign = hover_sign_ref.resolve(packset)
            if hover_sign is None:
                self.ui_set_preview_name(TRANS_UNKNOWN_SIGN.format(id=hover_sign_ref.id))
                self.ui_set_preview_img(IMG_ERROR, IMG_ERROR)
                await self.drag_man.hovered_item.wait_transition()
                continue

            self.ui_set_preview_name(TRANS_SIGN_NAME.format(name=hover_sign.name))

            style = self._cur_style_id.resolve(packset)
            if style is None:
                LOGGER.warning('No such style: {}', self._cur_style_id)
                self.ui_set_preview_img(IMG_ERROR, IMG_ERROR)
                await self.drag_man.hovered_item.wait_transition()
                continue

            single_left = get_icon(hover_sign, style)
            try:
                single_right = get_icon(packset.obj_by_id(Signage, 'SIGN_ARROW'), style)
            except KeyError:
                LOGGER.warning('No arrow signage defined!')
                single_right = IMG_BLANK

            double_left = single_left
            double_right = IMG_BLANK

            if hover_sign.prim_id:
                try:
                    double_left = get_icon(packset.obj_by_id(Signage, hover_sign.prim_id), style)
                except KeyError:
                    pass

            if hover_sign.sec_id:
                try:
                    double_right = get_icon(packset.obj_by_id(Signage, hover_sign.sec_id), style)
                except KeyError:
                    pass

            async with trio_util.move_on_when(self.drag_man.hovered_item.wait_transition):
                while True:
                    self.ui_set_preview_img(single_left, single_right)
                    await trio.sleep(1.0)
                    self.ui_set_preview_img(double_left, double_right)
                    await trio.sleep(1.0)
            # noinspection PyUnreachableCode
            self.ui_set_preview_name(TransToken.BLANK)
            self.ui_set_preview_img(IMG_BLANK, IMG_BLANK)

    def ui_win_show(self) -> None:
        """Show the window."""
        raise NotImplementedError

    def ui_win_hide(self) -> None:
        """Hide the window."""
        raise NotImplementedError

    def ui_set_preview_name(self, name: TransToken) -> None:
        """Set the text for the preview."""
        raise NotImplementedError

    def ui_set_preview_img(self, left: img.Handle, right: img.Handle) -> None:
        """Set the images for the preview."""
        raise NotImplementedError
