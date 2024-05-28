"""Implements an adaptive 2D matrix for storing items at arbitrary coordinates efficiently.

"""
from __future__ import annotations
from collections.abc import Iterable, Iterator, Mapping, MutableMapping, ValuesView, ItemsView
from typing import Any, Final, overload
import copy

from srctools.math import AnyVec, FrozenMatrix, FrozenVec, Vec
import attrs


# Sentinel object for empty slots and parameter defaults.
_UNSET: Any = type('_UnsetType', (), {'__repr__': lambda s: 'UNSET'})()


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
        if not isinstance(dist, (int, float)):
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


class PlaneGrid[ValT](MutableMapping[tuple[int, int], ValT]):
    """An adaptive 2D matrix holding arbitary values.

    This is implemented with a list of lists, with an offset value for all.
    An (x, y) value is located at data[y - yoff][x - xoff[y - yoff]]
    """
    def __init__(
        self,
        contents: Mapping[tuple[int, int], ValT] | Iterable[tuple[tuple[int, int], ValT]] = (),
        *,
        default: ValT = _UNSET,
    ) -> None:
        """Initalises the plane with the provided values."""
        # Track the minimum/maximum position found
        self._min_x = self._min_y = self._max_x = self._max_y = 0
        self._yoff = 0
        self._xoffs: list[int] = []
        self._data: list[list[ValT] | None] = []
        self._used = 0
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
        return self._used

    def __repr__(self) -> str:
        return f'Plane({dict(self.items())!r})'

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
            res._xoffs = source._xoffs.copy()
            res._data = [
                None if row is None else [value] * len(row)
                for row in source._data
            ]
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
        cpy._xoffs = self._xoffs.copy()
        cpy._data = [
            None if row is None else row.copy()
            for row in self._data
        ]
        return cpy

    __copy__ = copy

    def __deepcopy__(self, memodict: dict[int, Any] | None = None) -> PlaneGrid[ValT]:
        """Deep-copy the plane."""
        cpy = PlaneGrid.__new__(PlaneGrid)
        cpy.__dict__.update(self.__dict__) # Immutables
        cpy._xoffs = self._xoffs.copy()
        cpy._data = copy.deepcopy(self._data, memodict)
        return cpy

    def __getitem__(self, pos: tuple[float, float]) -> ValT:
        """Return the value at a given position."""
        return self.get(pos, self.default)

    def __contains__(self, pos: tuple[float, float] | object) -> bool:
        """Check if a value is set at the given location."""
        try:
            x, y = map(int, pos)  # type: ignore
        except (ValueError, TypeError):
            return False

        y += self._yoff
        if y < 0:
            return False
        try:
            x += self._xoffs[y]
            if x < 0:
                return False
            return (row := self._data[y]) is not None and row[x] is not _UNSET
        except IndexError:
            return False

    @overload
    def get(self, __key: tuple[float, float]) -> ValT | None: ...
    @overload
    def get[DefaultT](self, __key: tuple[float, float], __default: ValT | DefaultT) -> ValT | DefaultT: ...

    def get[DefaultT](self, pos: tuple[float, float], default: DefaultT | None = None) -> DefaultT | ValT | None:
        """Return the value at a given position, or a default if not present."""
        try:
            x, y = map(int, pos)
        except (ValueError, TypeError):
            if default is _UNSET:  # For __getitem__ only.
                raise KeyError(pos) from None
            else:
                return default

        out: ValT = _UNSET
        y += self._yoff
        # Zero checks ensure we don't do negative indexing.
        if y >= 0:
            try:
                x += self._xoffs[y]
                if x >= 0 and (row := self._data[y]) is not None:
                    out = row[x]
            except IndexError:
                pass
        if out is _UNSET:
            if default is _UNSET:
                raise KeyError(pos)
            else:
                return default
        return out

    def __setitem__(self, pos: tuple[float, float], val: ValT) -> None:
        """Set the value at the given position, resizing if required."""
        try:
            x, y = map(int, pos)
        except (ValueError, TypeError):
            raise KeyError(pos) from None

        if not self._data:
            # The entire table is empty, we should move offsets and put this at index 0, 0.
            self._yoff = -y
            self._xoffs.append(-x)
            self._data.append([val])
            self._used += 1
            self._min_x = self._max_x = x
            self._min_y = self._max_y = y
            return

        if y < self._min_y:
            self._min_y = y
        if y > self._max_y:
            self._max_y = y
        if x < self._min_x:
            self._min_x = x
        if x > self._max_x:
            self._max_x = x

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
            self._xoffs += [0] * change
            self._data += [None] * change
            y_ind = -1  # y_bound - 1, but list can compute that.

        # Now x.
        data = self._data[y_ind]
        if data is None or not data:
            # This row is empty, so we can just move its offset to wherever we are and create
            # the list.
            self._data[y_ind] = [val]
            self._xoffs[y_ind] = -x
            self._used += 1
            return

        x_ind = x + self._xoffs[y_ind]
        x_bound = len(data)
        if x_ind < 0:
            change = -x_ind
            self._xoffs[y_ind] += change
            data[0:0] = [_UNSET] * change
            x_ind = 0
        elif x_ind >= x_bound:
            change = x_ind - x_bound + 1
            data += [_UNSET] * change
            x_ind = -1

        if data[x_ind] is _UNSET:
            self._used += 1

        data[x_ind] = val

    def __iter__(self) -> Iterator[tuple[int, int]]:
        """Return all used keys."""
        for y, (xoff, row) in enumerate(zip(self._xoffs, self._data), start=-self._yoff):
            if row is None:
                continue
            for x, data in enumerate(row, start=-xoff):
                if data is not _UNSET:
                    yield (x, y)

    def __delitem__(self, pos: tuple[float, float]) -> None:
        """Remove the value at a given position, doing nothing if not set."""
        try:
            x, y = map(int, pos)
        except (ValueError, TypeError):
            raise KeyError(pos) from None

        y += self._yoff
        if y < 0:
            return
        try:
            x += self._xoffs[y]
            if x < 0:
                return
            if (row := self._data[y]) is not None and row[x] is not _UNSET:
                self._used -= 1
                row[x] = _UNSET
        except IndexError:  # Already deleted.
            pass

    def clear(self) -> None:
        """Remove all data from the plane."""
        self._min_x = self._min_y = self._max_x = self._max_y = 0
        self._yoff = self._used = 0
        self._xoffs.clear()
        self._data.clear()

    def values(self) -> ValuesView[ValT]:
        """D.values() -> a set-like object providing a view on D's values"""
        return GridValues(self)

    def items(self) -> ItemsView[tuple[int, int], ValT]:
        """D.items() -> a set-like object providing a view on D's items"""
        return GridItems(self)


# noinspection PyProtectedMember
class GridValues[ValT](ValuesView[ValT]):
    """Implementation of PlaneGrid.values()."""
    __slots__ = ()
    _mapping: PlaneGrid[ValT]  # Defined in superclass.

    def __contains__(self, item: object) -> bool:
        """Check if the provided item is a value."""
        for row in self._mapping._data:
            if row is None:
                continue
            if item in row:
                return True
        return False

    def __iter__(self) -> Iterator[ValT]:
        """Produce all values in the plane."""
        for row in self._mapping._data:
            if row is None:
                continue
            for value in row:
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
        for y, (xoff, row) in enumerate(
            zip(self._mapping._xoffs, self._mapping._data),
            start=-self._mapping._yoff,
        ):
            if row is None:
                continue
            for x, data in enumerate(row, start=-xoff):
                if data is not _UNSET:
                    yield (x, y), data
