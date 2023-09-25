from typing import Dict, Iterable, Mapping, Union

from srctools import Keyvalues, logger
import attrs

import config


LOGGER = logger.get_logger(__name__, 'conf.signs')
DEFAULT_IDS = {
    3: 'SIGN_NUM_1',
    4: 'SIGN_NUM_2',
    5: 'SIGN_NUM_3',
    6: 'SIGN_NUM_4',

    7: 'SIGN_EXIT',
    8: 'SIGN_CUBE_DROPPER',
    9: 'SIGN_BALL_DROPPER',
    10: 'SIGN_REFLECT_CUBE',

    11: 'SIGN_GOO_TOXIC',
    12: 'SIGN_TBEAM',
    13: 'SIGN_TBEAM_POLARITY',
    14: 'SIGN_LASER_RELAY',

    15: 'SIGN_TURRET',
    16: 'SIGN_LIGHT_BRIDGE',
    17: 'SIGN_PAINT_BOUNCE',
    18: 'SIGN_PAINT_SPEED',
    # Remaining are blank.
    **dict.fromkeys(range(19, 31), ''),
}
VALID_TIME = set(range(3, 31))


def _sign_converter(value: Mapping[int, str]) -> Mapping[int, str]:
    """Ensure existing dicts are copied, and that all keys are present."""
    return {
        i: value.get(i, '')
        for i in VALID_TIME
    }


@config.APP.register
@attrs.frozen(slots=False)
class Layout(config.Data, conf_name='Signage'):
    """A layout of selected signs."""
    signs: Mapping[int, str] = attrs.field(default=DEFAULT_IDS, converter=_sign_converter)

    @classmethod
    def parse_legacy(cls, kv: Keyvalues) -> Dict[str, 'Layout']:
        """Parse the old config format."""
        # Simply call the new parse, it's unchanged.
        sign = Layout.parse_kv1(kv.find_children('Signage'), 1)
        return {'': sign}

    @classmethod
    def parse_kv1(cls, data: Union[Keyvalues, Iterable[Keyvalues]], version: int) -> 'Layout':
        """Parse Keyvalues1 config values."""
        if not data:  # No config, use defaults.
            return cls(DEFAULT_IDS)

        sign = dict.fromkeys(VALID_TIME, '')
        for child in data:
            try:
                timer = int(child.name)
            except (ValueError, TypeError):
                LOGGER.warning('Non-numeric timer value "{}"!', child.name)
                continue

            if timer not in sign:
                LOGGER.warning('Invalid timer value {}!', child.name)
                continue
            sign[timer] = child.value
        return cls(sign)

    def export_kv1(self) -> Keyvalues:
        """Generate keyvalues for saving signages."""
        kv = Keyvalues('Signage', [])
        for timer, sign in self.signs.items():
            kv.append(Keyvalues(str(timer), sign))
        return kv
