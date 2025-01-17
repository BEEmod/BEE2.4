from __future__ import annotations
from typing import override

from collections.abc import Sequence
import base64

from srctools import Keyvalues, bool_as_int, logger
from srctools.dmx import Element
import attrs

import config
from consts import DEFAULT_PLAYER
import utils


LOGGER = logger.get_logger(__name__, 'conf.comp_pane')

# Hardcoded IDs to corresponding package IDs
PLAYER_MODEL_LEGACY_IDS = {
    'PETI': DEFAULT_PLAYER,
    'SP': utils.obj_id('VALVE_CHELL'),
    'ATLAS': utils.obj_id('VALVE_ATLAS'),
    'PBODY': utils.obj_id('VALVE_PBODY'),
}


@config.PALETTE.register
@config.APP.register
@attrs.frozen
class CompilePaneState(config.Data, conf_name='CompilerPane', version=2):
    """State saved in palettes.

    Note: We specifically do not save/load the following:
        - packfile dumping
        - compile counts
    This is because these are more system-dependent than map dependent.
    """
    sshot_type: str = 'PETI'
    sshot_cleanup: bool = False
    sshot_cust_fname: str = ''
    sshot_cust: bytes = attrs.field(repr=False, default=b'')
    spawn_elev: bool = False
    player_mdl: utils.ObjectID = DEFAULT_PLAYER
    use_voice_priority: bool = False

    @classmethod
    @override
    def parse_legacy(cls, conf: Keyvalues) -> dict[str, CompilePaneState]:
        """Parse legacy config data."""
        # No change from new KV1 format.
        return {'': cls.parse_kv1(
            conf.find_key('CompilerPane', or_blank=True),
            1,
        )}

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> CompilePaneState:
        """Parse Keyvalues1 format data."""
        if version not in (1, 2):
            raise config.UnknownVersion(version, '1-2')
        if 'sshot_data' in data:
            screenshot_parts = b'\n'.join([
                prop.value.encode('ascii')
                for prop in
                data.find_children('sshot_data')
            ])
            screenshot_data = base64.decodebytes(screenshot_parts)
        else:
            screenshot_data = b''

        sshot_type = data['sshot_type', 'PETI'].upper()
        if sshot_type not in ['AUTO', 'CUST', 'PETI']:
            LOGGER.warning('Unknown screenshot type "{}"!', sshot_type)
            sshot_type = 'AUTO'

        if version == 1:
            legacy_mdl = data['player_model', 'PETI'].upper()
            try:
                player_mdl = PLAYER_MODEL_LEGACY_IDS[legacy_mdl]
            except KeyError:
                LOGGER.warning('Unknown legacy player model "{}"!', legacy_mdl)
                player_mdl = DEFAULT_PLAYER
        else:
            player_mdl = utils.obj_id(data['player_model', DEFAULT_PLAYER])

        return CompilePaneState(
            sshot_type=sshot_type,
            sshot_cleanup=data.bool('sshot_cleanup', False),
            sshot_cust=screenshot_data,
            sshot_cust_fname=data['sshot_fname', ''],
            spawn_elev=data.bool('spawn_elev', False),
            player_mdl=player_mdl,
            use_voice_priority=data.bool('voiceline_priority', False),
        )

    @override
    def export_kv1(self) -> Keyvalues:
        """Generate keyvalues1 format data."""
        kv = Keyvalues('', [
            Keyvalues('sshot_type', self.sshot_type),
            Keyvalues('sshot_cleanup', bool_as_int(self.sshot_cleanup)),
            Keyvalues('spawn_elev', bool_as_int(self.spawn_elev)),
            Keyvalues('player_model', self.player_mdl),
            Keyvalues('voiceline_priority', bool_as_int(self.use_voice_priority)),
        ])

        # Embed the screenshot in so that we can load it later.
        if self.sshot_type == 'CUST':
            # encodebytes() splits it into multiple lines, which we write
            # in individual blocks to prevent having a massively long line
            # in the file.
            kv.append(Keyvalues(
                'sshot_data',
                [
                    Keyvalues('b64', data) for data in
                    base64.encodebytes(self.sshot_cust).decode('ascii').splitlines()
                ]
            ))
            kv.append(Keyvalues('sshot_fname', self.sshot_cust_fname))
        return kv

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> CompilePaneState:
        """Parse DMX format data."""
        if version not in (1, 2):
            raise config.UnknownVersion(version, '1-2')

        try:
            sshot_type = data['sshot_type'].val_str.upper()
        except KeyError:
            sshot_type = 'AUTO'
        else:
            if sshot_type not in ['AUTO', 'CUST', 'PETI']:
                LOGGER.warning('Unknown screenshot type "{}"!', sshot_type)
                sshot_type = 'AUTO'

        if sshot_type == 'CUST':
            try:
                screenshot_data = data['sshot_data'].val_binary
            except KeyError:
                screenshot_data = b''
            try:
                screenshot_fname = data['sshot_fname'].val_string
            except KeyError:
                screenshot_fname = ''
        else:
            screenshot_data = b''
            screenshot_fname = ''

        if version == 1:
            legacy_mdl = data['player_model'].val_str.upper()
            try:
                player_mdl = PLAYER_MODEL_LEGACY_IDS[legacy_mdl]
            except KeyError:
                LOGGER.warning('Unknown legacy player model "{}"!', legacy_mdl)
                player_mdl = DEFAULT_PLAYER
        else:
            try:
                player_mdl = utils.obj_id(data['player_model'].val_str)
            except KeyError:
                player_mdl = DEFAULT_PLAYER

        try:
            sshot_cleanup = data['sshot_cleanup'].val_bool
        except KeyError:
            sshot_cleanup = False

        try:
            spawn_elev = data['spawn_elev'].val_bool
        except KeyError:
            spawn_elev = False

        try:
            use_voice_priority = data['voiceline_priority'].val_bool
        except KeyError:
            use_voice_priority = False

        return CompilePaneState(
            sshot_type=sshot_type,
            sshot_cleanup=sshot_cleanup,
            sshot_cust=screenshot_data,
            sshot_cust_fname=screenshot_fname,
            spawn_elev=spawn_elev,
            player_mdl=player_mdl,
            use_voice_priority=use_voice_priority,
        )

    @override
    def export_dmx(self) -> Element:
        """Generate DMX format data."""
        elem = Element('CompilerPaneState', 'DMElement')
        elem['sshot_type'] = self.sshot_type
        elem['sshot_cleanup'] = self.sshot_cleanup
        elem['spawn_elev'] = self.spawn_elev
        elem['player_model'] = self.player_mdl
        elem['voiceline_priority'] = self.use_voice_priority
        if self.sshot_type == 'CUST':
            elem['sshot_data'] = self.sshot_cust
            elem['sshot_fname'] = self.sshot_cust_fname
        return elem
