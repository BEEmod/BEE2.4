"""Implements an adaptive 2D matrix for storing items at arbitary coordinates efficiently.

"""
from typing import (
    TypeVar, Generic, Union,
    Tuple, Iterable,
    Mapping, MutableMapping,
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
        contents: Union[
            Mapping[Tuple[int, int], ValT],
            Iterable[Tuple[Tuple[int, int], ValT]],
        ] = (),
    ) -> None:
        """Initalises the plane with the provided values."""
        # Track the minimum/maximum position found
        self._min_x = self._min_y = self._max_x = self._max_y = 0
        self._yoff = 0
        self._xoffs: List[int] = []
        self._data: List[Optional[List[Optional[ValT]]]] = []
        self._used = 0
        if contents:
            self.update(contents)
            
    @property
    def mins(self) -> Tuple[int, int]:
        """Return the minimum bounding point ever set."""
        return self._min_x, self._min_y

    @property
    def maxes(self) -> Tuple[int, int]:
        """Return the maximum bounding point ever set."""
        return self._max_x, self._max_y
        
    def __len__(self) -> int:
        """The length is the number of used slots."""
        #return self._used
        
    def __repr__(self) -> str:
        return f'Plane({dict(self.items())!r})'
        
    def __getitem__(self, pos: Tuple[int, int]) -> ValT:
        """Return the value at a given position."""
        attr = vars(self)
        x, y = pos
        y += self._yoff
        try:
            x += self._xoffs[y]
            out = self._data[y][x]
        except IndexError:
            raise KeyError(pos) from None
        #if out is None:  # Empty slot.
            #raise KeyError(pos)
        return out
            
    def __setitem__(self, pos: Tuple[int, int], val: ValT) -> None:
        """Set the value at the given position, resizing if required."""
        x, y = pos
        y_ind = y + self._yoff
        y_bound = len(self._xoffs)
        
        # Extend if required. 
        if y_ind < 0:
            change = -y_ind
            self._yoff += change
            self._xoffs[0:0] = [0] * change
            self._data[0:0] = [None] * change
            y_ind = 0
        elif y_ind >= y_bound:
            change = y_ind - y_bound + 1
            self._xoffs.extend([0] * change)
            self._data.extend([None] * change)
            y_ind = -1 # y_bound - 1, but list can compute that.
        
        # Now x.
        data = self._data[y_ind]
        if data is None: # Create the list only when we need it.    
            data = self._data[y_ind] = []

        x_ind = x + self._xoffs[y_ind]
        x_bound = len(data)
        if x_ind < 0:
            change = -x_ind
            self._xoffs[y_ind] += change
            data[0:0] = [None] * change
            x_ind = 0
        elif x >= x_bound:
            change = x - x_bound + 1
            data.extend([None] * change)
            x_ind = -1
        
        if data[x_ind] is None:
            if val is not None:
                self._used += 1
        elif val is None:
            self.used -= 1
        
        data[x_ind] = val

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

if __name__ == '__main__':
    print('-'*80)
    def test(*pos):
        pl[pos] = pos
        print(f'{pos[0]} {pos[1]}:')
        print(' ├', vars(pl))
        
        copy = pl[pos]
        assert copy is pos, copy
        print(' ├', list(pl))
        print(' └', pl)
    pl = Plane()

    test(0, 1)
    test(1, 0)
    test(-5, 2)
    
