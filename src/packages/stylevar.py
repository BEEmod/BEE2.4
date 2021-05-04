from typing import List

import srctools
from packages import PakObject, Style, ParseData, ExportData
from srctools import Property


class StyleVar(PakObject, allow_mult=True):
    def __init__(
        self,
        var_id: str,
        name: str,
        styles: List[str],
        unstyled: bool=False,
        default: bool=False,
        desc: str='',
    ):
        self.id = var_id
        self.name = name
        self.default = default
        self.enabled = default
        self.desc = desc
        if unstyled:
            self.styles = None
        else:
            self.styles = styles

    @classmethod
    def parse(cls, data: 'ParseData') -> 'StyleVar':
        """Parse StyleVars from configs."""
        name = data.info['name', '']

        unstyled = data.info.bool('unstyled')
        default = data.info.bool('enabled')
        styles = [
            prop.value
            for prop in
            data.info.find_all('Style')
        ]
        desc = '\n'.join(
            prop.value
            for prop in
            data.info.find_all('description')
        )
        return cls(
            data.id,
            name,
            styles,
            unstyled=unstyled,
            default=default,
            desc=desc,
        )

    def add_over(self, override: 'StyleVar') -> None:
        """Override a stylevar to add more compatible styles."""
        # Setting it to be unstyled overrides any other values!
        if self.styles is None:
            return
        elif override.styles is None:
            self.styles = None
        else:
            self.styles.extend(override.styles)

        if not self.name:
            self.name = override.name

        # If they both have descriptions, add them together.
        # Don't do it if they're both identical though.
        # bool(strip()) = has a non-whitespace character
        stripped_over = override.desc.strip()
        if stripped_over and stripped_over not in self.desc:
            if self.desc.strip():
                self.desc += '\n\n' + override.desc
            else:
                self.desc = override.desc

    def __repr__(self) -> str:
        return '<Stylevar "{}", name="{}", default={}, styles={}>:\n{}'.format(
            self.id,
            self.name,
            self.default,
            self.styles,
            self.desc,
        )

    def applies_to_style(self, style: Style) -> bool:
        """Check to see if this will apply for the given style.

        """
        if self.styles is None:
            return True  # Unstyled stylevar

        if style.id in self.styles:
            return True

        return any(
            base.id in self.styles
            for base in
            style.bases
        )

    def applies_to_all(self) -> bool:
        """Check if this applies to all styles."""
        if self.styles is None:
            return True

        for style in Style.all():
            if not self.applies_to_style(style):
                return False
        return True

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export style var selections into the config.

        The .selected attribute is a dict mapping ids to the boolean value.
        """
        # Add the StyleVars block, containing each style_var.

        exp_data.vbsp_conf.append(Property('StyleVars', [
            Property(key, srctools.bool_as_int(val))
            for key, val in
            exp_data.selected.items()
        ]))
