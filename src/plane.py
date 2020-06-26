"""Implements an adaptive 2D matrix for storing items at arbitary coordinates efficiently.

"""
from typing import (
    TypeVar, Generic,
    Tuple, Iterable,
    MutableMapping,
)

ValT = TypeVar('ValT')


class Plane(Generic[ValT], MutableMapping[Tuple[int, int], ValT]):
    """An adaptive 2D matrix holding arbitary values.
    
    Note that None is considered empty / lack of a value.
    
    This is implemented with a list of lists, with an offset value for all.
    An (x, y) value is located at data[y - yoff][x - xoff[y - yoff]]
    """
    def __init__(
        self, 
        contents: Iterable[Tuple[Tuple[int, int], ValT]] = (),
    ) -> None:
        """Initalises the plane with the provided values."""
        # Track the minimum/maximum position found
        #self.mins = (0, 0)
        #self.maxes = (0, 0)
        self._yoff = 0
        self._xoffs: List[int] = []
        self._data: List[Optional[List[Optional[ValT]]]] = []
        #self._used = 0
        
    def __len__(self) -> int:
        """The length is the number of used slots."""
        #return self._used
        
    def __repr__(self) -> str:
        return f'Plane({list(self.items())!r})'
        
    def __getitem__(self, pos: Tuple[int, int]) -> ValT:
        """Return the value at a given position."""
        x, y = pos
        y += self._yoff
        try:
            x += self._xoffs[y]
            out = self._data[x]
        except IndexError:
            raise KeyError(pos) from None
        if out is None:  # Empty slot.
            raise KeyError(pos)
        return out
            
    def __setitem__(self, pos: Tuple[int, int], val: ValT) -> None:
        """Set the value at the given position, resizing if required."""
        x, y = pos
        y += self._yoff
        y_bound = len(self._xoffs)
        
        # Extend if required. 
        if y < 0:
            change = -y
            self._yoff += change
            self._xoffs[0:0] = [0] * change
            self._data[0:0] = [None] * change
            y = 0
        elif y >= y_bound:
            change = y - y_bound + 1
            self._yoff -= change
            self._xoffs.extend([0] * change)
            self._data.extend([None] * change)
            y = -1
        
        # Now x.
        data = self._data[y]
        if data is None:
            data = self._data[y] = []

        x += self._xoffs[y]
        x_bound = len(data)
        if x < 0:
            change = -x
            self._xoffs[y] += change
            data[0:0] = [None] * change
            x = 0
        elif x >= x_bound:
            change = x - x_bound + 1
            self._xoffs[y] -= change
            data.extend([None] * change)
            x = -1
        data[x] = val

    def __iter__(self) -> Tuple[int, int]:
        """Return all used keys."""
        for y, (xoff, row) in enumerate(zip(self._xoffs, self._data), start=-self._yoff):
            if row is None:
                continue
            for x, data in enumerate(row, start=-xoff):
                if data is not None:
                    yield (x, y)
                    
    def __delitem__(self, pos: Tuple[int, int]) -> None:
        self[x, y] = None
        
pl = Plane()
print(pl)
pl[0, 1] = (0, 1)
print('0, 1:', vars(pl))
pl[1, 0] = (1, 0)
print('1, 0:', vars(pl))
pl[-5, 2] = (-5, 2)
print('-5, 2:', vars(pl))
