''' VMF Library
Wraps property_parser tree in a set of classes which smartly handle specifics of VMF files.
'''
from collections import defaultdict
import io

from property_parser import Property, KeyValError, NoKeyError
from utils import Vec
import utils

CURRENT_HAMMER_VERSION = 400
CURRENT_HAMMER_BUILD = 5304
# Used to set the defaults for versioninfo

_ID_types = {
    'brush' : 'solid_id',
    'face'  : 'face_id',
    'ent'   : 'ent_id'
    }

_FIXUP_KEYS = ["replace0" + str(i) for i in range(1,10)] + ["replace" + str(i) for i in range(10,17)]
    # $replace01, $replace02, ..., $replace15, $replace16

_DISP_ROWS = ('normals','distances','offsets','offset_normals','alphas','triangle_tags')
    # all the rows that displacements have, in the form
    # "row0" "???"
    # "row1" "???"
    # etc

def conv_int(str, default=0):
    '''Converts a string to an integer, using a default if the string is unparsable.'''
    try:
        return int(str)
    except ValueError:
        return int(default)

def conv_float(str, default=0):
    '''Converts a string to an float, using a default if the string is unparsable.'''
    try:
        return float(str)
    except ValueError:
        return float(default)

def conv_bool(str, default=False):
    '''Converts a string to a boolean, using a default if the string is unparsable.'''
    if isinstance(str, bool): # True, False
        return str
    elif str.isnumeric(): # 0,1
        try:
            return bool(int(str))
        except ValueError:
            return default
    elif str.casefold() == 'false':
        return False
    elif str.casefold() == 'true':
        return True
    else:
        return default

def conv_vec(str, x=0, y=0, z=0):
    '''Convert a string in the form '(4 6 -4)' into a vector, using a default if the string is unparsable.'''
    parts = str.split(' ')
    if len(parts) == 3:
        # strip off the brackets if present
        if parts[0][0] in ('(','{','[', '<'):
            parts[0] = parts[0][1:]
        if parts[2][-1] in (')','}',']', '>'):
            parts[2] = parts[2][:-1]
        try:
            return Vec(float(parts[0]),float(parts[1]),float(parts[2]))
        except ValueError:
            return Vec(x,y,z)

class VMF:
    '''Represents a VMF file, and holds counters for various IDs used.

    Has functions for searching for specific entities or brushes, and
    converts to/from a property_parser tree.
    '''
    def __init__(
            self,
            map_info={},
            spawn=None,
            entities=None,
            brushes=None,
            cameras=None,
            cordons=None,
            visgroups=None):
        self.solid_id = [] # All occupied solid ids
        self.face_id = []
        self.ent_id = []
        self.entities = [] if entities is None else entities
        self.brushes = [] if brushes is None else brushes
        self.cameras = [] if cameras is None else cameras
        self.cordons = [] if cordons is None else cordons
        self.visgroups = [] if visgroups is None else visgroups

        self.spawn = Entity(self, []) if spawn is None else spawn
        self.spawn.solids = self.brushes
        self.spawn.hidden_brushes = self.brushes

        self.is_prefab = conv_bool(map_info.get('prefab', '_'), False)
        self.cordon_enabled = conv_bool(map_info.get('cordons_on', '_'), False)
        self.map_ver = conv_int(map_info.get('mapversion', '_'), 0)
        if self.spawn['mapversion'] is not None:
            del self.spawn['mapversion']

        #These three are mostly useless for us, but we'll preserve them anyway
        self.format_ver = conv_int(map_info.get('formatversion', '_'), 100)
        self.hammer_ver = conv_int(map_info.get('editorversion', '_'), CURRENT_HAMMER_VERSION)
        self.hammer_build = conv_int(map_info.get('editorbuild', '_'), CURRENT_HAMMER_BUILD)
        self.show_grid = conv_bool(map_info.get('showgrid', '_'), True)
        self.show_3d_grid = conv_bool(map_info.get('show3dgrid', '_'), False)
        self.snap_grid = conv_bool(map_info.get('snaptogrid', '_'), True)
        self.show_logic_grid = conv_bool(map_info.get('showlogicalgrid', '_'), False)
        self.grid_spacing = conv_int(map_info.get('gridspacing', '_'), 64)
        self.active_cam = conv_int(map_info.get('active_cam', '_'), -1)
        self.quickhide_count = conv_int(map_info.get('quickhide', '_'), -1)

    def add_brush(self, item):
        self.brushes.append(item)

    def remove_brush(self, item):
        self.brushes.remove(item)

    def add_ent(self, item):
        self.entities.append(item)

    def remove_ent(self, item):
        self.entities.remove(item)

    def add_brushes(self, item):
        for i in item:
            self.add_brush(i)

    def add_ents(self, item):
        for i in item:
            self.add_ent(i)

    @staticmethod
    def parse(tree):
        '''Convert a property_parser tree into VMF classes.'''
        if not isinstance(tree, Property):
            # if not a tree, try to read the file
            with open(tree, "r") as file:
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
            'bSnapToGrid' : 'snaptogrid',
            'bShowGrid' : 'showgrid',
            'bShow3DGrid' : 'show3dgrid',
            'bShowLogicalGrid' : 'showlogicalgrid',
            'nGridSpacing' : 'gridspacing'
            }
        for key in view_dict:
            map_info[view_dict[key]] = view_opt[key, '']

        cordons = tree.find_key('cordons', [])
        map_info['cordons_on'] = cordons['active', '0']

        cam_props = tree.find_key('cameras', [])
        map_info['active_cam']  = conv_int((cam_props['activecamera', '']),-1)
        map_info['quickhide'] = tree.find_key('quickhide', [])['count', '']


        map = VMF(map_info = map_info)

        for c in cam_props:
            if c.name != 'activecamera':
                Camera.parse(map, c)

        for ent in cordons.find_all('cordon'):
            Cordon.parse(map, ent)

        map.entities = [Entity.parse(map, ent, hidden=False) for ent in tree.find_all('Entity')]
        # find hidden entities
        for hidden_ent in tree.find_all('hidden'):
            map.entities.extend([Entity.parse(map, ent, hidden=True) for ent in hidden_ent])

        map_spawn = tree.find_key('world', [])
        if map_spawn is None:
            # Generate a fake default to parse through
            map_spawn = Property("world", [])
        map.spawn = Entity.parse(map, map_spawn)

        if map.spawn.solids is not None:
           map.brushes = map.spawn.solids

        return map
    pass

    def export(self, file=None, inc_version=True):
        '''Serialises the object's contents into a VMF file.

        - If no file is given the map will be returned as a string.
        - By default, this will increment the map's version - set inc_version to False to suppress this.
        '''
        if file is None:
            file = io.stringIO()
            # acts like a file object but is actually a string. We're
            # using this to prevent having Python duplicate the entire
            # string every time we append
            ret_string = True
        else:
            ret_string = False

        if inc_version:
            # Increment this to indicate the map was modified
            self.map_ver += 1

        file.write('versioninfo\n{\n')
        file.write('\t"editorversion" "' + str(self.hammer_ver) + '"\n')
        file.write('\t"editorbuild" "' + str(self.hammer_build) + '"\n')
        file.write('\t"mapversion" "' + str(self.map_ver) + '"\n')
        file.write('\t"formatversion" "' + str(self.format_ver) + '"\n')
        file.write('\t"prefab" "' + utils.bool_as_int(self.is_prefab) + '"\n}\n')

        # TODO: Visgroups

        file.write('viewsettings\n{\n')
        file.write('\t"bSnapToGrid" "' + utils.bool_as_int(self.snap_grid) + '"\n')
        file.write('\t"bShowGrid" "' + utils.bool_as_int(self.show_grid) + '"\n')
        file.write('\t"bShowLogicalGrid" "' + utils.bool_as_int(self.show_logic_grid) + '"\n')
        file.write('\t"nGridSpacing" "' + str(self.grid_spacing) + '"\n')
        file.write('\t"bShow3DGrid" "' + utils.bool_as_int(self.show_3d_grid) + '"\n}\n')


        self.spawn['mapversion'] = str(self.map_ver)
        self.spawn.export(file, ent_name = 'world')

        for ent in self.entities:
            ent.export(file)

        file.write('cameras\n{\n')
        if len(self.cameras) == 0:
            self.active_cam = -1
        file.write('\t"activecamera" "' + str(self.active_cam) + '"\n')
        for cam in self.cameras:
            cam.export(file, '\t')
        file.write('}\n')


        file.write('cordons\n{\n')
        if len(self.cordons) > 0:
            file.write('\t"active" "' + utils.bool_as_int(self.cordon_enabled) + '"\n')
            for cord in self.cordons:
                cord.export(file, '\t')
        else:
            file.write('\t"active" "0"\n')
        file.write('}\n')

        if self.quickhide_count > 0:
            file.write('quickhide\n{\n')
            file.write('\t"count" "' + str(self.quickhide_count) + '"\n')
            file.write('}\n')

        if ret_string:
            string = file.getvalue()
            file.close()
            return string

    def get_id(self, ids, desired=-1):
        '''Get an unused ID of a type. Used by entities, solids and brush sides to keep their IDs valid.'''
        if ids not in _ID_types:
            raise ValueError('Invalid ID type!')
        if desired==-1:
            desired = 1
        list_ = getattr(self,_ID_types[ids])
        if len(list_)==0 or desired not in list_ :
            list_.append(int(desired))
            return desired
        # Need it in ascending order
        list_.sort()
        for id in range(0, list_[-1]+1):
            if id not in list_:
                list_.append(int(id))
                return id

    def iter_wbrushes(self, world=True, detail=True):
        '''Iterate through all world and detail solids in the map.'''
        if world:
            for br in self.brushes:
                yield br
        if detail:
            for ent in self.iter_ents(classname='func_detail'):
                for solid in ent.solids:
                    yield solid

    def iter_ents(self, **cond):
        '''Iterate through entities having the given keyvalue values.'''
        items = cond.items()
        for ent in self.entities[:]:
            for key,value in items:
                if not ent.has_key(key) or ent[key] != value:
                    break
            else:
                yield ent

    def iter_ents_tags(self, vals = {}, tags = {}):
        '''Iterate through all entities with the given keyvalue values, and with keyvalues containing the tags.'''
        for ent in self.entities[:]:
            for key,value in vals.items():
                if not ent.has_key(key) or ent[key] != value:
                    break
            else: # passed through without breaks
                for key,value in tags.items():
                    if not ent.has_key(key) or value not in ent[key]:
                        break
                else:
                    yield ent

    def iter_inputs(self, name):
        '''Loop through all Outputs which target the named entity.

        - Allows using * at beginning/end
        '''
        wild_start = name[:1]=='*'
        wild_end = name[-1:]=='*'
        if wild_start:
            name = name[1:]
        if wild_end:
            name = name[:-1]
        for ent in self.entities:
            for out in ent.outputs:
                if wild_start:
                    if wild_end:
                        if name in out.target: # blah-target-blah
                            yield out
                    else:
                        if out.target.endswith(name): # target-blah
                            yield out
                else:
                    if wild_end:
                        if out.target.startswith(name): # blah-target
                            yield out
                    else:
                        if out.target == name: # target
                            yield out

class Camera:
    def __init__(self, map, pos, targ):
        self.pos = pos
        self.target = targ
        self.map = map
        map.cameras.append(self)

    def targ_ent(self, ent):
        '''Point the camera at an entity.'''
        if ent['origin']:
            self.target = conv_vec(ent['origin'], 0,0,0)

    def is_active(self):
        '''Is this camera in use?'''
        return map.active_cam == map.cameras.index(self)+1

    def set_active(self):
        '''Set this to be the map's active camera'''
        map.active_cam = map.cameras.index(self) + 1

    def set_inactive_all(self):
        '''Disable all cameras in this map.'''
        map.active_cam = -1

    @staticmethod
    def parse(map, tree):
        '''Read a camera from a property_parser tree.'''
        pos = conv_vec(tree.find_key('position', '_').value, 0,0,0)
        targ = conv_vec(tree.find_key('look', '_').value, 0,64,0)
        return Camera(map, pos, targ)

    def copy(self):
        '''Duplicate this camera object.'''
        return Camera(self.map, self.pos.copy(), self.target.copy())

    def remove(self):
        '''Delete this camera from the map.'''
        map.cameras.remove(self)
        if self.is_active():
            self.set_inactive()

    def export(self, buffer, ind=''):
        buffer.write(ind + 'camera\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"position" "[' + self.pos.join(' ') + ']"\n')
        buffer.write(ind + '\t"look" "[' + self.target.join(' ') + ']"\n')
        buffer.write(ind + '}\n')

class Cordon:
    '''Represents one cordon volume.'''
    def __init__(self, map, min_, max_, is_active=True, name='Cordon'):
        self.map = map
        self.name = name
        self.bounds_min = min_
        self.bounds_max = max_
        self.active = is_active
        map.cordons.append(self)

    @staticmethod
    def parse(map, tree):
        name = tree['name', 'cordon']
        is_active = conv_bool(tree['active', '0'], False)
        bounds = tree.find_key('box', [])
        min_ = conv_vec(bounds['mins', '(0 0 0)'], 0, 0, 0)
        max_ = conv_vec(bounds['maxs', '(128 128 128)'], 128, 128, 128)
        return Cordon(map, min_, max_, is_active, name)

    def export(self, buffer, ind=''):
        buffer.write(ind + 'cordon\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"name" "' + self.name + '"\n')
        buffer.write(ind + '\t"active" "' + utils.bool_as_int(self.active) + '"\n')
        buffer.write(ind + '\tbox\n')
        buffer.write(ind + '\t{\n')
        buffer.write(ind + '\t\t"mins" "(' + self.bounds_min.join(' ') + ')"\n')
        buffer.write(ind + '\t\t"maxs" "(' + self.bounds_max.join(' ') + ')"\n')
        buffer.write(ind + '\t}\n')
        buffer.write(ind + '}\n')

    def copy(self):
        '''Duplicate this cordon.'''
        return Cordon(self.map, self.bounds_min.copy(), self.bounds_max.copy(), self.active, self.name)

    def remove(self):
        '''Remove this cordon from the map.'''
        map.cordons.remove(self)

class Solid:
    '''A single brush, serving as both world brushes and brush entities.'''
    def __init__(self, map, des_id=-1, sides=None, editor=None, hidden=False):
        self.map = map
        self.sides = [] if sides is None else sides
        self.id = map.get_id('brush', des_id)
        self.editor = {} if editor is None else editor
        self.hidden=hidden

    def copy(self, des_id=-1):
        '''Duplicate this brush.'''
        editor = {}
        for key in ('color','groupid','visgroupshown', 'visgroupautoshown'):
            if key in self.editor:
                editor[key] = self.editor[key]
        if 'visgroup' in self.editor:
            editor['visgroup'] = self.editor['visgroup'][:]
        sides = [s.copy() for s in self.sides]
        return Solid(map, des_id=des_id, sides=sides, editor=editor, hidden=self.hidden)

    @staticmethod
    def parse(map, tree, hidden=False):
        '''Parse a Property tree into a Solid object.'''
        id = conv_int(tree["id", '-1'])
        try:
            id = int(id)
        except TypeError:
            id = -1
        sides = []
        for side in tree.find_all("side"):
            sides.append(Side.parse(map, side))

        editor = {'visgroup' : []}
        for v in tree.find_key("editor", []):
            if v.name in ('visgroupshown', 'visgroupautoshown', 'cordonsolid'):
                editor[v.name] = conv_bool(v.value, default=True)
            elif v.name == 'color' and ' ' in v.value:
                editor['color'] = v.value
            elif v.name == 'group':
                editor[v.name] = conv_int(v.value, default = -1)
                if editor[v.name] == -1:
                    del editor[v.name]
            elif v.name == 'visgroupid':
                val = conv_int(v.value, default = -1)
                if val:
                    editor['visgroup'].append(val)
        if len(editor['visgroup'])==0:
            del editor['visgroup']
        return Solid(map, des_id=id, sides=sides, editor=editor, hidden=hidden)

    def export(self, buffer, ind = ''):
        '''Generate the strings needed to define this brush.'''
        if self.hidden:
            buffer.write(ind + 'hidden\n' + ind + '{\n')
            ind = ind + '\t'
        buffer.write(ind + 'solid\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        for s in self.sides:
            s.export(buffer, ind + '\t')

        buffer.write(ind + '\teditor\n')
        buffer.write(ind + '\t{\n')
        if 'color' in self.editor:
            buffer.write(ind + '\t\t"color" "' +
                self.editor['color'] + '"\n')
        if 'groupid' in self.editor:
            buffer.write(ind + '\t\t"groupid" "' +
                self.editor['groupid'] + '"\n')
        if 'visgroup' in self.editor:
            for id in self.editor['visgroup']:
                buffer.write(ind + '\t\t"groupid" "' + str(id) + '"\n')
        for key in ('visgroupshown', 'visgroupautoshown', 'cordonsolid'):
            if key in self.editor:
                buffer.write(ind + '\t\t"' + key + '" "' +
                    utils.bool_as_int(self.editor[key]) + '"\n')
        buffer.write(ind + '\t}\n')

        buffer.write(ind + '}\n')
        if self.hidden:
            buffer.write(ind[:-1] + '}\n')

    def __str__(self):
        '''Return a user-friendly description of our data.'''
        st = "<solid:" + str(self.id) + ">\n{\n"
        for s in self.sides:
            st += str(s) + "\n"
        st += "}"
        return st

    def __iter__(self):
        for s in self.sides:
            yield s

    def __del__(self):
        '''Forget this solid's ID when the object is destroyed.'''
        if self.id in self.map.solid_id:
            self.map.solid_id.remove(self.id)

    def get_bbox(self):
        '''Get two vectors representing the space this brush takes up.'''
        bbox_min, bbox_max = self.sides[0].get_bbox()
        for s in self.sides[1:]:
            side_min, side_max = s.get_bbox()
            bbox_max.max(side_max)
            bbox_min.min(side_min)
        return bbox_min, bbox_max

    def get_origin(self, bbox_min=None, bbox_max=None):
        '''Calculates a vector representing the exact center of this brush.'''
        if bbox_min is None or bbox_max is None:
            bbox_min, bbox_max = self.get_bbox()
        return (bbox_min+bbox_max)/2

    def translate(self, diff):
        '''Move this solid by the specified vector.

        - This does not translate textures as well.
        - A tuple can be passed in instead if desired.
        '''
        "Move this brush by the specified vector. A tuple can be passed instead if desired."
        for s in self.sides:
            s.translate(diff)

class Side:
    "A brush face."
    __slots__ = ('map', 'planes', 'id', 'lightmap', 'smooth', 'mat', 'ham_rot', 'uaxis', 'vaxis',
                 'disp_power', 'disp_pos', 'disp_flags', 'disp_elev', 'disp_is_subdiv', 'disp_allowed_verts', 'disp_data', 'is_disp')
    def __init__(self, map, planes=[(0, 0, 0),(0, 0, 0),(0, 0, 0)], opt={}, des_id=-1, disp_data={}):
        self.map = map
        self.planes = [0,0,0]
        self.id = map.get_id('face', des_id)
        for i,pln in enumerate(planes):
            self.planes[i]=Vec(x=pln[0], y=pln[1], z=pln[2])
        self.lightmap = opt.get("lightmap", 16)
        self.smooth = opt.get("smoothing", 0)
        self.mat = opt.get("material", "")
        self.ham_rot = opt.get("rotation" , 0)
        self.uaxis = opt.get("uaxis", "[0 1 0 0] 0.25")
        self.vaxis = opt.get("vaxis", "[0 1 -1 0] 0.25")
        if len(disp_data) > 0:
            self.disp_power = conv_int(disp_data.get('power', '_'), 4)
            self.disp_pos = conv_vec(disp_data.get('pos', '_'), 0,0,0)
            self.disp_flags = conv_int(disp_data.get('flags', '_'), 0)
            self.disp_elev = conv_float(disp_data.get('elevation', '_'), 0)
            self.disp_is_subdiv = conv_bool(disp_data.get('subdiv', '_'), False)
            self.disp_allowed_verts = disp_data.get('allowed_verts', {})
            self.disp_data = {}
            for v in _DISP_ROWS:
                self.disp_data[v] = disp_data.get(v, [])
            self.is_disp = True
        else:
            self.is_disp = False

    @staticmethod
    def parse(map, tree):
        '''Parse the property tree into a Side object.'''
        # planes = "(x1 y1 z1) (x2 y2 z2) (x3 y3 z3)"
        verts = tree["plane", "(0 0 0) (0 0 0) (0 0 0)"][1:-1].split(") (")
        id = conv_int(tree.find_key("id", '-1').value)
        planes = [0,0,0]
        for i,v in enumerate(verts):
            verts = v.split(" ")
            if len(verts) == 3:
                planes[i]=[float(v) for v in verts]
            else:
                raise ValueError("Invalid planes in '" + plane + "'!")
        if not len(planes) == 3:
            raise ValueError("Wrong number of solid planes in '" + plane + "'!")
        opt = {
            'material' : tree.find_key('material', '').value,
            'uaxis' : tree.find_key('uaxis', '[0 1  0 0] 0.25').value,
            'vaxis' : tree.find_key('vaxis', '[0 0 -1 0] 0.25').value,
            'rotation' : conv_int(tree.find_key('rotation', '0').value, 0),
            'lightmap' : conv_int(tree.find_key('lightmapscale', '16').value, 16),
            'smoothing' : conv_int(tree.find_key('smoothing_groups', '0').value, 0),
            }
        disp_tree = tree.find_key('dispinfo', [])
        disp_data = {}
        if len(disp_tree) > 0:
            disp_data['power'] = disp_tree.find_key('power', '4').value
            disp_data['pos'] = disp_tree.find_key('startposition', '4').value
            disp_data['flags'] = disp_tree.find_key('flags', '0').value
            disp_data['elevation'] = disp_tree.find_key('elevation', '0').value
            disp_data['subdiv'] = disp_tree.find_key('subdiv', '0').value
            disp_data['allowed_verts'] = {}
            for prop in disp_tree.find_key('allowed_verts', []):
                disp_data['allowed_verts'][prop.name] = prop.value
            for v in _DISP_ROWS:
                rows = disp_tree.find_key(v, []).value
                if len(rows) > 0:
                    rows.sort(key=lambda x: conv_int(x.name[3:],0))
                    disp_data[v] = [v.value for v in rows]
        return Side(map, planes=planes, opt=opt, des_id=id, disp_data=disp_data)

    def copy(self, des_id=-1):
        '''Duplicate this brush side.'''
        planes = [p.as_tuple() for p in self.planes]
        opt = {
            'material' : self.mat,
            'rotation' : self.ham_rot,
            'uaxis' : self.uaxis,
            'vaxis' : self.vaxis,
            'smoothing' : self.smooth,
            'lightmap' : self.lightmap,
            }
        return Side(map, planes=planes, opt=opt, des_id=des_id)

    def export(self, buffer, ind = ''):
        '''Generate the strings required to define this side in a VMF.'''
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
            buffer.write(ind + '\t\t"startposition" "[' + self.disp_pos.join(' ') + ']"\n')
            buffer.write(ind + '\t\t"flags" "' + str(self.disp_flags) + '"\n')
            buffer.write(ind + '\t\t"elevation" "' + str(self.disp_elev) + '"\n')
            buffer.write(ind + '\t\t"subdiv" "' + utils.bool_as_int(self.disp_is_subdiv) + '"\n')
            for v in _DISP_ROWS:
                if len(self.disp_data[v]) > 0:
                    buffer.write(ind + '\t\t' + v + '\n')
                    buffer.write(ind + '\t\t{\n')
                    for i, data in enumerate(self.disp_data[v]):
                        buffer.write(ind + '\t\t\t"row' + str(i) + '" "' + data + '"\n')
                    buffer.write(ind + '\t\t}\n')
            if len(self.disp_allowed_verts) > 0:
                buffer.write(ind + '\t\tallowed_verts\n')
                buffer.write(ind + '\t\t{\n')
                for k,v in self.disp_allowed_verts.items():
                    buffer.write(ind + '\t\t\t"' + k + '" "' + v + '"\n')
                buffer.write(ind + '\t\t}\n')
            buffer.write(ind + '\t}\n')
        buffer.write(ind + '}\n')

    def __str__(self):
        '''Dump a user-friendly representation of the side.'''
        st = "\tmat = " + self.mat
        st += "\n\trotation = " + self.ham_rot + '\n'
        pl_str = ['(' + p.join(' ') + ')' for p in self.planes]
        st += '\tplane: ' + ", ".join(pl_str) + '\n'
        return st

    def __del__(self):
        '''Forget this side's ID when the object is destroyed.'''
        if self.id in self.map.face_id:
            self.map.face_id.remove(self.id)

    def get_bbox(self):
        '''Generate the highest and lowest points these planes form.'''
        bbox_max=self.planes[0].copy()
        bbox_min=self.planes[0].copy()
        for v in self.planes[1:]:
            bbox_max.max(v)
            bbox_min.min(v)
        return bbox_min, bbox_max

    def get_origin(self):
        '''Calculates a vector representing the exact center of this plane.'''
        size_min, size_max = self.get_bbox()
        origin = (size_min + size_max) / 2
        return origin

    def translate(self, diff):
        '''Move this side by the specified vector.

        - This does not translate textures as well.
        - A tuple can be passed in instead if desired.
        '''
        for p in self.planes:
            p += diff

    def plane_desc(self):
        '''Return a string which describes this face, for use in texture randomisation.'''
        return self.planes[0].join(' ') + self.planes[1].join(' ') + self.planes[2].join(' ')

class Entity():
    '''A representation of either a point or brush entity.

    Creation:
    Entity(args) for a brand-new Entity
    Entity.parse(property) if reading from a VMF file
    ent.copy() to duplicate an existing entity

    Supports [] operations to read and write keyvalues.
    If reading instance $replace values use get_fixup(), set_fixup() and del_fixup().
    '''
    def __init__(
            self,
            map,
            keys = None,
            fixup = None,
            id=-1,
            outputs=None,
            solids=None,
            editor=None,
            hidden=False):
        self.map = map
        self.keys = {} if keys is None else keys
        self._fixup = {} if fixup is None else fixup
        self.outputs = [] if outputs is None else outputs
        self.solids = [] if solids is None else solids
        self.id = map.get_id('ent', desired = id)
        self.hidden = hidden
        self.editor = {'visgroup' : []} if editor is None else editor
        
        if 'logicalpos' not in self.editor:
            self.editor['logicalpos'] = '[0 ' + str(self.id) + ']'
        if 'visgroupshown' not in self.editor:
            self.editor['visgroupshown'] = '1'
        if 'visgroupautoshown' not in self.editor:
            self.editor['visgroupautoshown'] = '1'
        if 'color' not in self.editor:
            self.editor['color'] = '255 255 255'

    def copy(self, des_id=-1):
        '''Duplicate this entity entirely, including solids and outputs.'''
        new_keys = {}
        new_fixup = {}
        new_editor = {}
        for key, value in self.keys.items():
            new_keys[key] = value

        for key, value in self._fixup.items():
            new_fixup[key] = (value[0],value[1])

        for key, value in self.editor.items():
            if key != 'visgroup':
                new_editor[key] = value
        new_editor['visgroup'] = self.editor['visgroup'][:]

        new_solids = [s.copy() for s in self.solids]
        outs = [o.copy() for o in self.outputs]

        return Entity(
            map=self.map,
            keys=new_keys,
            fixup=new_fixup,
            id=des_id,
            outputs=outs,
            solids=new_solids,
            editor=new_editor,
            hidden=self.hidden)

    @staticmethod
    def parse(map, tree_list, hidden=False):
        '''Parse a property tree into an Entity object.'''
        id = -1
        solids = []
        keys = {}
        outputs = []
        editor = { 'visgroup' : []}
        fixup = {}
        for item in tree_list:
            name = item.name.casefold()
            if name == "id" and item.value.isnumeric():
                id = item.value
            elif name in _FIXUP_KEYS:
                vals = item.value.split(" ",1)
                fixup[vals[0][1:]] = (vals[1], item.name[-2:])
            elif name == "solid":
                if item.has_children():
                    solids.append(Solid.parse(map, item))
                else:
                    keys[item.name] = item.value
            elif name == "connections" and item.has_children():
                for out in item:
                    outputs.append(Output.parse(out))
            elif name == "hidden":
                if item.has_children():
                    solids.extend([Solid.parse(map, br, hidden=True) for br in item])
                else:
                    keys[item.name]=item.value
            elif name == "editor" and item.has_children():
                for v in item:
                    if v.name in ("visgroupshown", "visgroupautoshown"):
                        editor[v.name] = conv_bool(v.value, default=True)
                    elif v.name == 'color' and ' ' in v.value:
                        editor['color'] = v.value
                    elif v.name == 'logicalpos' and v.value.startswith('[') and v.value.endswith(']'):
                        editor['logicalpos'] = v.value
                    elif v.name == 'comments':
                        editor['comments'] = v.value
                    elif v.name == 'group':
                        editor[v.name] = conv_int(v.value, default = -1)
                        if editor[v.name] == -1:
                            del editor[v.name]
                    elif v.name == 'visgroupid':
                        val = conv_int(v.value, default = -1)
                        if val:
                            editor['visgroup'].append(val)
            else:
                keys[item.name] = item.value

        return Entity(
            map,
            keys=keys,
            id=id,
            solids=solids,
            outputs=outputs,
            editor=editor,
            hidden=hidden,
            fixup=fixup)

    def is_brush(self):
        '''Is this Entity a brush entity?'''
        return len(self.solids) > 0

    def export(self, buffer, ent_name = 'entity', ind=''):
        '''Generate the strings needed to create this entity.'''

        if self.hidden:
            buffer.write(ind + 'hidden\n' + ind + '{\n')
            ind = ind + '\t'

        buffer.write(ind + ent_name + '\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        for key in sorted(self.keys.keys()):
            buffer.write(ind + '\t"' + key + '" "' + str(self.keys[key]) + '"\n')
        if len(self._fixup) > 0:
            for val in sorted(self._fixup.items(), key=lambda x: x[1][1]):
                # we end up with (key, (val, index)) and we want to sort by the index
                buffer.write(ind + '\t"replace' + val[1][1] + '" "$' + val[0] + " " + val[1][0] + '"\n')
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
            buffer.write(ind + '\t\t"color" "' +
                self.editor['color'] + '"\n')
        if 'groupid' in self.editor:
            buffer.write(ind + '\t\t"groupid" "' +
                self.editor['groupid'] + '"\n')
        if 'visgroup' in self.editor:
            for id in self.editor['visgroup']:
                buffer.write(ind + '\t\t"groupid" "' + str(id) + '"\n')
        for key in ('visgroupshown', 'visgroupautoshown'):
            if key in self.editor:
                buffer.write(ind + '\t\t"' + key + '" "' +
                    utils.bool_as_int(self.editor[key]) + '"\n')
        for key in ('logicalpos','comments'):
            if key in self.editor:
                buffer.write(ind + '\t\t"' + key + '" "' +
                    self.editor[key] + '"\n')
        buffer.write(ind + '\t}\n')

        buffer.write(ind + '}\n')
        if self.hidden:
            buffer.write(ind[:-1] + '}\n')

    def sides(self):
        '''Iterate through all our brush sides.'''
        if self.is_brush():
            for solid in self.solids:
                for face in solid:
                    yield face

    def add_out(self, output):
        "Add the output to our list."
        self.outputs.append(output)

    def remove(self):
        '''Remove this entity from the map.

        Useful if it is required to delete an entity while looping, as
        this will still keep the object intact. Ensure any lists are
        also deleted so the object will be garbage-collected.
        '''
        self.map.entities.remove(self)
        if self.id in self.map.ent_id:
            self.map.ent_id.remove(self.id)

    def __str__(self):
        '''Dump a user-friendly representation of the entity.'''
        st ="<Entity>: \n{\n"
        for k,v in self.keys.items():
            if not isinstance(v, list):
                st+="\t " + k + ' = "' + v + '"\n'
        for out in self.outputs:
            st+='\t' + str(out) +'\n'
        st += "}\n"
        return st

    def __getitem__(self, key, default = None):
        '''Allow using [] syntax to search for keyvalues.

        - This will return None instead of KeyError if the value is not found.
        - It ignores case-matching, but will use the first given version of a key.
        - If used via Entity.get() the default argument is available.
        - A tuple can be passed for the default to be set, inside the [] syntax.
        '''
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
        '''Allow using [] syntax to save a keyvalue.

        - It is case-insensitive, so it will overwrite a key which only differs by case
        '''
        key_fold = key.casefold()
        for k in self.keys:
            if k.casefold() == key_fold:
                # Check case-insensitively for this key first
                self.keys[k] = val
                break
        else:
            self.keys[key] = val

    def __delitem__(self, key):
        key = key.casefold()
        for k in self.keys:
            if k.casefold() == key:
                del self.keys[k]
                break

    def get_fixup(self, var, default=None):
        '''Get the value of an instance $replace variable.'''
        if var[0] == '$':
            var = var[1:]
        if var in self._fixup:
            return self._fixup[var][0] # don't return the index
        else:
            return default

    def has_fixup(self, var):
        '''Determine if this instance has the named $replace variable.'''
        return var in self._fixup

    def set_fixup(self, var, val):
        '''Set the value of an instance $replace variable, creating it if needed.'''
        if var[0] == '$':
            var = var[1:]
        if var not in self._fixup:
            max = 1
            for i in self._fixup.values():
                if int(i[1]) > max:
                    max = int(i[1])
            if max <9:
                max = "0" + str(max)
            else:
                max = str(max)
            self._fixup[var] = (val, max)
        else:
            self._fixup[var] = (val, self._fixup[var][1])

    def rem_fixup(self, var):
        '''Delete a instance $replace variable.'''
        if var[0] == '$':
            var = var[1:]
        if var in self._fixup:
            del self._fixup[var]

    get = __getitem__

    def has_key(self, key):
        '''Determine if a value exists for the given key.'''
        key = key.casefold()
        for k in self.keys:
            if k.casefold() == key:
                return True
        else:
            return False

    def __del__(self):
        '''Forget this entity's ID when the object is destroyed.'''
        if self.id in self.map.ent_id:
            self.map.ent_id.remove(self.id)

    def get_bbox(self):
        '''Get two vectors representing the space this entity takes up.'''
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
        '''Return a vector representing the center of this entity's brushes.'''
        if self.is_brush():
            bbox_min, bbox_max = self.get_bbox()
            return (bbox_min+bbox_max)/2
        else:
            return Vec(self['origin'].split(" "))

class Output:
    '''An output from one entity pointing to another.'''
    __slots__ = ('output', 'inst_out', 'target',
                 'input', 'inst_in', 'params', 'delay',
                 'times', 'sep')
    def __init__(self,
                 out,
                 targ,
                 inp,
                 param = '',
                 delay = 0.0,
                 times = -1,
                 inst_out = None,
                 inst_in = None,
                 comma_sep = False):
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
        "Convert the VMF Property into an Output object."
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
                param = vals[2],
                delay = float(vals[3]),
                times=int(vals[4]),
                inst_out = inst_out,
                inst_in = inst_inp,
                comma_sep = sep)

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
        '''Generate a user-friendly representation of this output.'''
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
            st += " (once" if self.times==1 else (" (" + str(self.times) + " times")
            st += " only)"
        return st

    def export(self, buffer, ind = ''):
        '''Generate the text required to define this output in the VMF.'''
        buffer.write(ind + '"' + self.exp_out())

        if self.inst_in:
            params = self.params
            inp = 'instance:' + self.inst_in + ';' + self.input
        else:
            inp = self.input
            params = self.params

        buffer.write('" "' + self.sep.join(
        (self.target, inp, self.params, str(self.delay), str(self.times))) + '"\n')

    def copy(self):
        '''Duplicate this output object.'''
        return Outputs(
            self.output,
            self.target,
            self.input,
            param=self.params,
            times=self.times,
            inst_out=self.inst_out,
            inst_in=self.inst_in,
            comma_sep = (self.sep == ','))

if __name__ == '__main__':
    print('parsing...')
    map = VMF.parse('test.vmf')
    print('saving...')
    with open('test_out.vmf', 'w') as file:
        map.export(file)
    print('done!')