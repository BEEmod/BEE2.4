"""Test parsing window state definitions."""
import attrs
import pytest
from srctools import Property as Keyvalues
from srctools.dmx import Element, Attribute, Vec2

from config.windows import WindowState
from . import isolate_gen_opts, GEN_OPTS


def test_parse_legacy(isolate_gen_opts) -> None:
    """Test parsing data from the legacy GEN_OPTS."""
    GEN_OPTS['win_state'] = {
        'style_x': '45',
        'pal_x': '-265',
        'pal_y': '18',
        'pal_width': '160',
        'pal_height': '265',
        'pal_visible': '0',
        'compiler_x': '-266',
        'compiler_y': '297',
        'compiler_width': '263',
        'compiler_height': '-1',
    }
    res = WindowState.parse_legacy(Keyvalues.root())
    assert res == {
        'style': WindowState(x=45, y=-1, width=-1, height=-1, visible=True),
        'pal': WindowState(x=-265, y=18, width=160, height=265, visible=False),
        'compiler': WindowState(x=-266, y=297, width=263, height=-1),
    }


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 data."""
    state = WindowState.parse_kv1(Keyvalues('Window', []), 1)
    assert state == WindowState(x=-1, y=-1, width=-1, height=-1, visible=True)

    kv = Keyvalues('Window', [
        Keyvalues('x', '450'),
        Keyvalues('y', '320'),
        Keyvalues('width', '1283'),
        Keyvalues('height', '628'),
        Keyvalues('visible', '0'),
    ])
    assert WindowState.parse_kv1(kv, 1) == WindowState(
        x=450,
        y=320,
        width=1283,
        height=628,
        visible=False,
    )

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        WindowState.parse_kv1(kv, 2)


def test_export_kv1() -> None:
    """Test exporting keyvalues1 data."""
    state = WindowState(
        x=289,
        y=371,
        width=289,
        height=189,
        visible=False,
    )

    kv = state.export_kv1()
    assert len(kv) == 5
    assert kv['x'] == '289'
    assert kv['y'] == '371'
    assert kv['width'] == '289'
    assert kv['height'] == '189'
    assert kv['visible'] == '0'

    state = attrs.evolve(state, visible=True)
    assert state.export_kv1()['visible'] == '1'


def test_parse_dmx() -> None:
    """Test parsing DMX configs."""
    elem = Element('Window', 'DMEconfig')

    state = WindowState.parse_dmx(elem, 1)
    assert state == WindowState(x=-1, y=-1, width=-1, height=-1, visible=True)

    assert len(elem) == 0
    elem['pos'] = Attribute.vec2('pos', (450, 320))
    elem['visible'] = Attribute.bool('visible', False)
    elem['width'] = Attribute.int('width', 1283)
    elem['height'] = Attribute.int('height', 628)

    assert WindowState.parse_dmx(elem, 1) == WindowState(
        x=450,
        y=320,
        width=1283,
        height=628,
        visible=False,
    )

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        WindowState.parse_dmx(elem, 2)


def test_export_dmx() -> None:
    """Test exporting keyvalues1 data."""
    state = WindowState(
        x=289,
        y=371,
        width=289,
        height=189,
        visible=False,
    )

    elem = state.export_dmx()
    assert len(elem) == 4
    assert elem['pos'].val_vec2 == Vec2(289, 371)
    assert elem['width'].val_int == 289
    assert elem['height'].val_int == 189
    assert elem['visible'].val_bool is False

    state = attrs.evolve(state, visible=True)
    assert state.export_dmx()['visible'].val_bool is True
