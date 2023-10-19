"""
General app configuration options, controlled by the options window.
"""
from typing import Any, Dict, List
from typing_extensions import TypeGuard, override
from enum import Enum

from srctools import Keyvalues
from srctools.dmx import Element
import attrs

from BEE2_config import GEN_OPTS as LEGACY_CONF
import config


class AfterExport(Enum):
    """Specifies what happens after exporting."""
    NORMAL = 0  # Stay visible
    MINIMISE = 1  # Minimise to tray
    QUIT = 2  # Quit the app.


@config.APP.register
@attrs.frozen(slots=False)
class GenOptions(config.Data, conf_name='Options', palette_stores=False, version=2):
    """General app config options, mainly booleans. These are all changed in the options window."""
    # The boolean values are handled the same way, using the metadata to record the old legacy names.
    # If the name has a :, the first is the section and the second is the name.
    # Otherwise, it's just the section name and the attr name is the same as the option name.
    after_export: AfterExport = AfterExport.NORMAL
    launch_after_export: bool = attrs.field(default=True, metadata={'legacy': 'General:launch_game'})

    play_sounds: bool = attrs.field(default=True, metadata={'legacy': 'General'})
    keep_win_inside: bool = attrs.field(default=True, metadata={'legacy': 'General'})
    force_load_ontop: bool = attrs.field(default=True, metadata={'legacy': 'General:splash_stay_ontop'})
    compact_splash: bool = attrs.field(default=True, metadata={'legacy': 'General'})
    music_collapsed: bool = attrs.field(default=True, metadata={'legacy': 'Last_Selected'})

    # Log window.
    show_log_win: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    log_win_level: str = 'INFO'

    # Stuff mainly for devs.
    preserve_resources: bool = attrs.field(default=False, metadata={'legacy': 'General:preserve_bee2_resource_dir'})
    # Split from preserve_resources, before v2 use that value.
    preserve_fgd: bool = False
    dev_mode: bool = attrs.field(default=False, metadata={'legacy': 'Debug:development_mode'})
    # If the user has accepted the warning on the developer options page.
    accepted_dev_warning: bool = False
    log_missing_ent_count: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    log_missing_styles: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    log_item_fallbacks: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    visualise_inheritance: bool = False
    force_all_editor_models: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})

    language: str = ''

    @classmethod
    @override
    def parse_legacy(cls, conf: Keyvalues) -> Dict[str, 'GenOptions']:
        """Parse from the GEN_OPTS config file."""
        log_win_level = LEGACY_CONF.get(
            'Debug', 'window_log_level',
            fallback=attrs.fields(GenOptions).log_win_level.default,
        )
        try:
            after_export = AfterExport(LEGACY_CONF.get_int('General', 'after_export_action', -1))
        except ValueError:
            after_export = AfterExport.NORMAL

        res: Dict[str, bool] = {}
        for field in gen_opts_bool:
            try:
                section: str = field.metadata['legacy']
            except KeyError:
                # New field.
                res[field.name] = field.default
                continue
            try:
                section, name = section.split(':')
            except ValueError:
                name = field.name
            res[field.name] = LEGACY_CONF.get_bool(section, name, field.default)

        return {'': GenOptions(
            after_export=after_export,
            log_win_level=log_win_level,
            preserve_fgd=res['preserve_resources'],
            # Mypy#5382
            **res,  # type: ignore[arg-type]
        )}

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> 'GenOptions':
        """Parse KV1 values."""
        if version > 2:
            raise AssertionError('Unknown version!')
        preserve_fgd = data.bool('preserve_fgd' if version > 1 else 'preserve_resources')
        try:
            after_export = AfterExport(data.int('after_export', 0))
        except ValueError:
            after_export = attrs.fields(GenOptions).after_export.default

        return GenOptions(
            after_export=after_export,
            log_win_level=data['log_win_level', 'INFO'],
            language=data['language', ''],
            preserve_fgd=preserve_fgd,
            **{
                field.name: data.bool(field.name, field.default)
                for field in gen_opts_bool
            },
        )

    @override
    def export_kv1(self) -> Keyvalues:
        """Produce KV1 values."""
        kv = Keyvalues('', [
            Keyvalues('after_export', str(self.after_export.value)),
            Keyvalues('log_win_level', self.log_win_level),
            Keyvalues('language', self.language),
            Keyvalues('preserve_fgd', '1' if self.preserve_fgd else '0')
        ])
        for field in gen_opts_bool:
            kv.append(Keyvalues(field.name, '1' if getattr(self, field.name) else '0'))
        return kv

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> 'GenOptions':
        """Parse DMX configuration."""
        if version > 2:
            raise AssertionError('Unknown version!')

        res: Dict[str, Any] = {}
        try:
            res['preserve_fgd'] = data['preserve_fgd' if version > 1 else 'preserve_resources'].val_bool
        except KeyError:
            pass
        try:
            res['after_export'] = AfterExport(data['after_export'].val_int)
        except (KeyError, ValueError):
            pass
        try:
            res['log_win_level'] = data['log_win_level'].val_str
        except (KeyError, ValueError):
            pass
        try:
            res['language'] = data['language'].val_str
        except KeyError:
            pass

        for field in gen_opts_bool:
            try:
                res[field.name] = data[field.name].val_bool
            except KeyError:
                res[field.name] = field.default
        return GenOptions(**res)

    @override
    def export_dmx(self) -> Element:
        """Produce DMX configuration."""
        elem = Element('Options', 'DMElement')
        elem['after_export'] = self.after_export.value
        elem['language'] = self.language
        elem['preserve_fgd'] = self.preserve_fgd
        elem['log_win_level'] = self.log_win_level
        for field in gen_opts_bool:
            elem[field.name] = getattr(self, field.name)
        return elem


# Todo: For full type safety, make field = attrs.Attribute[Any], once mypy infers a union for iter(tuple).
def _is_bool_attr(field: object) -> TypeGuard['attrs.Attribute[bool]']:
    """Check if this is a boolean-type attribute."""
    return isinstance(field, attrs.Attribute) and (field.type is bool or str(field.type) == 'bool')


gen_opts_bool: List['attrs.Attribute[bool]'] = [
    field
    for field in attrs.fields(GenOptions)
    if _is_bool_attr(field)
    if field.name != 'preserve_fgd'  # Needs special handling
]
del _is_bool_attr
