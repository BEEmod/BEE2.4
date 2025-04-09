from __future__ import annotations
from typing import override

from collections.abc import Sequence, Mapping

from srctools import Keyvalues, logger
import attrs

import config
import utils


LOGGER = logger.get_logger(__name__, 'conf.signs')
type SignLayout = Mapping[int, utils.ObjectID | utils.BlankID]
DEFAULT_IDS: SignLayout = {
    3: utils.obj_id('SIGN_NUM_1'),
    4: utils.obj_id('SIGN_NUM_2'),
    5: utils.obj_id('SIGN_NUM_3'),
    6: utils.obj_id('SIGN_NUM_4'),

    7: utils.obj_id('SIGN_EXIT'),
    8: utils.obj_id('SIGN_CUBE_DROPPER'),
    9: utils.obj_id('SIGN_BALL_DROPPER'),
    10: utils.obj_id('SIGN_REFLECT_CUBE'),

    11: utils.obj_id('SIGN_GOO_TOXIC'),
    12: utils.obj_id('SIGN_TBEAM'),
    13: utils.obj_id('SIGN_TBEAM_POLARITY'),
    14: utils.obj_id('SIGN_LASER_RELAY'),

    15: utils.obj_id('SIGN_TURRET'),
    16: utils.obj_id('SIGN_LIGHT_BRIDGE'),
    17: utils.obj_id('SIGN_PAINT_BOUNCE'),
    18: utils.obj_id('SIGN_PAINT_SPEED'),
    # Remaining are blank.
    **dict.fromkeys(range(19, 31), ''),
}
VALID_TIME = range(3, 31)


def _sign_converter(value: Mapping[int, str]) -> Mapping[int, utils.ObjectID | utils.BlankID]:
    """Ensure existing dicts are copied, and that all keys are present."""
    return {
        i: utils.obj_id_optional(value.get(i, ''))
        for i in VALID_TIME
    }


@config.PALETTE.register
@config.APP.register
@attrs.frozen
class Layout(config.Data, conf_name='Signage'):
    """A layout of selected signs."""
    signs: SignLayout = attrs.field(default=DEFAULT_IDS, converter=_sign_converter)

    @classmethod
    @override
    def parse_legacy(cls, kv: Keyvalues) -> dict[str, Layout]:
        """Parse the old config format."""
        # Simply call the new parse, it's unchanged.
        sign = Layout.parse_kv1(list(kv.find_children('Signage')), 1)
        return {'': sign}

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues | Sequence[Keyvalues], version: int) -> Layout:
        """Parse Keyvalues1 config values."""
        if version != 1:
            raise config.UnknownVersion(version, '1')

        if not data:  # No config, use defaults.
            return cls(DEFAULT_IDS)

        sign: dict[int, utils.ObjectID | utils.BlankID] = dict.fromkeys(VALID_TIME, utils.ID_EMPTY)
        for child in data:
            try:
                timer = int(child.name)
            except (ValueError, TypeError):
                LOGGER.warning('Non-numeric timer value "{}"!', child.name)
                continue

            if timer not in sign:
                LOGGER.warning('Invalid timer value {}!', child.name)
                continue
            if not child.value:
                continue  # Don't re-assign blank IDs.
            try:
                sign[timer] = utils.obj_id(child.value, 'Signage')
            except ValueError as exc:
                LOGGER.warning(exc.args[0])
        return cls(sign)

    @override
    def export_kv1(self) -> Keyvalues:
        """Generate keyvalues for saving signages."""
        kv = Keyvalues('Signage', [])
        for timer, sign in self.signs.items():
            kv.append(Keyvalues(str(timer), sign))
        return kv
