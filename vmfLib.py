""" VMF Library
Wraps property_parser tree in a set of classes which smartly handle
specifics of VMF files.
"""
import io
from collections import defaultdict
from contextlib import suppress

from property_parser import Property
from utils import Vec
import utils

# Used to set the defaults for versioninfo
CURRENT_HAMMER_VERSION = 400
CURRENT_HAMMER_BUILD = 5304

# $replace01, $replace02, ..., $replace15, $replace16
_FIXUP_KEYS = (
    ["replace0" + str(i) for i in range(1, 10)] +
    ["replace" + str(i) for i in range(10, 17)]
)

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


def find_empty_id(used_id, desired=-1):
        """Ensure this item has a unique ID.

        Used by entities, solids and brush sides to keep their IDs valid.
        used_id must be sorted, and will be kept sorted.
        """
        # Add_sorted adds the items while keeping the list sorted, so we never
        # have to actually sort the list.

        if desired == -1:
            desired = 1
        else:
            desired = int(desired)

        if len(used_id) == 0 or desired not in used_id:
            utils.add_sorted(used_id, desired)
            return desired
        for poss_id in range(used_id[-1]+1):
            if poss_id not in used_id:
                utils.add_sorted(used_id, poss_id)
                return poss_id


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
        self.solid_id = []  # All occupied solid ids
        self.face_id = []  # Ditto for faces
        self.ent_id = []  # Same for entities

        # Allow quick searching for particular groups, without checking
        # the whole map
        self.by_target = defaultdict(CopySet)
        self.by_class = defaultdict(CopySet)

        self.entities = []
        self.add_ents(entities or [])  # need to set the by_ dicts too.
        self.brushes = brushes or []
        self.cameras = cameras or []
        self.cordons = cordons or []
        self.visgroups = visgroups or []

        # mapspawn entity, which is the entity world brushes are saved
        # to.
        self.spawn = spawn or Entity(self, [])
        self.spawn.solids = self.brushes
        self.spawn.hidden_brushes = self.brushes

        self.is_prefab = utils.conv_bool(map_info.get('prefab'), False)
        self.cordon_enabled = utils.conv_bool(map_info.get('cordons_on'), False)
        self.map_ver = utils.conv_int(map_info.get('mapversion'))
        if 'mapversion' in self.spawn:
            # This is saved only in the main VMF object, delete the copy.
            del self.spawn['mapversion']

        # These three are mostly useless for us, but we'll preserve them anyway
        self.format_ver = utils.conv_int(
            map_info.get('formatversion'), 100)
        self.hammer_ver = utils.conv_int(
            map_info.get('editorversion'), CURRENT_HAMMER_VERSION)
        self.hammer_build = utils.conv_int(
            map_info.get('editorbuild'), CURRENT_HAMMER_BUILD)

        # Various Hammer settings
        self.show_grid = utils.conv_bool(
            map_info.get('showgrid'), True)
        self.show_3d_grid = utils.conv_bool(
            map_info.get('show3dgrid'), False)
        self.snap_grid = utils.conv_bool(
            map_info.get('snaptogrid'), True)
        self.show_logic_grid = utils.conv_bool(
            map_info.get('showlogicalgrid'), False)
        self.grid_spacing = utils.conv_int(
            map_info.get('gridspacing'), 64)
        self.active_cam = utils.conv_int(
            map_info.get('active_cam'), -1)
        self.quickhide_count = utils.conv_int(
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

        After this is called, the entity will no longer by exported.
        The object still exists, so it can be reused.
        """
        self.entities.remove(item)
        self.by_class[item['classname', None]].remove(item)
        self.by_target[item['targetname', None]].remove(item)

    def add_brushes(self, item):
        for i in item:
            self.add_brush(i)

    def add_ents(self, item):
        for i in item:
            self.add_ent(i)

    def create_ent(self, **kargs):
        """Quick method to allow creating point entities.

        This constructs an entity, adds it to the map, and then returns
        it.
        """
        ent = Entity(self, keys=kargs)
        self.add_ent(ent)
        return ent

    @staticmethod
    def parse(tree):
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
        map_info['active_cam'] = utils.conv_int(
            (cam_props['activecamera', '']), -1)
        map_info['quickhide'] = tree.find_key('quickhide', [])['count', '']

        map_obj = VMF(map_info=map_info)

        for c in cam_props:
            if c.name != 'activecamera':
                Camera.parse(map_obj, c)

        for ent in cordons.find_all('cordon'):
            Cordon.parse(map_obj, ent)

        map_obj.add_ents(
            Entity.parse(map_obj, ent, hidden=False)
            for ent in
            tree.find_all('Entity')
        )
        # find hidden entities
        for hidden_ent in tree.find_all('hidden'):
            map_obj.add_ents(
                Entity.parse(map_obj, ent, hidden=True)
                for ent in
                hidden_ent
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

    def export(self, dest_file=None, inc_version=True):
        """Serialises the object's contents into a VMF file.

        - If no file is given the map will be returned as a string.
        - By default, this will increment the map's version - set
          inc_version to False to suppress this.
        """
        if dest_file is None:
            dest_file = io.stringIO()
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
                        utils.bool_as_int(self.is_prefab) + '"\n}\n')

        # TODO: Visgroups

        dest_file.write('viewsettings\n{\n')
        dest_file.write('\t"bSnapToGrid" "' +
                        utils.bool_as_int(self.snap_grid) + '"\n')
        dest_file.write('\t"bShowGrid" "' +
                        utils.bool_as_int(self.show_grid) + '"\n')
        dest_file.write('\t"bShowLogicalGrid" "' +
                        utils.bool_as_int(self.show_logic_grid) + '"\n')
        dest_file.write('\t"nGridSpacing" "' +
                        str(self.grid_spacing) + '"\n')
        dest_file.write('\t"bShow3DGrid" "' +
                        utils.bool_as_int(self.show_3d_grid) + '"\n}\n')

        self.spawn['mapversion'] = str(self.map_ver)
        self.spawn.export(dest_file, ent_name='world')
        del self.spawn['mapversion']

        for ent in self.entities:
            ent.export(dest_file)

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
                            utils.bool_as_int(self.cordon_enabled) +
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

    def get_face_id(self, desired=-1):
        """Get an unused face ID.
        """
        return find_empty_id(self.face_id, desired)

    def get_brush_id(self, desired=-1):
        """Get an unused solid ID.
        """
        return find_empty_id(self.solid_id, desired)

    def get_ent_id(self, desired=-1):
        """Get an unused entity ID.
        """
        return find_empty_id(self.ent_id, desired)

    def iter_wbrushes(self, world=True, detail=True):
        """Iterate through all world and detail solids in the map."""
        if world:
            for br in self.brushes:
                yield br
        if detail:
            for ent in self.iter_ents(classname='func_detail'):
                for solid in ent.solids:
                    yield solid

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
    def __init__(self, vmf_file, min_, max_, is_active=True, name='Cordon'):
        self.map = vmf_file
        self.name = name
        self.bounds_min = min_
        self.bounds_max = max_
        self.active = is_active
        vmf_file.cordons.append(self)

    @staticmethod
    def parse(vmf_file, tree):
        name = tree['name', 'cordon']
        is_active = utils.conv_bool(tree['active', '0'], False)
        bounds = tree.find_key('box', [])
        min_ = Vec.from_str(bounds['mins', '(0 0 0)'])
        max_ = Vec.from_str(bounds['maxs', '(128 128 128)'], 128, 128, 128)
        return Cordon(vmf_file, min_, max_, is_active, name)

    def export(self, buffer, ind=''):
        buffer.write(ind + 'cordon\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"name" "' + self.name + '"\n')
        buffer.write(ind + '\t"active" "' +
                     utils.bool_as_int(self.active) +
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
            vmf_file,
            des_id=-1,
            sides=None,
            editor=None,
            hidden=False,
            ):
        self.map = vmf_file
        self.sides = sides or []
        self.id = vmf_file.get_brush_id(des_id)
        self.editor = editor or {}
        self.hidden = hidden

    def copy(self, des_id=-1):
        """Duplicate this brush."""
        editor = {}
        for key in ('color', 'groupid', 'visgroupshown', 'visgroupautoshown'):
            if key in self.editor:
                editor[key] = self.editor[key]
        if 'visgroup' in self.editor:
            editor['visgroup'] = self.editor['visgroup'][:]
        sides = [s.copy() for s in self.sides]
        return Solid(
            self.map,
            des_id=des_id,
            sides=sides,
            editor=editor,
            hidden=self.hidden,
        )

    @staticmethod
    def parse(vmf_file, tree, hidden=False):
        """Parse a Property tree into a Solid object."""
        solid_id = utils.conv_int(tree["id", '-1'])
        try:
            solid_id = int(solid_id)
        except TypeError:
            solid_id = -1
        sides = []
        for side in tree.find_all("side"):
            sides.append(Side.parse(vmf_file, side))

        editor = {'visgroup': []}
        for v in tree.find_key("editor", []):
            if v.name in ('visgroupshown', 'visgroupautoshown', 'cordonsolid'):
                editor[v.name] = utils.conv_bool(v.value, default=True)
            elif v.name == 'color' and ' ' in v.value:
                editor['color'] = v.value
            elif v.name == 'group':
                editor[v.name] = utils.conv_int(v.value, default=-1)
                if editor[v.name] == -1:
                    del editor[v.name]
            elif v.name == 'visgroupid':
                val = utils.conv_int(v.value, default=-1)
                if val:
                    editor['visgroup'].append(val)
        if len(editor['visgroup']) == 0:
            del editor['visgroup']
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
        if 'visgroup' in self.editor:
            for vis_id in self.editor['visgroup']:
                buffer.write(ind + '\t\t"groupid" "' + str(vis_id) + '"\n')
        for key in ('visgroupshown', 'visgroupautoshown', 'cordonsolid'):
            if key in self.editor:
                buffer.write(
                    ind + '\t\t"' + key + '" "' +
                    utils.bool_as_int(self.editor[key]) +
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

    def get_bbox(self):
        """Get two vectors representing the space this brush takes up."""
        bbox_min, bbox_max = self.sides[0].get_bbox()
        for s in self.sides[1:]:
            side_min, side_max = s.get_bbox()
            bbox_max.max(side_max)
            bbox_min.min(side_min)
        return bbox_min, bbox_max

    def get_origin(self, bbox_min=None, bbox_max=None):
        """Calculates a vector representing the exact center of this brush."""
        if bbox_min is None or bbox_max is None:
            bbox_min, bbox_max = self.get_bbox()
        return (bbox_min+bbox_max)/2

    def translate(self, diff):
        """Move this solid by the specified vector.

        - This does not translate textures as well.
        - A tuple can be passed in instead if desired.
        """
        for s in self.sides:
            s.translate(diff)


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
            planes=[
                (0, 0, 0),
                (0, 0, 0),
                (0, 0, 0)
                ],
            opt=utils.EmptyMapping,
            des_id=-1,
            disp_data={},
            ):
        """
        :type planes: list of [(int, int, int)]
        """
        self.map = vmf_file
        self.planes = [Vec(), Vec(), Vec()]
        self.id = vmf_file.get_face_id(des_id)
        for i, pln in enumerate(planes):
            self.planes[i] = Vec(x=pln[0], y=pln[1], z=pln[2])
        self.lightmap = opt.get("lightmap", 16)
        self.smooth = opt.get("smoothing", 0)
        self.mat = opt.get("material", "")
        self.ham_rot = opt.get("rotation", 0)
        self.uaxis = opt.get("uaxis", "[0 1 0 0] 0.25")
        self.vaxis = opt.get("vaxis", "[0 1 -1 0] 0.25")
        if len(disp_data) > 0:
            self.disp_power = utils.conv_int(
                disp_data.get('power', '_'), 4)
            self.disp_pos = Vec.from_str(
                disp_data.get('pos', '_'))
            self.disp_flags = utils.conv_int(
                disp_data.get('flags', '_'))
            self.disp_elev = utils.conv_float(
                disp_data.get('elevation', '_'))
            self.disp_is_subdiv = utils.conv_bool(
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
        side_id = utils.conv_int(tree["id", '-1'])
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

        opt = {
            'material': tree['material', ''],
            'uaxis': tree['uaxis', '[0 1  0 0] 0.25'],
            'vaxis': tree['vaxis', '[0 0 -1 0] 0.25'],
            'rotation': utils.conv_int(
                tree['rotation', '0']),
            'lightmap': utils.conv_int(
                tree['lightmapscale', '16'], 16),
            'smoothing': utils.conv_int(
                tree['smoothing_groups', '0']),
            }
        disp_tree = tree.find_key('dispinfo', [])
        disp_data = {}
        if len(disp_tree) > 0:
            disp_data['power'] = disp_tree['power', '4']
            disp_data['pos'] = disp_tree['startposition', '4']
            disp_data['flags'] = disp_tree['flags', '0']
            disp_data['elevation'] = disp_tree['elevation', '0']
            disp_data['subdiv'] = disp_tree['subdiv', '0']
            disp_data['allowed_verts'] = {}
            for prop in disp_tree.find_key('allowed_verts', []):
                disp_data['allowed_verts'][prop.name] = prop.value
            for v in _DISP_ROWS:
                rows = disp_tree[v, []]
                if len(rows) > 0:
                    rows.sort(key=lambda x: utils.conv_int(x.name[3:]))
                    disp_data[v] = [v.value for v in rows]
        return Side(
            vmf_file,
            planes=planes,
            opt=opt,
            des_id=side_id,
            disp_data=disp_data,
        )

    def copy(self, des_id=-1):
        """Duplicate this brush side."""
        planes = [p.as_tuple() for p in self.planes]
        opt = {
            'material': self.mat,
            'rotation': self.ham_rot,
            'uaxis': self.uaxis,
            'vaxis': self.vaxis,
            'smoothing': self.smooth,
            'lightmap': self.lightmap,
            }
        return Side(self.map, planes=planes, opt=opt, des_id=des_id)

    def export(self, buffer, ind=''):
        """Generate the strings required to define this side in a VMF."""
        buffer.write(ind + 'side\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        pl_str = ['(' + p.join(' ') + ')' for p in self.planes]
        buffer.write(ind + '\t"plane" "' + ' '.join(pl_str) + '"\n')
        buffer.write(ind + '\t"material" "' + self.mat + '"\n')
        buffer.write(ind + '\t"uaxis" "' + self.uaxis + '"\n')
        buffer.write(ind + '\t"vaxis" "' + self.vaxis + '"\n')
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
                         utils.bool_as_int(self.disp_is_subdiv) +
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

    def get_bbox(self):
        """Generate the highest and lowest points these planes form."""
        bbox_max = self.planes[0].copy()
        bbox_min = self.planes[0].copy()
        for v in self.planes[1:]:
            bbox_max.max(v)
            bbox_min.min(v)
        return bbox_min, bbox_max

    def get_origin(self):
        """Calculates a vector representing the exact center of this plane."""
        size_min, size_max = self.get_bbox()
        origin = (size_min + size_max) / 2
        return origin

    def translate(self, diff):
        """Move this side by the specified vector.

        - This does not translate textures as well.
        - A tuple can be passed in instead if desired.
        """
        for p in self.planes:
            p += diff

    def plane_desc(self):
        """Return a string which describes this face.

         This is for use in texture randomisation.
         """
        return (
            self.planes[0].join(' ') +
            self.planes[1].join(' ') +
            self.planes[2].join(' ')
            )

    def normal(self):
        """Compute the unit vector which extends perpendicular to the face.

        """
        # The three points are in clockwise order, so we need the first and last
        # starting from the center point. Then calculate in reverse to get the
        # normal in the correct direction.
        point_1 = self.planes[0] - self.planes[1]
        point_2 = self.planes[2] - self.planes[1]

        return point_2.cross(point_1).norm()


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
            vmf_file,
            keys=None,
            fixup=None,
            ent_id=-1,
            outputs=None,
            solids=None,
            editor=None,
            hidden=False):
        self.map = vmf_file
        self.keys = keys or {}
        self.fixup = EntityFixup(fixup or {})
        self.outputs = outputs or []
        self.solids = solids or []
        self.id = vmf_file.get_ent_id(ent_id)
        self.hidden = hidden
        self.editor = editor or {'visgroup': []}

        if 'logicalpos' not in self.editor:
            self.editor['logicalpos'] = '[0 ' + str(self.id) + ']'
        if 'visgroupshown' not in self.editor:
            self.editor['visgroupshown'] = '1'
        if 'visgroupautoshown' not in self.editor:
            self.editor['visgroupautoshown'] = '1'
        if 'color' not in self.editor:
            self.editor['color'] = '255 255 255'

    def copy(self, des_id=-1):
        """Duplicate this entity entirely, including solids and outputs."""
        new_keys = {}
        new_fixup = self.fixup.copy_dict()
        new_editor = {}
        for key, value in self.keys.items():
            new_keys[key] = value

        for key, value in self.editor.items():
            if key != 'visgroup':
                new_editor[key] = value
        new_editor['visgroup'] = self.editor['visgroup'][:]

        new_solids = [s.copy() for s in self.solids]
        outs = [o.copy() for o in self.outputs]

        return Entity(
            vmf_file=self.map,
            keys=new_keys,
            fixup=new_fixup,
            ent_id=des_id,
            outputs=outs,
            solids=new_solids,
            editor=new_editor,
            hidden=self.hidden,
        )

    @staticmethod
    def parse(vmf_file, tree_list, hidden=False):
        """Parse a property tree into an Entity object."""
        ent_id = -1
        solids = []
        keys = {}
        outputs = []
        editor = {'visgroup': []}
        fixup = {}
        for item in tree_list:
            name = item.name
            if name == "id" and item.value.isnumeric():
                ent_id = item.value
            elif name in _FIXUP_KEYS:
                vals = item.value.split(" ", 1)
                var = vals[0][1:]  # Strip the $ sign
                value = vals[1]
                index = item.name[-2:]  # Index is the last 2 digits
                fixup[var.casefold()] = (var, value, index)
            elif name == "solid":
                if item.has_children():
                    solids.append(Solid.parse(vmf_file, item))
                else:
                    keys[item.name] = item.value
            elif name == "connections" and item.has_children():
                for out in item:
                    outputs.append(Output.parse(out))
            elif name == "hidden":
                if item.has_children():
                    solids.extend(
                        Solid.parse(vmf_file, br, hidden=True)
                        for br in
                        item
                    )
                else:
                    keys[item.name] = item.value
            elif name == "editor" and item.has_children():
                for v in item:
                    if v.name in ("visgroupshown", "visgroupautoshown"):
                        editor[v.name] = utils.conv_bool(v.value, default=True)
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
                        editor[v.name] = utils.conv_int(v.value, default=-1)
                        if editor[v.name] == -1:
                            del editor[v.name]
                    elif v.name == 'visgroupid':
                        val = utils.conv_int(v.value, default=-1)
                        if val:
                            editor['visgroup'].append(val)
            else:
                keys[item.name] = item.value

        return Entity(
            vmf_file,
            keys=keys,
            ent_id=ent_id,
            solids=solids,
            outputs=outputs,
            editor=editor,
            hidden=hidden,
            fixup=fixup)

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
        for key in sorted(self.keys.keys()):
            buffer.write(
                ind +
                '\t"{}" "{!s}"\n'.format(key, self.keys[key])
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
                    utils.bool_as_int(self.editor[key]) + '"\n'
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

    def add_out(self, output):
        """Add the output to our list."""
        self.outputs.append(output)

    def remove(self):
        """Remove this entity from the map."""
        self.map.entities.remove(self)
        if self.id in self.map.ent_id:
            self.map.ent_id.remove(self.id)

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

    def __getitem__(self, key, default=None):
        """Allow using [] syntax to search for keyvalues.

        - This will return None instead of KeyError if the value is not
          found.
        - It ignores case-matching, but will use the first given version
          of a key.
        - If used via Entity.get() the default argument is available.
        - A tuple can be passed for the default to be set, inside the
          [] syntax.
        """
        if isinstance(key, tuple):
            default = key[1]
            key = key[0]
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
        if isinstance(key, tuple):
            # Allow using += syntax with default
            key, default = key
        else:
            default = None
        key_fold = key.casefold()
        for k in self.keys:
            if k.casefold() == key_fold:
                # Check case-insensitively for this key first
                orig_val = self.keys.get(k, default)
                self.keys[k] = val
                break
        else:
            orig_val = self.keys.get(key, default)
            self.keys[key] = val

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
        for k in self.keys:
            if k.casefold() == key:
                del self.keys[k]
                break

    get = __getitem__

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


class EntityFixup:
    """A speciallised mapping which keeps track of the variable indexes.

    This also treats variable names case-insensitively, and strips $
    signs off the front of them.
    """

    def __init__(self, fixes=None):
        self._fixup = fixes or {}
        # In _fixup each variable is stored as a tuple of (var_name,
        # value, index) with keys equal to the casefolded var name.

    def get(self, var, default: str=None):
        """Get the value of an instance $replace variable."""
        if var[0] == '$':
            var = var[1:]
        folded_var = var.casefold()
        if folded_var in self._fixup:
            return self._fixup[folded_var][1]  # don't return the index
        else:
            return default

    def copy_dict(self):
        return self._fixup.copy()

    def __contains__(self, var: str):
        """Determine if this instance has the named $replace variable."""
        return var.casefold() in self._fixup

    def __getitem__(self, key):
        if isinstance(key, tuple):
            return self.get(key[0], default=key[1])
        else:
            return self.get(key)

    def __setitem__(self, var, val):
        """Set the value of an instance $replace variable.

        """
        if var[0] == '$':
            var = var[1:]
        folded_var = var.casefold()
        if folded_var not in self._fixup:
            max_id = 1
            for i in self._fixup.values():
                if int(i[1]) > max_id:
                    max_id = int(i[1])
            if max_id < 9:
                max_id = "0" + str(max_id)
            else:
                max_id = str(max_id)
            self._fixup[folded_var] = (var, val, max_id)
        else:
            self._fixup[folded_var] = (var, val, self._fixup[var][2])

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
            yield value[0]

    __iter__ = keys

    def items(self):
        """Iterate over all variable-value pairs."""
        for value in self._fixup.values():
            yield value[0], value[1]

    def values(self):
        for value in self._fixup.values():
            yield value[1]

    def export(self, buffer, ind):
        """Export all the replace values into the VMF."""
        if len(self._fixup) > 0:
            for (key, value, index) in sorted(
                    self._fixup.values(), key=lambda x: x[2]
                    ):
                # we end up with (key, val, index) and we want to sort
                # by the index
                buffer.write(ind + '\t"replace{}" "${} {}"\n'.format(
                    index, key, value))


class Output:
    """An output from one entity pointing to another."""
    __slots__ = [
        'output',
        'inst_out',
        'target',
        'input',
        'inst_in',
        'params',
        'delay',
        'times',
        'sep',
        ]

    def __init__(self,
                 out,
                 targ,
                 inp,
                 param='',
                 delay=0.0,
                 times=-1,
                 inst_out=None,
                 inst_in=None,
                 comma_sep=False):
        self.output = out
        self.inst_out = inst_out
        self.target = targ
        self.input = inp
        self.inst_in = inst_in
        self.params = param
        self.delay = delay
        self.times = times
        self.sep = ',' if comma_sep else chr(27)

    @staticmethod
    def parse(prop):
        """Convert the VMF Property into an Output object."""
        if chr(27) in prop.value:
            sep = False
            vals = prop.value.split(chr(27))
        else:
            sep = True
            vals = prop.value.split(',')
        if len(vals) == 5:
            if prop.name.startswith('instance:'):
                out = prop.name.split(';')
                inst_out = out[0][9:]
                out = out[1]
            else:
                inst_out = None
                out = prop.name

            if vals[1].startswith('instance:'):
                inp = vals[1].split(';')
                inst_inp = inp[0][9:]
                inp = inp[1]
            else:
                inst_inp = None
                inp = vals[1]
            return Output(
                out,
                vals[0],
                inp,
                param=vals[2],
                delay=float(vals[3]),
                times=int(vals[4]),
                inst_out=inst_out,
                inst_in=inst_inp,
                comma_sep=sep,
                )

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

        if self.inst_in:
            inp = 'instance:' + self.inst_in + ';' + self.input
        else:
            inp = self.input

        buffer.write(
            '" "' +
            self.sep.join((
                self.target,
                inp,
                self.params,
                str(self.delay),
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
            param=self.params,
            times=self.times,
            inst_out=self.inst_out,
            inst_in=self.inst_in,
            comma_sep=(self.sep == ','),
            )

if __name__ == '__main__':
    # Test the VMF parser by duplicating a test file
    print('parsing...')
    map_file = VMF.parse('test.vmf')

    print('saving...')

    with open('test_out.vmf', 'w') as test_file:
        map_file.export(test_file)
    print('done!')