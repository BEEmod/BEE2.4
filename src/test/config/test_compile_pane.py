"""Test item default configs."""
from random import Random
import base64


from srctools import Keyvalues
from srctools.dmx import Element, Attribute
import pytest

import utils
from config import UnknownVersion
from config.compile_pane import CompilePaneState
from consts import DEFAULT_PLAYER


# We don't test that the value is actually a screenshot, just use some random data.
SCREENSHOT_DATA = Random(1234).randbytes(256)
# Also not testing base64 itself. encodebytes() splits these into 72-long lines.
SCREENSHOT_BASE64 = base64.encodebytes(SCREENSHOT_DATA).decode('ascii').splitlines()


def test_parse_invalid_versions() -> None:
    """Test errors are raised for invalid versions."""
    kv = Keyvalues('CompilePaneState', [])
    elem = Element('CompilePaneState', 'DMEConfig')

    with pytest.raises(UnknownVersion):
        CompilePaneState.parse_kv1(kv, 3)

    with pytest.raises(UnknownVersion):
        CompilePaneState.parse_dmx(elem, 3)


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 data."""

    assert CompilePaneState.parse_kv1(
        Keyvalues('', []), 2,
    ) == CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=False,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=False,
        player_mdl=DEFAULT_PLAYER,
        use_voice_priority=False,
    )

    assert CompilePaneState.parse_kv1(Keyvalues('', [
        Keyvalues('spawn_elev', '0'),
        Keyvalues('voiceline_priority', '1'),
        Keyvalues('player_model', 'VALVE_PBODY'),
        Keyvalues('sshot_type', 'PeTI'),
        Keyvalues('sshot_cleanup', '1'),
    ]), 2) == CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=True,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=False,
        player_mdl=utils.obj_id('VALVE_PBODY'),
        use_voice_priority=True,
    )

    assert CompilePaneState.parse_kv1(Keyvalues('', [
        Keyvalues('spawn_elev', '1'),
        Keyvalues('voiceline_priority', '0'),
        Keyvalues('player_model', 'apertURE_tag'),
        Keyvalues('sshot_type', 'auTO'),
        Keyvalues('sshot_cleanup', '1'),
    ]), 2) == CompilePaneState(
        sshot_type='AUTO',
        sshot_cleanup=True,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=True,
        player_mdl=utils.obj_id('APERTURE_TAG'),
        use_voice_priority=False,
    )

    assert CompilePaneState.parse_kv1(Keyvalues('', [
        Keyvalues('spawn_elev', '1'),
        Keyvalues('voiceline_priority', '1'),
        Keyvalues('sshot_type', 'CUST'),
        Keyvalues('sshot_data', [
            Keyvalues('b64', line)
            for line in SCREENSHOT_BASE64
        ]),
        Keyvalues('sshot_cleanup', '1'),
    ]), 2) == CompilePaneState(
        sshot_type='CUST',
        sshot_cleanup=True,
        sshot_cust=SCREENSHOT_DATA,
        sshot_cust_fname='',
        spawn_elev=True,
        player_mdl=DEFAULT_PLAYER,
        use_voice_priority=True,
    )


def test_export_kv1() -> None:
    """Test exporting keyvalues1 data."""
    kv = CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=False,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=False,
        player_mdl=DEFAULT_PLAYER,
        use_voice_priority=False,
    ).export_kv1()
    assert len(kv) == 5
    assert kv['sshot_type'] == 'PETI'
    assert kv['sshot_cleanup'] == '0'
    assert kv['spawn_elev'] == '0'
    assert kv['player_model'] == DEFAULT_PLAYER
    assert kv['voiceline_priority'] == '0'

    kv = CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=True,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=False,
        player_mdl=utils.obj_id('VALVE_PBODY'),
        use_voice_priority=True,
    ).export_kv1()
    assert len(kv) == 5
    assert kv['sshot_type'] == 'PETI'
    assert kv['sshot_cleanup'] == '1'
    assert kv['spawn_elev'] == '0'
    assert kv['player_model'] == 'VALVE_PBODY'
    assert kv['voiceline_priority'] == '1'

    kv = CompilePaneState(
        sshot_type='AUTO',
        sshot_cleanup=True,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=True,
        player_mdl=utils.obj_id('VALVE_ATLAS'),
        use_voice_priority=False,
    ).export_kv1()
    assert len(kv) == 5
    assert kv['sshot_type'] == 'AUTO'
    assert kv['sshot_cleanup'] == '1'
    assert kv['spawn_elev'] == '1'
    assert kv['player_model'] == 'VALVE_ATLAS'
    assert kv['voiceline_priority'] == '0'

    kv = CompilePaneState(
        sshot_type='CUST',
        sshot_cleanup=True,
        sshot_cust=SCREENSHOT_DATA,
        sshot_cust_fname='C:/some_custom_file.png',
        spawn_elev=True,
        player_mdl=utils.obj_id('REVO_KATE'),
        use_voice_priority=False,
    ).export_kv1()
    assert len(kv) == 7
    assert kv['sshot_type'] == 'CUST'
    assert kv['sshot_fname'] == 'C:/some_custom_file.png'
    assert kv['sshot_cleanup'] == '1'
    assert kv['spawn_elev'] == '1'
    assert kv['player_model'] == 'REVO_KATE'
    assert kv['voiceline_priority'] == '0'
    sshot_data = kv.find_block('sshot_data')
    assert sshot_data.as_array() == SCREENSHOT_BASE64


def test_parse_dmx() -> None:
    """Test parsing DMX configs."""
    elem = Element('CompilePaneState', 'DMElement')

    assert CompilePaneState.parse_kv1(
        Keyvalues('', []), 2,
    ) == CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=False,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=False,
        player_mdl=DEFAULT_PLAYER,
        use_voice_priority=False,
    )

    elem['spawn_elev'] = False
    elem['voiceline_priority'] = True
    elem['player_model'] = 'VALVE_PBODY'
    elem['sshot_type'] = 'PeTI'
    elem['sshot_cleanup'] = True

    assert CompilePaneState.parse_dmx(elem, 2) == CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=True,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=False,
        player_mdl=utils.obj_id('VALVE_PBODY'),
        use_voice_priority=True,
    )

    elem = Element('CompilePaneState', 'DMElement')
    elem['spawn_elev'] = False
    elem['voiceline_priority'] = True
    elem['player_model'] = 'TESTING_TURRET'
    elem['sshot_type'] = 'PeTI'
    elem['sshot_cleanup'] = True

    assert CompilePaneState.parse_dmx(elem, 2) == CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=True,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=False,
        player_mdl=utils.obj_id('TESTING_TURRET'),
        use_voice_priority=True,
    )

    elem = Element('CompilePaneState', 'DMElement')
    elem['spawn_elev'] = True
    elem['voiceline_priority'] = False
    elem['player_model'] = 'valVE_atLAS'
    elem['sshot_type'] = 'auTO'
    elem['sshot_cleanup'] = True

    assert CompilePaneState.parse_dmx(elem, 2) == CompilePaneState(
        sshot_type='AUTO',
        sshot_cleanup=True,
        sshot_cust=b'',
        sshot_cust_fname='',
        spawn_elev=True,
        player_mdl=utils.obj_id('VALVE_ATLAS'),
        use_voice_priority=False,
    )

    elem = Element('CompilePaneState', 'DMElement')
    elem['spawn_elev'] = True
    elem['voiceline_priority'] = True
    elem['player_model'] = 'revo_KATE'
    elem['sshot_type'] = 'CUST'
    elem['sshot_cleanup'] = True
    elem['sshot_fname'] = 'C:/some_custom_file.png'
    elem['sshot_data'] = SCREENSHOT_DATA

    assert CompilePaneState.parse_dmx(elem, 2) == CompilePaneState(
        sshot_type='CUST',
        sshot_cleanup=True,
        sshot_cust=SCREENSHOT_DATA,
        sshot_cust_fname='C:/some_custom_file.png',
        spawn_elev=True,
        player_mdl=utils.obj_id('REVO_KATE'),
        use_voice_priority=True,
    )


def test_export_dmx() -> None:
    """Test exporting DMX configs."""
    elem = CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=False,
        sshot_cust=b'',
        spawn_elev=False,
        player_mdl=DEFAULT_PLAYER,
        use_voice_priority=False,
    ).export_dmx()
    assert len(elem) == 6
    assert elem['sshot_type'] == Attribute.string('sshot_type', 'PETI')
    assert elem['sshot_cleanup'] == Attribute.bool('sshot_cleanup', False)
    assert elem['spawn_elev'] == Attribute.bool('spawn_elev', False)
    assert elem['player_model'] == Attribute.string('player_model', DEFAULT_PLAYER)
    assert elem['voiceline_priority'] == Attribute.bool('voiceline_priority', False)

    elem = CompilePaneState(
        sshot_type='PETI',
        sshot_cleanup=True,
        sshot_cust=b'',
        spawn_elev=False,
        player_mdl=utils.obj_id('VALVE_PBODY'),
        use_voice_priority=True,
    ).export_dmx()
    assert len(elem) == 6
    assert elem['sshot_type'] == Attribute.string('sshot_type', 'PETI')
    assert elem['sshot_cleanup'] == Attribute.bool('sshot_cleanup', True)
    assert elem['spawn_elev'] == Attribute.bool('spawn_elev', False)
    assert elem['player_model'] == Attribute.string('player_model', 'VALVE_PBODY')
    assert elem['voiceline_priority'] == Attribute.bool('voiceline_priority', True)

    elem = CompilePaneState(
        sshot_type='AUTO',
        sshot_cleanup=True,
        sshot_cust=b'',
        spawn_elev=True,
        player_mdl=utils.obj_id('VALVE_ATLAS'),
        use_voice_priority=False,
    ).export_dmx()
    assert len(elem) == 6
    assert elem['sshot_type'] == Attribute.string('sshot_type', 'AUTO')
    assert elem['sshot_cleanup'] == Attribute.bool('sshot_cleanup', True)
    assert elem['spawn_elev'] == Attribute.bool('spawn_elev', True)
    assert elem['player_model'] == Attribute.string('player_model', 'VALVE_ATLAS')
    assert elem['voiceline_priority'] == Attribute.bool('voiceline_priority', False)

    elem = CompilePaneState(
        sshot_type='CUST',
        sshot_cleanup=True,
        sshot_cust=SCREENSHOT_DATA,
        sshot_cust_fname='C:/some_custom_file.png',
        spawn_elev=True,
        player_mdl=utils.obj_id('APERTURE_TAGGED'),
        use_voice_priority=False,
    ).export_dmx()
    assert len(elem) == 8
    assert elem['sshot_type'] == Attribute.string('sshot_type', 'CUST')
    assert elem['sshot_cleanup'] == Attribute.bool('sshot_cleanup', True)
    assert elem['sshot_fname'] == Attribute.string('sshot_fname', 'C:/some_custom_file.png')
    assert elem['sshot_data'] == Attribute.binary('sshot_data', SCREENSHOT_DATA)
    assert elem['spawn_elev'] == Attribute.bool('spawn_elev', True)
    assert elem['player_model'] == Attribute.string('player_model', 'APERTURE_TAGGED')
    assert elem['voiceline_priority'] == Attribute.bool('voiceline_priority', False)


LEGACY_PLAYERMODELS = [
    ('PeTI', DEFAULT_PLAYER),
    ('ATlas', utils.obj_id('VALVE_ATLAS')),
    ('PbodY', utils.obj_id('VALVE_PBODY')),
    ('Sp', utils.obj_id('VALVE_CHELL')),
]


@pytest.mark.parametrize('legacy, new', LEGACY_PLAYERMODELS)
def test_parse_kv1_legacy_player(legacy: str, new: utils.ObjectID) -> None:
    """Check all four legacy player models."""
    assert CompilePaneState.parse_kv1(
        Keyvalues('', [
            Keyvalues('player_model', legacy)
        ]), 1,
    ).player_mdl == new


@pytest.mark.parametrize('legacy, new', LEGACY_PLAYERMODELS)
def test_parse_dmx_legacy_player(legacy: str, new: utils.ObjectID) -> None:
    """Check all four legacy player models."""
    elem = Element('CompilePaneState', 'DMElement')
    elem['player_model'] = legacy

    assert CompilePaneState.parse_dmx(elem, 1).player_mdl == new
