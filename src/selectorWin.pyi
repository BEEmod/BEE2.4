from enum import Enum

from srctools import Vec
from typing import NamedTuple, Optional, Union

class AttrTypes(Enum): ...

class AttrDef(NamedTuple('AttrDef', [
    ('id', str),
    ('type', AttrTypes),
    ('desc', str),
    ('default', Union[str, list, bool, Vec]),
])):
    """The definition for attributes."""
    def __new__(
            cls,
            id: str,
            desc='',
            default: Optional[Union[str, list, bool, Vec]]=None,
            type=AttrTypes.STRING,
        ) -> 'AttrDef': ...

    # Generated from AttrTypes, so we need stubs...
    @classmethod
    def string(cls, id: str, desc='', default: str=None) -> 'AttrDef':
        """An alternative constructor to create string-type attrs."""

    @classmethod
    def list(cls, id: str, desc='', default: list=None) -> 'AttrDef':
        """An alternative constructor to create list-type attrs."""

    @classmethod
    def bool(cls, id: str, desc='', default: bool=None) -> 'AttrDef':
        """An alternative constructor to create bool-type attrs."""

    @classmethod
    def color(cls, id: str, desc='', default: Vec=None) -> 'AttrDef':
        """An alternative constructor to create color-type attrs."""
