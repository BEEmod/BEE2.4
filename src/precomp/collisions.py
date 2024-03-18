"""Records the collisions for each item."""
from collections import defaultdict
from io import StringIO
from typing import Dict, List, Optional

import attrs
from srctools import Entity, Matrix, VMF, Vec
from srctools.math import format_float
from srctools.vmf import EntityGroup

from collisions import *  # re-export.
from editoritems import Item
from tree import RTree


__all__ = ['CollideType', 'BBox', 'Volume', 'Collisions', 'Hit', 'trace_ray']


@attrs.define
class Collisions:
    """All the collisions for items in the map."""
    # type -> bounding box -> items with that bounding box.
    _by_bbox: Dict[CollideType, RTree[BBox]] = attrs.field(factory=lambda: defaultdict(RTree), repr=False, eq=False)
    # Item names -> bounding boxes of that item
    _by_name: Dict[str, List[BBox]] = attrs.Factory(dict)

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

    def collisions_for_item(self, name: str) -> List[BBox]:
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
            for mins, maxs, volume in tree:
                ent = vmf.create_ent(
                    'bee2_vscript_collision',
                    origin=(volume.mins + volume.maxes) / 2,
                    mins=volume.mins,
                    maxs=volume.maxes,
                    contents=coll_type.value,
                )
                if isinstance(volume, Volume):
                    for i, plane in enumerate(volume.planes, 1):
                        ent[f'plane_{i:02}'] = f'{plane.normal} {format_float(plane.distance)}'
