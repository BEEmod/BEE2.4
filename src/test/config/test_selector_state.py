"""Test selectorwin UI state configuration."""
import pytest
from srctools import Property as Keyvalues
from srctools.dmx import Element

from config.windows import SelectorState


def test_parse_legacy() -> None:
    """Test parsing the legacy configuration file."""
    kv = Keyvalues.root(Keyvalues('Selectorwindow', [
        Keyvalues('stylewin', [
            Keyvalues('width', '192'),
            Keyvalues('height', '983'),
            Keyvalues('groups', [
                Keyvalues('open', '1'),
                Keyvalues('closed', '0'),
            ])
        ]),
        Keyvalues('somethingelse', [
            Keyvalues('width', '271'),
            Keyvalues('height', '1365'),
            Keyvalues('groups', [
                Keyvalues('first', '0'),
                Keyvalues('second', '1'),
                Keyvalues('', '1'),
            ])
        ])
    ]))
    data = SelectorState.parse_legacy(kv)
    assert set(data.keys()) == {'stylewin', 'somethingelse'}
    assert data['stylewin'] == SelectorState(
        width=192,
        height=983,
        open_groups={
            'open': True,
            'closed': False,
        }
    )
    assert data['somethingelse'] == SelectorState(
        width=271,
        height=1365,
        open_groups={
            '': True,
            'first': False,
            'second': True,
        }
    )


def test_parse_kv1() -> None:
    """Test parsing Keyvalues1 state."""
    kv = Keyvalues('Selector', [
        Keyvalues('width', '278'),
        Keyvalues('height', '4578'),
        Keyvalues('groups', [
            Keyvalues('', '1'),
            Keyvalues('closed', '0'),
            Keyvalues('open gROup', '1'),
            Keyvalues('anothergroup', 'true'),
            Keyvalues('notgroup', 'false'),
        ])
    ])
    state = SelectorState.parse_kv1(kv, 1)
    assert state == SelectorState(
        width=278,
        height=4578,
        open_groups={
            '': True,
            'closed': False,
            'open group': True,
            'anothergroup': True,
            'notgroup': False,
        }
    )

    with pytest.raises(AssertionError):
        SelectorState.parse_kv1(kv, 2)


def test_export_kv1() -> None:
    """Test exporting Keyvalues1 state."""
    state = SelectorState(
        width=198,
        height=1685,
        open_groups={
            '': True,
            'closed': False,
            'open group': True,
            'anothergroup': True,
            'notgroup': False,
        }
    )
    kv = state.export_kv1()
    assert len(kv) == 3
    assert kv['width'] == '198'
    assert kv['height'] == '1685'
    groups = kv.find_key('groups')
    assert len(groups) == 5
    assert groups[''] == '1'
    assert groups['closed'] == '0'
    assert groups['open group'] == '1'
    assert groups['anothergroup'] == '1'
    assert groups['notgroup'] == '0'


def test_parse_dmx() -> None:
    """Test parsing DMX state."""
    elem = Element('Selector', 'DMConfig')
    elem['width'] = 289
    elem['height'] = 1475
    elem['opened'] = [
        'anopengROup', ''
    ]
    elem['closed'] = ['closedGroup']

    state = SelectorState.parse_dmx(elem, 1)
    assert state == SelectorState(
        width=289,
        height=1475,
        open_groups={
            'anopengroup': True,
            '': True,
            'closedgroup': False,
        }
    )

    with pytest.raises(AssertionError):
        SelectorState.parse_dmx(elem, 2)


def test_export_dmx() -> None:
    """Test exporting DMX state."""
    state = SelectorState(
        width=198,
        height=1685,
        open_groups={
            '': True,
            'closed': False,
            'open group': True,
            'anothergroup': True,
            'notgroup': False,
        }
    )
    elem = state.export_dmx()
    assert len(elem) == 5
    assert elem['width'].val_int == 198
    assert elem['height'].val_int == 1685
    assert set(elem['opened'].iter_string()) == {'', 'open group', 'anothergroup'}
    assert set(elem['closed'].iter_string()) == {'closed', 'notgroup'}
