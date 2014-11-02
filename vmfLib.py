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
    
def conv_int(str, default = 0):
    '''Converts a string to an integer, using a default if the string is unparsable.'''
    if str.isnumeric():
        return int(str)
    else:
        return default
        
def conv_bool(str, default = False):
    '''Converts a string to a boolean, using a default if the string is unparsable.'''
    if str.isnumeric():
        return bool(int(str))
    elif str.casefold() == 'false':
        return False
    elif str.casefold() == 'true':
        return True
    else:
        return default
        
def bool_to_str(bool):
    if bool:
        return '1'
    else:
        return '0'

class VMF:
    '''
    Represents a VMF file, and holds counters for various IDs used. Has functions for searching
    for specific entities or brushes, and converts to/from a property_parser tree.
    '''
    def __init__(
            self, 
            map_info={},
            spawn=None,
            entities=None,
            brushes=None,
            cameras=None, 
            visgroups=None):
        self.solid_id = [] # All occupied solid ids
        self.face_id = []
        self.ent_id = []
        self.entities = [] if entities is None else entities
        self.brushes = [] if brushes is None else brushes
        self.cameras = [] if cameras is None else cameras
        self.visgroups = [] if visgroups is None else visgroups
        
        self.spawn = Entity(self, []) if spawn is None else spawn
        self.spawn.solids = self.brushes
        self.spawn.hidden_brushes = self.brushes
        
        self.is_prefab = conv_bool(map_info.get('prefab', '_'), False)
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
        "Convert a property_parser tree into VMF classes."
        if not isinstance(tree, list):
            # if not a tree, try to read the file
            with open(tree, "r") as file:
                tree = Property.parse(file)
        map_info = {}
        
        ver_info = Property.find_key(tree, 'versioninfo', [])
        for key in ('editorversion', 'mapversion', 'editorbuild', 'prefab'):
            map_info[key] = ver_info.find_key(key, '_').value
        map_info['formatversion'] = ver_info.find_key('formatversion', '100').value
        if map_info['formatversion'] != '100':
            # If the version is different, this is probably to fail horribly
            print('WARNING: Unknown VMF format version " ' + map_info['formatversion'] + '"!')
        
        view_opt = Property.find_key(tree, 'viewsettings', [])
        view_dict = { 
            'bSnapToGrid' : 'snaptogrid',
            'bShowGrid' : 'showgrid',
            'bShow3DGrid' : 'show3dgrid',
            'bShowLogicalGrid' : 'showlogicalgrid',
            'nGridSpacing' : 'gridspacing'
            }
        for key in view_dict:
            map_info[view_dict[key]] = view_opt.find_key(key, '_').value
        
        cam_props = Property.find_key(tree, 'cameras', [])
        map_info['active_cam']  = cam_props.find_key('activecamera', -1).value
        map_info['quickhide'] = Property.find_key(tree, 'quickhide', []).find_key('count', '_').value
            
        map = VMF(map_info = map_info)
        cams = []
        for c in cam_props:
            if c.name != 'activecamera':
                cams.append(Camera.parse(map, c))
        
        ents = []
        map.entities = [Entity.parse(map, ent, hidden=False) for ent in Property.find_all(tree, 'Entity')]
        # find hidden entities
        map.entities.extend([Entity.parse(map, ent[0], hidden=True) for ent in Property.find_all(tree, 'hidden') if len(ent)==1])
        
        
        map_spawn = Property.find_key(tree, 'world', None)
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
        
        If no file is given the map will be returned as a string. By default, this
        will increment the map's version - set inc_version to False to suppress this.
        '''
        if file is None:
            file = io.stringIO() 
            # acts like a file object but is actually a string. We're 
            # using this to prevent having Python duplicate the entire
            # string every time we append b
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
        file.write('\t"prefab" "' + bool_to_str(self.is_prefab) + '"\n}\n')
            
        # TODO: Visgroups
        
        file.write('viewsettings\n{\n')
        file.write('\t"bSnapToGrid" "' + bool_to_str(self.snap_grid) + '"\n')
        file.write('\t"bShowGrid" "' + bool_to_str(self.show_grid) + '"\n')
        file.write('\t"bShowLogicalGrid" "' + bool_to_str(self.show_logic_grid) + '"\n')
        file.write('\t"nGridSpacing" "' + str(self.grid_spacing) + '"\n')
        file.write('\t"bShow3DGrid" "' + bool_to_str(self.show_3d_grid) + '"\n}\n')
        
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
        
        if self.quickhide_count > 0:
            file.write('quickhide\n{\n')
            file.write('\t"count" "' + str(self.quickhide_count) + '"\n')
            file.write('}\n')
            
        if ret_string:
            string = file.getvalue()
            file.close()
            return string
    
    def get_id(self, ids, desired=-1):
        "Get an unused ID of a type."
        if ids not in _ID_types:
            raise ValueError('Invalid ID type!')
        list_ = self.__dict__[_ID_types[ids]]
        if len(list_)==0 or desired not in list_ :
            if desired==-1:
                desired = 1
            list_.append(desired)
            return desired
        # Need it in ascending order
        list_.sort()
        for id in range(0, list_[-1]+1):
            if id not in list_:
                list_.append(id)
                return id
                
    def find_ents(self, vals = {}, tags = {}):
        "Return a list of entities with the given keyvalue values, and with keyvalues containing the tags."
        if len(vals) == 0 and len(tags) == 0:
            return self.entities[:] # skip to just returning the whole thing
        else:
            ret = []
            for ent in self.entities:
                for key,value in vals.items():
                    if not ent.has_key(key) or ent[key] != value:
                        break
                else: # passed through without breaks
                    for key,value in tags.items():
                        if not ent.has_key(key) or value not in ent[key]:
                            break
                    else:
                        ret.append(ent)
            return ret
            
    def iter_ents(self, vals = {}, tags = {}):
        "Iterate through all entities with the given keyvalue values, and with keyvalues containing the tags."
        for ent in self.entities:
            for key,value in vals.items():
                if not ent.has_key(key) or ent[key] != value:
                    break
            else: # passed through without breaks
                for key,value in tags.items():
                    if not ent.has_key(key) or value not in ent[key]:
                        break
                else:
                    yield ent    
class Camera:
    def __init__(self, map, pos, targ):
        self.pos = pos
        self.target = targ
        self.map = map
        map.cameras.append(self)
        
    def targ_ent(self, ent):
        if ent['origin']:
            self.target = ent['origin']
        
    def is_active(self):
        return map.active_cam == map.cameras.index(self)+1
        
    def set_active(self):
        map.active_cam = map.cameras.index(self) + 1
        
    def set_inactive_all(self):
        map.active_cam = -1
        
    @staticmethod
    def parse(map, tree):
        pos = tree.find_key('position', '[0 0 0]').value
        targ = tree.find_key('look', '[0 64 0]').value
        return Camera(map, pos, targ)
        
    def export(self, buffer, ind=''):
        buffer.write(ind + 'camera\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"position" "' + self.pos + '"\n')
        buffer.write(ind + '\t"look" "' + self.target + '"\n')
        buffer.write(ind + '}\n')
            
class Solid:
    "A single brush, as a world brushes and brush entities."
    def __init__(self, map, des_id=-1, sides=None, editor=None):
        self.map = map
        self.sides = [] if sides is None else sides
        self.id = map.get_id('brush', des_id)
        self.editor = {} if editor is None else editor
        
    @staticmethod    
    def parse(map, tree):
        "Parse a Property tree into a Solid object."
        id = conv_int(tree.find_key("id", '-1').value)
        try: 
            id = int(id)
        except TypeError:
            id = -1
        sides = []
        for side in tree.find_all("side"):
            sides.append(Side.parse(map, side))
            
        editor = {'visgroup' : []}
        for v in tree.find_key("editor", []):
            if v.name in ("visgroupshown", "visgroupautoshown"):
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
        return Solid(map, des_id = id, sides=sides, editor = editor)
        
    def export(self, buffer, ind = ''):
        "Generate the strings needed to define this brush."
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
        for key in ('visgroupshown', 'visgroupautoshown'):
            if key in self.editor:
                buffer.write(ind + '\t\t"' + key + '" "' + 
                    bool_to_str(self.editor[key]) + '"\n')
        buffer.write(ind + '\t}\n')
        
        buffer.write(ind + '}\n')
    
    def __str__(self):
        "Return a description of our data."
        st = "<solid:" + str(self.id) + ">\n{\n"
        for s in self.sides:
            st += str(s) + "\n"
        st += "}"
        return st
        
    def __iter__(self):
        for s in self.sides:
            yield s
        
    def __del__(self):
        "Forget this solid's ID when the object is destroyed."
        self.map.solid_id.remove(self.id)
        
    def get_bbox(self):
        "Get two vectors representing the space this brush takes up."
        bbox_min, bbox_max = self.sides[0].get_bbox()
        for s in self.sides[1:]:
            side_min, side_max = s.get_bbox()
            bbox_max.max(side_max)
            bbox_min.min(side_min)
        return bbox_min, bbox_max
        
    def get_origin(self):
        bbox_min, bbox_max = self.get_bbox()
        return (bbox_min+bbox_max)/2

class Side:
    "A brush face."
    def __init__(self, map, planes=[(0, 0, 0),(0, 0, 0),(0, 0, 0)], opt={}, des_id=-1):
        self.map = map
        self.planes = [0,0,0]
        self.id = map.get_id('face', des_id)
        for i,pln in enumerate(planes):
            self.planes[i]=Vec(x=pln[0], y=pln[1], z=pln[2])
        self.lightmap = opt.get("lightmap", 16)
        try: 
            self.lightmap = int(self.lightmap)
        except TypeError:
            self.lightmap = 16
        try:
            self.smooth = opt.get("smoothing", 0)
        except TypeError:
            self.smooth = bin(0)

        self.mat = opt.get("material", "")
        self.ham_rot = opt.get("rotation" , "0")
        self.uaxis = opt.get("uaxis", "[0 1 0 0] 0.25")
        self.vaxis = opt.get("vaxis", "[0 1 -1 0] 0.25")
            
    @staticmethod    
    def parse(map, tree):
        "Parse the property tree into a Side object."
        # planes = "(x1 y1 z1) (x2 y2 z2) (x3 y3 z3)"
        verts = tree.find_key("plane", "(0 0 0) (0 0 0) (0 0 0)").value[1:-1].split(") (")
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
        return Side(map, planes=planes, opt = opt, des_id = id)
        
    def make_vec(self, plane):
        return ("(" + str(plane['x']) +
                " " + str(plane['y']) +
                " " + str(plane['z']) + ")")
        
    def export(self, buffer, ind = ''):
        "Return the text required to define this side."
        buffer.write(ind + 'side\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        pl_str = [self.make_vec(p) for p in self.planes]
        buffer.write(ind + '\t"plane" "' + ' '.join(pl_str) + '"\n')
        buffer.write(ind + '\t"material" "' + self.mat + '"\n')
        buffer.write(ind + '\t"uaxis" "' + self.uaxis + '"\n')
        buffer.write(ind + '\t"vaxis" "' + self.vaxis + '"\n')
        buffer.write(ind + '\t"rotation" "' + str(self.ham_rot) + '"\n')
        buffer.write(ind + '\t"lightmapscale" "' + str(self.lightmap) + '"\n')
        buffer.write(ind + '\t"smoothing_groups" "' + str(self.smooth) + '"\n')
        buffer.write(ind + '}\n')
 
    def __str__(self):
        st = "\tmat = " + self.mat
        st += "\n\trotation = " + self.ham_rot + '\n'
        pl_str = [self.make_vec(p) for p in self.planes]
        st += '\tplane: ' + ", ".join(pl_str) + '\n'
        return st
        
    def __del__(self):
        "Forget this side's ID when the object is destroyed."
        self.map.face_id.remove(self.id)
        
    def get_bbox(self):
        "Generate the highest and lowest points these planes form."
        bbox_max=self.planes[0].copy()
        bbox_min=self.planes[0].copy()
        for v in self.planes[1:]:
            bbox_max.max(v)
            bbox_min.min(v)
        return bbox_min, bbox_max
        
    def get_origin(self):
        size_min, size_max = self.get_bbox()
        origin = (size_min + size_max) / 2
        return origin    
        
class Entity():
    "Either a point or brush entity."
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
        self.outputs = outputs
        self.solids = [] if solids is None else solids
        self.id = map.get_id('ent', desired = id)
        self.hidden = hidden
        self.editor = {'visgroup' : []} if editor is None else editor
        
    @staticmethod
    def parse(map, tree_list, hidden=False):
        "Parse a property tree into an Entity object."
        id = -1
        solids = []
        keys = {}
        outputs = []
        editor = { 'visgroup' : []}
        fixup = {}
        for item in tree_list:
            if item.name == "id" and item.value.isnumeric():
                id = item.value
            elif item.name == "solid":
                solids.append(Solid.parse(map, item))
            elif item.name == "connections" and item.has_children():
                for out in item:
                    outputs.append(Output.parse(out))
            elif item.name == "editor" and item.has_children():
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
                    elif v.name in REPLACE_KEYS:
                        vals = v.value.split(" ",1)
                        fixup[vals[0][1:]] = (vals[1], v.name[-2:])
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
        return len(self.solids) > 0
    
    def export(self, buffer, ent_name = 'entity', ind=''):
        "Return the strings needed to create this entity."
        
        if self.hidden:
            buffer.write(ind + 'hidden\n' + ind + '{\n')
            ind = ind + '\t'
        
        buffer.write(ind + ent_name + '\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        for key in sorted(self.keys.keys()):
            buffer.write(ind + '\t"' + key + '" "' + str(self.keys[key]) + '"\n')
        if len(self._fixup) > 0:
            for val in enumerate(sorted(self._fixup.items(), key=lambda x: x[1][1])):
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
                buffer.write(ind + '\t\t"groupid" "' + id + '"\n')
        for key in ('visgroupshown', 'visgroupautoshown'):
            if key in self.editor:
                buffer.write(ind + '\t\t"' + key + '" "' + 
                    bool_to_str(self.editor[key]) + '"\n')
        for key in ('logicalpos','comments'):
            if key in self.editor:
                buffer.write(ind + '\t\t"' + key + '" "' + 
                    self.editor[key] + '"\n')
        buffer.write(ind + '\t}\n')
        
        buffer.write(ind + '}\n')
        if self.hidden:
            buffer.write(ind[:-1] + '}\n')
        
    def remove(self):
        "Remove this entity from the map."
        self.map.entities.remove(self)
        self.map.ent_id.remove(self.id)
        
    def __str__(self):
        st ="<Entity>: \n{\n"
        for k,v in self.keys.items():
            if not isinstance(v, list):
                st+="\t " + k + ' = "' + v + '"\n'
        for out in self.outputs:
            st+='\t' + str(out) +'\n'
        st += "}\n"
        return st
        
    def __getitem__(self, key, default = None):
        if key in self.keys:
            return self.keys[key]
        else:
            return default
            
    def __setitem__(self, key, val):
        self.keys[key] = val
        
    def __delitem__(self, key):
        if key in self.keys:
            del self.keys[key]
            
    def get_fixup(self, var):
        if var in self._fixup:
            return self._fixup[var][0] # don't return the index
        else:
            return None
     
    def set_fixup(self, var, val):
        if var not in self._fixup:
            max = 0
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
        if var in self._fixup:
            del self._fixup[var]
            
    get = __getitem__
            
    def has_key(self, key):
        return key in self.keys
        
    def __del__(self):
        "Forget this entity's ID when the object is destroyed."
        self.map.ent_id.remove(self.id)
        
class Output:
    "An output from this item pointing to another."
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
        if ',' in prop.value:
            sep = True
            vals = prop.value.split(',')
        else:
            sep = False
            vals = prop.value.split(chr(27))
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
        "Generate the text required to define this output in the VMF."
        buffer.write(ind + '"' + self.exp_out())
        
        if self.inst_in:
            params = self.params
            inp = 'instance:' + self.inst_in + ';' + self.input
        else:
            inp = self.input
            params = self.params
            
        buffer.write('" "' + self.sep.join(
        (self.target, inp, self.params, str(self.delay), str(self.times))) + '"\n')
        
if __name__ == '__main__':
    map = VMF.parse('test.vmf')
    for br in map.brushes:
        if br.id == 59535:
            for s in br.sides:
                print(*[str(p) for p in s.planes])
                print(s.get_origin())
    
    #print('saving...')
    #with open('test_out.vmf', 'w') as file:
    #    map.export(file)
    print('done!')