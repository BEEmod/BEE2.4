"""Style specific features which can be enabled or disabled."""
from __future__ import annotations
from typing import Iterator

from packages import PackagesSet, PakObject, ParseData, Style
from transtoken import TransToken, TransTokenSource


class StyleVar(PakObject, allow_mult=True, needs_foreground=True):
    """Style specific features which can be enabled or disabled."""
    def __init__(
        self,
        var_id: str,
        name: TransToken,
        styles: list[str],
        desc: TransToken,
        *,
        unstyled: bool,
        inherit: bool,
        default: bool,
    ) -> None:
        self.id = var_id
        self.name = name
        self.default = default
        self.enabled = default
        self.desc = desc
        self.inherit = inherit
        self.styles = None if unstyled else styles

    @classmethod
    def unstyled(cls, id: str, name: TransToken, default: bool, desc: TransToken) -> StyleVar:
        """For builtin variables, define it as fully unstyled."""
        return cls(id, name, [], desc, unstyled=True, inherit=False, default=default)

    @property
    def is_unstyled(self) -> bool:
        """check if the variable is unstyled."""
        return self.styles is None

    @classmethod
    async def parse(cls, data: ParseData) -> StyleVar:
        """Parse StyleVars from configs."""
        name = TransToken.parse(data.pak_id, data.info['name', ''])

        styles = [
            prop.value
            for prop in
            data.info.find_all('Style')
        ]
        desc = TransToken.parse(data.pak_id, '\n'.join(
            prop.value
            for prop in
            data.info.find_all('description')
        ))
        return cls(
            data.id,
            name,
            styles,
            desc,
            unstyled=data.info.bool('unstyled'),
            inherit=data.info.bool('inherit', True),
            default=data.info.bool('enabled'),
        )

    def add_over(self, override: StyleVar) -> None:
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
        stripped_over = override.desc.token.strip()
        if stripped_over and stripped_over not in self.desc.token:
            if self.desc.token.strip():
                self.desc = TransToken.untranslated('{a}\n\n{b}').format(a=self.desc, b=override.desc)
            else:
                self.desc = override.desc

    def __repr__(self) -> str:
        return (
            f'<Stylevar "{self.id}", name="{self.name}", '
            f'default={self.default}, '
            f'styles={self.styles}>'
        )

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield translation tokens used by this stylevar."""
        yield self.name, self.id + '.name'
        yield self.desc, self.id + '.desc'

    def applies_to_style(self, style: Style) -> bool:
        """Check to see if this will apply for the given style.

        """
        if self.styles is None:
            return True

        if style.id in self.styles:
            return True

        return self.inherit and any(
            base.id in self.styles
            for base in
            style.bases
        )

    def applies_to_all(self, packset: PackagesSet) -> bool:
        """Check if this applies to all styles."""
        if self.is_unstyled:
            return True

        for style in packset.all_obj(Style):
            if not self.applies_to_style(style):
                return False
        return True
