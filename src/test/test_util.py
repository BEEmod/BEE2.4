"""Test misc utils."""
from typing import assert_type
import re

import pytest

import utils


def test_not_none() -> None:
    """Test the not_none() assert."""
    utils.not_none(0)
    utils.not_none(False)
    with pytest.raises(AssertionError, match=re.escape('Value was none!')):
        utils.not_none(None)
    # Basic typechecker test.
    nonable: int | None = [1, None][eval('0')]
    assert_type(utils.not_none(nonable), int)


def test_iter_neighbours() -> None:
    """Test iter_neighbours()."""
    assert [*utils.iter_neighbours([])] == []
    assert [*utils.iter_neighbours([1])] == [(None, 1, None)]
    assert [*utils.iter_neighbours(['first', 'second'])] == [
        (None, 'first', 'second'), ('first', 'second', None),
    ]
    assert [*utils.iter_neighbours(['first', 'second', 3])] == [
        (None, 'first', 'second'), ('first', 'second', 3), ('second', 3, None),
    ]
    assert [*utils.iter_neighbours(range(5))] == [
        (None, 0, 1),
        (0, 1, 2),
        (1, 2, 3),
        (2, 3, 4),
        (3, 4, None),
    ]
