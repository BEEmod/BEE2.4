from enum import Enum
from typing import Any, Dict

import attrs
from srctools import Property
from srctools.dmx import Element

from BEE2_config import GEN_OPTS as LEGACY_CONF
import config


class AfterExport(Enum):
    """Specifies what happens after exporting."""
    NORMAL = 0  # Stay visible
    MINIMISE = 1  # Minimise to tray
    QUIT = 2  # Quit the app.


@config.APP.register
@attrs.frozen(slots=False)
class GenOptions(config.Data, conf_name='Options', palette_stores=False):
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
    dev_mode: bool = attrs.field(default=False, metadata={'legacy': 'Debug:development_mode'})
    log_missing_ent_count: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    log_missing_styles: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    log_item_fallbacks: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    visualise_inheritance: bool = False
    force_all_editor_models: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})

    @classmethod
    def parse_legacy(cls, conf: Property) -> Dict[str, 'GenOptions']:
        """Parse from the GEN_OPTS config file."""
        log_win_level = LEGACY_CONF['Debug']['window_log_level']
        try:
            after_export = AfterExport(LEGACY_CONF.get_int(
                'General', 'after_export_action',
                0,
            ))
        except ValueError:
            after_export = AfterExport.NORMAL

        res = {}
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
            **res,
        )}

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'GenOptions':
        """Parse KV1 values."""
        assert version == 1
        try:
            after_export = AfterExport(data.int('after_export', 0))
        except ValueError:
            after_export = AfterExport.NORMAL

        return GenOptions(
            after_export=after_export,
            log_win_level=data['log_win_level', 'INFO'],
            **{
                field.name: data.bool(field.name, field.default)
                for field in gen_opts_bool
            },
        )

    def export_kv1(self) -> Property:
        """Produce KV1 values."""
        prop = Property('', [
            Property('after_export', str(self.after_export.value)),
            Property('log_win_level', self.log_win_level),
        ])
        for field in gen_opts_bool:
            prop[field.name] = '1' if getattr(self, field.name) else '0'
        return prop

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'GenOptions':
        """Parse DMX configuration."""
        assert version == 1
        res: dict[str, Any] = {}
        try:
            res['after_export'] = AfterExport(data['after_export'].val_int)
        except (KeyError, ValueError):
            res['after_export'] = AfterExport.NORMAL
        try:
            res['log_win_level'] = data['log_win_level'].val_str
        except (KeyError, ValueError):
            res['log_win_level'] = 'INFO'
        for field in gen_opts_bool:
            try:
                res[field.name] = data[field.name].val_bool
            except KeyError:
                res[field.name] = field.default
        return GenOptions(**res)

    def export_dmx(self) -> Element:
        """Produce DMX configuration."""
        elem = Element('Options', 'DMElement')
        elem['after_export'] = self.after_export.value
        for field in gen_opts_bool:
            elem[field.name] = getattr(self, field.name)
        return elem


gen_opts_bool = [
    field
    for field in attrs.fields(GenOptions)
    if field.default in (True, False)
]
