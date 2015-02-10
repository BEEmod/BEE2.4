import random
from operator import itemgetter

from utils import Vec
import vmfLib as VLib
import utils

GLOBAL_INSTANCES = []
ALL_INST = []
conditions = []

TEX_FIZZLER = {
    "effects/fizzler_center" : "center",
    "effects/fizzler_l"      : "left",
    "effects/fizzler_r"      : "right",
    "effects/fizzler"        : "short",
    "tools/toolsnodraw"      : "nodraw",
    }

ANTLINES = {
    "signage/indicator_lights/indicator_lights_floor" : "antline",
    "signage/indicator_lights/indicator_lights_corner_floor" : "antlinecorner"
    }


def add(prop_block):
    '''Add a condition to the list.'''
    flags = []
    results = []
    priority = 0
    for prop in prop_block:
        if prop.name == 'result':
            results.extend(prop.value) # join multiple ones together
        elif prop.name == 'priority':
            priority = VLib.conv_int(prop.value, priority)
        else:
            flags.append(prop)

    if len(results) > 0: # is it valid?
        con = {
            "flags" : flags,
            "results" : results,
            "priority": priority,
            }
        conditions.append(con)

def init(settings, vmf, seed, preview, mode, inst_list, inst_files):
    # Get a bunch of values from VBSP, since we can't import directly.
    global VMF, STYLE_VARS, VOICE_ATTR, OPTIONS, MAP_RAND_SEED, IS_PREVIEW
    global GAME_MODE, ALL_INST, INST_FILES
    VMF = vmf
    STYLE_VARS = settings['style_vars']
    VOICE_ATTR = settings['has_attr']
    OPTIONS = settings['options']
    MAP_RAND_SEED = seed
    IS_PREVIEW = preview
    GAME_MODE = mode
    ALL_INST = inst_list
    INST_FILES = {key.casefold(): value for key,value in inst_files.items()}

    # Sort by priority, where higher = done earlier
    conditions.sort(key=itemgetter('priority'), reverse=True)
    setup_cond()

def check_all():
    '''Check all conditions.'''

    utils.con_log('Checking Conditions...')
    for condition in conditions:
        for inst in VMF.iter_ents(classname='func_instance'):
            run_cond(inst, condition)
            if len(condition['results']) == 0:
                break
    remove_blank_inst()

    utils.con_log('Map has attributes: ', [key for key,value in VOICE_ATTR.items() if value])
    utils.con_log('Style Vars:', dict(STYLE_VARS.items()))
    utils.con_log('Global instances: ', GLOBAL_INSTANCES)

def check_inst(inst):
    '''Run all condtions on a given instance.'''
    for condition in conditions:
        run_cond(inst, condition)
    remove_blank_inst()

def remove_blank_inst():
    '''Remove instances with blank file attr.

    This allows conditions to strip the instances when requested.
    '''
    for inst in VMF.iter_ents(classname='func_instance', file=''):
        VMF.remove_ent(inst)

def setup_cond():
    '''Some conditions require setup logic before they are run.'''
    for cond in conditions:
        for res in cond['results'][:]:
            if res.name == 'variant':
                res.value = variant_weight(res)
            elif res.name == 'custantline':
                res.value = {
                    'instance' : res.find_key('instance', '').value,
                    'antline' : [p.value for p in res.find_all('straight')],
                    'antlinecorner' : [p.value for p in res.find_all('corner')],
                    'outputs' : list(res.find_all('addOut'))
                    }
                if len(res.value['antline']) == 0 or len(res.value['antlinecorner']) == 0:
                    cond['results'].remove(res) # invalid

def run_cond(inst, cond):
    '''Try to satisfy this condition on the given instance.'''
    for flag in cond['flags']:
        if not check_flag(flag, inst):
            return

    inst['file'] = inst['file', ''][:-4] # our suffixes won't touch the .vmf extension
    for res in cond['results']:
        try:
            func = RESULT_LOOKUP[res.name]
        except KeyError:
            utils.con_log('"' + flag.name + '" is not a valid condition result!')
        else:
            func(inst, res)
    if not inst['file'].endswith('vmf'):
        inst['file'] += '.vmf'


def check_flag(flag, inst):
    print('checking ' + flag.name + '(' + str(flag.value) + ') on ' + inst['file'])
    try:
        func = FLAG_LOOKUP[flag.name]
    except KeyError:
        utils.con_log('"' + flag.name + '" is not a valid condition flag!')
        return False
    else:
        res = func(inst, flag)
        return res
def variant_weight(var):
    '''Read variant commands from settings and create the weight list.'''
    count = var['number', '']
    if count.isdecimal():
        count = int(count)
        weight = var['weights', '']
        if weight == '' or ',' not in weight:
            utils.con_log('Invalid weight! (' + weight + ')')
            weight = [str(i) for i in range(1,count + 1)]
        else:
            vals=weight.split(',')
            weight=[]
            if len(vals) == count:
                for i,val in enumerate(vals):
                    if val.isdecimal():
                        weight.extend([str(i+1) for tmp in range(1,int(val)+1)]) # repeat the index the correct number of times
                    else:
                        break
            if len(weight) == 0:
                utils.con_log('Failed parsing weight! (' + weight + ')')
                weight = [str(i) for i in range(1,count + 1)]
        # random.choice(weight) will now give an index with the correct probabilities.
        return weight
    else:
        return [''] # This won't append anything to the file

def add_output(inst, prop, target):
    '''Add a customisable output to an instance.'''
    inst.add_out(VLib.Output(
        prop['output',''],
        target,
        prop['input',''],
        inst_in=prop['targ_in',''],
        inst_out=prop['targ_out',''],
        ))

def resolve_inst_path(path):
    '''Allow referring to the instFile section in condtion parameters.'''
    if path.startswith('<') and path.endswith('>'):
        try:
            path = INST_FILES[path[1:-1].casefold()]
        except KeyError:
            utils.con_log(path + ' not found in instanceFiles block!')
    return path.casefold()

###########
## FLAGS ##
###########


def flag_and(inst, flag):
    for sub_flag in flag:
        if not check_flag(sub_flag, inst):
            return False
        # If the AND block is empty, return True
        return len(sub_flag.value) == 0


def flag_or(inst, flag):
    for sub_flag in flag:
        if check_flag(sub_flag, inst):
            return True
    return False


def flag_not(inst, flag):
    if len(flag.value) == 1:
        return not check_flag(flag[0], inst)
    return False


def flag_nor(inst, flag):
    return not flag_or(inst,flag)


def flag_nand(inst, flag):
    return not flag_and(inst,flag)


def flag_file_equal(inst, flag):
    return inst['file'].casefold() == resolve_inst_path(flag.value)


def flag_file_cont(inst, flag):
    return resolve_inst_path(flag.value) in inst['file'].casefold()


def flag_has_inst(inst, flag):
    '''Return true if the filename is present anywhere in the map.'''
    return resolve_inst_path(flag.value) in ALL_INST


def flag_instvar(inst, flag):
    bits = flag.value.split(' ')
    return inst.fixup[bits[0]] == bits[1]


def flag_stylevar(inst, flag):
    return bool(STYLE_VARS[flag.value.casefold()])


def flag_voice_has(inst, flag):
    return bool(VOICE_ATTR[flag.value])


def flag_music(inst, flag):
    return OPTIONS['music_id'] == flag.value


def flag_option(inst, flag):
    bits = flag.value.split(' ')
    key = bits[0].casefold()
    if key in OPTIONS:
        return OPTIONS[key] == bits[1]
    else:
        return False


def flag_game_mode(inst, flag):
    return GAME_MODE.casefold() == flag


def flag_is_preview(inst, flag):
    return IS_PREVIEW == (flag == "1")

#############
## RESULTS ##
#############


def res_change_instance(inst, res):
    '''Set the file to a value.'''
    inst['file'] = resolve_inst_path(res.value)


def res_add_suffix(inst, res):
    '''Add the specified suffix to the filename.'''
    inst['file'] += '_' + res.value

def res_set_style_var(inst, res):
    for opt in res.value:
        if opt.name == 'settrue':
            STYLE_VARS[opt.value.casefold()] = True
        elif opt.name == 'setfalse':
            STYLE_VARS[opt.value.casefold()] = False

def res_set_voice_attr(inst, res):
    for opt in res.value:
        if opt.value.casefold() == '1':
            VOICE_ATTR[opt.name] = True
        elif opt.value.casefold() == '0':
            VOICE_ATTR[opt.name] = False

def res_set_option(inst, res):
    for opt in res.value:
        if opt.name in OPTIONS['options']:
            OPTIONS['options'][opt.name] = opt.value

def res_add_inst_var(inst, res):
    '''Append the value of an instance variable to the filename.

    Pass either the variable name, or a set of value:suffix pairs for a
    lookup.
    '''
    if res.has_children():
        val = inst.fixup[res['variable', '']]
        for rep in res: # lookup the number to determine the appending value
            if rep.name == 'variable':
                continue # this isn't a lookup command!
            if rep.name == val:
                inst['file'] += '_' + rep.value
                break
    else: # append the value
        inst['file'] += '_' + inst.fixup[res.value, '']

def res_add_variant(inst, res):
    '''This allows using a random instance from a weighted group.

    A suffix will be added in the form "_var4".
    '''
    if inst['targetname', ''] == '':
        # some instances don't get names, so use the global
        # seed instead for stuff like elevators.
        random.seed(MAP_RAND_SEED + inst['origin'] + inst['angles'])
    else:
        random.seed(inst['targetname'])
    inst['file'] += "_var" + random.choice(res.value)

def res_add_global_inst(inst, res):
    '''Add one instance in a location.

    Once this is executed, it will be ignored thereafter.
    '''
    if res.value is not None:
        if (res['file'] not in GLOBAL_INSTANCES or
                res['allow_multiple', '0'] == '1'):
            # By default we will skip adding the instance
            # if was already added - this is helpful for
            # items that add to original items, or to avoid
            # bugs.
            new_inst = VLib.Entity(VMF, keys={
                "classname" : "func_instance",
                "targetname" : res['name', ''],
                "file" : resolve_inst_path(res['file']),
                "angles" : res['angles', '0 0 0'],
                "origin" : res['position', '0 0 -10000'],
                "fixup_style" : res['fixup_style', '0'],
                })
            GLOBAL_INSTANCES.append(res['file'])
            if new_inst['targetname'] == '':
                new_inst['targetname'] = "inst_"+str(unique_id())
            VMF.add_ent(new_inst)
            res.value = None # Disable this
def res_add_overlay_inst(inst, res):
    '''Add another instance on top of this one.'''
    print('adding overlay', res['file'])
    new_inst = VLib.Entity(VMF, keys={
        "classname" : "func_instance",
        "targetname" : inst['targetname'],
        "file" : resolve_inst_path(res['file', '']),
        "angles" : inst['angles'],
        "origin" : inst['origin'],
        "fixup_style" : res['fixup_style', '0'],
        })
    VMF.add_ent(new_inst)

def res_cust_output(inst, res):
    '''Add an additional output to the instance with any values.

    Always points to the targeted item.
    '''
    over_name = '@' + inst['targetname'] + '_indicator'
    for toggle in VMF.iter_ents(classname='func_instance'):
        if toggle.fixup['indicator_name', ''] == over_name:
            toggle_name = toggle['targetname']
            break
    else:
        toggle_name = '' # we want to ignore the toggle instance, if it exists

    # Make this a set to ignore repeated targetnames
    targets = {o.target for o in inst.outputs if o.target != toggle_name}

    kill_signs = res["remIndSign", '0'] == '1'
    dec_con_count = res["decConCount", '0'] == '1'
    if kill_signs or dec_con_count:
        for con_inst in VMF.iter_ents(classname='func_instance'):
            if con_inst['targetname'] in targets:
                if kill_signs and (con_inst['file'] == INST_FILE['indPanTimer'] or
                                   con_inst['file'] == INST_FILE['indPanCheck']):
                    VMF.remove_ent(con_inst)
                if dec_con_count and 'connectioncount' in con_inst:
                # decrease ConnectionCount on the ents,
                # so they can still process normal inputs
                    try:
                        val = int(con_inst.fixup['connectioncount'])
                        con_inst.fixup['connectioncount'] = str(val-1)
                    except ValueError:
                        # skip if it's invalid
                        utils.con_log(con_inst['targetname'] + ' has invalid ConnectionCount!')
    for targ in targets:
        for out in res.find_all('addOut'):
            add_output(inst, out, targ)

def res_cust_antline(inst, res):
    '''Customise the output antline texture, toggle instances.

    This allows adding extra outputs between the instance and the toggle.
    '''
    over_name = '@' + inst['targetname'] + '_indicator'
    for over in VMF.iter_ents(
            classname='info_overlay',
            targetname=over_name):
        random.seed(over['origin'])
        new_tex = random.choice(res.value[ANTLINES[over['material'].casefold()]])
        set_antline_mat(over, new_tex)

    # allow replacing the indicator_toggle instance
    if res.value['instance']:
        for toggle in VMF.iter_ents(classname='func_instance'):
            if toggle.fixup['indicator_name', ''] == over_name:
                toggle['file'] = res.value['instance']
                if len(res.value['outputs']) > 0:
                    for out in inst.outputs[:]:
                        if out.target == toggle['targetname']:
                            inst.outputs.remove(out) # remove the original outputs
                    for out in res.value['outputs']:
                        # Allow adding extra outputs to customly trigger the toggle
                        add_output(inst, out, toggle['targetname'])
                break # Stop looking!

def res_faith_mods(inst, res):
    '''Modify the trigger_catrapult that is created for ItemFaithPlate items.'''
    # Get data about the trigger this instance uses for flinging
    fixup_var = res['instvar', '']
    for trig in VMF.iter_ents(classname="trigger_catapult"):
        if inst['targetname'] in trig['targetname']:
            for out in trig.outputs:
                if out.inst_in == 'animate_angled_relay':
                    out.inst_in = res['angled_targ', 'animate_angled_relay']
                    out.input = res['angled_in', 'Trigger']
                    if fixup_var:
                        inst.fixup[fixup_var] = 'angled'
                    break
                elif out.inst_in == 'animate_straightup_relay':
                    out.inst_in = res['straight_targ', 'animate_straightup_relay']
                    out.input = res['straight_in', 'Trigger']
                    if fixup_var:
                        inst.fixup[fixup_var] = 'straight'
                    break
            else:
                continue # Check the next trigger
            break # If we got here, we've found the output - stop scanning

def res_cust_fizzler(base_inst, res):
    '''Modify a fizzler item to allow for custom brush ents.'''
    model_name = res['modelname', None]
    make_unique = res['UniqueModel', '0'] == '1'
    fizz_name = base_inst['targetname','']
    if make_unique:
        unique_ind = 0

    # search for the model instances
    model_targetnames = (
        fizz_name + '_modelStart',
        fizz_name + '_modelEnd',
        )
    for inst in VMF.iter_ents(classname='func_instance'):
        if inst['targetname', ''] in model_targetnames:
            if inst.fixup['skin', '0'] == '2':
                # This is a laserfield! We can't edit that!
                utils.con_log('CustFizzler excecuted on LaserField!')
                return
            if model_name is not None:
                if model_name == '':
                    inst['targetname'] = base_inst['targetname']
                else:
                    inst['targetname'] = base_inst['targetname'] + '-' + model_name
            if make_unique:
                unique_ind += 1
                inst['targetname'] += str(unique_id)

            for key, value in base_inst.fixup.items():
                inst.fixup[key] = value

    new_brush_config = list(res.find_all('brush'))
    if len(new_brush_config) > 0:
        for orig_brush in VMF.iter_ents(
                classname='trigger_portal_cleanser',
                targetname=fizz_name + '_brush',
                ):
            VMF.remove_ent(orig_brush)
            for config in new_brush_config:
                new_brush = orig_brush.copy()
                VMF.add_ent(new_brush)
                new_brush.keys.clear() # Wipe the original keyvalues
                new_brush['origin'] = orig_brush['origin']
                new_brush['targetname'] = fizz_name + '-' + config['name', 'brush']
                # All ents must have a classname!
                new_brush['classname'] = 'trigger_portal_cleanser'

                for prop in config['keys', []]:
                    new_brush[prop.name] = prop.value

                laserfield_conf = config.find_key('MakeLaserField', None)
                if laserfield_conf.value is not None:
                    # Resize the brush into a laserfield format, without
                    # the 128*64 parts. If the brush is 128x128, we can
                    # skip the resizing since it's already correct.
                    laser_tex = laserfield_conf['texture', 'effects/laserplane']
                    nodraw_tex = laserfield_conf['nodraw', 'tools/toolsnodraw']
                    tex_width = VLib.conv_int(laserfield_conf['texwidth', '512'], 512)
                    is_short = False
                    for side in new_brush.sides():
                        if side.mat.casefold() == 'effects/fizzler':
                            is_short = True
                            break

                    if is_short:
                        for side in new_brush.sides():
                            if side.mat.casefold() == 'effects/fizzler':
                                side.mat = laser_tex

                                uaxis = side.uaxis.split(" ")
                                vaxis = side.vaxis.split(" ")
                                # the format is like "[1 0 0 -393.4] 0.25"
                                side.uaxis = ' '.join(uaxis[:3]) + ' 0] 0.25'
                                side.vaxis = ' '.join(vaxis[:4]) + ' 0.25'
                            else:
                                side.mat = nodraw_tex
                    else:
                        # The hard part - stretching the brush.
                        convert_to_laserfield(new_brush, laser_tex, nodraw_tex, tex_width)
                else:
                    # Just change the textures
                    for side in new_brush.sides():
                        try:
                            side.mat = config[TEX_FIZZLER[side.mat.casefold()]]
                        except (KeyError, IndexError):
                            # If we fail, just use the original textures
                            pass

def convert_to_laserfield(brush, laser_tex, nodraw_tex, tex_width):
    '''Convert a fizzler into a laserfield func_brush.
    We need to stretch the brush to get rid of the side sections.
    This is the same as moving all the solids to match the
     bounding box. We first get the origin, used to figure out if
     a point should be set to the max or min axis.
    '''

    # Get the origin and bbox.
    # The origin isn't in the center, but it still works as long as it's in-between the outermost coordinates
    origin = Vec(*[int(v) for v in brush['origin'].split(' ')])
    bbox_min, bbox_max = brush.get_bbox()

    # we only want the middle one with the center, the others are
    # useless. PeTI happens to always have that in the middle.
    brush.solids = [brush.solids[1]]

    for side in brush.solids[0].sides:
        # For every coordinate, set to the maximum if it's larger than the origin.
        for v in side.planes:
            for ax in 'xyz':
                if int(v[ax]) > origin[ax]:
                    v[ax] = str(bbox_max[ax])
                else:
                    v[ax] = str(bbox_min[ax])

        # Determine the shape of this plane.
        bounds_min, bounds_max = side.get_bbox()
        dimensions = [0,0,0]
        for i in range(3):
            dimensions[i] = bounds_max[i] - bounds_min[i]
        if 2 in dimensions: # The front/back won't have this dimension
            # This must be a side of the brush.
            side.mat = nodraw_tex
        else:
            side.mat = laser_tex
            # Now we figure out the corrrect u/vaxis values for the texture.

            uaxis = side.uaxis.split(" ")
            vaxis = side.vaxis.split(" ")
            # the format is like "[1 0 0 -393.4] 0.25"
            size = 0
            offset = 0
            for i, wid in enumerate(dimensions):
                if wid > size:
                    size = int(wid)
                    offset = int(bounds_min[i])
            side.uaxis = (
                " ".join(uaxis[:3]) + " " +
                # texture offset to fit properly
                str(tex_width/size * -offset) + "] " +
                str(size/tex_width) # scaling
                )
            # heightwise it's always the same
            side.vaxis = (" ".join(vaxis[:3]) + " 256] 0.25")


FLAG_LOOKUP = {
    'and': flag_and,
    'or': flag_or,
    'not': flag_not,
    'nor': flag_nor,
    'nand': flag_nand,
    'instance': flag_file_equal,
    'instpart': flag_file_cont,
    'instvar': flag_instvar,
    'hasinst': flag_has_inst,
    'stylevar': flag_stylevar,
    'has': flag_voice_has,
    'hasmusic': flag_music,
    'ifmode': flag_game_mode,
    'ifpreview': flag_is_preview,
    'ifoption': flag_option,
    }

RESULT_LOOKUP = {
    "changeinstance": res_change_instance,
    'suffix': res_add_suffix,
    'instvar': res_add_inst_var,
    "variant": res_add_variant,
    "addglobal": res_add_global_inst,
    "addoverlay": res_add_overlay_inst,
    "custoutput": res_cust_output,
    "custantline": res_cust_antline,
    "custfizzler": res_cust_fizzler,
    "faithmods": res_faith_mods,
    "stylevar": res_set_style_var,
    "has": res_set_voice_attr,
    "setoption": res_set_option,
    }