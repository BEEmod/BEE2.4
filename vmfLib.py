''' VMF Library
Wraps property_parser tree in a set of classes which smartly handle specifics of VMF files.
'''
from collections import defaultdict
import io

from property_parser import Property, KeyValError, NoKeyError
import utils

CURRENT_HAMMER_VERSION = 400
CURRENT_HAMMER_BUILD = 5304
# Used to set the defaults for versioninfo

_ID_types = {
    'brush' : 'solid_id', 
    'face'  : 'face_id', 
    'ent'   : 'ent_id'
    }
    
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
    def __init__(self, map_info = {}, spawn = None, entities = None, brushes = None):
        self.solid_id = [] # All occupied solid ids
        self.face_id = []
        self.ent_id = []
        self.entities = [] if entities is None else entities
        self.brushes = [] if brushes is None else brushes
        self.spawn = Entity(self, []) if spawn is None else spawn
        
        self.is_prefab = conv_bool(map_info.get('prefab', '_'), False)
        self.map_ver = conv_int(map_info.get('mapversion', '_'), 0)
        
        #These three are mostly useless for us, but we'll preserve them anyway
        self.format_ver = conv_int(map_info.get('formatversion', '_'), 100)
        self.hammer_ver = conv_int(map_info.get('editorversion', '_'), CURRENT_HAMMER_VERSION)
        self.hammer_build = conv_int(map_info.get('editorbuild', '_'), CURRENT_HAMMER_BUILD)
        
        self.show_grid = conv_bool(map_info.get('showgrid', '_'), True)
        self.show_3d_grid = conv_bool(map_info.get('show3dgrid', '_'), False)
        self.snap_grid = conv_bool(map_info.get('snaptogrid', '_'), True)
        self.show_logic_grid = conv_bool(map_info.get('showlogicalgrid', '_'), False)
        self.grid_spacing = conv_int(map_info.get('gridspacing', '_'), 64)
        
    def add_brush(self, item):
        self.brushes.append(item)
        
    def add_ent(self, item):
        self.entities.append(item)
        
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
        map = VMF()
        ents = []
        map.entities = [Entity.parse(map, ent) for ent in Property.find_all(tree, 'Entity')]
        
        map_spawn = Property.find_key(tree, 'world', None)
        if map_spawn is None:
            map_spawn = Property("world", [])
            
        map.spawn = Entity.parse(map, map_spawn)
        print(map.spawn)
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
        
        self.spawn.export(file, ent_name = 'world')
        
        for ent in self.entities:
            ent.export(file)
            
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
                
    def find_ent(self, vals = {}, tags = {}):
        "Return a list of entities with the given keyvalue values, and with keyvalues containing the tags."
        if len(vals) == 0 and len(tags) == 0:
            return self.entities[:]
        else:
            ret = []
            for ent in self.entities:
                for key,value in vals.items():
                    print(ent[key], value)
                    if not ent.has_key(key) or ent[key] != value:
                        continue # It failed!        
                for key,value in vals.items():
                    if not ent.has_key(key) or value not in ent[key]:
                        continue # It failed!
                ret.append(ent)
            return ret
class Solid:
    "A single brush, as a world brushes and brush entities."
    def __init__(self, map, des_id=-1, sides = None):
        self.map = map
        self.sides = [] if sides is None else sides
        self.id = map.get_id('brush', des_id)
        
    @staticmethod    
    def parse(map, tree):
        "Parse a Property tree into a Solid object."
        id = tree.find_key("id", -1).value
        try: 
            id = int(id)
        except TypeError:
            id = -1
        sides = []
        for side in tree.find_all("side"):
            sides.append(Side.parse(map, side))
        return Solid(map, des_id = id, sides=sides)
        
    def export(self, buffer, ind = ''):
        "Generate the strings needed to define this brush."
        buffer.write(ind + 'solid\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        for s in self.sides:
            s.export(buffer, ind + '\t')
        buffer.write(ind + '}\n')
    
    def __str__(self):
        "Return a description of our data."
        st = "<solid:" + str(self.id) + ">\n{\n"
        for s in self.sides:
            st += str(s) + "\n"
        st += "}"
        return st

class Side:
    "A brush face."
    def __init__(self, map, planes=[(0, 0, 0),(0, 0, 0),(0, 0, 0)], opt={}, des_id=-1):
        self.map = map
        self.planes = [0,0,0]
        self.id = map.get_id('face', des_id)
        for i,pln in enumerate(planes):
            self.planes[i]=dict(x=pln[0], y=pln[1], z=pln[2])
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
        planes = [0,0,0]
        for i,v in enumerate(verts):
            verts = v.split(" ")
            if len(verts) == 3:
                planes[i]=verts
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
        return Side(map, planes=planes, opt = opt)
        
    def make_vec(self, plane):
        return ("(" + str(plane['x']) +
                " " + str(plane['x']) +
                " " + str(plane['x']) + ")")
        
    def export(self, buffer, ind = ''):
        "Return the text required to define this side."
        buffer.write(ind + 'side\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        pl_str = [self.make_vec(p) for p in self.planes]
        buffer.write(ind + '"plane" "' + ' '.join(pl_str) + '"\n')
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
        
class Entity():
    "Either a point or brush entity."
    def __init__(self, map, keys = None, id=-1, outputs = None, solids = None, editor = None):
        self.map = map
        self.keys = {} if keys is None else keys
        self.outputs = outputs
        self.solids = solids
        self.id = map.get_id('ent', desired = id)
        self.editor = {'visgroup' : []} if editor is None else editor
        
    @staticmethod
    def parse(map, tree_list):
        "Parse a property tree into an Entity object."
        id = -1
        solids = []
        keys = {}
        outputs = []
        editor = { 'visgroup' : []}
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
                    elif v.name == 'visgroupid':
                        val = conv_int(v.value, default = -1)
                        if val:
                            editor['visgroup'].append(val)
            else:
                keys[item.name] = item.value
        return Entity(map, keys = keys, id = id, solids = solids, outputs=outputs, editor=editor)
    
    def is_brush(self):
        return len(self.solids) > 0
    
    def export(self, buffer, ent_name = 'Entity', ind=''):
        "Return the strings needed to create this entity."
        buffer.write(ind + ent_name + '\n')
        buffer.write(ind + '{\n')
        buffer.write(ind + '\t"id" "' + str(self.id) + '"\n')
        for key in sorted(self.keys.keys()):
            buffer.write(ind + '\t"' + key + '" "' + str(self.keys[key]) + '"\n')
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
        
    def has_key(self, key):
        return key in self.keys
        
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
                inst_out = out[1]
                out = out[0][9:]
            else:
                inst_out = None
                out = prop.name
                
            if vals[1].startswith('instance:'):
                inp = vals[1].split(';')
                inst_inp = inp[1]
                inp = inp[0][9:]
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
        if self.inst_out:
            buffer.write(ind + '"instance:' + self.inst_out + ';' + self.output)
        else:
            buffer.write(ind + '"' + self.output)
            
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
    print('saving...')
    with open('test_out.vmf', 'w') as file:
        map.export(file)
    print('done!')