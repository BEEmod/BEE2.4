from property_parser import Property, KeyValError
from utils import Vec
import vmfLib as VLib
import utils
import voiceLine

GLOBAL_INSTANCES = []

def init(settings, vmf, seed, preview, mode):
    # Get a bunch of values from VBSP, since we can't import directly.
    global conditions, VMF, STYLE_VARS, VOICE_ATTR, MAP_RAND_SEED, IS_PREVIEW, GAME_MODE
    VMF = vmf
    conditions = settings['conditions']
    STYLE_VARS = settings['style_vars']
    VOICE_ATTR = settings['has_attr']
    MAP_RAND_SEED = map_seed
    IS_PREVIEW = preview
    GAME_MODE = mode

def check_all():
    '''Check all conditions.'''
    setup_cond()
    
    for condition in conditions:
        for inst in VMF.iter_ents(classname='func_instance'):
            run_cond(inst, condition)
            
    
def setup_cond():
    for cond in conditions:
        for res in cond['results']:
            res_name = res.name.casefold()
            if res_name == 'variant':
                res.value = variant_weight(res.value)

def run_cond(inst, cond):
    '''Try to satisfy this condition on the given instance.'''     
    sat = True
    for flag in cond['flags']:
        if not check_flag(name, flag, inst):
            sat = False
            break  
    if sat:
        inst['file'] = inst['file', ''][:-4] # our suffixes won't touch the .vmf extension
        for res in cond['results']:
            try: 
                func = RESULT_LOOKUP[res.name.casefold()]
            except KeyError:
                utils.con_log('"' + flag.name + '" is not a valid condition result!')
            else:
                func(inst, res)  
        if not inst['file'].endswith('vmf'):
            inst['file'] += '.vmf'
    
    
def check_flag(flag, inst):
    try: 
        func = FLAG_LOOKUP[flag.name.casefold()]
    except KeyError:
        utils.con_log('"' + flag.name + '" is not a valid condition flag!')
        return False
    else:
        return func(flag, inst)
        
def variant_weight(var):
    "Read variant commands from settings and create the weight list."
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
    inst.add_out(VLib.Output(
        prop['output',''],
        target,
        prop['input',''],
        inst_in=prop['targ_in',''],
        inst_out=prop['targ_out',''],
        ))
        
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
    return inst['file'].casefold() == flag.value.casefold()
    
def flag_file_cont(inst, flag):
    return flag.value.casefold() in inst['file'].casefold()
    
def flag_instvar(inst, flag):
    bits = flag.value.split(' ')
    return inst.get_fixup(bits[0]) == bits[1]
    
def flag_stylevar(inst, flag):
    return STYLE_VARS[flag.value.casefold()]
    
def flag_voice_has(inst, flag):
    return VOICE_ATTR[flag.value]
    
def flag_music(inst, flag):
    return settings['options']['music_id'] == flag.value
    
def flag_game_mode(inst, flag):
    return GAME_MODE.casefold() == val
    
def flag_is_preview(inst, flag):
    return IS_PREVIEW == (val=="1")

#############
## RESULTS ##
#############
   
def res_change_instance(inst, res):
    '''Set the file to a value.'''
    inst['file'] = res.value
    
def res_add_suffix(inst, res):
    '''Add the specified suffix to the filename.'''
    inst['file'] += '_' + res.value

def res_add_inst_var(inst, res):
    '''Append the value of an instance variable to the filename.
    
    Pass either the variable name, or a set of value:suffix pairs for a
    lookup.
    '''
    if res.has_children():
        val = inst.get_fixup(res['variable', ''])
        for rep in res: # lookup the number to determine the appending value
            if rep.name.casefold() == 'variable':
                continue # this isn't a lookup command!
            if rep.name == val:
                inst['file'] += '_' + rep.value
                break
    else: # append the value
        inst['file'] += '_' + inst.get_fixup(res.value, '')
        
def res_add_variant(inst, res):
    '''This allows using a random instance from a weighted group.
    
    A suffix will be added in the form "_var4".
    '''
    if inst['targetname', ''] == '':
        # some instances don't get names, so use the global
        # seed instead for stuff like elevators.
        random.seed(VBSP.map_seed + inst['origin'] + inst['angles'])
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
            new_inst = VLib.Entity(map, keys={
                "classname" : "func_instance",
                "targetname" : res['name', ''],
                "file" : res['file'],
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
    new_inst = VLib.Entity(map, keys={
        "classname" : "func_instance",
        "targetname" : inst['targetname'],
        "file" : res['file', ''],
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
        if toggle.get_fixup('indicator_name', '') == over_name:
            toggle_name = toggle['targetname']
            break
    else:
        toggle_name = '' # we want to ignore the toggle instance, if it exists
        
    # Make this a set to ignore repeated targetnames
    targets = {o.target for o in inst.outputs if o.target != toggle_name}
    
    kill_signs = res["remIndSign", '0'] == '1'
    dec_con_count = res["decConCount", '0'] == '1'
    if kill_signs or dec_con_count:
        for con_inst in map.iter_ents(classname='func_instance'):
            if con_inst['targetname'] in targets:
                if kill_signs and (con_inst['file'] == INST_FILE['indPanTimer'] or
                                   con_inst['file'] == INST_FILE['indPanCheck']):
                    map.remove_ent(con_inst)
                if dec_con_count and con_inst.has_fixup('connectioncount'):
                # decrease ConnectionCount on the ents,
                # so they can still process normal inputs
                    try:
                        val = int(con_inst.get_fixup('connectioncount'))
                        con_inst.set_fixup('connectioncount', str(val-1))
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
        for toggle in map.iter_ents(classname='func_instance'):
            if toggle.get_fixup('indicator_name', '') == over_name:
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
    # Get data about the trigger this instance uses for flinging
    fixup_var = res['instvar', '']
    for trig in map.iter_ents(classname="trigger_catapult"):
        if inst['targetname']  in trig['targetname']:
            for out in trig.outputs:
                if out.inst_in == 'animate_angled_relay':
                    out.inst_in = res['angled_targ', 'animate_angled_relay']
                    out.input = res['angled_in', 'Trigger']
                    if fixup_var:
                        inst.set_fixup(fixup_var, 'angled')
                    break
                elif out.inst_in == 'animate_straightup_relay':
                    out.inst_in = res['straight_targ', 'animate_straightup_relay']
                    out.input = res['straight_in', 'Trigger']
                    if fixup_var:
                        inst.set_fixup(fixup_var, 'straight')
                    break
            else:
                continue # Check the next trigger
            break # If we got here, we've found the output - stop scanning  
            
def res_set_style_var(inst, res):
    for opt in res.value:
        if opt.name.casefold() == 'settrue':
            STYLE_VARS[opt.value.casefold()] = True
        elif opt.name.casefold() == 'setfalse':
            STYLE_VARS[opt.value.casefold()] = False
            
def res_set_voice_attr(inst, res):
    for opt in res.value:
        if opt.value.casefold() == '1':
            VOICE_ATTR[opt.name] = True
        elif opt.value.casefold() == '0':
            VOICE_ATTR[opt.name] = False
            
def res_set_option(inst, res):
    for opt in res.value:
        if opt.name.casefold() in settings['options']:
            settings['options'][opt.name.casefold()] = opt.value
    
FLAG_LOOKUP = {
    'and': flag_and,
    'or': flag_or,
    'not': flag_not,
    'nor': flag_nor,
    'nand': flag_nand,
    'instance': flag_file_equal,
    'instfile': flag_file_cont,
    'instvar': flag_instvar,
    'stylevar': flag_stylevar,
    'has': flag_voice_has,
    'has_music': flag_music,
    'ifmode': flag_game_mode,
    'ifpreview': flag_is_preview,
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
    "faithmods": res_faith_mods,
    "stylevar": res_set_style_var,
    "has": res_set_voice_attr,
    "setoption": res_set_option,
    }