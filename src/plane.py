"""Implements an adaptive 2D matrix for storing items at arbitary coordinates efficiently.

"""
from typing import (
    TypeVar, Generic,
    Tuple, Iterable,
    MutableMapping,
)

ValT = TypeVar('ValT')


class Plane(Generic[ValT], MutableMapping[Tuple[int, int], ValT]):
    """An adaptive 2D matrix holding arbitary values."""
    def __init__(
        self, 
        contents: Iterable[Tuple[int, int, ValT]] = (),
    ) -> None:
        """Initalises the plane with the provided values."""
        
