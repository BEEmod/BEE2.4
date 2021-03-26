"""Implements an adaptive 2D matrix for storing items at arbitary coordinates efficiently.

"""
from typing import (
    TypeVar, Generic, Union, Any,
    Tuple, Iterable, Optional,
    Mapping, MutableMapping,
    ValuesView, ItemsView,
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
        self._xoffs: list[int] = []
        self._data: list[Optional[list[Optional[ValT]]]] = []
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
        return self._used
        
    def __repr__(self) -> str:
        return f'Plane({dict(self.items())!r})'
        
    def __getitem__(self, pos: Tuple[int, int]) -> ValT:
        """Return the value at a given position."""
        x, y = pos
        y += self._yoff
        try:
            x += self._xoffs[y]
            out = self._data[y][x]
        except IndexError:
            raise KeyError(pos) from None
        if out is None:  # Empty slot.
            raise KeyError(pos)
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
            if y < self._min_y:
                self._min_y = y
        elif y_ind >= y_bound:
            change = y_ind - y_bound + 1
            self._xoffs.extend([0] * change)
            self._data.extend([None] * change)
            y_ind = -1 # y_bound - 1, but list can compute that.
            if y > self._max_y:
                self._max_y = y
        
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
            if x < self._min_x:
                self._min_x = x
        elif x >= x_bound:
            change = x - x_bound + 1
            data.extend([None] * change)
            x_ind = -1
            if x > self._max_x:
                self._max_x = x
        
        if data[x_ind] is None:
            if val is not None:
                self._used += 1
        elif val is None:
            self._used -= 1
        
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
        self[pos] = None
        
    def clear(self) -> None:
        """Remove all data from the plane."""
        self._min_x = self._min_y = self._max_x = self._max_y = 0
        self._yoff = self._used = 0
        self._xoffs.clear()
        self._data.clear()
        
    def values(self) -> ValuesView[ValT]:
        """D.values() -> a set-like object providing a view on D's values"""
        return PlaneValues(self)
        
    def items(self) -> ItemsView[Tuple[int, int], ValT]:
        """D.items() -> a set-like object providing a view on D's items"""
        return PlaneItems(self)


class PlaneValues(ValuesView[ValT]):
    """Implementation of Plane.values()."""
    __slots__ = ()  # _mapping is defined in superclass.
    def __init__(self, plane: Plane[ValT]) -> None:
        self._mapping = plane
        super().__init__(plane)
        
    def __contains__(self, item: Any) -> bool:
        """Check if the provided item is a value."""
        if item is None:
            return False
        for row in self._mapping._data:
            if item in row:
                return True
        return False
    
    def __iter__(self) -> None:
        """Produce all values in the plane."""
        for row in self._mapping._data:
            for value in row:
                if value is not None:
                    yield value


class PlaneItems(ItemsView[Tuple[int, int], ValT]):
    """Implementation of Plane.items()."""
    __slots__ = ()  # _mapping is defined in superclass.
    def __init__(self, plane: Plane[ValT]) -> None:
        self._mapping = plane
        super().__init__(plane)
        
    def __contains__(self, item: Any) -> bool:
        """Check if the provided pos/value pair is present."""
        if not isinstance(item, tuple):
            return False
        try:
            xy, value = item
            return self._mapping[xy] == value
        except ValueError:  # len(tup) != 3
            return False
        except KeyError:  # Not present
            return False
    
    def __iter__(self) -> None:
        """Produce all coord, value pairs in the plane."""
        for y, (xoff, row) in enumerate(
            zip(self._mapping._xoffs, self._mapping._data), 
            start=-self._mapping._yoff,
        ):
            if row is None:
                continue
            for x, data in enumerate(row, start=-xoff):
                if data is not None:
                    yield (x, y), data

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
    
