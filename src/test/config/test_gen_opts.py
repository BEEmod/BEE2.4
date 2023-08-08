"""Test parsing the general options."""
from typing import NoReturn, cast

from srctools import Keyvalues
from srctools.dmx import Element, ValueType
import pytest
import attrs

from BEE2_config import GEN_OPTS
from config.gen_opts import GenOptions, AfterExport, gen_opts_bool
from test.config import isolate_conf


BOOL_OPTIONS = {field.name for field in gen_opts_bool}


class Landmine:
    """Errors if you do anything with it."""
    def __getattribute__(self, attr: str) -> NoReturn:
        pytest.fail(f"Accessed Landmine.{attr}", pytrace=False)

    def __getitem__(self, item: object) -> NoReturn:
        pytest.fail(f"Accessed Landmine[{item!r}]", pytrace=False)


def parse_from_legacy() -> GenOptions:
    """Call GenOptions.parse_legacy(), doing some checks."""
    conf = GenOptions.parse_legacy(Landmine())  # Arg is unused.
    assert list(conf.keys()) == ['']
    return conf['']



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


def test_parse_legacy_blank() -> None:
    """Upgrading from a blank INI config will produce the defaults."""
    with isolate_conf(GEN_OPTS):
        # Blank = must use defaults.
        conf = parse_from_legacy()
    assert conf == GenOptions()


@pytest.mark.parametrize('section, name, attr', [
    ('General', 'launch_game', attrs.fields(GenOptions).launch_after_export),
    ('General', 'play_sounds', attrs.fields(GenOptions).play_sounds),
    ('General', 'keep_win_inside', attrs.fields(GenOptions).keep_win_inside),
    ('General', 'splash_stay_ontop', attrs.fields(GenOptions).force_load_ontop),
    ('General', 'compact_splash', attrs.fields(GenOptions).compact_splash),
    ('Last_Selected', 'music_collapsed', attrs.fields(GenOptions).music_collapsed),
    ('Debug', 'show_log_win', attrs.fields(GenOptions).show_log_win),
    ('Debug', 'development_mode', attrs.fields(GenOptions).dev_mode),
    ('Debug', 'log_missing_ent_count', attrs.fields(GenOptions).log_missing_ent_count),
    ('Debug', 'log_missing_styles', attrs.fields(GenOptions).log_missing_styles),
    ('Debug', 'log_item_fallbacks', attrs.fields(GenOptions).log_item_fallbacks),
    ('Debug', 'force_all_editor_models', attrs.fields(GenOptions).force_all_editor_models),
])
def test_parse_legacy_bools(section: str, name: str, attr: 'attrs.Attribute[bool]') -> None:
    """Test upgrading these booleans from the legacy INI config."""
    with isolate_conf(GEN_OPTS):
        GEN_OPTS[section][name] = '0'
        conf = parse_from_legacy()
    assert getattr(conf, attr.name) is False

    with isolate_conf(GEN_OPTS):
        GEN_OPTS[section][name] = '1'
        conf = parse_from_legacy()
    assert getattr(conf, attr.name) is True

    with isolate_conf(GEN_OPTS):
        GEN_OPTS[section][name] = 'not_a_bool'
        conf = parse_from_legacy()
    assert getattr(conf, attr.name) is attr.default


def test_parse_legacy_log_win_level() -> None:
    """Test upgrading the log win level from the legacy INI config."""
    with isolate_conf(GEN_OPTS):
        GEN_OPTS['Debug']['window_log_level'] = 'INFO'
        conf = parse_from_legacy()
    assert conf.log_win_level == 'INFO'

    with isolate_conf(GEN_OPTS):
        GEN_OPTS['Debug']['window_log_level'] = 'DEBUG'
        conf = parse_from_legacy()
    assert conf.log_win_level == 'DEBUG'


def test_parse_legacy_after_export() -> None:
    """Test upgrading the after export action from the legacy INI config."""
    with isolate_conf(GEN_OPTS):
        GEN_OPTS['General']['after_export_action'] = '0'
        conf = parse_from_legacy()
    assert conf.after_export is AfterExport.NORMAL

    with isolate_conf(GEN_OPTS):
        GEN_OPTS['General']['after_export_action'] = '1'
        conf = parse_from_legacy()
    assert conf.after_export is AfterExport.MINIMISE

    with isolate_conf(GEN_OPTS):
        GEN_OPTS['General']['after_export_action'] = '2'
        conf = parse_from_legacy()
    assert conf.after_export is AfterExport.QUIT

    with isolate_conf(GEN_OPTS):
        GEN_OPTS['General']['after_export_action'] = 'blah'
        conf = parse_from_legacy()
    assert conf.after_export is AfterExport.NORMAL


def test_parse_legacy_preserve() -> None:
    """Test upgrading preserve resources/FGD from the legacy INI config."""
    with isolate_conf(GEN_OPTS):
        GEN_OPTS['General']['preserve_bee2_resource_dir'] = '0'
        conf = parse_from_legacy()
    assert conf.preserve_resources is False
    assert conf.preserve_fgd is False

    with isolate_conf(GEN_OPTS):
        GEN_OPTS['General']['preserve_bee2_resource_dir'] = '1'
        conf = parse_from_legacy()
    assert conf.preserve_resources is True
    assert conf.preserve_fgd is True

    with isolate_conf(GEN_OPTS):
        GEN_OPTS['General']['preserve_bee2_resource_dir'] = 'not_a_bool'
        conf = parse_from_legacy()
    assert conf.preserve_resources is False
    assert conf.preserve_fgd is False


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
    kv = GenOptions(
        after_export=AfterExport.NORMAL,
        log_win_level='WARNING',
        language='en_UK'
    ).export_kv1()
    assert kv['after_export'] == '0'
    assert kv['log_win_level'] == 'WARNING'
    assert kv['language'] == 'en_UK'

    kv = GenOptions(
        after_export=AfterExport.QUIT,
        log_win_level='DEBUG',
        language='de',
    ).export_kv1()
    assert kv['after_export'] == '2'
    assert kv['log_win_level'] == 'DEBUG'
    assert kv['language'] == 'de'


def test_export_dmx() -> None:
    """Test other properties are exported correctly to DMX."""
    dmx = GenOptions(
        after_export=AfterExport.NORMAL,
        log_win_level='WARNING',
        language='en_UK'
    ).export_dmx()
    assert dmx['after_export'].type is ValueType.INT
    assert dmx['after_export'].val_int == 0
    assert dmx['log_win_level'].val_str == 'WARNING'
    assert dmx['language'].val_str == 'en_UK'

    dmx = GenOptions(
        after_export=AfterExport.QUIT,
        log_win_level='DEBUG',
        language='de',
    ).export_dmx()
    assert dmx['after_export'].type is ValueType.INT
    assert dmx['after_export'].val_int == 2
    assert dmx['log_win_level'].val_str == 'DEBUG'
    assert dmx['language'].val_str == 'de'


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


@pytest.mark.parametrize('preserve_fgd', [False, True])
@pytest.mark.parametrize('preserve_res', [False, True])
def test_preserve_fgd_export_kv1(preserve_fgd: bool, preserve_res: bool) -> None:
    """Test these keys are exported correctly for KV1."""
    conf = GenOptions(
        preserve_fgd=preserve_fgd,
        preserve_resources=preserve_res,
    ).export_kv1()
    assert conf['preserve_fgd'] == '1' if preserve_fgd else '0'
    assert conf['preserve_resources'] == '1' if preserve_res else '0'


@pytest.mark.parametrize('preserve_fgd', [False, True])
@pytest.mark.parametrize('preserve_res', [False, True])
def test_preserve_fgd_export_dmx(preserve_fgd: bool, preserve_res: bool) -> None:
    """Test these keys are exported correctly for DMX."""
    conf = GenOptions(
        preserve_fgd=preserve_fgd,
        preserve_resources=preserve_res,
    ).export_dmx()
    assert conf['preserve_fgd'].type is ValueType.BOOL
    assert conf['preserve_fgd'].val_bool is preserve_fgd
    assert conf['preserve_resources'].type is ValueType.BOOL
    assert conf['preserve_resources'].val_bool is preserve_res
