"""Automatically parse condition tests or results based on annotated attrs classes."""
from typing import (
    Annotated, Any, Protocol, Self, get_origin as get_type_origin,
    get_args as get_type_args,
)

from collections.abc import Iterable, Iterator

from srctools import Keyvalues
from srctools.dmx import Element, Attribute
import annotated_types
import attrs


class Config(attrs.AttrsInstance, Protocol):
    """Protocol representing configurations."""
    @classmethod
    def parse_kv1(cls, kv: Keyvalues) -> Self:
        """Parse handwritten keyvalues1 configs."""
        raise NotImplementedError

    @classmethod
    def parse_dmx(cls, elem: Element) -> Self:
        """Parse DMX files."""
        parse: ConfigParser[Self] = ConfigParser.from_type(cls)
        return parse.parse_dmx(elem, '')

    def export_dmx(self) -> Element:
        """Build a DMX version of the config."""
        return ConfigParser.from_type(type(self)).export_dmx(self)


@attrs.frozen
class Empty(Config):
    """Blank config used when none is required."""
    @classmethod
    def parse_kv1(cls, kv: Keyvalues) -> 'Empty':
        """The keyvalues are ignored."""
        return EMPTY


EMPTY = Empty()


def unpack_annotations(annotations: Iterable[object]) -> Iterator[annotated_types.BaseMetadata]:
    """Split annotations into simpler forms."""
    for ann in annotations:
        if isinstance(ann, annotated_types.GroupedMetadata):
            yield from unpack_annotations(ann)
        elif isinstance(ann, annotated_types.BaseMetadata):
            yield ann


@attrs.define
class FieldParser[ValueT]:
    """Represents the annotation for a single field."""

    @classmethod
    def from_type(cls, attr_type: object) -> 'FieldParser[Any]':
        """Build from an annotated type."""
        if get_type_origin(attr_type) is Annotated:
            [attr_type, *raw_ann] = get_type_args(attr_type)
            annotations = list(unpack_annotations(raw_ann))
        else:
            annotations = []
        try:
            field_class = _FIELD_TYPES[attr_type]
        except KeyError:
            raise NotImplementedError(f'Unsupported config type: {attr_type!r}') from None
        return field_class._from_annotation(annotations)

    @classmethod
    def _from_annotation(cls, annotations: list[annotated_types.BaseMetadata]) -> Self:
        """Parse annotations."""
        raise NotImplementedError

    def parse_dmx(self, field: Attribute) -> ValueT:
        """Parse a DMX value."""
        raise NotImplementedError

    def export_dmx(self, name: str, value: ValueT) -> Attribute:
        """Output to DMX."""
        raise NotImplementedError


@attrs.define
class ConfigParser[Conf]:
    """Parse a specific config."""
    conf_cls: type[Conf]
    fields: list[tuple[attrs.Attribute, FieldParser[Any]]]

    @classmethod
    # @functools.cache
    def from_type[ClsT: Config](cls, conf_type: type[ClsT]) -> 'ConfigParser[ClsT]':
        """A parser for a specific config class."""
        fields = [
            (attr, FieldParser.from_type(attr.type))
            for attr in attrs.fields(conf_type)
        ]
        return ConfigParser(conf_type, fields)

    def parse_dmx(self, elem: Element, path: str) -> Conf:
        """Parse a DMX element."""
        result = {}
        for attr_info, field_parser in self.fields:
            name = attr_info.alias or attr_info.name
            try:
                attr = elem[name]
            except KeyError:
                if attr_info.default is attrs.NOTHING:
                    raise ValueError(f'{path}/{attr_info.name}: Value is required!')
                result[name] = attr_info.default
            else:
                result[name] = field_parser.parse_dmx(attr)

        return self.conf_cls(**result)

    def export_dmx(self, conf: Conf) -> Element:
        """Output to DMX."""
        elem = Element('', self.conf_cls.__name__)
        for attr_info, field_parser in self.fields:
            name = attr_info.alias or attr_info.name
            value = getattr(conf, attr_info.name)
            elem[name] = field_parser.export_dmx(name, value)
        return elem


@attrs.define
class IntegralField(FieldParser[int]):
    """Integer fields may be constrained to specific values."""
    # These are inclusive.
    mins: int | None
    maxs: int | None

    @classmethod
    def _from_annotation(cls, annotations: list[annotated_types.BaseMetadata]) -> Self:
        """Parse from annotations."""
        mins: int | None = None
        maxs: int | None = None
        for ann in annotations:
            match ann:
                case annotated_types.Lt():
                    assert maxs is None, 'Multiple mins defined?'
                    assert isinstance(ann.lt, int)
                    maxs = ann.lt - 1
                case annotated_types.Le():
                    assert maxs is None, 'Multiple mins defined?'
                    assert isinstance(ann.le, int)
                    maxs = ann.le
                case annotated_types.Gt():
                    assert mins is None, 'Multiple maxes defined?'
                    assert isinstance(ann.gt, int)
                    mins = ann.gt + 1
                case annotated_types.Ge():
                    assert mins is None, 'Multiple maxes defined?'
                    assert isinstance(ann.ge, int)
                    mins = ann.ge
        return cls(mins, maxs)

    def parse_dmx(self, field: Attribute) -> int:
        """Parse a dmx value."""
        value = field.val_int
        if self.mins is not None and self.maxs is not None:
            if not (self.mins <= value <= self.maxs):
                raise ValueError(f'Value {value} is not in [{self.mins} - {self.maxs}]')
        if self.mins is not None and value < self.mins:
            raise ValueError(f'Value {value} is less than {self.mins}!')
        if self.maxs is not None and value > self.maxs:
            raise ValueError(f'Value {value} is greater than {self.maxs}!')
        return value

    def export_dmx(self, name: str, value: int) -> Attribute:
        return Attribute.int(name, value)


class StringField(FieldParser[str]):
    """String fields are unconstrained."""
    @classmethod
    def _from_annotation(cls, annotations: list[annotated_types.BaseMetadata]) -> Self:
        return cls()

    def parse_dmx(self, field: Attribute) -> str:
        return field.val_string

    def export_dmx(self, name: str, value: str) -> Attribute:
        return Attribute.string(name, value)


_FIELD_TYPES: dict[object, type[FieldParser]] = {
    int: IntegralField,
    str: StringField,
}
