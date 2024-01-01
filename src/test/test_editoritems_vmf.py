"""Test the VMF-based item configuration system."""
from typing import List, Union

import pytest

from editoritems_vmf import numeric_sort
from dirty_equals import IsList


@pytest.mark.parametrize('value, expected', [
    ('regular_string', ['regular_string']),
    ('rope1234567890', ['rope', 1234567890]),
    ('item42group84_test', ['item', 42, 'group', 84, '_test'])
])
def test_numeric_sort(value: str, expected: List[Union[str, int]]) -> None:
    """Test the numeric sort helper."""
    result = numeric_sort(value)
    assert result == IsList(*expected)
    assert ''.join(map(str, result)) == value
