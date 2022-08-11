"""Test the main config logic."""
import pytest
from srctools import Property, bool_as_int
from typing_extensions import Literal, TypeAlias

import config

Triple: TypeAlias = Literal["a", "b", "c"]


class DataSingle(config.Data, conf_name='TestName', version=2, uses_id=False):
    """Simple data type, not using IDs."""
    def __init__(self, value: str, triple: Triple) -> None:
        self.value = value
        self.triple = triple

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DataSingle):
            return self.value == other.value and self.triple == other.triple
        return NotImplemented

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'DataSingle':
        """Parse keyvalues."""
        triple: Triple
        if version == 2:
            triple_str = data['triple']
            if triple_str in {"a", "b", "c"}:
                triple = triple_str
            else:
                raise ValueError('Illegal triple.', triple_str)
        elif version == 1:
            triple = "b" if data.bool('is_bee') else "a"
        else:
            raise ValueError('Unknown version', version)
        return DataSingle(data['value'], triple)

    def export_kv1(self) -> Property:
        """Write out KV1 data."""
        return Property('TestData', [
            Property('value', self.value),
            Property('triple', self.triple),
        ])


def test_basic_store() -> None:
    """Test storing config values."""
    spec = config.ConfigSpec(None)
    spec.register(DataSingle)

    data_1 = DataSingle("value_1", "b")
    data_2 = DataSingle("value_2", "b")
    data_3 = DataSingle("value_3", "a")

    with pytest.raises(KeyError):
        spec.get_cur_conf(DataSingle)
    assert spec.get_cur_conf(DataSingle, default=data_2) is data_2

    spec.store_conf(data_1)
    assert spec.get_cur_conf(DataSingle) is data_1
    assert spec.get_cur_conf(DataSingle, default=data_2) is data_1

    spec.store_conf(data_3)
    assert spec.get_cur_conf(DataSingle) is data_3
    assert spec.get_cur_conf(DataSingle, default=data_1) is data_3


@pytest.mark.parametrize('triple', ['a', 'b'])
@pytest.mark.parametrize('value', [
    'testing testing',
    'multi\nline\nstring',
])
def test_parse_kv1_upgrades(value: str, triple: Triple) -> None:
    """Test parsing Keyvalues1 data, and upgrading old versions."""
    spec = config.ConfigSpec(None)
    spec.register(DataSingle)

    props = Property.root(
        Property('version', '1'),
        Property('TestName', [
            Property('_version', '1'),
            Property('value', value),
            Property('is_bee', bool_as_int(triple == 'b')),
        ])
    )
    conf, upgraded = spec.parse_kv1(props)
    assert upgraded
    assert conf == {DataSingle: {'': DataSingle(value, triple)}}

    props = Property.root(
        Property('version', '1'),
        Property('TestName', [
            Property('_version', '2'),
            Property('value', value),
            Property('triple', triple),
        ])
    )
    conf, upgraded = spec.parse_kv1(props)
    assert not upgraded
    assert conf == {DataSingle: {'': DataSingle(value, triple)}}
