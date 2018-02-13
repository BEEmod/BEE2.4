"""Handles generating Piston Platforms with specific logic."""
from typing import Tuple, Dict, List

import conditions
import utils
from conditions import make_result, make_result_setup, local_name
from srctools import Entity, VMF, Property, Output, Vec, Solid
from instanceLocs import resolve_one as resolve_single
import template_brush
from connections import ITEMS
from comp_consts import FixupVars
import vbsp

COND_MOD_NAME = 'Piston Platform'

LOGGER = utils.getLogger(__name__, 'cond.piston_plat')

INST_NAMES = [
    # Static bottom pistons
    'static_1',
    'static_2',
    'static_3',
    # 4 can't happen, if it's not moving the whole thing isn't.
    # Fullstatic is used.

    # Moving pistons.
    'dynamic_1',
    'dynamic_2',
    'dynamic_3',
    'dynamic_4',

    # The entire item, when never moving.
    'fullstatic_0',
    'fullstatic_1',
    'fullstatic_2',
    'fullstatic_3',
    'fullstatic_4',
]

SOUND_LOC = 'scripts/vscripts/BEE2/piston/'

# For the start/stop sound, we need to provide them via VScript.
# (casefolded start, stop) -> (filename,code)
SOUNDS = {}  # type: Dict[Tuple[str, str], Tuple[str, str]]

SCRIPT_TEMP = '''\
STTART_SND <- "{start}";
STOP_SND <- "{stop}";
'''


@make_result_setup('PistonPlatform')
def res_piston_plat_setup(res: Property):
    # Allow reading instances direct from the ID.
    # But use direct ones first.
    item_id = res['itemid', None]
    inst = {}
    for name in INST_NAMES:
        if name in res:
            lookup = res[name]
        elif item_id is not None:
            lookup = '<{}:bee2_pist_{}>'.format(item_id, name)
        else:
            raise ValueError('No "{}" specified!'.format(name))
        inst[name] = resolve_single(lookup, error=True)

    template = template_brush.get_template(res['template'])

    visgroup_names = [
        res['visgroup_1', 'pist_1'],
        res['visgroup_2', 'pist_2'],
        res['visgroup_3', 'pist_3'],
        res['visgroup_top', 'pist_4'],
    ]

    return (
        template,
        visgroup_names,
        inst,
        res['auto_var', ''],
        res['color_var', ''],
        res['source_ent', ''],
        res['snd_start', ''],
        res['snd_loop', ''],
        res['snd_stop', ''],
    )


@make_result('PistonPlatform')
def res_piston_plat(vmf: VMF, inst: Entity, res: Property):
    """Generates piston platforms with optimized logic."""
    (
        template,
        visgroup_names,
        inst_filenames,
        automatic_var,
        color_var,
        source_ent,
        snd_start,
        snd_loop,
        snd_stop,
    ) = res.value  # type: Tuple[template_brush.Template, List[str], Dict[str, str], str, str, str, str, str, str]

    min_pos = inst.fixup.int(FixupVars.PIST_BTM)
    max_pos = inst.fixup.int(FixupVars.PIST_TOP)
    start_up = inst.fixup.bool(FixupVars.PIST_IS_UP)

    if len(ITEMS[inst['targetname']].inputs) == 0:
        # No inputs. Check for the 'auto' var if applicable.
        if automatic_var and inst.fixup.bool(automatic_var):
            pass
            # The item is automatically moving, so we generate the dynamics.
        else:
            # It's static, we just make that and exit.
            position = max_pos if start_up else min_pos
            inst.fixup[FixupVars.PIST_BTM] = position
            inst.fixup[FixupVars.PIST_TOP] = position
            static_inst = inst.copy()
            vmf.add_ent(static_inst)
            static_inst['file'] = inst_filenames['fullstatic_' + str(position)]
            return

    scripts = ['BEE2/piston/common.nut']
    vbsp.PACK_FILES.add('scripts/vscripts/BEE2/piston/common.nut')

    if snd_start or snd_stop:
        snd_key = snd_start.casefold(), snd_stop.casefold()
        try:
            snd_filename, snd_code = SOUNDS[snd_key]
        except KeyError:
            # We need to generate this.
            snd_code = SCRIPT_TEMP.format(start=snd_start, stop=snd_stop)
            snd_filename = 'snd_{:02}.nut'.format(len(SOUNDS) + 1)
            SOUNDS[snd_key] = snd_filename, snd_code

        scripts.append('BEE2/piston/' + snd_filename)

    if start_up:
        # Notify the script that we start up.
        scripts.append('BEE2/piston/spawn_up.nut')
        vbsp.PACK_FILES.add('scripts/vscripts/BEE2/piston/spawn_up.nut')

    script_ent = vmf.create_ent(
        classname='info_target',
        targetname=local_name(inst, 'script'),
        vscripts=' '.join(scripts),
        origin=inst['origin'],
    )

    if start_up:
        st_pos, end_pos = max_pos, min_pos
    else:
        st_pos, end_pos = min_pos, max_pos

    script_ent.add_out(
        Output('OnUser1', '!self', 'RunScriptCode', 'moveto({})'.format(st_pos)),
        Output('OnUser2', '!self', 'RunScriptCode', 'moveto({})'.format(end_pos)),
    )

    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles'])
    off = Vec(z=128).rotate(*angles)
    move_ang = off.to_angle()

    # Index -> func_movelinear.
    pistons = {}  # type: Dict[int, Entity]

    static_ent = vmf.create_ent('func_brush', origin=origin)

    color_var = conditions.resolve_value(inst, color_var).casefold()

    if color_var == 'white':
        top_color = template_brush.MAT_TYPES.white
    elif color_var == 'black':
        top_color = template_brush.MAT_TYPES.black
    else:
        top_color = None

    for pist_ind in range(1, 5):
        pist_ent = inst.copy()
        vmf.add_ent(pist_ent)

        if pist_ind <= min_pos:
            # It's below the lowest position, so it can be static.
            pist_ent['file'] = inst_filenames['static_' + str(pist_ind)]
            pist_ent['origin'] = brush_pos = origin + pist_ind * off
            temp_targ = static_ent
        else:
            # It's a moving component.
            pist_ent['file'] = inst_filenames['dynamic_' + str(pist_ind)]
            if pist_ind > max_pos:
                # It's 'after' the highest position, so it never extends.
                # So simplify by merging those all.
                # That's before this so it'll have to exist.
                temp_targ = pistons[max_pos]
                if start_up:
                    pist_ent['origin'] = brush_pos = origin + max_pos * off
                else:
                    pist_ent['origin'] = brush_pos = origin + min_pos * off
                pist_ent.fixup['$parent'] = 'pist' + str(max_pos)
            else:
                # It's actually a moving piston.
                if start_up:
                    brush_pos = origin + pist_ind * off
                else:
                    brush_pos = origin + min_pos * off

                pist_ent['origin'] = brush_pos
                pist_ent.fixup['$parent'] = 'pist' + str(pist_ind)

                pistons[pist_ind] = temp_targ = vmf.create_ent(
                    'func_movelinear',
                    targetname=local_name(pist_ent, 'pist' + str(pist_ind)),
                    origin=brush_pos - off,
                    movedir=move_ang,
                    startposition=start_up,
                    movedistance=128,
                    speed=150,
                )
                if pist_ind - 1 in pistons:
                    pistons[pist_ind]['parentname'] = local_name(
                        pist_ent, 'pist' + str(pist_ind - 1),
                    )

        temp_result = template_brush.import_template(
            template,
            brush_pos,
            angles,
            force_type=template_brush.TEMP_TYPES.world,
            add_to_map=False,
            additional_visgroups={visgroup_names[pist_ind - 1]},
        )
        temp_targ.solids.extend(temp_result.world)

        template_brush.retexture_template(
            temp_result,
            origin,
            pist_ent.fixup,
            force_colour=top_color,
            force_grid='special',
            no_clumping=True,
        )

    if not static_ent.solids:
        static_ent.remove()

    if snd_loop:
        script_ent['classname'] = 'ambient_generic'
        script_ent['message'] = snd_loop
        script_ent['health'] = 10  # Volume
        script_ent['pitch'] = '100'
        script_ent['spawnflags'] = 16  # Start silent, looped.
        script_ent['radius'] = 1024

        if source_ent:
            # Parent is irrelevant for actual entity locations, but it
            # survives for the script to read.
            script_ent['SourceEntityName'] = script_ent['parentname'] = local_name(inst, source_ent)


def write_vscripts(vrad_conf: Property):
    """Write script functions for sounds out for VRAD to use."""
    if not SOUNDS:
        return

    conf_block = vrad_conf.ensure_exists('InjectFiles')

    for filename, code in SOUNDS.values():
        with open('BEE2/inject/' + filename, 'w') as f:
            f.write(code)
        conf_block[filename] = SOUND_LOC + filename
