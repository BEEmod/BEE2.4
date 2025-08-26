"""Records the collisions for each item."""
from collections import defaultdict
from collections.abc import Iterator

import attrs
from srctools import Entity, Matrix, VMF, Vec
from srctools.math import format_float
from srctools.vmf import EntityGroup

from collisions import CollideType, BBox, Hit, Volume, trace_ray  # re-export
from editoritems import Item
from tree import RTree


__all__ = ['CollideType', 'BBox', 'Volume', 'Collisions', 'Hit', 'trace_ray']


@attrs.define(eq=False)
class Collisions:
    """All the collisions for items in the map."""
    # type -> bounding box -> items with that bounding box.
    _by_bbox: dict[CollideType, RTree[BBox]] = attrs.field(factory=lambda: defaultdict(RTree), repr=False)
    # Item names -> bounding boxes of that item
    _by_name: dict[str, list[BBox]] = attrs.field(factory=dict, repr=False)

    # Indicates flags which VScript code has requested be exposed.
    vscript_flags: CollideType = CollideType.NOTHING

    def add(self, bbox: BBox) -> None:
        """Add the given bounding box to the map."""
        if not bbox.name:
            raise ValueError(f'Collision {bbox!r} must have a name to be inserted!')
        self._by_bbox[bbox.contents].insert(bbox.mins, bbox.maxes, bbox)
        lst = self._by_name.setdefault(bbox.name.casefold(), [])
        if bbox not in lst:
            lst.append(bbox)

    def remove_bbox(self, bbox: BBox) -> None:
        """Remove the given bounding box from the map."""
        if not bbox.name:
            raise ValueError(f'Collision {bbox!r} must have a name to be removed!')
        self._by_bbox[bbox.contents].remove(bbox.mins, bbox.maxes, bbox)
        try:
            self._by_name[bbox.name.casefold()].remove(bbox)
        except LookupError:
            # already not present.
            pass

    def iter_inside(
        self,
        mins: Vec, maxs: Vec,
        mask: CollideType = CollideType.EVERYTHING,
    ) -> Iterator[BBox]:
        """Iterate over bounding boxes which match the specified mask."""
        for coll_type, tree in self._by_bbox.items():
            if coll_type & mask is CollideType.NOTHING:
                continue
            yield from tree.find_bbox(mins, maxs)

    def trace_ray(
        self,
        start: Vec, delta: Vec,
        mask: CollideType = CollideType.EVERYTHING,
    ) -> Hit | None:
        """Trace a ray against all matching volumes."""
        mins, maxs = Vec.bbox(start, start + delta)
        return trace_ray(start, delta, self.iter_inside(mins - 1.0, maxs + 1.0, mask))

    def collisions_for_item(self, name: str) -> list[BBox]:
        """Fetch the bounding boxes for this item."""
        try:
            return self._by_name[name.casefold()].copy()
        except KeyError:
            return []

    def add_item_coll(self, item: Item, inst: Entity) -> None:
        """Add the default collisions from an item definition for this instance."""
        origin = Vec.from_str(inst['origin'])
        orient = Matrix.from_angstr(inst['angles'])
        for coll in item.collisions:
            self.add((coll @ orient + origin).with_attrs(name=inst['targetname']))

    def export_debug(self, vmf: VMF, vis_name: str) -> None:
        """After compilation, export all collisions for debugging purposes."""
        visgroup = vmf.create_visgroup(vis_name)
        for name, bb_list in self._by_name.items():
            group = EntityGroup(vmf, shown=False)
            for bbox in bb_list:
                ent = bbox.as_ent(vmf)
                vmf.add_ent(ent)
                ent['item_id'] = name
                ent.visgroup_ids.add(visgroup.id)
                ent.groups.add(group.id)
                ent.vis_shown = False
                ent.hidden = True

    def export_vscript(self, vmf: VMF) -> None:
        """After compilation, export a subset of collisions to VScript files.

        This allows traces to be performed at runtime.
        """
        if self.vscript_flags is CollideType.NOTHING:
            return
        vmf.spawn['bee2_vscript_coll_mask'] = self.vscript_flags.value

        for coll_type, tree in self._by_bbox.items():
            if coll_type & self.vscript_flags is CollideType.NOTHING:
                continue
            if CollideType.SOLID in coll_type:
                continue  # This would produce an excessive amount of data.
            for mins, maxs, volume in tree:
                center = (volume.mins + volume.maxes) / 2
                ent = vmf.create_ent(
                    'bee2_vscript_collision',
                    origin=center,
                    mins=volume.mins - center,
                    maxs=volume.maxes - center,
                    contents=coll_type.value,
                )
                if isinstance(volume, Volume):
                    for i, poly in enumerate(volume.geo.polys, 1):
                        ent[f'plane_{i:02}'] = f'{poly.plane.normal} {format_float(poly.plane.dist)}'
