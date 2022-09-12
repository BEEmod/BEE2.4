"""Test the signage configuration."""
from random import Random

from srctools import Property as Keyvalues

from config.signage import DEFAULT_IDS, Layout


DELAYS = range(3, 31)
TEST_EMPTIES = [8, 12, 13, 14]


def test_defaults_filled() -> None:
    """Check all timer IDs have a default."""
    assert 2 not in DELAYS
    assert 3 in DELAYS
    assert 30 in DELAYS
    assert 31 not in DELAYS

    for i in DELAYS:
        assert i in DEFAULT_IDS


def test_parse_kv() -> None:
    """Test parsing keyvalues1 configs."""
    kv_list = [
        Keyvalues(str(i), "" if i in TEST_EMPTIES else f'TIMER_{i}_SIGN')
        for i in DELAYS
    ]
    Random(38927).shuffle(kv_list)
    kv = Keyvalues('Signage', kv_list)
    conf = Layout.parse_kv1(kv, 1)
    assert len(conf.signs) == 28
    for i in DELAYS:
        if i in TEST_EMPTIES:
            assert conf.signs[i] == ""
        else:
            assert conf.signs[i] == f'TIMER_{i}_SIGN'


def test_blank_layouts() -> None:
    """Test that parsing a blank config produces defaults."""
    assert Layout.parse_kv1(Keyvalues('Signage', []), 1).signs == DEFAULT_IDS
    assert Layout.parse_kv1(Keyvalues('Signage', [Keyvalues('5', '')]), 1).signs == dict.fromkeys(DELAYS, '')


def test_layout_copies() -> None:
    """Test the Layout class copies the mapping, to keep it immutable."""
    assert len(Layout().signs) == 28
    orig = {
        3: 'three', 5: 'five', 23: 'twenty-three'
    }
    layout = Layout(orig)
    assert len(layout.signs) == 28
    assert layout.signs[8] == ''
    assert layout.signs[23] == 'twenty-three'
    orig[3] = 'III'
    assert layout.signs[3] == 'three'


def test_export_kv() -> None:
    """Test exporting keyvalues1 configs."""
    conf = DEFAULT_IDS.copy()
    conf[12] = 'CUSTOM_SIGN'
    kv = Layout(conf).export_kv1()
    assert len(kv) == 28

    assert kv['7'] == 'SIGN_EXIT'
    assert kv['8'] == 'SIGN_CUBE_DROPPER'
    assert kv['9'] == 'SIGN_BALL_DROPPER'
    assert kv['10'] == 'SIGN_REFLECT_CUBE'
    assert kv['12'] == 'CUSTOM_SIGN'
