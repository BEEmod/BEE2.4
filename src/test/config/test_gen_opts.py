"""Test parsing the general options."""
from srctools import Keyvalues
from srctools.dmx import Element, ValueType
import pytest
import attrs

from config.gen_opts import GenOptions, AfterExport, gen_opts_bool


BOOL_OPTIONS = {field.name for field in gen_opts_bool}


@pytest.mark.parametrize('name', BOOL_OPTIONS)
def test_bool_basics(name: str) -> None:
    """Test that boolean options are in fact booleans."""
    conf_false = GenOptions(**{name: False})
    conf_true = GenOptions(**{name: True})

    assert getattr(GenOptions(), name) in (False, True)
    assert getattr(conf_false, name) is False
    assert getattr(conf_true, name) is True


@pytest.mark.parametrize('name', BOOL_OPTIONS)
def test_bool_parse_kv1(name: str) -> None:
    """Test that boolean options are parsed from KV1 correctly."""
    kv_false = GenOptions.parse_kv1(Keyvalues('KV', [
        Keyvalues(name, '0')
    ]), version=2)
    kv_true = GenOptions.parse_kv1(Keyvalues('KV', [
        Keyvalues(name, '1')
    ]), version=2)
    assert getattr(kv_false, name) is False
    assert getattr(kv_true, name) is True


@pytest.mark.parametrize('name', BOOL_OPTIONS)
def test_bool_parse_dmx(name: str) -> None:
    """Test that boolean options are parsed from DMX correctly."""
    elem = Element('GenOptions', 'DMElement')
    elem[name] = False
    dmx_false = GenOptions.parse_dmx(elem, version=2)
    elem[name] = True
    dmx_true = GenOptions.parse_dmx(elem, version=2)
    assert getattr(dmx_false, name) is False
    assert getattr(dmx_true, name) is True


@pytest.mark.parametrize('name', BOOL_OPTIONS)
def test_bool_export_kv1(name: str) -> None:
    """Test that KV1 export works correctly."""
    kv1_false = GenOptions(**{name: False}).export_kv1()
    kv1_true = GenOptions(**{name: True}).export_kv1()

    assert kv1_false[name] == '0'
    assert kv1_true[name] == '1'


@pytest.mark.parametrize('name', BOOL_OPTIONS)
def test_bool_export_dmx(name: str) -> None:
    """Test that DMX export works correctly."""
    dmx_false = GenOptions(**{name: False}).export_dmx()
    dmx_true = GenOptions(**{name: True}).export_dmx()

    assert dmx_false[name].type is ValueType.BOOL
    assert dmx_false[name].val_bool is False
    assert dmx_true[name].type is ValueType.BOOL
    assert dmx_true[name].val_bool is True


def test_parse_legacy() -> None:
    """Test upgrading from the INI config file."""
    # TODO


def test_parse_kv1() -> None:
    """Test other properties are parsed correctly."""
    conf = GenOptions.parse_kv1(Keyvalues('', [
        Keyvalues('after_export', '0'),
        Keyvalues('language', 'en_UK'),
        Keyvalues('log_win_level', 'WARNING'),
    ]), 2)
    assert conf.after_export is AfterExport.NORMAL
    assert conf.language == 'en_UK'
    assert conf.log_win_level == 'WARNING'

    assert GenOptions.parse_kv1(Keyvalues('', [
        Keyvalues('after_export', '1')
    ]), 1).after_export is AfterExport.MINIMISE

    assert GenOptions.parse_kv1(Keyvalues('', [
        Keyvalues('after_export', '2')
    ]), 1).after_export is AfterExport.QUIT
    assert GenOptions.parse_kv1(Keyvalues('', [
        Keyvalues('after_export', '3')
    ]), 1).after_export is AfterExport.NORMAL


def test_parse_dmx() -> None:
    """Test other properties are parsed correctly."""
    elem = Element('GenOptions', 'DMElement')
    elem['after_export'] = 0
    elem['language'] = 'en_UK'
    elem['log_win_level'] = 'WARNING'
    conf = GenOptions.parse_dmx(elem, 2)
    assert conf.after_export is AfterExport.NORMAL
    assert conf.language == 'en_UK'
    assert conf.log_win_level == 'WARNING'

    elem['after_export'] = 1
    assert GenOptions.parse_dmx(elem, 2).after_export is AfterExport.MINIMISE
    elem['after_export'] = 2
    assert GenOptions.parse_dmx(elem, 2).after_export is AfterExport.QUIT
    # Invalid.
    elem['after_export'] = 3
    assert GenOptions.parse_dmx(elem, 2).after_export is AfterExport.NORMAL


def test_export_kv1() -> None:
    """Test other properties are exported correctly to KV1."""
    # TODO


def test_export_dmx() -> None:
    """Test other properties are exported correctly to DMX."""
    # TODO


def test_v1_preserve_fgd_parse_kv1() -> None:
    """Test the v1->2 split of preserve_resources into preserve_fgd, for KV1."""
    conf = GenOptions.parse_kv1(Keyvalues('', [
        Keyvalues('preserve_resources', '0'),
        Keyvalues('preserve_fgd', '1'),  # Ignored!
    ]), 1)
    assert conf.preserve_fgd is False
    assert conf.preserve_resources is False

    conf = GenOptions.parse_kv1(Keyvalues('', [
        Keyvalues('preserve_resources', '1'),
        Keyvalues('preserve_fgd', '0'),
    ]), 1)
    assert conf.preserve_fgd is True
    assert conf.preserve_resources is True


def test_v1_preserve_fgd_parse_dmx() -> None:
    """Test the v1->2 split of preserve_resources into preserve_fgd, for KV1."""
    elem = Element('GenOptions', 'DMElement')
    elem['preserve_resources'] = False
    elem['preserve_fgd'] = True  # Ignored!
    conf = GenOptions.parse_dmx(elem, 1)
    assert conf.preserve_fgd is False
    assert conf.preserve_resources is False

    elem['preserve_resources'] = True
    elem['preserve_fgd'] = False
    conf = GenOptions.parse_dmx(elem, 1)
    assert conf.preserve_fgd is True
    assert conf.preserve_resources is True


@pytest.mark.parametrize('preserve_fgd', [False, True])
@pytest.mark.parametrize('preserve_res', [False, True])
def test_v2_preserve_fgd_parse_kv1(preserve_fgd: bool, preserve_res: bool) -> None:
    """Test that the two preserve options are independent in V2, for KV1."""
    conf = GenOptions.parse_kv1(Keyvalues('', [
        Keyvalues('preserve_resources', '1' if preserve_res else '0'),
        Keyvalues('preserve_fgd', '1' if preserve_fgd else '0'),
    ]), 2)
    assert conf.preserve_fgd is preserve_fgd
    assert conf.preserve_resources is preserve_res


@pytest.mark.parametrize('preserve_fgd', [False, True])
@pytest.mark.parametrize('preserve_res', [False, True])
def test_v2_preserve_fgd_parse_dmx(preserve_fgd: bool, preserve_res: bool) -> None:
    """Test that the two preserve options are independent in V2, for DMX."""
    elem = Element('GenOptions', 'DMElement')
    elem['preserve_resources'] = preserve_res
    elem['preserve_fgd'] = preserve_fgd
    conf = GenOptions.parse_dmx(elem, 2)
    assert conf.preserve_fgd is preserve_fgd
    assert conf.preserve_resources is preserve_res


def test_preserve_fgd_export_kv1() -> None:
    """Test these keys are exported correctly for KV1."""
    # TODO


def test_preserve_fgd_export_dmx() -> None:
    """Test these keys are exported correctly for DMX."""
    # TODO
