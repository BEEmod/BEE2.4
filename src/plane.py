"""Implements an adaptive 2D matrix for storing items at arbitrary coordinates efficiently.

"""
from __future__ import annotations
from typing import Any, Final, overload, ClassVar

from collections.abc import (
    ItemsView, Iterable, Iterator, Mapping, MutableMapping, ValuesView, Sequence,
)
import copy

from srctools.math import AnyVec, FrozenMatrix, FrozenVec, Vec
import attrs

__all__ = ['PlaneKey', 'PlaneGrid']

# Sentinel object for empty slots and parameter defaults. TODO use PEP 661
_UNSET: Any = type('_UnsetType', (), {'__repr__': lambda s: 'UNSET'})()
# Size of each plane grid cell.
CELL_SIZE = 8
CELL_SIZE_SQR = CELL_SIZE ** 2
# Corresponding coordinates in a cell, cached so we can zip this with the contents.
CELL_COORDS: Sequence[tuple[int, int]] = [
    (x, y) for y in range(CELL_SIZE) for x in range(CELL_SIZE)
]


# The 6 possible normal vectors for the plane.
# Reuse the same instance for the vector, and precompute the hash.
_NORMALS: Final[Mapping[FrozenVec, tuple[FrozenVec, int]]] = {
    FrozenVec.N: (FrozenVec.N, hash(b'n')),
    FrozenVec.S: (FrozenVec.S, hash(b's')),
    FrozenVec.E: (FrozenVec.E, hash(b'e')),
    FrozenVec.W: (FrozenVec.W, hash(b'w')),
    FrozenVec.T: (FrozenVec.T, hash(b't')),
    FrozenVec.B: (FrozenVec.B, hash(b'b')),
}
# The orientation points Z = normal, X = sideways, Y = upward.
_ORIENTS: Final[Mapping[FrozenVec, FrozenMatrix]] = {
    FrozenVec.N: FrozenMatrix.from_basis(x=Vec(-1, 0, 0), y=Vec(0, 0, 1)),
    FrozenVec.S: FrozenMatrix.from_basis(x=Vec(1, 0, 0), y=Vec(0, 0, 1)),
    FrozenVec.E: FrozenMatrix.from_basis(x=Vec(0, 1, 0), y=Vec(0, 0, 1)),
    FrozenVec.W: FrozenMatrix.from_basis(x=Vec(0, -1, 0), y=Vec(0, 0, 1)),
    FrozenVec.T: FrozenMatrix.from_basis(x=Vec(1, 0, 0), y=Vec(0, 1, 0)),
    FrozenVec.B: FrozenMatrix.from_basis(x=Vec(-1, 0, 0), y=Vec(0, 1, 0)),
}
_INV_ORIENTS: Final[Mapping[FrozenVec, FrozenMatrix]] = {
    norm: orient.transpose()
    for norm, orient in _ORIENTS.items()
}


@attrs.frozen(eq=False, hash=False, init=False)
class PlaneKey:
    """A hashable key used to identify 2-dimensional plane slices."""

    normal: FrozenVec
    distance: float
    _hash: int = attrs.field(repr=False)

    def __init__(self, normal: AnyVec, dist: AnyVec | float) -> None:
        try:
            norm, norm_hash = _NORMALS[FrozenVec(normal)]
        except KeyError:
            raise ValueError(f'{normal!r} is not an on-axis normal!') from None
        if not isinstance(dist, int | float):
            dist = norm.dot(dist)

        self.__attrs_init__(norm, dist, hash(dist) ^ norm_hash)

    @property
    def is_horizontal(self) -> bool:
        """Return whether this is pointing up or down."""
        # We reuse one of the preset vectors, so direct comparison is all that's required.
        return self.normal.z != 0.0

    @property
    def orient(self) -> FrozenMatrix:
        """Return a matrix with the +Z direction facing along the slice."""
        return _ORIENTS[self.normal]

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PlaneKey):
            return self.normal is other.normal and self.distance == other.distance
        else:
            return NotImplemented

    def __ne__(self, other: object) -> bool:
        if isinstance(other, PlaneKey):
            return self.normal is not other.normal or self.distance != other.distance
        else:
            return NotImplemented

    def plane_to_world(self, x: float, y: float, z: float = 0.0) -> Vec:
        """Return a position relative to this plane."""
        orient = _ORIENTS[self.normal]
        return Vec(x, y, z) @ orient + self.normal * self.distance

    def world_to_plane(self, pos: AnyVec) -> Vec:
        """Take a world position and return the location relative to this plane."""
        orient = _INV_ORIENTS[self.normal]
        return (Vec(pos) - self.normal * self.distance) @ orient


class Cell[ValT]:
    """Stores a CELL_SIZE x CELL_SIZE grid of values."""
    array: list[ValT]
    count: int
    def __init__(self, count: int, data: list[ValT]) -> None:
        self.array = data
        self.count = count

    def __repr__(self) -> str:
        return f'Cell({self.count}, {self.array!r})'

    def copy(self) -> 'Cell[ValT]':
        """Shallow-copy the cell."""
        return Cell(self.count, self.array.copy())

    def validate(self) -> None:
        """Check the count is accurate."""
        assert self.count == sum(v is not _UNSET for v in self.array), self


class SingleCell[ValT]:
    """Represents a cell entirely filled with a single value."""
    count: ClassVar[int] = CELL_SIZE_SQR
    # Should not be unset!
    value: ValT
    def __init__(self, value: ValT) -> None:
        assert value is not _UNSET
        self.value = value

    def __repr__(self) -> str:
        return f'SingleCell({self.count}, {self.value!r})'

    def copy(self) -> 'SingleCell[ValT]':
        """Shallow-copy the cell."""
        return SingleCell(self.value)

    def validate(self) -> None:
        """Does nothing."""
        pass

    def inflate(self) -> 'Cell[ValT]':
        """Inflate the array to full size."""
        return Cell(CELL_SIZE_SQR, [self.value] * CELL_SIZE_SQR)


class PlaneGrid[ValT](MutableMapping[tuple[int, int], ValT]):
    """An adaptive 2D matrix holding arbitary values.

    We store items in CELL_SIZE^2 arrays.
    """
    _cells: dict[tuple[int, int], Cell[ValT] | SingleCell[ValT]]
    def __init__(
        self,
        contents: Mapping[tuple[int, int], ValT] | Iterable[tuple[tuple[int, int], ValT]] = (),
        *,
        default: ValT = _UNSET,
    ) -> None:
        """Initalises the plane with the provided values."""
        # Track the minimum/maximum position found
        self._min_x = self._min_y = self._max_x = self._max_y = 0
        self._cells = {}
        self.default = default
        if contents:
            self.update(contents)

    @property
    def mins(self) -> tuple[int, int]:
        """Return the minimum bounding point ever set."""
        return self._min_x, self._min_y

    @property
    def maxes(self) -> tuple[int, int]:
        """Return the maximum bounding point ever set."""
        return self._max_x, self._max_y

    @property
    def dimensions(self) -> tuple[int, int]:
        """Return the difference between the mins and maxes."""
        return self._max_x - self._min_x, self._max_y - self._min_y

    def __len__(self) -> int:
        """The length is the number of used slots."""
        return sum(cell.count for cell in self._cells.values())

    def __bool__(self) -> bool:
        """The grid is true if a value is present."""
        return bool(self._cells)

    def __repr__(self) -> str:
        return f'Plane({dict(self.items())!r})'

    def range_x(self) -> range:
        """Iterate over all valid X positions."""
        return range(self._min_x, self._max_x + 1)

    def range_y(self) -> range:
        """Iterate over all valid Y positions."""
        return range(self._min_y, self._max_y + 1)

    range_u = range_x
    range_v = range_y

    @classmethod
    def fromkeys(
        cls: type[PlaneGrid[ValT]],
        source: PlaneGrid[Any] | Iterable[tuple[int, int]],
        value: ValT,
    ) -> PlaneGrid[ValT]:
        """Create a plane from an existing set of keys, setting all values to a specific value."""
        if isinstance(source, PlaneGrid):
            res: PlaneGrid[ValT] = cls.__new__(cls)
            res.__dict__.update(source.__dict__)  # Immutables
            res._cells = {
                pos: SingleCell(value)
                if isinstance(cell, SingleCell) else
                Cell(cell.count, [value if orig is not _UNSET else _UNSET for orig in cell.array])
                for pos, cell in source._cells.items()
            }
            return res
        else:
            res = PlaneGrid()
            for xy in source:
                res[xy] = value
            return res

    def copy(self) -> PlaneGrid[ValT]:
        """Shallow-copy the plane."""
        cpy = PlaneGrid.__new__(PlaneGrid)
        cpy.__dict__.update(self.__dict__)  # Immutables
        cpy._cells = {
            pos: cell.copy()
            for pos, cell in self._cells.items()
        }
        return cpy

    __copy__ = copy

    def __deepcopy__(self, memodict: dict[int, Any]) -> PlaneGrid[ValT]:
        """Deep-copy the plane."""
        cpy = PlaneGrid.__new__(PlaneGrid)
        cpy.__dict__.update(self.__dict__)  # Immutables
        cpy._cells = copy.deepcopy(self._cells, memodict)
        return cpy

    def __getitem__(self, pos: tuple[float, float]) -> ValT:
        """Return the value at a given position."""
        return self.get(pos, self.default)

    def __contains__(self, pos: tuple[float, float] | object) -> bool:
        """Check if a value is set at the given location."""
        if not isinstance(pos, tuple):
            return False
        try:
            p1, p2 = pos
            x = int(p1)
            y = int(p2)
        except (ValueError, TypeError):
            return False
        cell_x, x = divmod(x, CELL_SIZE)
        cell_y, y = divmod(y, CELL_SIZE)
        try:
            cell = self._cells[cell_x, cell_y]
        except KeyError:
            return False
        if isinstance(cell, SingleCell):
            return True
        else:
            return cell.array[y * CELL_SIZE + x] is not _UNSET

    @overload
    def get(self, key: tuple[float, float], /) -> ValT | None: ...
    @overload
    def get[DefaultT](self, key: tuple[float, float], default: ValT | DefaultT, /) -> ValT | DefaultT: ...

    def get[DefaultT](self, pos: tuple[float, float], default: DefaultT | None = None) -> DefaultT | ValT | None:
        """Return the value at a given position, or a default if not present."""
        try:
            p1, p2 = pos
            x = int(p1)
            y = int(p2)
        except (ValueError, TypeError):
            if default is _UNSET:  # For __getitem__ only.
                raise KeyError(pos) from None
            else:
                return default
        cell_x = x // CELL_SIZE
        cell_y = y // CELL_SIZE
        x %= CELL_SIZE
        y %= CELL_SIZE
        try:
            cell = self._cells[cell_x, cell_y]
        except KeyError:
            if default is _UNSET:
                raise KeyError(pos) from None
            else:
                return default
        if isinstance(cell, SingleCell):
            return cell.value
        else:
            value = cell.array[y * CELL_SIZE + x]
        if value is _UNSET:
            if default is _UNSET:
                raise KeyError(pos) from None
            else:
                return default
        return value

    def __setitem__(self, pos: tuple[float, float], val: ValT) -> None:
        """Set the value at the given position, resizing if required."""
        try:
            p1, p2 = pos
            x = int(p1)
            y = int(p2)
        except (ValueError, TypeError):
            raise KeyError(pos) from None

        if not self._cells:
            # First value, set this as the min/max.
            self._min_x = self._max_x = x
            self._min_y = self._max_y = y
        else:
            if y < self._min_y:
                self._min_y = y
            if y > self._max_y:
                self._max_y = y
            if x < self._min_x:
                self._min_x = x
            if x > self._max_x:
                self._max_x = x

        cell_x, x = divmod(x, CELL_SIZE)
        cell_y, y = divmod(y, CELL_SIZE)
        ind = y * CELL_SIZE + x
        try:
            cell = self._cells[cell_x, cell_y]
        except KeyError:
            # Missing, we don't need to check for _UNSET
            cell = self._cells[cell_x, cell_y] = Cell(1, [_UNSET] * CELL_SIZE_SQR)
            cell.array[ind] = val
        else:
            if isinstance(cell, SingleCell):
                self._cells[cell_x, cell_y] = cell = cell.inflate()
            if cell.array[ind] is _UNSET:
                cell.count += 1
            cell.array[ind] = val

    def __iter__(self) -> Iterator[tuple[int, int]]:
        """Return all used keys."""
        for (cell_x, cell_y), cell in self._cells.items():
            cell_x *= CELL_SIZE
            cell_y *= CELL_SIZE
            if isinstance(cell, SingleCell):
                for x, y in CELL_COORDS:
                    yield (cell_x + x, cell_y + y)
            else:
                for (x, y), value in zip(CELL_COORDS, cell.array):
                    if value is not _UNSET:
                        yield (cell_x + x, cell_y + y)

    def __delitem__(self, pos: tuple[float, float]) -> None:
        """Remove the value at a given position, doing nothing if not set."""
        try:
            p1, p2 = pos
            x = int(p1)
            y = int(p2)
        except (ValueError, TypeError):
            raise KeyError(pos) from None

        cell_x, x = divmod(x, CELL_SIZE)
        cell_y, y = divmod(y, CELL_SIZE)
        try:
            cell = self._cells[cell_x, cell_y]
        except KeyError:
            pass
        else:
            ind = y * CELL_SIZE + x
            if isinstance(cell, SingleCell):
                self._cells[cell_x, cell_y] = cell = cell.inflate()
                cell.count -= 1
                cell.array[ind] = _UNSET
            elif cell.array[ind] is not _UNSET:
                if cell.count == 1:
                    # Emptied completely, just discard.
                    del self._cells[cell_x, cell_y]
                else:
                    cell.count -= 1
                    cell.array[ind] = _UNSET

    def clear(self) -> None:
        """Remove all data from the plane."""
        self._min_x = self._min_y = self._max_x = self._max_y = 0
        self._cells.clear()

    def values(self) -> ValuesView[ValT]:
        """D.values() -> a set-like object providing a view on D's values"""
        return GridValues(self)

    def items(self) -> ItemsView[tuple[int, int], ValT]:
        """D.items() -> a set-like object providing a view on D's items"""
        return GridItems(self)

    def compact(self) -> None:
        """Look for cells with the same value, and consolidate them."""
        for pos, cell in list(self._cells.items()):
            if cell.count == 0:
                del self._cells[pos]
            elif isinstance(cell, Cell) and cell.count == CELL_SIZE_SQR:
                first = cell.array[0]
                if all(value == first for value in cell.array):
                    self._cells[pos] = SingleCell(first)

    def largest_index(self) -> tuple[int, int, ValT]:
        """Find a high index position, then return it plus the value."""
        # TODO: Replace with an iterator or something, this isn't very efficient to call repeatedly.
        try:
            cell_x, cell_y = pos = max(self._cells)
        except ValueError:
            raise KeyError('Empty grid!') from None
        cell = self._cells[pos]
        cell_x *= CELL_SIZE
        cell_y *= CELL_SIZE
        if isinstance(cell, SingleCell):
            return (cell_x + CELL_SIZE - 1, cell_y + CELL_SIZE - 1, cell.value)
        for (x, y), value in zip(reversed(CELL_COORDS), reversed(cell.array)):
            if value is not _UNSET:
                return (cell_x + x, cell_y + y, value)
        raise AssertionError(f'Cell {pos} is empty? {self._cells}')


# noinspection PyProtectedMember
class GridValues[ValT](ValuesView[ValT]):
    """Implementation of PlaneGrid.values()."""
    __slots__ = ()
    _mapping: PlaneGrid[ValT]  # Defined in superclass.

    def __contains__(self, item: object) -> bool:
        """Check if the provided item is a value."""
        for cell in self._mapping._cells.values():
            if isinstance(cell, SingleCell):
                if cell.value == item:
                    return True
            else:
                if item in cell.array:
                    return True
        return False

    def __iter__(self) -> Iterator[ValT]:
        """Produce all values in the plane."""
        for cell in self._mapping._cells.values():
            if isinstance(cell, SingleCell):
                for _ in range(CELL_SIZE_SQR):
                    yield cell.value
            else:
                for value in cell.array:
                    if value is not _UNSET:
                        yield value


# noinspection PyProtectedMember
class GridItems[ValT](ItemsView[tuple[int, int], ValT]):
    """Implementation of PlaneGrid.items()."""
    __slots__ = ()
    _mapping: PlaneGrid[ValT]  # Defined in superclass.

    def __contains__(self, item: object) -> bool:
        """Check if the provided pos/value pair is present."""
        if not isinstance(item, tuple):
            return False
        try:
            xy, value = item
            return bool(self._mapping[xy] == value)
        except ValueError:  # len(tup) != 3
            return False
        except KeyError:  # Not present
            return False

    def __iter__(self) -> Iterator[tuple[tuple[int, int], ValT]]:
        """Produce all coord, value pairs in the plane."""
        for (cell_x, cell_y), cell in self._mapping._cells.items():
            cell_x *= CELL_SIZE
            cell_y *= CELL_SIZE
            if isinstance(cell, SingleCell):
                for x, y in CELL_COORDS:
                    yield (cell_x + x, cell_y + y), cell.value
            else:
                for (x, y), value in zip(CELL_COORDS, cell.array):
                    if value is not _UNSET:
                        yield (cell_x + x, cell_y + y), value
