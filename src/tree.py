"""Wraps the Rtree package, adding typing and usage of our Vec class."""
from typing import Dict, Generic, Iterator, List, Tuple, TypeVar

from rtree import index
from srctools.math import Vec
import attrs


ValueT = TypeVar('ValueT')
PROPS = index.Property()
PROPS.dimension = 3


@attrs.frozen
class ValueHolder(Generic[ValueT]):
    """Holds the list of values."""
    values: List[ValueT]
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float


class RTree(Generic[ValueT]):
    """A 3-dimensional R-Tree. Multiple values with the same bbox are allowed."""
    tree: index.Index
    # id(holder) -> holder.
    # We can't store the object directly in the tree.
    _by_id: Dict[int, ValueHolder[ValueT]]
    _by_coord: Dict[
        Tuple[float, float, float, float, float, float],
        ValueHolder[ValueT]
    ]
    def __init__(self) -> None:
        self.tree = index.Index(properties=PROPS)
        self._by_id = {}
        self._by_coord = {}

    def __len__(self) -> int:
        return sum(len(holder.values) for holder in self._by_id.values())

    def __iter__(self) -> Iterator[Tuple[Vec, Vec, ValueT]]:
        """Iterating over the tree returns each bbox and value associated with it."""
        for holder in self._by_id.values():
            mins = Vec(holder.min_x, holder.min_y, holder.min_z)
            maxes = Vec(holder.max_x, holder.max_y, holder.max_z)
            for val in holder.values:
                yield mins.copy(), maxes.copy(), val

    def insert(self, p1: Vec, p2: Vec, value: ValueT) -> None:
        """Add the specified value occupying the specified region."""
        mins, maxs = Vec.bbox(p1, p2)
        coords = (mins.x, mins.y, mins.z, maxs.x, maxs.y, maxs.z)
        try:
            holder = self._by_coord[coords]
        except KeyError:
            # Make one.
            holder = ValueHolder([value], *coords)
            self._by_id[id(holder)] = self._by_coord[coords] = holder
            self.tree.insert(id(holder), coords)
        else:
            # Append if not already present.
            if value not in holder.values:
                holder.values.append(value)

    def remove(self, p1: Vec, p2: Vec, value: ValueT) -> None:
        """Remove the specified value from the tree."""
        mins, maxs = Vec.bbox(p1, p2)
        coords = (mins.x, mins.y, mins.z, maxs.x, maxs.y, maxs.z)
        try:
            holder = self._by_coord[coords]
            holder.values.remove(value)
        except LookupError:
            raise KeyError(mins, maxs, value) from None
        # Removed, check to see if the holder is empty, and we can discard.
        if not holder.values:
            del self._by_id[id(holder)]
            del self._by_coord[coords]
            self.tree.delete(id(holder), coords)

    def find_bbox(self, p1: Vec, p2: Vec) -> Iterator[ValueT]:
        """Find all values intersecting the given bounding box."""
        mins, maxs = Vec.bbox(p1, p2)
        for holder_id in self.tree.intersection((*mins, *maxs)):
            yield from self._by_id[holder_id].values

    def find_nearest(self, point: Vec, min_count: int = 1) -> Iterator[ValueT]:
        """Find the values nearest to a point.

        Return at least the specified number of points - if equidistant more
        may be returned to break the tie.
        """
        for holder_id in self.tree.nearest((point.x, point.y, point.z), min_count):
            yield from self._by_id[holder_id].values
