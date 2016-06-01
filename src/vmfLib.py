""" VMF Library
Wraps property_parser tree in a set of classes which smartly handle
specifics of VMF files.
"""
import io
import itertools
import operator
from collections import defaultdict, namedtuple
from contextlib import suppress

from typing import (
    Optional, Union,
    Dict, List, Tuple, Set, Iterable, Iterator
)

from srctools import Property, Vec
import srctools
import utils

# Used to set the defaults for versioninfo
CURRENT_HAMMER_VERSION = 400
CURRENT_HAMMER_BUILD = 5304

# all the rows that displacements have, in the form
# "row0" "???"
# "row1" "???"
# etc
_DISP_ROWS = (
    'normals',
    'distances',
    'offsets',
    'offset_normals',
    'alphas',
    'triangle_tags',
)

# Return value for VMF.make_prism()
PrismFace = namedtuple(
    "PrismFace",
    "solid, top, bottom, north, south, east, west"
)

# The character used to separate output values.
OUTPUT_SEP = chr(27)

class IDMan(set):
    """Allocate and manage a set of unique IDs."""
    __slots__ = ()

    def get_id(self, desired=-1):
        """Get a valid ID."""

        if desired == -1:
            # Start with the lowest ID, and look upwards
            desired = 1

        if desired not in self:
            # The desired ID is avalible!
            self.add(desired)
            return desired

        # Check every ID in order to find a valid one
        for poss_id in itertools.count(start=1):
            if poss_id not in self:
                self.add(poss_id)
                return poss_id


def find_empty_id(used_id, desired=-1):
        """Ensure this item has a unique ID.

        Used by entities, solids and brush sides to keep their IDs valid.
        used_id must be sorted, and will be kept sorted.
        """

        if desired == -1:
            desired = 1
        else:
            desired = int(desired)
        used_id.sort()
        if len(used_id) == 0 or desired not in used_id:
            used_id.append(desired)
            return desired
        for poss_id in range(used_id[-1]+1):
            if poss_id not in used_id:
                used_id.append(poss_id)
                return poss_id


def overlay_bounds(over):
    """Compute the bounding box of an overlay."""
    origin = Vec.from_str(over['origin'])
    return Vec.bbox(
        (origin + Vec.from_str(over['uv' + str(x)]))
        for x in
        range(4)
    )


def make_overlay(
        vmf: 'VMF',
        normal: Vec,
        origin: Vec,
        uax: Vec,
        vax: Vec,
        material: str,
        surfaces: Iterable['Side'],
        u_repeat=1,
        v_repeat=1,
        swap=False,
        render_order=0
        ) -> 'Entity':
    """Generate an overlay on an axis-aligned surface.

    - origin is the center point of the overlay.
    - uax is the direction and distance for the texture's width ('right').
    - vax is the direction and distance for the texture's height ('up').
    - normal is the normal of the surfaces (axis-aligned).
    - material is the material used.
    - u_ and v_repeat define how many times to repeat the texture in that
      direction.
    - If swap is true, the texture will be rotated 90.
    """
    if swap:
        uax, vax = vax, uax

    u_dist = uax.mag()/2
    v_dist = vax.mag()/2
    basis_u = uax.norm()
    basis_v = vax.norm()

    if normal.x < 0 or normal.y < 0:
        basis_v *= -1
    if normal.z < 0:
        basis_u *= -1

    return vmf.create_ent(
        classname='info_overlay',
        angles='0 0 0',  # Not actually used by VBSP!
        origin=origin.join(' '),

        basisNormal=normal.join(' '),
        basisOrigin=origin.join(' '),
        basisU=basis_u.join(' '),
        basisV=basis_v.join(' '),

        material=material,
        sides=' '.join(str(side.id) for side in surfaces),

        startU='0',
        startV='0',
        endU=str(u_repeat),
        endV=str(v_repeat),

        uv0='-{} -{} 0'.format(u_dist, v_dist),
        uv1='-{} {} 0'.format(u_dist, v_dist),
        uv2='{} {} 0'.format(u_dist, v_dist),
        uv3='{} -{} 0'.format(u_dist, v_dist),
    )


def localise_overlay(over, origin, angles=None):
    """Rotate an overlay like what is done in instances."""
    if angles is not None:
        for key in ('basisNormal', 'basisU', 'basisV'):
            ang = Vec.from_str(over[key]).rotate(angles.x, angles.y, angles.z)
            over[key] = ang.join(' ')
    else:
        angles = Vec(0, 0, 0)

    for key in ('basisOrigin', 'origin'):
        ang = Vec.from_str(over[key]).rotate(angles.x, angles.y, angles.z)
        ang += origin
        over[key] = ang.join(' ')


class CopySet(set):
    """Modified version of a Set which allows modification during iteration.

    """
    __slots__ = []  # No extra vars

    def __iter__(self):
        cur_items = set(self)

        yield from cur_items
        # after iterating through ourselves, iterate through any new ents.
        yield from (self - cur_items)


class VMF:
    """Represents a VMF file, and holds counters for various IDs used.

    Has functions for searching for specific entities or brushes, and
    converts to/from a property_parser tree.

    The dictionaries by_target and by_class allow quickly getting a set
    of entities with the given class or targetname.
    """
    def __init__(
            self,
            map_info=utils.EmptyMapping,
            spawn=None,
            entities=None,
            brushes=None,
            cameras=None,
            cordons=None,
            visgroups=None):
        self.solid_id = IDMan()  # All occupied solid ids
        self.face_id = IDMan()  # Ditto for faces
        self.ent_id = IDMan()  # Same for entities
        self.group_id = IDMan()  # Group IDs (not visgroups)

        # Allow quick searching for particular groups, without checking
        # the whole map
        self.by_target = defaultdict(CopySet)  # type: Dict[str, Set[Entity]]
        self.by_class = defaultdict(CopySet)  # type: Dict[str, Set[Entity]]

        self.entities = []  # type: List[Entity]
        self.add_ents(entities or [])  # We need to set the by_ dicts too.
        self.brushes = brushes or []  # type: List[Solid]
        self.cameras = cameras or []  # type: List[Camera]
        self.cordons = cordons or []  # type: List[Cordon]
        self.visgroups = visgroups or []

        # mapspawn entity, which is the entity world brushes are saved
        # to.
        self.spawn = spawn or Entity(self)
        self.spawn.solids = self.brushes
        self.spawn.hidden_brushes = self.brushes

        self.is_prefab = srctools.conv_bool(map_info.get('prefab'), False)
        self.cordon_enabled = srctools.conv_bool(map_info.get('cordons_on'), False)
        self.map_ver = srctools.conv_int(map_info.get('mapversion'))
        if 'mapversion' in self.spawn:
            # This is saved only in the main VMF object, delete the copy.
            del self.spawn['mapversion']

        # These three are mostly useless for us, but we'll preserve them anyway
        self.format_ver = srctools.conv_int(
            map_info.get('formatversion'), 100)
        self.hammer_ver = srctools.conv_int(
            map_info.get('editorversion'), CURRENT_HAMMER_VERSION)
        self.hammer_build = srctools.conv_int(
            map_info.get('editorbuild'), CURRENT_HAMMER_BUILD)

        # Various Hammer settings
        self.show_grid = srctools.conv_bool(
            map_info.get('showgrid'), True)
        self.show_3d_grid = srctools.conv_bool(
            map_info.get('show3dgrid'), False)
        self.snap_grid = srctools.conv_bool(
            map_info.get('snaptogrid'), True)
        self.show_logic_grid = srctools.conv_bool(
            map_info.get('showlogicalgrid'), False)
        self.grid_spacing = srctools.conv_int(
            map_info.get('gridspacing'), 64)
        self.active_cam = srctools.conv_int(
            map_info.get('active_cam'), -1)
        self.quickhide_count = srctools.conv_int(
            map_info.get('quickhide'), -1)

    def add_brush(self, item):
        """Add a world brush to this map."""
        self.brushes.append(item)

    def remove_brush(self, item):
        """Remove a world brush from this map."""
        self.brushes.remove(item)

    def add_ent(self, item):
        """Add an entity to the map.

        The entity should have been created with this VMF as a parent.
        """
        self.entities.append(item)
        self.by_class[item['classname', None]].add(item)
        self.by_target[item['targetname', None]].add(item)

    def remove_ent(self, item):
        """Remove an entity from the map.

        After this is called, the entity will no longer be exported.
        The object still exists, so it can be reused.
        """
        self.entities.remove(item)
        self.by_class[item['classname', None]].remove(item)
        self.by_target[item['targetname', None]].remove(item)

        if item.id in self.ent_id:
            self.ent_id.remove(item.id)

    def add_brushes(self, item):
        for i in item:
            self.add_brush(i)

    def add_ents(self, item):
        for i in item:
            self.add_ent(i)

    def create_ent(self, **kargs) -> 'Entity':
        """Quick method to allow creating point entities.

        This constructs an entity, adds it to the map, and then returns
        it.
        """
        ent = Entity(self, keys=kargs)
        self.add_ent(ent)
        return ent

    @staticmethod
    def parse(tree: Union[Property, str]):
        """Convert a property_parser tree into VMF classes.
        """
        if not isinstance(tree, Property):
            # if not a tree, try to read the file
            with open(tree) as file:
                tree = Property.parse(file)

        map_info = {}
        ver_info = tree.find_key('versioninfo', [])
        for key in ('editorversion',
                    'mapversion',
                    'editorbuild',
                    'prefab'):
            map_info[key] = ver_info[key, '']

        map_info['formatversion'] = ver_info['formatversion', '100']
        if map_info['formatversion'] != '100':
            # If the version is different, we're probably about to fail horribly
            raise Exception(
                'Unknown VMF format version " ' +
                map_info['formatversion'] + '"!'
                )

        view_opt = tree.find_key('viewsettings', [])
        view_dict = {
            'bSnapToGrid': 'snaptogrid',
            'bShowGrid': 'showgrid',
            'bShow3DGrid': 'show3dgrid',
            'bShowLogicalGrid': 'showlogicalgrid',
            'nGridSpacing': 'gridspacing'
            }
        for key in view_dict:
            map_info[view_dict[key]] = view_opt[key, '']

        cordons = tree.find_key('cordons', [])
        map_info['cordons_on'] = cordons['active', '0']

        cam_props = tree.find_key('cameras', [])
        map_info['active_cam'] = srctools.conv_int(
            (cam_props['activecamera', '']), -1)
        map_info['quickhide'] = tree.find_key('quickhide', [])['count', '']

        map_obj = VMF(map_info=map_info)

        for c in cam_props:
            if c.name != 'activecamera':
                Camera.parse(map_obj, c)

        for ent in cordons.find_all('cordon'):
            Cordon.parse(map_obj, ent)

        for ent in tree.find_all('Entity'):
            map_obj.add_ent(
                Entity.parse(map_obj, ent, hidden=False)
            )

        # find hidden entities
        for hidden_ent in tree.find_all('hidden'):
            for ent in hidden_ent:
                map_obj.add_ent(
                    Entity.parse(map_obj, ent, hidden=True)
                )

        map_spawn = tree.find_key('world', [])
        if map_spawn is None:
            # Generate a fake default to parse through
            map_spawn = Property("world", [])
        map_obj.spawn = Entity.parse(map_obj, map_spawn)

        if map_obj.spawn.solids is not None:
            map_obj.brushes = map_obj.spawn.solids

        return map_obj
    pass

    def export(self, dest_file=None, inc_version=True, minimal=False):
        """Serialises the object's contents into a VMF file.

        - If no file is given the map will be returned as a string.
        - By default, this will increment the map's version - set
          inc_version to False to suppress this.
        - If minimal is True, several blocks will be skipped
          (Viewsettings, cameras, cordons and visgroups)
        """
        if dest_file is None:
            dest_file = io.StringIO()
            # acts like a file object but is actually a string. We're
            # using this to prevent having Python duplicate the entire
            # string every time we append
            ret_string = True
        else:
            ret_string = False

        if inc_version:
            # Increment this to indicate the map was modified
            self.map_ver += 1

        dest_file.write('versioninfo\n{\n')
        dest_file.write('\t"editorversion" "' + str(self.hammer_ver) + '"\n')
        dest_file.write('\t"editorbuild" "' + str(self.hammer_build) + '"\n')
        dest_file.write('\t"mapversion" "' + str(self.map_ver) + '"\n')
        dest_file.write('\t"formatversion" "' + str(self.format_ver) + '"\n')
        dest_file.write('\t"prefab" "' +
                        srctools.bool_as_int(self.is_prefab) + '"\n}\n')

        # TODO: Visgroups

        if not minimal:
            dest_file.write('viewsettings\n{\n')
            dest_file.write('\t"bSnapToGrid" "' +
                            srctools.bool_as_int(self.snap_grid) + '"\n')
            dest_file.write('\t"bShowGrid" "' +
                            srctools.bool_as_int(self.show_grid) + '"\n')
            dest_file.write('\t"bShowLogicalGrid" "' +
                            srctools.bool_as_int(self.show_logic_grid) + '"\n')
            dest_file.write('\t"nGridSpacing" "' +
                            str(self.grid_spacing) + '"\n')
            dest_file.write('\t"bShow3DGrid" "' +
                            srctools.bool_as_int(self.show_3d_grid) + '"\n}\n')

        self.spawn['mapversion'] = str(self.map_ver)
        self.spawn.export(dest_file, ent_name='world')
        del self.spawn['mapversion']

        for ent in self.entities:
            ent.export(dest_file)

        if not minimal:
            dest_file.write('cameras\n{\n')
            if len(self.cameras) == 0:
                self.active_cam = -1
            dest_file.write('\t"activecamera" "' + str(self.active_cam) + '"\n')
            for cam in self.cameras:
                cam.export(dest_file, '\t')
            dest_file.write('}\n')

            dest_file.write('cordons\n{\n')
            if len(self.cordons) > 0:
                dest_file.write('\t"active" "' +
                                srctools.bool_as_int(self.cordon_enabled) +
                                '"\n')
                for cord in self.cordons:
                    cord.export(dest_file, '\t')
            else:
                dest_file.write('\t"active" "0"\n')
            dest_file.write('}\n')

        if self.quickhide_count > 0:
            dest_file.write('quickhide\n{\n')
            dest_file.write('\t"count" "' + str(self.quickhide_count) + '"\n')
            dest_file.write('}\n')

        if ret_string:
            string = dest_file.getvalue()
            dest_file.close()
            return string

    def iter_wbrushes(self, world=True, detail=True) -> Iterator['Solid']:
        """Iterate through all world and detail solids in the map."""
        if world:
            yield from self.brushes
        if detail:
            for ent in self.iter_ents(classname='func_detail'):
                yield from ent.solids

    def iter_wfaces(self, world=True, detail=True) -> Iterator['Side']:
        """Iterate through the faces of world and detail solids."""
        for brush in self.iter_wbrushes(world, detail):
            yield from brush

    def iter_ents(self, **cond):
        """Iterate through entities having the given keyvalue values."""
        items = cond.items()
        for ent in self.entities[:]:
            for key, value in items:
                if key not in ent or ent[key] != value:
                    break
            else:
                yield ent

    def iter_ents_tags(self, vals=utils.EmptyMapping, tags=utils.EmptyMapping):
        """Iterate through all entities.

        The returned entities must have exactly the given keyvalue values,
        and have keyvalues containing the tags.
        """
        for ent in self.entities[:]:
            for key, value in vals.items():
                if key not in ent or ent[key] != value:
                    break
            else:  # passed through without breaks
                for key, value in tags.items():
                    if key not in ent or value not in ent[key]:
                        break
                else:
                    yield ent

    def iter_inputs(self, name):
        """Loop through all Outputs which target the named entity.

        - Allows using * at beginning/end
        """
        wild_start = name[:1] == '*'
        wild_end = name[-1:] == '*'
        if wild_start:
            name = name[1:]
        if wild_end:
            name = name[:-1]
        for ent in self.entities:
            for out in ent.outputs:
                if wild_start:
                    if wild_end:
                        if name in out.target:  # blah-target-blah
                            yield out
                    else:
                        if out.target.endswith(name):  # target-blah
                            yield out
                else:
                    if wild_end:
                        if out.target.startswith(name):  # blah-target
                            yield out
                    else:
                        if out.target == name:  # target
                            yield out

    def make_prism(self, p1, p2, mat='tools/toolsnodraw') -> PrismFace:
        """Create an axis-aligned brush connecting the two points.

        A PrismFaces tuple will be returned which containes the six
        faces, as well as the solid.
        All faces will be textured with 'mat'.
        """
        b_min = Vec(p1)
        b_max = Vec(p1)
        b_min.min(p2)
        b_max.max(p2)

        f_bottom = Side(
            self,
            planes=[  # -z side
                (b_min.x, b_min.y, b_min.z),
                (b_max.x, b_min.y, b_min.z),
                (b_max.x, b_max.y, b_min.z),
            ],
            mat=mat,
            uaxis=UVAxis(1, 0, 0),
            vaxis=UVAxis(0, -1, 0),
        )

        f_top = Side(
            self,
            planes=[  # +z side
                (b_min.x, b_max.y, b_max.z),
                (b_max.x, b_max.y, b_max.z),
                (b_max.x, b_min.y, b_max.z),
            ],
            mat=mat,
            uaxis=UVAxis(1, 0, 0),
            vaxis=UVAxis(0, -1, 0),
        )

        f_west = Side(
            self,
            planes=[  # -x side
                (b_min.x, b_max.y, b_max.z),
                (b_min.x, b_min.y, b_max.z),
                (b_min.x, b_min.y, b_min.z),
            ],
            mat=mat,
            uaxis=UVAxis(0, 1, 0),
            vaxis=UVAxis(0, 0, -1),
        )

        f_east = Side(
            self,
            planes=[  # +x side
                (b_max.x, b_max.y, b_min.z),
                (b_max.x, b_min.y, b_min.z),
                (b_max.x, b_min.y, b_max.z),
            ],
            mat=mat,
            uaxis=UVAxis(0, 1, 0),
            vaxis=UVAxis(0, 0, -1),
        )

        f_south = Side(
            self,
            planes=[  # -y side
                (b_max.x, b_min.y, b_min.z),
                (b_min.x, b_min.y, b_min.z),
                (b_min.x, b_min.y, b_max.z),
            ],
            mat=mat,
            uaxis=UVAxis(1, 0, 0),
            vaxis=UVAxis(0, 0, -1),
        )

        f_north = Side(
            self,
            planes=[  # +y side
                (b_min.x, b_max.y, b_min.z),
                (b_max.x, b_max.y, b_min.z),
                (b_max.x, b_max.y, b_max.z),
            ],
            mat=mat,
            uaxis=UVAxis(1, 0, 0),
            vaxis=UVAxis(0, 0, -1),
        )

        solid = Solid(
            self,
            sides=[
                f_bottom,
                f_top,
                f_north,
                f_south,
                f_east,
                f_west,
            ],
        )
        return PrismFace(
            solid=solid,
            top=f_top,
            bottom=f_bottom,
            north=f_north,
            south=f_south,
            east=f_east,
            west=f_west,
        )

    def make_hollow(
            self,
            p1, p2,
            thick=16,
            mat='tools/toolsnodraw',
            ) -> List['Solid']:
        """Create 6 brushes to surround the given region."""
        b_min, b_max = Vec.bbox(p1, p2)

        top = self.make_prism(
            Vec(b_min.x, b_min.y, b_max.z),
            Vec(b_max.x, b_max.y, b_max.z + thick),
            mat,
        ).solid

        bottom = self.make_prism(
            Vec(b_min.x, b_min.y, b_min.z),
            Vec(b_max.x, b_max.y, b_min.z - thick),
            mat,
        ).solid

        west = self.make_prism(
            Vec(b_min.x - thick, b_min.y, b_min.z),
            Vec(b_min.x, b_max.y, b_max.z),
            mat,
        ).solid

        east = self.make_prism(
            Vec(b_max.x, b_min.y, b_min.z),
            Vec(b_max.x + thick, b_max.y, b_max.z),
            mat
        ).solid

        north = self.make_prism(
            Vec(b_min.x, b_max.y, b_min.z),
            Vec(b_max.x, b_max.y + thick, b_max.z),
            mat,
        ).solid

        south = self.make_prism(
            Vec(b_min.x, b_min.y - thick, b_min.z),
            Vec(b_max.x, b_min.y, b_max.z),
            mat,
        ).solid

        return [north, south, east, west, top, bottom]


class Camera:
    def __init__(self, vmf_file, pos, targ):
        self.pos = pos
        self.target = targ
        self.map = vmf_file
        vmf_file.cameras.append(self)

    def targ_ent(self, ent):
        """Point the camera at an entity."""
        if ent['origin']:
            self.target = Vec.from_str(ent['origin'])

    def is_active(self):
        """Is this camera in use?"""
        return self.map.active_cam == self.map.cameras.index(self) + 1

    def set_active(self):
        """Set this to be the map's active camera"""
        self.map.active_cam = self.map.cameras.index(self) + 1

    def set_inactive_all(self):
        """Disable all cameras in this map."""
        self.map.active_cam = -1

    @staticmethod
    def parse(vmf_file, tree):
        """Read a camera from a property_parser tree."""
        pos = Vec.from_str(tree.find_key('position', '_').value)
        targ = Vec.from_str(tree.find_key('look', '_').value, y=64)
        return Camera(vmf_file, pos, targ)

    def copy(self):
        """Duplicate this camera object."""
        return Camera(self.map, self.pos.copy(), self.target.copy())

    def remove(self):
        """Delete this camera from the map."""
        self.map.cameras.remove(self)
        if self.is_active():
            self.set_inactive_all()

    def export(self, buffer, ind=''):
        buffer.write(ind + 'camera\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"position" "[' + self.pos.join(' ') + ']"\n')
        buffer.write(ind + '\t"look" "[' + self.target.join(' ') + ']"\n')
        buffer.write(ind + '}\n')


class Cordon:
    """Represents one cordon volume."""
    def __init__(
            self,
            vmf_file: VMF,
            min_: Vec,
            max_: Vec,
            is_active=True,
            name='Cordon',
            ):
        self.map = vmf_file
        self.name = name
        self.bounds_min = min_
        self.bounds_max = max_
        self.active = is_active
        vmf_file.cordons.append(self)

    @staticmethod
    def parse(vmf_file, tree):
        name = tree['name', 'cordon']
        is_active = srctools.conv_bool(tree['active', '0'], False)
        bounds = tree.find_key('box', [])
        min_ = Vec.from_str(bounds['mins', '(0 0 0)'])
        max_ = Vec.from_str(bounds['maxs', '(128 128 128)'], 128, 128, 128)
        return Cordon(vmf_file, min_, max_, is_active, name)

    def export(self, buffer, ind=''):
        buffer.write(ind + 'cordon\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"name" "' + self.name + '"\n')
        buffer.write(ind + '\t"active" "' +
                     srctools.bool_as_int(self.active) +
                     '"\n')
        buffer.write(ind + '\tbox\n')
        buffer.write(ind + '\t{\n')
        buffer.write(ind + '\t\t"mins" "(' +
                     self.bounds_min.join(' ') +
                     ')"\n')
        buffer.write(ind + '\t\t"maxs" "(' +
                     self.bounds_max.join(' ') +
                     ')"\n')
        buffer.write(ind + '\t}\n')
        buffer.write(ind + '}\n')

    def copy(self):
        """Duplicate this cordon."""
        return Cordon(
            self.map,
            self.bounds_min.copy(),
            self.bounds_max.copy(),
            self.active,
            self.name,
        )

    def remove(self):
        """Remove this cordon from the map."""
        self.map.cordons.remove(self)


class Solid:
    """A single brush, serving as both world brushes and brush entities."""
    def __init__(
            self,
            vmf_file: VMF,
            des_id=-1,
            sides=None,
            editor=None,
            hidden=False,
            ):
        self.map = vmf_file
        self.sides = sides or []  # type: List[Side]
        self.id = vmf_file.solid_id.get_id(des_id)
        self.editor = editor or {}
        self.hidden = hidden

    def copy(self, des_id=-1, map=None, side_mapping=utils.EmptyMapping):
        """Duplicate this brush."""
        editor = {}
        for key in ('color', 'groupid', 'visgroupshown', 'visgroupautoshown'):
            if key in self.editor:
                editor[key] = self.editor[key]
        if 'visgroup' in self.editor:
            editor['visgroup'] = self.editor['visgroup'][:]
        sides = [
            s.copy(map=map, side_mapping=side_mapping)
            for s in
            self.sides
        ]
        return Solid(
            map or self.map,
            des_id=des_id,
            sides=sides,
            editor=editor,
            hidden=self.hidden,
        )

    @staticmethod
    def parse(vmf_file, tree, hidden=False):
        """Parse a Property tree into a Solid object."""
        solid_id = srctools.conv_int(tree["id", '-1'], -1)
        sides = []
        for side in tree.find_all("side"):
            sides.append(Side.parse(vmf_file, side))

        editor = {}
        for v in tree.find_key("editor", []):
            if v.name in ('visgroupshown', 'visgroupautoshown', 'cordonsolid'):
                editor[v.name] = srctools.conv_bool(v.value, default=True)
            elif v.name == 'color' and ' ' in v.value:
                editor['color'] = v.value
            elif v.name == 'group':
                editor[v.name] = srctools.conv_int(v.value, default=-1)
                if editor[v.name] == -1:
                    del editor[v.name]
            elif v.name == 'visgroupid':
                val = srctools.conv_int(v.value, default=-1)
                if val:
                    editor.setdefault('visgroup', []).append(val)
        return Solid(
            vmf_file,
            des_id=solid_id,
            sides=sides,
            editor=editor,
            hidden=hidden,
        )

    def export(self, buffer, ind=''):
        """Generate the strings needed to define this brush."""
        if self.hidden:
            buffer.write(ind + 'hidden\n' + ind + '{\n')
            ind += '\t'
        buffer.write(ind + 'solid\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        for s in self.sides:
            s.export(buffer, ind + '\t')

        buffer.write(ind + '\teditor\n')
        buffer.write(ind + '\t{\n')
        if 'color' in self.editor:
            buffer.write(
                ind + '\t\t"color" "' +
                self.editor['color'] + '"\n')
        if 'groupid' in self.editor:
            buffer.write(ind + '\t\t"groupid" "' +
                         self.editor['groupid'] + '"\n')
        for vis_id in self.editor.get('visgroup', []):
            buffer.write(ind + '\t\t"groupid" "' + str(vis_id) + '"\n')
        for key in ('visgroupshown', 'visgroupautoshown', 'cordonsolid'):
            if key in self.editor:
                buffer.write(
                    ind + '\t\t"' + key + '" "' +
                    srctools.bool_as_int(self.editor[key]) +
                    '"\n'
                    )
        buffer.write(ind + '\t}\n')

        buffer.write(ind + '}\n')
        if self.hidden:
            buffer.write(ind[:-1] + '}\n')

    def __str__(self):
        """Return a user-friendly description of our data."""
        st = "<solid:" + str(self.id) + ">\n{\n"
        for s in self.sides:
            st += str(s) + "\n"
        st += "}"
        return st

    def __iter__(self):
        for s in self.sides:
            yield s

    def __del__(self):
        """Forget this solid's ID when the object is destroyed."""
        if self.id in self.map.solid_id:
            self.map.solid_id.remove(self.id)

    def get_bbox(self) -> Tuple[Vec, Vec]:
        """Get two vectors representing the space this brush takes up."""
        bbox_min, bbox_max = self.sides[0].get_bbox()
        for s in self.sides[1:]:
            side_min, side_max = s.get_bbox()
            bbox_max.max(side_max)
            bbox_min.min(side_min)
        return bbox_min, bbox_max

    def get_origin(self, bbox_min: Vec=None, bbox_max: Vec=None) -> Vec:
        """Calculates a vector representing the exact center of this brush."""
        if bbox_min is None or bbox_max is None:
            bbox_min, bbox_max = self.get_bbox()
        return (bbox_min + bbox_max) / 2

    def translate(self, diff: Vec):
        """Move this solid by the specified vector."""
        for s in self.sides:
            s.translate(diff)

    def localise(self, origin: Vec, angles: Vec=None):
        """Shift this brush by the given origin/angles."""
        for s in self.sides:
            s.localise(origin, angles)


class UVAxis:
    """Values saved into Side.uaxis and Side.vaxis.

    These define the alignment of textures on a face.
    """
    __slots__ = [
        'x', 'y', 'z',
        'scale',
        'offset',
    ]

    def __init__(self, x, y, z, offset=0.0, scale=0.25):
        self.x = x  # type: float
        self.y = y  # type: float
        self.z = z  # type: float
        self.offset = offset
        self.scale = scale

    @staticmethod
    def parse(value):
        vals = value.split()
        return UVAxis(
            x=float(vals[0].lstrip('[')),
            y=float(vals[1]),
            z=float(vals[2]),
            offset=float(vals[3].rstrip(']')),
            scale=float(vals[4]),
        )

    def copy(self):
        return UVAxis(
            x=self.x,
            y=self.y,
            z=self.z,
            offset=self.offset,
            scale=self.scale,
        )

    def __str__(self):
        """Generate the text form for this UV data."""
        return '[{x:g} {y:g} {z:g} {off:g}] {scale:g}'.format(
            x=self.x,
            y=self.y,
            z=self.z,
            off=self.offset,
            scale=self.scale,
        )

    def __repr__(self):
        rep = '{cls}({x:g}, {y:g}, {z:g}'.format(
            cls=self.__class__.__name__,
            x=self.x,
            y=self.y,
            z=self.z,
        )
        if self.offset != 0:
            rep += ', offset={:g}'.format(self.offset)
        if self.scale != 0.25:
            rep += ', scale={:g}'.format(self.scale)
        return rep + ')'


class Side:
    """A brush face."""
    __slots__ = [
        'map',
        'planes',
        'id',
        'lightmap',
        'smooth',
        'mat',
        'ham_rot',
        'uaxis',
        'vaxis',
        'disp_power',
        'disp_pos',
        'disp_flags',
        'disp_elev',
        'disp_is_subdiv',
        'disp_allowed_verts',
        'disp_data',
        'is_disp',
    ]

    def __init__(
            self,
            vmf_file,
            planes=(
                (0, 0, 0),
                (0, 0, 0),
                (0, 0, 0)
            ),
            des_id=-1,
            lightmap=16,
            smoothing=0,
            mat='tools/toolsnodraw',
            rotation=0,
            uaxis=None,
            vaxis=None,
            disp_data: dict=None,
            ):
        """
        :type planes: list of [(int, int, int)]
        """
        self.map = vmf_file
        self.planes = [Vec(), Vec(), Vec()]
        self.id = vmf_file.face_id.get_id(des_id)
        for i, pln in enumerate(planes):
            self.planes[i] = Vec(x=pln[0], y=pln[1], z=pln[2])
        self.lightmap = lightmap
        self.smooth = smoothing
        self.mat = mat
        self.ham_rot = rotation
        self.uaxis = uaxis or UVAxis(0, 1, 0)
        self.vaxis = vaxis or UVAxis(0, 0, -1)
        if disp_data is not None:
            self.disp_power = srctools.conv_int(
                disp_data.get('power', '_'), 4)
            self.disp_pos = Vec.from_str(
                disp_data.get('pos', '_'))
            self.disp_flags = srctools.conv_int(
                disp_data.get('flags', '_'))
            self.disp_elev = srctools.conv_float(
                disp_data.get('elevation', '_'))
            self.disp_is_subdiv = srctools.conv_bool(
                disp_data.get('subdiv', '_'), False)
            self.disp_allowed_verts = disp_data.get('allowed_verts', {})
            self.disp_data = {}
            for v in _DISP_ROWS:
                self.disp_data[v] = disp_data.get(v, [])
            self.is_disp = True
        else:
            self.is_disp = False

    @staticmethod
    def parse(vmf_file, tree):
        """Parse the property tree into a Side object."""
        # planes = "(x1 y1 z1) (x2 y2 z2) (x3 y3 z3)"
        verts = tree["plane", "(0 0 0) (0 0 0) (0 0 0)"][1:-1].split(") (")
        side_id = srctools.conv_int(tree["id", '-1'])
        planes = [0, 0, 0]
        for i, v in enumerate(verts):
            if i > 3:
                raise ValueError('Wrong number of solid planes in "' +
                                 tree['plane', ''] +
                                 '"')
            verts = v.split(" ")
            if len(verts) == 3:
                planes[i] = [float(v) for v in verts]
            else:
                raise ValueError('Invalid planes in "' +
                                 tree['plane', ''] +
                                 '"!')

        disp_tree = tree.find_key('dispinfo', [])
        if len(disp_tree) > 0:
            disp_data = {
                'power': disp_tree['power', '4'],
                'pos': disp_tree['startposition', '4'],
                'flags': disp_tree['flags', '0'],
                'elevation': disp_tree['elevation', '0'],
                'subdiv': disp_tree['subdiv', '0'],
                'allowed_verts': {},
            }
            for prop in disp_tree.find_key('allowed_verts', []):
                disp_data['allowed_verts'][prop.name] = prop.value
            for v in _DISP_ROWS:
                rows = disp_tree[v, []]
                if len(rows) > 0:
                    rows.sort(key=lambda x: srctools.conv_int(x.name[3:]))
                    disp_data[v] = [v.value for v in rows]
        else:
            disp_data = None

        return Side(
            vmf_file,
            planes=planes,
            des_id=side_id,
            disp_data=disp_data,
            mat=tree['material', ''],
            uaxis=UVAxis.parse(tree['uaxis', '[0 1 0 0] 0.25']),
            vaxis=UVAxis.parse(tree['vaxis', '[0 0 -1 0] 0.25']),
            rotation=srctools.conv_int(
                tree['rotation', '0']),
            lightmap=srctools.conv_int(
                tree['lightmapscale', '16'], 16),
            smoothing=srctools.conv_int(
                tree['smoothing_groups', '0']),
        )

    def copy(self, des_id=-1, map=None, side_mapping=utils.EmptyMapping):
        """Duplicate this brush side.

        des_id is the id which is desired for the new side.
        map is the VMF to add the new side to (defaults to the same map).
        If passed, side_mapping will be updated with a old -> new ID pair.
        """
        planes = [p.as_tuple() for p in self.planes]
        if self.is_disp:
            disp_data = self.disp_data.copy()
            disp_data['power'] = self.disp_power
            disp_data['flags'] = self.disp_flags
            disp_data['elevation'] = self.disp_elev
            disp_data['subdiv'] = self.disp_is_subdiv
            disp_data['allowed_verts'] = self.disp_allowed_verts
        else:
            disp_data = None

        if map is not None and des_id == -1:
            des_id = self.id

        copy = Side(
            map or self.map,
            planes=planes,
            des_id=des_id,
            mat=self.mat,
            rotation=self.ham_rot,
            uaxis=self.uaxis.copy(),
            vaxis=self.vaxis.copy(),
            smoothing=self.smooth,
            lightmap=self.lightmap,
            disp_data=disp_data,
        )
        side_mapping[str(self.id)] = str(copy.id)
        return copy

    def export(self, buffer, ind=''):
        """Generate the strings required to define this side in a VMF."""
        buffer.write(ind + 'side\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        pl_str = ('(' + p.join(' ') + ')' for p in self.planes)
        buffer.write(ind + '\t"plane" "' + ' '.join(pl_str) + '"\n')
        buffer.write(ind + '\t"material" "' + self.mat + '"\n')
        buffer.write(ind + '\t"uaxis" "' + str(self.uaxis) + '"\n')
        buffer.write(ind + '\t"vaxis" "' + str(self.vaxis) + '"\n')
        buffer.write(ind + '\t"rotation" "' + str(self.ham_rot) + '"\n')
        buffer.write(ind + '\t"lightmapscale" "' + str(self.lightmap) + '"\n')
        buffer.write(ind + '\t"smoothing_groups" "' + str(self.smooth) + '"\n')
        if self.is_disp:
            buffer.write(ind + '\tdispinfo\n')
            buffer.write(ind + '\t{\n')

            buffer.write(ind + '\t\t"power" "' + str(self.disp_power) + '"\n')
            buffer.write(ind + '\t\t"startposition" "[' +
                         self.disp_pos.join(' ') +
                         ']"\n')
            buffer.write(ind + '\t\t"flags" "' + str(self.disp_flags) +
                         '"\n')
            buffer.write(ind + '\t\t"elevation" "' + str(self.disp_elev) +
                         '"\n')
            buffer.write(ind + '\t\t"subdiv" "' +
                         srctools.bool_as_int(self.disp_is_subdiv) +
                         '"\n')
            for v in _DISP_ROWS:
                if len(self.disp_data[v]) > 0:
                    buffer.write(ind + '\t\t' + v + '\n')
                    buffer.write(ind + '\t\t{\n')
                    for i, data in enumerate(self.disp_data[v]):
                        buffer.write(ind + '\t\t\t"row' + str(i) +
                                     '" "' + data +
                                     '"\n')
                    buffer.write(ind + '\t\t}\n')
            if len(self.disp_allowed_verts) > 0:
                buffer.write(ind + '\t\tallowed_verts\n')
                buffer.write(ind + '\t\t{\n')
                for k, v in self.disp_allowed_verts.items():
                    buffer.write(ind + '\t\t\t"' + k + '" "' + v + '"\n')
                buffer.write(ind + '\t\t}\n')
            buffer.write(ind + '\t}\n')
        buffer.write(ind + '}\n')

    def __str__(self):
        """Dump a user-friendly representation of the side."""
        st = "\tmat = " + self.mat
        st += "\n\trotation = " + str(self.ham_rot) + '\n'
        pl_str = ['(' + p.join(' ') + ')' for p in self.planes]
        st += '\tplane: ' + ", ".join(pl_str) + '\n'
        return st

    def __del__(self):
        """Forget this side's ID when the object is destroyed."""
        if self.id in self.map.face_id:
            self.map.face_id.remove(self.id)

    def get_bbox(self) -> Tuple[Vec, Vec]:
        """Generate the highest and lowest points these planes form."""
        bbox_max = self.planes[0].copy()
        bbox_min = self.planes[0].copy()
        for v in self.planes[1:]:
            bbox_max.max(v)
            bbox_min.min(v)
        return bbox_min, bbox_max

    def get_origin(self) -> Vec:
        """Calculates a vector representing the exact center of this plane."""
        size_min, size_max = self.get_bbox()
        origin = (size_min + size_max) / 2
        return origin

    def translate(self, diff):
        """Move this side by the specified vector.

        - A tuple can be passed in instead if desired.
        """
        for p in self.planes:
            p += diff

        u_axis = Vec(self.uaxis.x, self.uaxis.y, self.uaxis.z)
        v_axis = Vec(self.vaxis.x, self.vaxis.y, self.vaxis.z)

        # Fix offset - see source-sdk: utils/vbsp/map.cpp line 2237
        self.uaxis.offset -= diff.dot(u_axis) / self.uaxis.scale
        self.vaxis.offset -= diff.dot(v_axis) / self.vaxis.scale

    def localise(self, origin: Vec, angles: Vec=None):
        """Shift the face by the given origin and angles.

        This preserves texture offsets
        """
        for p in self.planes:
            p.localise(origin, angles)
        # Rotate the uaxis values
        u_axis = Vec(self.uaxis.x, self.uaxis.y, self.uaxis.z)
        v_axis = Vec(self.vaxis.x, self.vaxis.y, self.vaxis.z)

        if angles is not None:
            u_axis.rotate(angles.x, angles.y, angles.z)
            v_axis.rotate(angles.x, angles.y, angles.z)

            self.uaxis.x, self.uaxis.y, self.uaxis.z = u_axis
            self.vaxis.x, self.vaxis.y, self.vaxis.z = v_axis

        # Fix offset - see source-sdk: utils/vbsp/map.cpp line 2237
        self.uaxis.offset -= origin.dot(u_axis) / self.uaxis.scale
        self.vaxis.offset -= origin.dot(v_axis) / self.vaxis.scale

        # Keep the values low. The highest texture size in P2 is 1024, so
        # do the next power just to be safe.
        # Add and subtract 1024 so the value is between -1024, 1024 not 0, 2048
        # (This just looks nicer)
        self.uaxis.offset = (self.uaxis.offset + 1024) % 2048 - 1024
        self.vaxis.offset = (self.vaxis.offset + 1024) % 2048 - 1024

    def plane_desc(self):
        """Return a string which describes this face.

         This is for use in texture randomisation.
         """
        return (
            self.planes[0].join(' ') +
            self.planes[1].join(' ') +
            self.planes[2].join(' ')
            )

    def normal(self) -> Vec:
        """Compute the unit vector which extends perpendicular to the face.

        """
        # The three points are in clockwise order, so we need the first and last
        # starting from the center point. Then calculate in reverse to get the
        # normal in the correct direction.
        point_1 = self.planes[0] - self.planes[1]
        point_2 = self.planes[2] - self.planes[1]

        return point_2.cross(point_1).norm()

    def scale(self, value):
        self.uaxis.scale = value
        self.vaxis.scale = value
    scale = property(fset=scale, doc='Set both scale attributes easily.')

    def offset(self, value):
        self.uaxis.offset = value
        self.vaxis.offset = value
    offset = property(fset=offset, doc='Set both offset attributes easily.')


class Entity:
    """A representation of either a point or brush entity.

    Creation:
    Entity(args) for a brand-new Entity
    Entity.parse(property) if reading from a VMF file
    ent.copy() to duplicate an existing entity

    Supports [] operations to read and write keyvalues.
    To read instance $replace values operate on entity.fixup[]
    """
    def __init__(
            self,
            vmf_file: VMF,
            keys=utils.EmptyMapping,
            fixup=(),
            ent_id=-1,
            outputs=None,
            solids=None,
            editor=None,
            hidden=False,
            groups=()):
        self.map = vmf_file
        self.keys = {
            # Ensure all values are strings. This allows passing ints and Vecs
            # normally.
            k: str(v)
            for k, v in
            keys.items()
        }
        self.fixup = EntityFixup(fixup)
        self.outputs = outputs or []  # type: List[Output]
        self.solids = solids or []  # type: List[Solid]
        self.id = vmf_file.ent_id.get_id(ent_id)
        self.hidden = hidden
        self.editor = editor or {'visgroup': []}
        self.groups = list(groups)

        if 'logicalpos' not in self.editor:
            self.editor['logicalpos'] = '[0 ' + str(self.id) + ']'
        if 'visgroupshown' not in self.editor:
            self.editor['visgroupshown'] = '1'
        if 'visgroupautoshown' not in self.editor:
            self.editor['visgroupautoshown'] = '1'
        if 'color' not in self.editor:
            self.editor['color'] = '255 255 255'

    def copy(self, des_id=-1, map=None, side_mapping=utils.EmptyMapping):
        """Duplicate this entity entirely, including solids and outputs."""
        new_keys = {}
        new_fixup = self.fixup.copy_values()
        new_editor = {}
        for key, value in self.keys.items():
            new_keys[key] = value

        for key, value in self.editor.items():
            if key != 'visgroup':
                new_editor[key] = value
        new_editor['visgroup'] = self.editor['visgroup'][:]

        new_solids = [
            solid.copy(map=map, side_mapping=side_mapping)
            for solid in
            self.solids
        ]
        outs = [o.copy() for o in self.outputs]

        new_groups = [group.copy() for group in self.groups]

        return Entity(
            vmf_file=map or self.map,
            keys=new_keys,
            fixup=new_fixup,
            ent_id=des_id,
            outputs=outs,
            solids=new_solids,
            editor=new_editor,
            hidden=self.hidden,
            groups=new_groups,
        )

    @staticmethod
    def parse(vmf_file, tree_list: Property, hidden=False):
        """Parse a property tree into an Entity object."""
        ent_id = -1
        solids = []
        keys = {}
        outputs = []
        editor = {'visgroup': []}
        fixup = []
        groups = []
        for item in tree_list:
            name = item.name
            if name == "id" and item.value.isnumeric():
                ent_id = int(item.value)
            elif name.startswith('replace'):
                index = item.name[-2:]  # Index is the last 2 digits
                try:
                    index = int(index)
                except TypeError:  # Not a replace value!
                    keys[name] = item.value
                else:
                    # Parse the $replace value
                    vals = item.value.split(" ", 1)
                    var = vals[0].lstrip('$')
                    value = vals[1]
                    fixup.append(FixupTuple(var, value, int(index)))
            elif name == "solid" and item.has_children():
                solids.append(Solid.parse(vmf_file, item))
            elif name == "connections" and item.has_children():
                for out in item:
                    outputs.append(Output.parse(out))
            elif name == "hidden" and item.has_children():
                    solids.extend(
                        Solid.parse(vmf_file, br, hidden=True)
                        for br in
                        item
                    )
            elif name == "group" and item.has_children():
                groups.append(EntityGroup.parse(vmf_file, item))
            elif name == "editor" and item.has_children():
                for v in item:
                    if v.name in ("visgroupshown", "visgroupautoshown"):
                        editor[v.name] = srctools.conv_bool(v.value, default=True)
                    elif v.name == 'color' and ' ' in v.value:
                        editor['color'] = v.value
                    elif (
                            v.name == 'logicalpos' and
                            v.value.startswith('[') and
                            v.value.endswith(']')
                            ):
                        editor['logicalpos'] = v.value
                    elif v.name == 'comments':
                        editor['comments'] = v.value
                    elif v.name == 'group':
                        editor[v.name] = srctools.conv_int(v.value, default=-1)
                        if editor[v.name] == -1:
                            del editor[v.name]
                    elif v.name == 'visgroupid':
                        val = srctools.conv_int(v.value, default=-1)
                        if val:
                            editor['visgroup'].append(val)
            else:
                keys[item.name] = item.value

        return Entity(
            vmf_file,
            keys,
            fixup,
            ent_id,
            outputs,
            solids,
            editor,
            hidden,
            groups,
        )

    def is_brush(self):
        """Is this Entity a brush entity?"""
        return len(self.solids) > 0

    def export(self, buffer, ent_name='entity', ind=''):
        """Generate the strings needed to create this entity.

        ent_name is the key used for the item's block, which is used to allow
        generating the MapSpawn data block from the entity object.
        """

        if self.hidden:
            buffer.write(ind + 'hidden\n' + ind + '{\n')
            ind += '\t'

        buffer.write(ind + ent_name + '\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        for key, value in sorted(self.keys.items(), key=operator.itemgetter(0)):
            buffer.write(
                ind +
                '\t"{}" "{!s}"\n'.format(key, value)
            )

        self.fixup.export(buffer, ind)

        if self.is_brush():
            for s in self.solids:
                s.export(buffer, ind=ind+'\t')
        if len(self.outputs) > 0:
            buffer.write(ind + '\tconnections\n')
            buffer.write(ind + '\t{\n')
            for o in self.outputs:
                o.export(buffer, ind=ind+'\t\t')
            buffer.write(ind + '\t}\n')

        buffer.write(ind + '\teditor\n')
        buffer.write(ind + '\t{\n')
        if 'color' in self.editor:
            buffer.write(
                ind +
                '\t\t"color" "' +
                self.editor['color'] +
                '"\n'
            )
        if 'groupid' in self.editor:
            buffer.write(
                ind +
                '\t\t"groupid" "' +
                self.editor['groupid'] +
                '"\n'
            )
        if 'visgroup' in self.editor:
            for vis_id in self.editor['visgroup']:
                buffer.write(ind + '\t\t"groupid" "' + str(vis_id) + '"\n')
        for key in ('visgroupshown', 'visgroupautoshown'):
            if key in self.editor:
                buffer.write(
                    ind + '\t\t"' + key + '" "' +
                    srctools.bool_as_int(self.editor[key]) + '"\n'
                )
        for key in ('logicalpos', 'comments'):
            if key in self.editor:
                buffer.write(
                    ind +
                    '\t\t"{}" "{}"\n'.format(key, self.editor[key])
                )
        buffer.write(ind + '\t}\n')

        buffer.write(ind + '}\n')
        if self.hidden:
            buffer.write(ind[:-1] + '}\n')

    def sides(self):
        """Iterate through all our brush sides."""
        if self.is_brush():
            for solid in self.solids:
                for face in solid:
                    yield face

    def add_out(self, *outputs):
        """Add the outputs to our list."""
        self.outputs.extend(outputs)

    def output_targets(self) -> Set[str]:
        """Return a set of the targetnames this entity triggers."""
        return {
            out.target
            for out in
            self.outputs
        }

    def remove(self):
        """Remove this entity from the map."""
        self.map.remove_ent(self)

    def make_unique(self):
        """Append our entity ID to the targetname, so it is uniquely-named.
        """
        self['targetname'] += str(self.id)
        return self

    def __str__(self):
        """Dump a user-friendly representation of the entity."""
        st = "<Entity>: \n{\n"
        for k, v in self.keys.items():
            if not isinstance(v, list):
                st += "\t " + k + ' = "' + v + '"\n'
        for out in self.outputs:
            st += '\t' + str(out) + '\n'
        st += "}\n"
        return st

    def __getitem__(self, key, default='') -> str:
        """Allow using [] syntax to search for keyvalues.

        - This will return '' if the value is not present.
        - It ignores case-matching, but will use the first given version
          of a key.
        - If used via Entity.get() the default argument is available.
        - A tuple can be passed for the default to be set, inside the
          [] syntax.
        """
        if isinstance(key, tuple):
            key, default = key
        key = key.casefold()
        for k in self.keys:
            if k.casefold() == key:
                return self.keys[k]
        else:
            return default

    def __setitem__(self, key, val):
        """Allow using [] syntax to save a keyvalue.

        - It is case-insensitive, so it will overwrite a key which only
          differs by case.
        """
        key_fold = key.casefold()
        for k in self.keys:
            if k.casefold() == key_fold:
                # Check case-insensitively for this key first
                orig_val = self.keys.get(k)
                self.keys[k] = str(val)
                break
        else:
            orig_val = self.keys.get(key)
            self.keys[key] = str(val)

        # Update the by_class/target dicts with our new value
        if key_fold == 'classname':
            with suppress(KeyError):
                self.map.by_class[orig_val].remove(self)
            self.map.by_class[val].add(self)
        elif key_fold == 'targetname':
            with suppress(KeyError):
                self.map.by_target[orig_val].remove(self)
            self.map.by_target[val].add(self)

    def __delitem__(self, key):
        key = key.casefold()
        if key == 'targetname':
            with suppress(KeyError):
                self.map.by_target[
                    self.keys.get('targetname', None)
                ].remove(self)
            self.map.by_target[None].add(self)

        if key == 'classname':
            with suppress(KeyError):
                self.map.by_class[
                    self.keys.get('classname', None)
                ].remove(self)
            self.map.by_class[None].add(self)

        for k in self.keys:
            if k.casefold() == key:
                del self.keys[k]
                break

    get = __getitem__

    def clear_keys(self):
        """Remove all keyvalues from an item."""
        # Delete these so the .by_class/name values are cleared.
        del self['targetname']
        del self['classname']
        self.keys.clear()
        # Clear $fixup as well.
        self.fixup.clear()

    def __contains__(self, key: str):
        """Determine if a value exists for the given key."""
        key = key.casefold()
        for k in self.keys:
            if k.casefold() == key:
                return True
        else:
            return False

    get_key = __contains__

    def __del__(self):
        """Forget this entity's ID when the object is destroyed."""
        if self.id in self.map.ent_id:
            self.map.ent_id.remove(self.id)

    def get_bbox(self) -> (Vec, Vec):
        """Get two vectors representing the space this entity takes up."""
        if self.is_brush():
            bbox_min, bbox_max = self.solids[0].get_bbox()
            for s in self.solids[1:]:
                side_min, side_max = s.get_bbox()
                bbox_max.max(side_max)
                bbox_min.min(side_min)
            return bbox_min, bbox_max
        else:
            origin = self.get_origin()
            # the bounding box is 0x0 large for a point ent basically
            return origin, origin.copy()

    def get_origin(self):
        """Return a vector representing the center of this entity's brushes."""
        if self.is_brush():
            bbox_min, bbox_max = self.get_bbox()
            return (bbox_min+bbox_max)/2
        else:
            return Vec(self['origin'].split(" "))

FixupTuple = namedtuple('FixupTuple', 'var value id')


class EntityFixup:
    """A speciallised mapping which keeps track of the variable indexes.

    This treats variable names case-insensitively, and optionally allows
    writing variables with $ signs in front.
    """
    __slots__ = ['_fixup']

    def __init__(self, fixup: Iterable[FixupTuple]=()):
        self._fixup = {}
        # In _fixup each variable is stored as a tuple of (var_name,
        # value, index) with keys equal to the casefolded var name.

        # Do a check to ensure all fixup values have valid indexes:
        used_indexes = set()
        extra_vals = []
        for fix in fixup:
            if fix.id not in used_indexes:
                used_indexes.add(fix.id)
                self._fixup[fix.var.casefold()] = fix
            else:
                extra_vals.append(fix)
        for fix in extra_vals:
            # Add these values wherever they'll fit.
            self[fix.var] = fix.value

    def get(self, var, default=''):
        """Get the value of an instance $replace variable.

        If not found, the default will be returned (an empty string).
        """
        if var[0] == '$':
            var = var[1:]
        folded_var = var.casefold()
        if folded_var in self._fixup:
            return self._fixup[folded_var].value
        else:
            return default

    def copy_values(self):
        """Generate a list that can be passed to the constructor."""
        return list(self._fixup.values())

    def clear(self):
        """Wipe all the $fixup values."""
        self._fixup.clear()

    def update(self, other):
        """Copy the keys of the other item to this one.

        Variable IDs are not preserved.
        """
        # Convert to dict - this handles EntityFixup + other mappings
        for key, value in dict(other).items():
            self[key] = value

    def __getitem__(self, key: Union[str, Tuple[str, str]]):
        """Retieve keys via fixup[key] or fixup[key, default].

        See EntityFixup.get().
        """
        if isinstance(key, tuple):
            return self.get(key[0], default=key[1])
        else:
            return self.get(key)

    def __contains__(self, var: str):
        """Check if a variable is present in the fixup list."""
        if var[0] == '$':
            var = var[1:]
        return var.casefold() in self._fixup

    def __setitem__(self, var, val):
        """Set the value of an instance $replace variable.

        """
        if var[0] == '$':
            var = var[1:]
        folded_var = var.casefold()
        if folded_var not in self._fixup:
            # Insert a new value. Use the lowest unused index.
            indexes = {
                fixup.id
                for fixup in
                self._fixup.values()
            }
            for ind in itertools.count(start=1):
                if ind not in indexes:
                    self._fixup[folded_var] = FixupTuple(var, val, ind)
                    break
        else:
            self._fixup[folded_var] = FixupTuple(
                var,
                val,
                self._fixup[folded_var].id,
            )

    def __delitem__(self, var):
        """Delete a instance $replace variable."""
        if var[0] == '$':
            var = var[1:]
        var = var.casefold()
        if var in self._fixup:
            del self._fixup[var]

    def keys(self):
        """Iterate over all set variable names."""
        for value in self._fixup.values():
            yield value.var

    __iter__ = keys

    def items(self):
        """Iterate over all variable-value pairs."""
        for value in self._fixup.values():
            yield value.var, value.value

    def values(self):
        for value in self._fixup.values():
            yield value.value

    def export(self, buffer, ind):
        """Export all the replace values into the VMF."""
        if len(self._fixup):
            for (key, value, index) in sorted(
                    self._fixup.values(), key=operator.attrgetter('id')):
                # When exporting, pad with zeros if needed
                buffer.write(ind + '\t"replace{:02}" "${} {}"\n'.format(
                    index, key, value))

    def __str__(self):
        items = '\n'.join(
            '\t${0.var} = {0.value!r}'.format(tup)
            for tup in
            sorted(self._fixup.values(), key=operator.attrgetter('id'))
        )
        return self.__class__.__name__ + '{\n' + items + '\n}'

    def __repr__(self):
        items = ', '.join(
            repr(tup)
            for tup in
            sorted(self._fixup.values(), key=operator.attrgetter('id'))
        )
        return self.__class__.__name__ + '([' + items + '])'


class EntityGroup:
    """Represents the 'group' blocks in entities.

    This allows the grouping of brushes.
    """
    def __init__(
            self,
            map: VMF,
            grp_id,
            vis_shown=False,
            vis_auto_shown=False,
            ):
        self.map = map
        self.id = map.group_id.get_id(grp_id)
        self.shown = vis_shown
        self.auto_shown = vis_auto_shown

    @classmethod
    def parse(cls, vmf_file, props):
        editor_block = props.find_key('editor', [])
        return cls(
            vmf_file,
            props['id'],
            vis_shown=srctools.conv_bool(
                editor_block['visgroupshown', None], True
            ),
            vis_auto_shown=srctools.conv_bool(
                editor_block['visgroupsautoshown', None], True
            ),
        )

    def copy(self, map=None):
        if map is None:
            map = self.map
        return EntityGroup(
            map,
            self.id,
            self.shown,
            self.auto_shown,
        )

    def export(self, buffer, ind):
        buffer.write(ind + 'group\n')
        buffer.write(ind + '\t{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        buffer.write(ind + '\teditor\n')
        buffer.write(ind + '\t\t{\n')
        buffer.write(ind + '\t\t"visgroupshown" "{}"'.format(
            srctools.bool_as_int(self.shown)
        ))
        buffer.write(ind + '\t\t"visgroupautoshown" "{}"'.format(
            srctools.bool_as_int(self.auto_shown)
        ))
        buffer.write(ind + '\t\t}\n')
        buffer.write(ind + '\t}')



class Output:
    """An output from one entity pointing to another.

    Attributes:
        output: The output which triggers this.
        target: The target entity.
        input: The input to fire.
        params: Parameters to give the input, or '' for none.
        delay: The number of seconds before the output should fire.

    Keyword only parameters:
        inst_out: The local entity for an instance output (instance:name;Output)
        inst_in: The local entity we are really triggering in instance inputs
            (instance:name;Input)
        comma_sep: Use a comma as a separator, instead of the OUTPUT_SEP
            character.
        times: The number of times to fire before being deleted.
            -1 means forever, Hammer only uses (-1, 1).
        only_once: Boolean alternative to 'times', setting -1/1 based on
            True/False.

    """
    __slots__ = [
        'output',
        'inst_out',
        'target',
        'input',
        'inst_in',
        'params',
        'delay',
        'times',
        'comma_sep',
    ]

    def __init__(
        self,
        out: str,
        targ: str,
        inp: str,
        param='',
        delay=0.0,
        *,
        times=-1,
        only_once=False,
        inst_out: str=None,
        inst_in: str=None,
        comma_sep=False
    ):
        self.output = out
        self.inst_out = inst_out
        self.target = targ
        self.input = inp
        self.inst_in = inst_in
        self.params = param
        self.delay = delay
        self.times = 1 if only_once else times
        self.comma_sep = comma_sep

    @property
    def only_once(self):
        """Check if the output is active only once."""
        return self.times == 1

    @only_once.setter
    def only_once(self, is_once):
        self.times = 1 if is_once else -1

    @staticmethod
    def parse(prop: Property):
        """Convert the VMF Property into an Output object."""
        if OUTPUT_SEP in prop.value:
            sep = False
            vals = prop.value.split(OUTPUT_SEP)
        else:
            sep = True
            vals = prop.value.split(',')

        try:
            targ, inp, param, delay, times = vals
        except ValueError as e:
            raise ValueError('Bad output value: "{}"'.format(prop.value)) from e

        inst_out, out = Output.parse_name(prop.real_name)
        inst_inp, inp = Output.parse_name(inp)

        return Output(
            out,
            targ,
            inp,
            param=param,
            delay=float(delay),
            times=int(times),
            inst_out=inst_out,
            inst_in=inst_inp,
            comma_sep=sep,
        )

    @staticmethod
    def parse_name(name: str) -> Tuple[Optional[str], str]:
        """Extranct the instance name from values of the form:

        'instance:local_name;Command'
        If not of this form, the
        """
        if name.casefold().startswith('instance:'):
            try:
                inst_part, command = name.split(';', 1)
            except ValueError as e:
                # Incorrectly-formatted instance: names will crash VBSP,
                # so abort now.
                raise Exception(
                    '"Instance:" in/output without command! ({})'.format(name)
                ).with_traceback(e.__traceback__)
            else:
                return inst_part[9:], command
        return None, name

    def exp_out(self):
        if self.inst_out:
            return 'instance:' + self.inst_out + ';' + self.output
        else:
            return self.output

    def exp_in(self):
        if self.inst_in:
            return 'instance:' + self.inst_in + ';' + self.input
        else:
            return self.input

    def __repr__(self):
        return (
            '{cls}({s.output}, {s.target}, {s.input}, {s.params!r}'
            '{s.delay!r}, {s.times!r}, {s.inst_out!r}, {s.inst_in!r},'
            ' {comma})'.format(
                s=self,
                cls=self.__class__.__name__,
                comma=self.comma_sep,
            )
        )

    def __str__(self):
        """Generate a user-friendly representation of this output."""
        st = "<Output> "
        if self.inst_out:
            st += self.inst_out + ":"
        st += self.output + " -> " + self.target
        if self.inst_in:
            st += "-" + self.inst_in
        st += " -> " + self.input

        if self.params and not self.inst_in:
            st += " (" + self.params + ")"
        if self.delay != 0:
            st += " after " + str(self.delay) + " seconds"
        if self.times != -1:
            st += " (once" if self.times == 1 else (
                " ({!s} times".format(self.times)
            )
            st += " only)"
        return st

    def export(self, buffer, ind=''):
        """Generate the text required to define this output in the VMF."""
        buffer.write(ind + '"' + self.exp_out())

        sep = ',' if self.comma_sep else OUTPUT_SEP

        buffer.write(
            '" "' +
            sep.join((
                self.target,
                self.exp_in(),
                self.params,
                # Strip the trailing 0 if it's really an integer.
                str(self.delay).replace('.0', ''),
                str(self.times),
            )) +
            '"\n'
        )

    def copy(self):
        """Duplicate this output object."""
        return Output(
            self.output,
            self.target,
            self.input,
            self.params,
            self.delay,
            times=self.times,
            inst_out=self.inst_out,
            inst_in=self.inst_in,
            comma_sep=self.comma_sep,
        )

if __name__ == '__main__':
    # Test the VMF parser by duplicating a test file
    print('parsing...')
    map_file = VMF.parse('test.vmf')

    print('saving...')

    with open('test_out.vmf', 'w') as test_file:
        map_file.export(test_file)
    print('done!')