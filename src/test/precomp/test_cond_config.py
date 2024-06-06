"""Test condition config handling."""
from typing import Annotated, Self

import pytest
from srctools import Keyvalues
from srctools.dmx import Element

from precomp import cond_config

import annotated_types
import attrs


@attrs.define
class SampleData(cond_config.Config):
    """A config with one of each supported type."""
    string: Annotated[str, annotated_types.doc('Some text.')]
    percentage: Annotated[
        int,
        annotated_types.Gt(0), annotated_types.Le(100),
        annotated_types.doc('A number between 1-100'),
    ]

    @classmethod
    def parse_kv1(cls, kv: Keyvalues) -> Self:
        return cls('Should not be used', 0)


def test_parse_string_field() -> None:
    """Test creating a string field."""
    field = cond_config.FieldParser.from_type(Annotated[
        str,
        annotated_types.doc('A string'),
    ])
    assert isinstance(field, cond_config.StringField)


def test_parse_integral_field() -> None:
    """Test creating an int field from an annotated type."""
    field = cond_config.FieldParser.from_type(Annotated[
        int,
        annotated_types.Gt(0),
        annotated_types.Le(100),
        annotated_types.doc('A number between 1-100'),
    ])
    assert isinstance(field, cond_config.IntegralField)
    assert field == cond_config.IntegralField(1, 100)

    field = cond_config.FieldParser.from_type(
        Annotated[int, annotated_types.doc('')]
    )
    assert field == cond_config.IntegralField(None, None)

    field = cond_config.FieldParser.from_type(Annotated[
        int,
        annotated_types.Gt(50),
    ])
    assert field == cond_config.IntegralField(51, None)

    field = cond_config.FieldParser.from_type(Annotated[
        int,
        annotated_types.Ge(50),
    ])
    assert field == cond_config.IntegralField(50, None)

    field = cond_config.FieldParser.from_type(Annotated[
        int,
        annotated_types.Lt(50),
    ])
    assert field == cond_config.IntegralField(None, 49)

    field = cond_config.FieldParser.from_type(Annotated[
        int,
        annotated_types.Le(50),
    ])
    assert field == cond_config.IntegralField(None, 50)


def test_basic_conf() -> None:
    """Test a sample config."""
    elem = Element('Config', 'SampleData')
    elem['string'] = 'test text'
    elem['percentage'] = -5

    with pytest.raises(ValueError, match=r'Value -5 is not in \[1 - 100\]'):
        SampleData.parse_dmx(elem)

    elem['percentage'] = 38
    result = SampleData.parse_dmx(elem)
    assert result == SampleData('test text', 38)
