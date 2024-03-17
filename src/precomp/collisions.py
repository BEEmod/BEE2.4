"""Records the collisions for each item."""
from typing import Dict, List

import attrs
from srctools import Entity, Matrix, VMF, Vec
from srctools.vmf import EntityGroup

from collisions import *  # re-export.
from editoritems import Item
from tree import RTree


__all__ = ['CollideType', 'BBox', 'Volume', 'Collisions', 'Hit', 'trace_ray']


@attrs.define
class Collisions:
    """All the collisions for items in the map."""
    # Bounding box -> items with that bounding box.
    _by_bbox: RTree[BBox] = attrs.field(factory=RTree, repr=False, eq=False)
    # Item names -> bounding boxes of that item
    _by_name: Dict[str, List[BBox]] = attrs.Factory(dict)

    def add(self, bbox: BBox) -> None:
        """Add the given bounding box to the map."""
        if not bbox.name:
            raise ValueError(f'Collision {bbox!r} must have a name to be inserted!')
        self._by_bbox.insert(bbox.mins, bbox.maxes, bbox)
        lst = self._by_name.setdefault(bbox.name.casefold(), [])
        if bbox not in lst:
            lst.append(bbox)

    def remove_bbox(self, bbox: BBox) -> None:
        """Remove the given bounding box from the map."""
        if not bbox.name:
            raise ValueError(f'Collision {bbox!r} must have a name to be removed!')
        self._by_bbox.remove(bbox.mins, bbox.maxes, bbox)
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

    def dump(self, vmf: VMF, vis_name: str = 'Collisions') -> None:
        """Dump all the bounding boxes as a set of brushes."""
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
