"""Wraps the Rtree package, adding typing and usage of our Vec class."""
from srctools.math import Vec
from typing import Generic, TypeVar, Iterator

from rtree import index

ValueT = TypeVar('ValueT')
PROPS = index.Property()
PROPS.dimension = 3


class RTree(Generic[ValueT]):
    """A 3-dimensional R-Tree."""
    def __init__(self) -> None:
        self.tree = index.Index(properties=PROPS)
        self.data: dict[int, tuple[
            tuple[float, float, float,
                  float, float, float],
            ValueT,
        ]] = {}

    def __iter__(self) -> 'tuple[Vec, Vec, ValueT]':
        """Iterating over the tree returns each bbox and value associated with it."""
        for (min_x, min_y, min_z, max_x, max_y, max_z), val in self.data.values():
            yield Vec(min_x, min_y, min_z), Vec(max_x, max_y, max_z), val

    def insert(self, p1: Vec, p2: Vec, value: ValueT) -> None:
        """Add the specified value occupying the specified region."""
        key = id(value)
        try:
            old_coords, _ = self.data.pop(key)
        except KeyError:
            pass
        else:
            self.tree.delete(key, old_coords)
        mins, maxs = Vec.bbox(p1, p2)
        coords = (mins.x, mins.y, mins.z, maxs.x, maxs.y, maxs.z)
        self.data[key] = coords, value
        self.tree.insert(key, coords)

    def delete(self, value: ValueT) -> None:
        """Remove the specified value from the tree."""
        try:
            coords, _ = self.data.pop(id(value))
        except KeyError:
            raise KeyError(value) from None
        self.tree.delete(id(value), coords)

    def _get_val(self, ind: int) -> ValueT:
        return self.data[ind][1]

    def find_bbox(self, p1: Vec, p2: Vec) -> Iterator[ValueT]:
        """Find all values intersecting the given bounding box."""
        mins, maxs = Vec.bbox(p1, p2)
        dat = self.data
        return (
            dat[val_id][1] for val_id in
            self.tree.intersection((*mins, *maxs))
        )

    def find_nearest(self, point: Vec, min_count: int = 1) -> ValueT:
        """Find the values nearest to a point.

        Return at least the specified number of points - if equidistant more
        may be returned to break the tie.
        """
        dat = self.data
        return (
            dat[val_id][1] for val_id in
            self.tree.nearest((point.x, point.y, point.z), min_count)
        )
