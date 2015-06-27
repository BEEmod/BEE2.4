# coding: utf-8
from decimal import Decimal
import random

from utils import Vec
from property_parser import Property
from instanceLocs import resolve as resolve_inst
import vmfLib as VLib
import utils

# Stuff we get from VBSP in init()
GLOBAL_INSTANCES = set()
OPTIONS = {}
ALL_INST = set()


conditions = []
FLAG_LOOKUP = {}
RESULT_LOOKUP = {}
RESULT_SETUP = {}

xp = utils.Vec_tuple(1, 0, 0)
xn = utils.Vec_tuple(-1, 0, 0)
yp = utils.Vec_tuple(0, 1, 0)
yn = utils.Vec_tuple(0, -1, 0)
zp = utils.Vec_tuple(0, 0, 1)
zn = utils.Vec_tuple(0, 0, -1)
DIRECTIONS = {
    # Translate these words into a normal vector
    '+x': xp,
    '-x': xn,

    '+y': yp,
    '-y': yn,

    '+z': zp,
    '-z': zn,

    'x': xp,  # For with allow_inverse
    'y': yp,
    'z': zp,

    'up': zp,
    'dn': zn,
    'down': zn,
    'floor': zp,
    'ceiling': zn,
    'ceil': zn,

    'n': yp,
    'north': yp,
    's': yn,
    'south': yn,

    'e': xp,
    'east': xp,
    'w': xn,
    'west': xn,

    'wall': 'WALL',  # Special case, not wall/ceiling
    'walls': 'WALL',
}

INST_ANGLE = {
    # The angles needed to point a PeTI instance in this direction
    # IE up = zp = floor
    zp: "0 0 0",
    zn: "0 0 0",

    xn: "0 0 0",
    yn: "0 90 0",
    xp: "0 180 0",
    yp: "0 270 0",

}

del xp, xn, yp, yn, zp, zn

class NextInstance(Exception):
    """Raised to skip to the next instance, from the SkipInstance result."""
    pass

class EndCondition(Exception):
    """Raised to skip the condition entirely, from the EndCond result."""
    pass


class Condition:
    __slots__ = ['flags', 'results', 'else_results', 'priority']

    def __init__(
            self,
            flags=None,
            results=None,
            else_results=None,
            priority=Decimal('0'),
    ):
        self.flags = flags or []
        self.results = results or []
        self.else_results = else_results or []
        self.priority = priority
        self.setup()

    def __repr__(self):
        return (
            'Condition(flags={!r}, '
            'results={!r}, else_results={!r}, '
            'priority={!r}'
        ).format(
            self.flags,
            self.results,
            self.else_results,
            self.priority,
        )

    @classmethod
    def parse(cls, prop_block):
        """Create a condition from a Property block."""
        flags = []
        results = []
        else_results = []
        priority = Decimal('0')
        for prop in prop_block:
            if prop.name == 'result':
                results.extend(prop.value)  # join multiple ones together
            elif prop.name == 'else':
                else_results.extend(prop.value)
            elif prop.name == 'priority':
                try:
                    priority = Decimal(prop.value)
                except ArithmeticError:
                    pass
            else:
                flags.append(prop)

        return cls(
            flags=flags,
            results=results,
            else_results=else_results,
            priority=priority,
        )

    def setup(self):
        """Some results need some pre-processing before they can be used.

        """
        for res in self.results[:]:
            func = RESULT_SETUP.get(res.name)
            if func:
                res.value = func(res)
                if res.value is None:
                    self.results.remove(res)

        for res in self.else_results[:]:
            func = RESULT_SETUP.get(res.name)
            if func:
                res.value = func(res)
                if res.value is None:
                    self.else_results.remove(res)


    def test(self, inst):
        """Try to satisfy this condition on the given instance."""
        success = True
        for flag in self.flags:
            if not check_flag(flag, inst):
                success = False
                break
        results = self.results if success else self.else_results
        for res in results[:]:
            try:
                func = RESULT_LOOKUP[res.name]
            except KeyError:
                utils.con_log(
                    '"{}" is not a valid condition result!'.format(
                        res.real_name,
                    )
                )
            else:
                should_del = func(inst, res)
                if should_del is True:
                    results.remove(res)

    def __lt__(self, other):
        """Condition items sort by priority."""
        if hasattr(other, 'priority'):
            return self.priority < other.priority
        return NotImplemented

    def __le__(self, other):
        """Condition items sort by priority."""
        if hasattr(other, 'priority'):
            return self.priority <= other.priority
        return NotImplemented

    def __gt__(self, other):
        """Condition items sort by priority."""
        if hasattr(other, 'priority'):
            return self.priority > other.priority
        return NotImplemented

    def __ge__(self, other):
        """Condition items sort by priority."""
        if hasattr(other, 'priority'):
            return self.priority >= other.priority
        return NotImplemented

def add_meta(func, priority, only_once=True):
    """Add a metacondtion, which executes a function at a priority level.

    Used to allow users to allow adding conditions before or after a
    transformation like the adding of quotes.
    """
    # This adds a condition result like "func" (with quotes), which cannot
    # be entered into property files.
    # The qualname will be unique across modules.
    name = '"' + func.__qualname__ + '"'
    print("Adding metacondition ({}) with priority {!s}!".format(
        name,
        priority,
    ))

    # Don't pass the prop_block onto the function,
    # it doesn't contain any useful data.
    RESULT_LOOKUP[name] = lambda inst, val: func(inst)

    cond = Condition(
        results=[Property(name, '')],
        priority=priority,
    )

    if only_once:
        cond.results.append(
            Property('endCondition', '')
        )
    conditions.append(cond)


def meta_cond(priority=0, only_once=True):
    """Decorator version of add_meta."""
    def x(func):
        add_meta(func, priority, only_once)
        return func
    return x

def make_flag(*names):
    """Decorator to add flags to the lookup."""
    def x(func):
        for name in names:
            FLAG_LOOKUP[name.casefold()] = func
        return func
    return x

def make_result(*names):
    """Decorator to add results to the lookup."""
    def x(func):
        for name in names:
            RESULT_LOOKUP[name.casefold()] = func
        return func
    return x

def make_result_setup(*names):
    """Decorator to do setup for this result."""
    def x(func):
        for name in names:
            RESULT_SETUP[name.casefold()] = func
        return func
    return x

def add(prop_block):
    """Parse and add a condition to the list."""
    con = Condition.parse(prop_block)
    if con.results or con.else_results:
        conditions.append(con)


def init(seed, inst_list, vmf_file):
    # Get a bunch of values from VBSP
    import vbsp
    global MAP_RAND_SEED, ALL_INST, VMF, STYLE_VARS, VOICE_ATTR, OPTIONS
    VMF = vmf_file
    MAP_RAND_SEED = seed
    ALL_INST = set(inst_list)
    OPTIONS = vbsp.settings
    STYLE_VARS = vbsp.settings['style_vars']
    VOICE_ATTR = vbsp.settings['has_attr']

    # Sort by priority, where higher = done later
    conditions.sort()


def check_all():
    """Check all conditions."""
    utils.con_log('Checking Conditions...')
    for condition in conditions:
        for inst in VMF.by_class['func_instance']:
                try:
                    condition.test(inst)
                except NextInstance:
                    # This is raised to immediately stop running
                    # this condition, and skip to the next instance.
                    pass
                except EndCondition:
                    # This is raised to immediately stop running
                    # this condition, and skip to the next condtion.
                    break
                if not condition.results and not condition.else_results:
                    utils.con_log('Exiting empty condition!')
                    break  # Condition has run out of results, quit early

    utils.con_log('Map has attributes: ', [
        key
        for key, value in
        VOICE_ATTR.items()
        if value
    ])
    utils.con_log('Style Vars:', dict(STYLE_VARS.items()))
    utils.con_log('Global instances: ', GLOBAL_INSTANCES)


def check_inst(inst):
    """Run all conditions on a given instance."""
    for condition in conditions:
        condition.test(inst)



def check_flag(flag, inst):
    # print('Checking {type} ({val!s} on {inst}'.format(
    #     type=flag.real_name,
    #     val=flag.value,
    #     inst=inst['file'],
    # ))
    try:
        func = FLAG_LOOKUP[flag.name]
    except KeyError:
        utils.con_log('"' + flag.name + '" is not a valid condition flag!')
        return False
    else:
        res = func(inst, flag)
        return res

@make_result_setup('variant')
def variant_weight(var):
    """Read variant commands from settings and create the weight list."""
    count = var['number', '']
    if count.isdecimal():
        count = int(count)
        weight = var['weights', '']
        if weight == '' or ',' not in weight:
            utils.con_log('Invalid weight! (' + weight + ')')
            weight = [str(i) for i in range(1, count + 1)]
        else:
            # Parse the weight
            vals = weight.split(',')
            weight = []
            if len(vals) == count:
                for i, val in enumerate(vals):
                    val = val.strip()
                    if val.isdecimal():
                        # repeat the index the correct number of times
                        weight.extend(
                            str(i+1)
                            for _ in
                            range(1, int(val)+1)
                        )
                    else:
                        # Abandon parsing
                        break
            if len(weight) == 0:
                utils.con_log('Failed parsing weight! ({!s})'.format(weight))
                weight = [str(i) for i in range(1, count + 1)]
        # random.choice(weight) will now give an index with the correct
        # probabilities.
        return weight
    else:
        return ['']  # This won't append anything to the file


def add_output(inst, prop, target):
    """Add a customisable output to an instance."""
    inst.add_out(VLib.Output(
        prop['output', ''],
        target,
        prop['input', ''],
        inst_in=prop['targ_in', ''],
        inst_out=prop['targ_out', ''],
        ))


def add_suffix(inst, suff):
    """Append the given suffix to the instance.
    """
    file = inst['file']
    old_name, dot, ext = file.partition('.')
    inst['file'] = ''.join((old_name, suff, dot, ext))

@make_flag('debug')
def debug_flag(inst, props):
    if props.has_children():
        utils.con_log('Debug:')
        utils.con_log(str(props))
        utils.con_log(str(inst))
    elif props.value.endswith('='):
        utils.con_log('Debug: {props}{inst!s}'.format(
            inst=inst,
            props=props.value,
        ))
    else:
        utils.con_log('Debug: ' + props.value)
    return True # The flag is always true

@make_result('debug')
def debug_result(inst, props):
    # Swallow the return value, so the flag isn't deleted
    debug_flag(inst, props)

@meta_cond(priority=1000, only_once=False)
def remove_blank_inst(inst):
    """Remove instances with blank file attr.

    This allows conditions to strip the instances when requested.
    """
    # If editoritems instances are set to "", PeTI will autocorrect it to
    # ".vmf" - we need to handle that too.
    if inst['file', ''] in ('', '.vmf'):
        VMF.remove_ent(inst)


@meta_cond(priority=0, only_once=True)
def fix_catapult_targets(inst):
    """Set faith plate targets to transmit to clients.

    This fixes some console spam in coop, and might improve trajectories
    for faith plates.
    """
    for targ in VMF.by_class['info_target']:
        targ['spawnflags'] = '3'  # Transmit to client, ignoring PVS

#########
# FLAGS #
#########

@make_flag('and')
def flag_and(inst, flag):
    for sub_flag in flag:
        if not check_flag(sub_flag, inst):
            return False
        # If the AND block is empty, return True
        return len(sub_flag.value) == 0


@make_flag('or')
def flag_or(inst, flag):
    for sub_flag in flag:
        if check_flag(sub_flag, inst):
            return True
    return False

@make_flag('not')
def flag_not(inst, flag):
    if len(flag.value) == 1:
        return not check_flag(flag[0], inst)
    return False


@make_flag('nor')
def flag_nor(inst, flag):
    return not flag_or(inst, flag)


@make_flag('nand')
def flag_nand(inst, flag):
    return not flag_and(inst, flag)


@make_flag('instance')
def flag_file_equal(inst, flag):
    return inst['file'].casefold() in resolve_inst(flag.value)


@make_flag('InstFlag')
def flag_file_cont(inst, flag):
    return flag.value in inst['file'].casefold()


@make_flag('hasInst')
def flag_has_inst(_, flag):
    """Return true if the filename is present anywhere in the map."""
    flags = resolve_inst(flag.value)
    return any(
        inst in flags
        for inst in
        ALL_INST
    )


@make_flag('instVar')
def flag_instvar(inst, flag):
    bits = flag.value.split(' ')
    return inst.fixup[bits[0]] == bits[1]


@make_flag('styleVar')
def flag_stylevar(_, flag):
    return STYLE_VARS[flag.value.casefold()]


@make_flag('has')
def flag_voice_has(_, flag):
    return VOICE_ATTR[flag.value.casefold()]


@make_flag('has_music')
def flag_music(_, flag):
    return OPTIONS['music_id'] == flag.value


@make_flag('ifOption')
def flag_option(_, flag):
    bits = flag.value.split(' ')
    key = bits[0].casefold()
    if key in OPTIONS:
        return OPTIONS[key] == bits[1]
    else:
        return False


@make_flag('ifMode')
def flag_game_mode(_, flag):
    import vbsp
    return vbsp.GAME_MODE.casefold() == flag.value.casefold()


@make_flag('ifPreview')
def flag_is_preview(_, flag):
    import vbsp
    return vbsp.IS_PREVIEW == utils.conv_bool(flag.value, False)

@make_flag(
    'rotation',
    'angle',
    'angles',
    'orient',
    'orientation',
    'dir',
    'direction',
)
def flag_angles(inst, flag):
    """Check that a instance is pointed in a direction."""
    angle = inst['angles', '0 0 0']

    if flag.has_children():
        targ_angle = flag['direction', '0 0 0']
        from_dir = flag['from_dir', '0 0 1']
        if from_dir.casefold() in DIRECTIONS:
            from_dir = Vec(DIRECTIONS[from_dir.casefold()])
        else:
            from_dir = Vec.from_str(from_dir, 0, 0, 1)
        allow_inverse = utils.conv_bool(flag['allow_inverse', '0'])
    else:
        targ_angle = flag.value
        from_dir = Vec(0, 0, 1)
        allow_inverse = False

    if angle == targ_angle:
        return True  # Check for exact match

    normal = DIRECTIONS.get(targ_angle.casefold(), None)
    if normal is None:
        return False  # If it's not a special angle,
        # so it failed the exact match

    angle = Vec.from_str(angle, 0, 0, 0)
    inst_normal = from_dir.rotate(angle.x, angle.y, angle.z)

    if normal == 'WALL':
        # Special case - it's not on the floor or ceiling
        return not (inst_normal == (0, 0, 1) or inst_normal == (0, 0, -1))
    else:
        return inst_normal == normal or (
            allow_inverse and -inst_normal == normal
        )

###########
# RESULTS #
###########


@make_result('rename', 'changeInstance')
def res_change_instance(inst, res):
    """Set the file to a value."""
    inst['file'] = resolve_inst(res.value)[0]


@make_result('suffix')
def res_add_suffix(inst, res):
    """Add the specified suffix to the filename."""
    add_suffix(inst, '_' + res.value)


@make_result('styleVar')
def res_set_style_var(_, res):
    for opt in res.value:
        if opt.name == 'settrue':
            STYLE_VARS[opt.value.casefold()] = True
        elif opt.name == 'setfalse':
            STYLE_VARS[opt.value.casefold()] = False
    return True  # Remove this result

@make_result('has')
def res_set_voice_attr(_, res):
    if res.has_children():
        for opt in res.value:
            VOICE_ATTR[opt.name] = True
    else:
        VOICE_ATTR[res.value.casefold()] = 1
    return True  # Remove this result


@make_result('setOption')
def res_set_option(_, res):
    for opt in res.value:
        if opt.name in OPTIONS:
            OPTIONS[opt.name] = opt.value
    return True  # Remove this result


@make_result('instVar', 'instVarSuffix')
def res_add_inst_var(inst, res):
    """Append the value of an instance variable to the filename.

    Pass either the variable name, or a set of value:suffix pairs for a
    lookup.
    """
    if res.has_children():
        val = inst.fixup[res['variable', '']]
        for rep in res:  # lookup the number to determine the appending value
            if rep.name == 'variable':
                continue  # this isn't a lookup command!
            if rep.name == val:
                add_suffix(inst, '_' + rep.value)
                break
    else:  # append the value
        add_suffix(inst, '_' + inst.fixup[res.value, ''])


@make_result('setInstVar')
def res_set_inst_var(inst, res):
    """Set an instance variable to the given value."""
    var_name, val = res.value.split(' ')
    inst.fixup[var_name] = val


@make_result('variant')
def res_add_variant(inst, res):
    """This allows using a random instance from a weighted group.

    A suffix will be added in the form "_var4".
    """
    if inst['targetname', ''] == '':
        # some instances don't get names, so use the global
        # seed instead for stuff like elevators.
        random.seed(MAP_RAND_SEED + inst['origin'] + inst['angles'])
    else:
        # We still need to use angles and origin, since things like
        # fizzlers might not get unique names.
        random.seed(inst['targetname'] + inst['origin'] + inst['angles'])
    add_suffix(inst, "_var" + random.choice(res.value))


@make_result('addGlobal')
def res_add_global_inst(_, res):
    """Add one instance in a location.

    Once this is executed, it will be ignored thereafter.
    """
    if res.value is not None:
        if (
                utils.conv_bool(res['allow_multiple', '0']) or
                res['file'] not in GLOBAL_INSTANCES):
            # By default we will skip adding the instance
            # if was already added - this is helpful for
            # items that add to original items, or to avoid
            # bugs.
            new_inst = VLib.Entity(VMF, keys={
                "classname": "func_instance",
                "targetname": res['name', ''],
                "file": resolve_inst(res['file'])[0],
                "angles": res['angles', '0 0 0'],
                "origin": res['position', '0 0 -10000'],
                "fixup_style": res['fixup_style', '0'],
                })
            GLOBAL_INSTANCES.add(res['file'])
            if new_inst['targetname'] == '':
                new_inst['targetname'] = "inst_"
                new_inst.make_unique()
            VMF.add_ent(new_inst)
    return True  # Remove this result


@make_result('addOverlay')
def res_add_overlay_inst(inst, res):
    """Add another instance on top of this one."""
    print('adding overlay', res['file'])
    overlay_inst = VMF.create_ent(
        classname='func_instance',
        targetname=inst['targetname', ''],
        file=resolve_inst(res['file', ''])[0],
        angles=inst['angles', '0 0 0'],
        origin=inst['origin'],
        fixup_style=res['fixup_style', '0'],
    )
    if utils.conv_bool(res['copy_fixup', '1']):
        # Copy the fixup values across from the original instance
        for fixup, value in inst.fixup.items():
            overlay_inst.fixup[fixup] = value


@make_result_setup('custOutput')
def res_cust_output_setup(res):
    for sub_res in res:
        if sub_res.name == 'targcondition':
            sub_res.value = Condition.parse(sub_res)
    return res.value

@make_result('custOutput')
def res_cust_output(inst, res):
    """Add an additional output to the instance with any values.

    Always points to the targeted item.
    """
    over_name = '@' + inst['targetname'] + '_indicator'
    for toggle in VMF.by_class['func_instance']:
        if toggle.fixup['indicator_name', ''] == over_name:
            toggle_name = toggle['targetname']
            break
    else:
        toggle_name = ''  # we want to ignore the toggle instance, if it exists

    # Make this a set to ignore repeated targetnames
    targets = {o.target for o in inst.outputs if o.target != toggle_name}

    kill_signs = utils.conv_bool(res["remIndSign", '0'], False)
    dec_con_count = utils.conv_bool(res["decConCount", '0'], False)
    targ_conditions = list(res.find_all("targCondition"))

    pan_files = resolve_inst('[indPan]')

    if kill_signs or dec_con_count or targ_conditions:
        for con_inst in VMF.by_class['func_instance']:
            if con_inst['targetname'] in targets:
                if kill_signs and con_inst in pan_files:
                    VMF.remove_ent(con_inst)
                if targ_conditions:
                    for cond in targ_conditions:
                        cond.value.test(con_inst)
                if dec_con_count and 'connectioncount' in con_inst.fixup:
                    # decrease ConnectionCount on the ents,
                    # so they can still process normal inputs
                    try:
                        val = int(con_inst.fixup['connectioncount'])
                        con_inst.fixup['connectioncount'] = str(val-1)
                    except ValueError:
                        # skip if it's invalid
                        utils.con_log(
                            con_inst['targetname'] +
                            ' has invalid ConnectionCount!'
                        )
    for targ in targets:
        for out in res.find_all('addOut'):
            add_output(inst, out, targ)

@make_result_setup('custAntline')
def res_cust_antline_setup(res):
    result = {
        'instance': res['instance', ''],
        'antline': [p.value for p in res.find_all('straight')],
        'antlinecorner': [p.value for p in res.find_all('corner')],
        'outputs': list(res.find_all('addOut')),
        }
    if (
            len(result['antline']) == 0 or
            len(result['antlinecorner']) == 0
            ):
        return None # remove result
    else:
        return result

@make_result('custAntline')
def res_cust_antline(inst, res):
    """Customise the output antline texture, toggle instances.

    This allows adding extra outputs between the instance and the toggle.
    """
    import vbsp

    over_name = '@' + inst['targetname'] + '_indicator'
    for over in (
            VMF.by_class['info_overlay'] &
            VMF.by_target[over_name]
            ):
        random.seed(over['origin'])
        new_tex = random.choice(
            res.value[
                vbsp.ANTLINES[
                    over['material'].casefold()
                ]
            ]
        )
        vbsp.set_antline_mat(over, new_tex, raw_mat=True)

    # allow replacing the indicator_toggle instance
    if res.value['instance']:
        for toggle in VMF.by_class['func_instance']:
            if toggle.fixup['indicator_name', ''] == over_name:
                toggle['file'] = res.value['instance']
                if len(res.value['outputs']) > 0:
                    for out in inst.outputs[:]:
                        if out.target == toggle['targetname']:
                            # remove the original outputs
                            inst.outputs.remove(out)
                    for out in res.value['outputs']:
                        # Allow adding extra outputs to customly
                        # trigger the toggle
                        add_output(inst, out, toggle['targetname'])
                break  # Stop looking!


@make_result('faithMods')
def res_faith_mods(inst, res):
    """Modify the trigger_catrapult that is created for ItemFaithPlate items.

    """
    # Get data about the trigger this instance uses for flinging
    fixup_var = res['instvar', '']
    offset = utils.conv_int(res['raise_trig', '0'])
    if offset:
        angle = Vec.from_str(inst['angles', '0 0 0'])
        offset = Vec(0, 0, offset).rotate(angle.x, angle.y, angle.z)
        ':type offset Vec'
    for trig in VMF.by_class['trigger_catapult']:
        if inst['targetname'] in trig['targetname']:
            if offset:  # Edit both the normal and the helper trigger
                trig['origin'] = (
                    Vec.from_str(trig['origin']) +
                    offset
                ).join(' ')
                for solid in trig.solids:
                    solid.translate(offset)

            for out in trig.outputs:
                if out.inst_in == 'animate_angled_relay':
                    out.inst_in = res['angled_targ', 'animate_angled_relay']
                    out.input = res['angled_in', 'Trigger']
                    if fixup_var:
                        inst.fixup[fixup_var] = 'angled'
                    break
                elif out.inst_in == 'animate_straightup_relay':
                    out.inst_in = res[
                        'straight_targ', 'animate_straightup_relay'
                    ]
                    out.input = res['straight_in', 'Trigger']
                    if fixup_var:
                        inst.fixup[fixup_var] = 'straight'
                    break

@make_result('custFizzler')
def res_cust_fizzler(base_inst, res):
    """Modify a fizzler item to allow for custom brush ents."""
    from vbsp import TEX_FIZZLER
    model_name = res['modelname', None]
    make_unique = utils.conv_bool(res['UniqueModel', '0'])
    fizz_name = base_inst['targetname', '']

    # search for the model instances
    model_targetnames = (
        fizz_name + '_modelStart',
        fizz_name + '_modelEnd',
        )
    is_laser = False
    for inst in VMF.by_class['func_instance']:
        if inst['targetname', ''] in model_targetnames:
            if inst.fixup['skin', '0'] == '2':
                is_laser = True
            if model_name is not None:
                if model_name == '':
                    inst['targetname'] = base_inst['targetname']
                else:
                    inst['targetname'] = (
                        base_inst['targetname'] +
                        '-' +
                        model_name
                    )
            if make_unique:
                inst.make_unique()

            for key, value in base_inst.fixup.items():
                inst.fixup[key] = value

    new_brush_config = list(res.find_all('brush'))
    if len(new_brush_config) == 0:
        return  # No brush modifications

    if is_laser:
        # This is a laserfield! We can't edit those brushes!
        utils.con_log('CustFizzler excecuted on LaserField!')
        return

    for orig_brush in (
            VMF.by_class['trigger_portal_cleanser'] &
            VMF.by_target[fizz_name + '_brush']):
        print(orig_brush)
        VMF.remove_ent(orig_brush)
        for config in new_brush_config:
            new_brush = orig_brush.copy()
            VMF.add_ent(new_brush)
            new_brush.clear_keys()  # Wipe the original keyvalues
            new_brush['origin'] = orig_brush['origin']
            new_brush['targetname'] = (
                fizz_name +
                '-' +
                config['name', 'brush']
            )
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
                tex_width = utils.conv_int(
                    laserfield_conf['texwidth', '512'], 512
                )
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
                    convert_to_laserfield(
                        new_brush,
                        laser_tex,
                        nodraw_tex,
                        tex_width,
                    )
            else:
                # Just change the textures
                for side in new_brush.sides():
                    try:
                        side.mat = config[
                            TEX_FIZZLER[side.mat.casefold()]
                        ]
                    except (KeyError, IndexError):
                        # If we fail, just use the original textures
                        pass


def convert_to_laserfield(
        brush: VLib.Entity,
        laser_tex: str,
        nodraw_tex: str,
        tex_width: int,
        ):
    """Convert a fizzler into a laserfield func_brush.

    We need to stretch the brush to get rid of the side sections.
    This is the same as moving all the solids to match the
    bounding box. We first get the origin, used to figure out if
    a point should be set to the max or min axis.

    :param brush: The trigger_portal_cleanser to modify.
    :param tex_width: The pixel width of the laserfield texture, used
                       to rescale it appropriately.
    :param laser_tex: The replacement laserfield texture.
    :param nodraw_tex: A replacement version of tools/nodraw.
    """

    # Get the origin and bbox.
    # The origin isn't in the center, but it still works as long as it's
    # in-between the outermost coordinates
    origin = Vec(*[int(v) for v in brush['origin'].split(' ')])
    bbox_min, bbox_max = brush.get_bbox()

    # we only want the middle one with the center, the others are
    # useless. PeTI happens to always have that in the middle.
    brush.solids = [brush.solids[1]]

    for side in brush.solids[0].sides:
        # For every coordinate, set to the maximum if it's larger than the
        # origin.
        for v in side.planes:
            for ax in 'xyz':
                if int(v[ax]) > origin[ax]:
                    v[ax] = str(bbox_max[ax])
                else:
                    v[ax] = str(bbox_min[ax])

        # Determine the shape of this plane.
        bounds_min, bounds_max = side.get_bbox()
        dimensions = bounds_max - bounds_min

        if 2 in dimensions:  # The front/back won't have this dimension
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
                str(size/tex_width)  # scaling
                )
            # heightwise it's always the same
            side.vaxis = (" ".join(vaxis[:3]) + " 256] 0.25")

make_result_setup('condition')(Condition.parse)
@make_result('condition')
def res_sub_condition(base_inst, res):
    """Check a different condition if the outer block is true."""
    res.value.test(base_inst)


@make_result('nextInstance')
def res_break(base_inst, res):
    """Skip to the next instance.

    """
    raise NextInstance

@make_result('endCondition')
def res_end_condition(base_inst, res):
    """Skip to the next condition

    """
    raise EndCondition

# For each direction, the two perpendicular axes and the axis it is pointing in.
PAIR_AXES = {
    (1, 0, 0):  'yz' 'x',
    (-1, 0, 0): 'yz' 'x',
    (0, 1, 0):  'xz' 'y',
    (0, -1, 0): 'xz' 'y',
    (0, 0, 1):  'xy' 'z',
    (0, 0, -1): 'xy' 'z',
}

@make_result('fizzlerModelPair')
def res_fizzler_pair(begin_inst, res):
    """Modify the instance of a fizzler to link with its pair."""
    orig_target = begin_inst['targetname']

    if 'modelEnd' in orig_target:
        return  # We only execute starting from the start side.

    orig_target = orig_target[:-11]  # remove "_modelStart"
    end_name = orig_target + '_modelEnd'  # What we search for

    # The name all these instances get
    pair_name = orig_target + '-model' + str(begin_inst.id)

    orig_file = begin_inst['file']

    begin_file = res['StartInst', orig_file]
    end_file = res['EndInst', orig_file]
    mid_file = res['MidInst', '']

    begin_inst['file'] = begin_file
    begin_inst['targetname'] = pair_name

    angles = Vec.from_str(begin_inst['angles'])
    # We round it to get rid of 0.00001 inprecision from the calculations.
    direction = Vec(0, 0, 1).rotate(angles.x, angles.y, angles.z)
    ':type direction: utils.Vec'

    begin_pos = Vec.from_str(begin_inst['origin'])
    axis_1, axis_2, main_axis = PAIR_AXES[direction.as_tuple()]
    for end_inst in VMF.by_class['func_instance']:
        if end_inst['targetname', ''] != end_name:
            # Only examine this barrier hazard's instances!
            continue
        end_pos = Vec.from_str(end_inst['origin'])
        if (
                begin_pos[axis_1] == end_pos[axis_1] and
                begin_pos[axis_2] == end_pos[axis_2]
                ):
            length = int(end_pos[main_axis] - begin_pos[main_axis])
            break
    else:
        utils.con_log('No matching pair for {}!!'.format(orig_target))
        return
    end_inst['targetname'] = pair_name
    end_inst['file'] = end_file

    if mid_file != '':
        # Go 64 from each side, and always have at least 1 section
        # A 128 gap will have length = 0
        for dis in range(0, abs(length) + 1, 128):
            new_pos = begin_pos + direction*dis
            VMF.create_ent(
                classname='func_instance',
                targetname=pair_name,
                angles=begin_inst['angles'],
                file=mid_file,
                origin=new_pos.join(' '),
            )

@make_result('clearOutputs', 'clearOutput')
def res_clear_outputs(inst, res):
    """Remove the outputs from an instance."""
    inst.outputs.clear()

@make_result('removeFixup')
def res_rem_fixup(inst, res):
    """Remove a fixup from the instance."""
    del inst.fixup['res']


CATWALK_TYPES = {
    utils.CONN_TYPES.straight: 'straight_128',
    utils.CONN_TYPES.corner: 'corner',
    utils.CONN_TYPES.all: 'crossjunction',
    utils.CONN_TYPES.side: 'end',
    utils.CONN_TYPES.triple: 'tjunction',
    utils.CONN_TYPES.none: 'NONE',
}


@make_result('makeCatwalk')
def res_make_catwalk(_, res):
    """Speciallised result to generate catwalks from markers.

    Only runs once, and then quits the condition list.
    """
    utils.con_log("Starting catwalk generator...")
    marker = resolve_inst(res['markerInst'])
    output_target = res['output_name', 'MARKER']

    instances = {
        name: resolve_inst(res[name, ''])[0]
        for name in
        (
            'straight_128', 'straight_256', 'straight_512',
            'corner', 'tjunction', 'crossjunction', 'end', 'stair', 'end_wall',
            'support_wall', 'support_ceil', 'support_floor', 'single_wall',
            'markerInst',
        )
    }
    # If there are no attachments remove a catwalk piece
    instances['NONE'] = ''
    if instances['end_wall'] == '':
        instances['end_wall'] = instances['end']

    connections = {}  # The directions this instance is connected by (NSEW)
    markers = {}

    for inst in VMF.by_class['func_instance']:
        if inst['file'].casefold() not in marker:
            continue
        loc = Vec.from_str(inst['origin'])
        #                             [North, South, East,  West ]
        connections[inst] = [False, False, False, False]
        markers[inst['targetname']] = inst

    if not markers:
        return True  # No catwalks!

    utils.con_log('Conn:', connections)
    utils.con_log('Markers:', markers)

    # First loop through all the markers, adding connecting sections
    for inst in markers.values():
        for conn in inst.outputs:
            if conn.output != output_target or conn.input != output_target:
                # Indicator toggles or similar, delete these
                print('Removing ', conn.target)
                for del_inst in VMF.by_target[conn.target]:
                    del_inst.remove()
                continue

            inst2 = markers[conn.target]
            print(inst['targetname'], '<->', inst2['targetname'])
            origin1 = Vec.from_str(inst['origin'])
            origin2 = Vec.from_str(inst2['origin'])
            if origin1.x != origin2.x and origin1.y != origin2.y:
                utils.con_log('Instances not aligned!')
                continue

            y_dir = origin1.x == origin2.x  # Which way the connection is
            if y_dir:
                dist = abs(origin1.y - origin2.y)
            else:
                dist = abs(origin1.x - origin2.x)
            vert_dist = origin1.z - origin2.z

            utils.con_log('Dist =', dist, ', Vert =', vert_dist)

            if dist//2 < vert_dist:
                # The stairs are 2 long, 1 high.
                utils.con_log('Not enough room for stairs!')
                continue

            if dist >= 128:
                # add straight sections in between
                x, y, z = str(origin1.x), str(origin1.y), str(origin1.z)
                if y_dir:
                    for y in range(
                            # + 128 to skip the first location
                            min(int(origin1.y), int(origin2.y)) + 128,
                            max(int(origin1.y), int(origin2.y)),
                            128):
                        VMF.create_ent(
                            classname='func_instance',
                            origin=(x + ' ' + str(y) + ' ' + z),
                            angles='0 90 0',
                            file=instances['straight_128'],
                        )
                else:
                    for x in range(
                            min(int(origin1.x), int(origin2.x)) + 128,
                            max(int(origin1.x), int(origin2.x)),
                            128):
                        VMF.create_ent(
                            classname='func_instance',
                            origin=(str(x) + ' ' + y + ' ' + z),
                            angles='0 0 0',
                            file=instances['straight_128'],
                        )

            # Update the lists based on the directions that were set
            conn_lst1 = connections[inst]
            conn_lst2 = connections[inst2]
            if origin1.x < origin2.x:
                conn_lst1[2] = True  # E
                conn_lst2[3] = True  # W
            elif origin2.x < origin1.x:
                conn_lst1[3] = True  # W
                conn_lst2[2] = True  # E

            if origin1.y < origin2.y:
                conn_lst1[0] = True  # N
                conn_lst2[1] = True  # S
            elif origin2.y < origin1.y:
                conn_lst1[1] = True  # S
                conn_lst2[0] = True  # N

    for inst, dir_mask in connections.items():
        # Set the marker instances based on the attached walkways.
        print(inst['targetname'], dir_mask)
        angle = Vec.from_str(inst['angles'], 0, 0, 0)
        new_type, inst['angles'] = utils.CONN_LOOKUP[tuple(dir_mask)]
        inst['file'] = instances[CATWALK_TYPES[new_type]]

        normal = Vec(0, 0, 1).rotate(angle.x, angle.y, angle.z)
        ':type normal: Vec'

        if new_type is utils.CONN_TYPES.side:
            # If the end piece is pointing at a wall, switch the instance.
            if normal.z == 0:
                # Treat booleans as ints to get the direction the connection is
                # in - True == 1, False == 0
                conn_dir = Vec(
                    x=dir_mask[2] - dir_mask[3],  # +E, -W
                    y=dir_mask[0] - dir_mask[1],  # +N, -S,
                    z=0,
                )
                if normal == conn_dir:
                    inst['file'] = instances['end_wall']
            continue  # We never have normal supports on end pieces
        elif new_type is utils.CONN_TYPES.none:
            # Unconnected catwalks on the wall switch to a special instance.
            # This lets players stand next to a portal surface on the wall.
            if normal.z == 0:
                inst['file'] = instances['single_wall']
                inst['angles'] = INST_ANGLE[normal.as_tuple()]
            else:
                inst.remove()
            continue  # These don't get supports otherwise

        # Add regular supports
        if normal == (0, 0, 1):
            supp = instances['support_floor']
        elif normal == (0, 0, -1):
            supp = instances['support_ceil']
        else:
            supp = instances['support_wall']

        if supp:
            VMF.create_ent(
                classname='func_instance',
                origin=inst['origin'],
                angles=INST_ANGLE[normal.as_tuple()],
                file=supp,
            )

    utils.con_log('Finished catwalk generation!')
    return True  # Don't run this again

@make_result_setup('staticPiston')
def make_static_pist_setup(res):
    return {
        name: resolve_inst(res[name, ''])[0]
        for name in
        (
            'bottom_1', 'bottom_2', 'bottom_3',
            'static_0', 'static_1', 'static_2', 'static_3', 'static_4',
        )
    }

@make_result('staticPiston')
def make_static_pist(ent, res):
    """Convert a regular piston into a static version.

    This is done to save entities and improve lighting."""

    bottom_pos = ent.fixup['bottom_level', '-1']

    if (ent.fixup['connectioncount', '0'] != "0" or
            ent.fixup['disable_autodrop', '0'] != "0"):  # can it move?
        if int(bottom_pos) > 0:
            # The piston doesn't go fully down, use alt instances.
            val = res.value['bottom_' + bottom_pos]
            if val:  # Only if defined
                ent['file'] = val
    else:  # we are static
        val = res.value[
            'static_' + (
                ent.fixup['top_level', '1']
                if utils.conv_bool(ent.fixup['start_up'], False)
                else bottom_pos
            )
        ]
        if val:
            ent['file'] = val

@make_result('trackPlatform')
def res_track_plat(_, res):
    """Logic specific to Track Platforms.

    This allows switching the instances used depending on if the track
    is horizontal or vertical and sets the track
    targetnames to a useful value.
    """
    # Get the instances from editoritems
    (
        inst_bot_grate, inst_bottom, inst_middle,
        inst_top, inst_plat, inst_plat_oscil, inst_single
    ) = resolve_inst(res['orig_item'])
    single_plat_inst = res['single_plat', '']
    track_targets = res['track_name', '']

    track_files = [inst_bottom, inst_middle, inst_top, inst_single]
    platforms = [inst_plat, inst_plat_oscil]

    # All the track_set in the map, indexed by origin
    track_instances = {
        Vec.from_str(inst['origin']).as_tuple(): inst
        for inst in
        VMF.by_class['func_instance']
        if inst['file'].casefold() in track_files
    }
    utils.con_log('Track instances:')
    utils.con_log('\n'.join(
        '{!s}: {}'.format(k, v['file'])
        for k, v in
        track_instances.items()
    ))

    # Now we loop through all platforms in the map, and then locate their
    # track_set
    for plat_inst in VMF.by_class['func_instance']:
        if plat_inst['file'].casefold() not in platforms:
            continue  # Not a platform!

        utils.con_log('Modifying "' + plat_inst['targetname'] + '"!')

        plat_loc = Vec.from_str(plat_inst['origin'])
        angles = Vec.from_str(plat_inst['angles'])
        # The direction away from the wall/floor/ceil
        normal = Vec(0, 0, 1).rotate(
            angles.x, angles.y, angles.z
        )

        for tr_origin, first_track in track_instances.items():
            if plat_loc == tr_origin:
                # Check direction

                if normal == Vec(0, 0, 1).rotate(
                        *Vec.from_str(first_track['angles'])
                        ):
                    break
        else:
            raise Exception('Platform "{}" has no track!'.format(
                plat_inst['targetname']
            ))

        track_type = first_track['file'].casefold()
        if track_type == inst_single:
            # Track is one block long, use a single-only instance and
            # remove track!
            plat_inst['file'] = single_plat_inst
            first_track.remove()
            continue  # Next platform

        track_set = set()
        if track_type == inst_top or track_type == inst_middle:
            # search left
            track_scan(
                track_set,
                track_instances,
                first_track,
                middle_file=inst_middle,
                x_dir=-1,
            )
        if track_type == inst_bottom or track_type == inst_middle:
            # search right
            track_scan(
                track_set,
                track_instances,
                first_track,
                middle_file=inst_middle,
                x_dir=+1,
            )

        # Give every track a targetname matching the platform
        for ind, track in enumerate(track_set, start=1):
            if track_targets == '':
                track['targetname'] = plat_inst['targetname']
            else:
                track['targetname'] = (
                    plat_inst['targetname'] +
                    '-' +
                    track_targets + str(ind)
                )

        # Now figure out which way the track faces:

        # The direction horizontal track is offset
        side_dir = Vec(0, 1, 0).rotate(*Vec.from_str(first_track['angles']))

        # The direction of the platform surface
        facing = Vec(-1, 0, 0).rotate(
            angles.x, angles.y, angles.z
        )
        if side_dir == facing:
            track_facing = 'HORIZ'
        elif side_dir == -facing:
            track_facing = 'HORIZ_MIRR'
        else:
            track_facing = 'VERT'
        # Now add the suffixes
        if track_facing == 'VERT':
            if utils.conv_bool(res['vert_suffix', '']):
                for inst in track_set:
                    add_suffix(inst, '_vert')
                if utils.conv_bool(res['plat_suffix', '']):
                    add_suffix(plat_inst, '_vert')
        elif track_facing == 'HORIZ_MIRR':
            if utils.conv_bool(res['horiz_suffix', '']):
                for inst in track_set:
                    add_suffix(inst, '_horiz_mirrored')
                if utils.conv_bool(res['plat_suffix', '']):
                    add_suffix(plat_inst, '_horiz')
        else:  # == 'HORIZ'
            if utils.conv_bool(res['horiz_suffix', '']):
                for inst in track_set:
                    add_suffix(inst, '_horiz')
                if utils.conv_bool(res['plat_suffix', '']):
                    add_suffix(plat_inst, '_horiz')
    return True  # Only run once!


def track_scan(
        tr_set,
        track_inst,
        start_track: VLib.Entity,
        middle_file: str,
        x_dir: int,
        ):
    """Build a set of track instances extending from a point.
    :param track_inst: A dictionary mapping origins to track instances
    :param start_track: The instance we start on
    :param middle_file: The file for the center track piece
    :param x_dir: The direction to look (-1 or 1)
    """
    track = start_track
    move_dir = Vec(x_dir*128, 0, 0).rotate(
        *Vec.from_str(track['angles'])
    )
    while track:
        tr_set.add(track)

        next_pos = Vec.from_str(track['origin']) + move_dir
        track = track_inst.get(next_pos.as_tuple(), None)
        if track is None:
            return
        if track['file'].casefold() != middle_file:
            # If the next piece is an end section, add it then quit
            tr_set.add(track)
            return
