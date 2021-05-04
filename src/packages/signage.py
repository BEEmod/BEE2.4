from typing import Dict, List, Tuple, NamedTuple

from packages import PakObject, ParseData, ExportData, Style
from app.img import Handle as ImgHandle
from srctools import Property
import srctools.logger

LOGGER = srctools.logger.get_logger(__name__)


class SignStyle(NamedTuple):
    """Signage information for a specific style."""
    world: str
    overlay: str
    icon: ImgHandle
    type: str


class Signage(PakObject, allow_mult=True):
    """Defines different square signage overlays."""

    def __init__(
        self,
        sign_id: str,
        styles: Dict[str, SignStyle],
        disp_name: str,
        primary_id: str=None,
        secondary_id: str=None,
        hidden: bool=False,
    ) -> None:
        self.hidden = hidden or sign_id == 'SIGN_ARROW'
        self.id = sign_id
        self.name = disp_name
        # style_id -> (world, overlay)
        self.styles = styles
        self.prim_id = primary_id
        self.sec_id = secondary_id

        # The icon the UI uses.
        self.dnd_icon = None

    @classmethod
    def parse(cls, data: ParseData) -> 'Signage':
        styles: Dict[str, SignStyle] = {}
        for prop in data.info.find_children('styles'):
            sty_id = prop.name.upper()

            if not prop.has_children():
                # Style lookup.
                try:
                    prop = next(data.info.find_all('styles', prop.value))
                except StopIteration:
                    raise ValueError('No style <{}>!'.format(prop.value))

            world_tex = prop['world', '']
            overlay_tex = prop['overlay', '']

            # Don't warn, we don't actually need this yet.

            # if not world_tex:
            #     LOGGER.warning(
            #         '"{}" signage has no "world" value '
            #         'for the "{}" style!',
            #         data.id,
            #         sty_id
            #     )
            if not overlay_tex:
                raise ValueError(
                    f'"{data.id}"" signage has no "overlay" value '
                    f'option for the "{sty_id}" style!'
                )

            styles[sty_id] = SignStyle(
                world_tex,
                overlay_tex,
                ImgHandle.parse(prop, data.pak_id, 64, 64, subkey='icon'),
                prop['type', 'square']
            )
        return cls(
            data.id,
            styles,
            data.info['name'],
            data.info['primary', None],
            data.info['secondary', None],
            data.info.bool('hidden'),
        )

    def add_over(self, override: 'Signage') -> None:
        """Append additional styles to the signage."""
        for sty_id, opts in override.styles.items():
            if sty_id in self.styles:
                raise ValueError(
                    f'Duplicate "{sty_id}" style definition for {self.id}!'
                )
            self.styles[sty_id] = opts
        if override.sec_id:
            if not self.sec_id:
                self.sec_id = override.sec_id
            elif self.sec_id != override.sec_id:
                raise ValueError(
                    'Mismatch in secondary IDs for '
                    f'signage "{self.id}"! '
                    f'({self.sec_id} != {override.sec_id})'
                )

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export the selected signage to the config."""
        # Timer value -> sign ID.
        sel_ids: List[Tuple[str, str]] = exp_data.selected

        # Special case, arrow is never selectable.
        sel_ids.append(('arrow', 'SIGN_ARROW'))

        conf = Property('Signage', [])

        for tim_id, sign_id in sel_ids:
            try:
                sign = Signage.by_id(sign_id)
            except KeyError:
                LOGGER.warning('Signage "{}" does not exist!', sign_id)
                continue
            prop_block = Property(str(tim_id), [])

            sign._serialise(prop_block, exp_data.selected_style)

            for sub_name, sub_id in [
                ('primary', sign.prim_id),
                ('secondary', sign.sec_id),
            ]:
                if sub_id:
                    try:
                        sub_sign = Signage.by_id(sub_id)
                    except KeyError:
                        LOGGER.warning(
                            'Signage "{}"\'s {} "{}" '
                            'does not exist!', sign_id, sub_name, sub_id)
                    else:
                        sub_block = Property(sub_name, [])
                        sub_sign._serialise(sub_block, exp_data.selected_style)
                        if sub_block:
                            prop_block.append(sub_block)

            if prop_block:
                conf.append(prop_block)

        exp_data.vbsp_conf.append(conf)

    def _serialise(self, parent: Property, style: Style) -> None:
        """Write this sign's data for the style to the provided property."""
        for potential_style in style.bases:
            try:
                data = self.styles[potential_style.id.upper()]
                break
            except KeyError:
                pass
        else:
            LOGGER.warning(
                'No valid "{}" style for "{}" signage!',
                style.id,
                self.id,
            )
            try:
                data = self.styles['BEE2_CLEAN']
            except KeyError:
                return
        parent.append(Property('world', data.world))
        parent.append(Property('overlay', data.overlay))
        parent.append(Property('type', data.type))
