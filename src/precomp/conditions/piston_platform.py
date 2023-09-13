"""Handles generating Piston Platforms with specific logic."""
from typing import Dict, Optional

from precomp import packing, template_brush, conditions
import srctools.logger
from consts import FixupVars
from precomp.connections import ITEMS
from precomp.instanceLocs import resolve_one as resolve_single
from srctools import Entity, Matrix, VMF, Keyvalues, Output, Vec
from precomp.texturing import GenCat
from precomp.tiling import TILES, Panel


COND_MOD_NAME = 'Piston Platform'

LOGGER = srctools.logger.get_logger(__name__, 'cond.piston_plat')

INST_NAMES = [
    # Static bottom pistons
    'static_1',
    'static_2',
    'static_3',
    # 4 can't happen, if it's not moving the whole thing isn't - fullstatic would be used.

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


@conditions.make_result('PistonPlatform')
def res_piston_plat(vmf: VMF, res: Keyvalues) -> conditions.ResultCallable:
    """Generates piston platforms with optimized logic.

    This does assume the item behaves similar to the original platform, and will use that VScript.

    The first thing this result does is determine if the piston is able to move (has inputs, or
    automatic mode is enabled). If it cannot, the entire piston can use `prop_static` props,
    so a single  "full static" instance is used. Otherwise, it will need to move, so
    `func_movelinears` must be generated. In this case, 4 pistons are generated. The ones below
    the bottom point set for the piston (if any) aren't going to move, so they can still be static.
    But the moving sections must be dynamic.

    So further user logic can react to the piston being static, in this case `$bottom_level` and
    `$top_level` are changed to be set to the same value - the height of the piston.

    Quite a number of instances are required. These can either be provided in the result
    configuration directly, or the "itemid" option can be provided. In that case, instances will
    be looked up under the `<ITEM_ID:bee2_pist_XXX>` names.

    Instances:
        * `fullstatic_0` - `fullstatic_4`: A fully assembled piston at the specified height, used
          when it will not move at all. The template below is not used, so this should be included
          in the instance.
        * `static_1` - `static_3`: Single piston section, below the moving ones and therefore
          doesn't need to move. 4 isn't present since if the piston is able to move, the tip/platform
          will always be moving.
        * `dynamic_1` - `dynamic_4`: Single piston section, which can move and is parented to
           `pistX`. These should probably be identical to the corresponding `static_X` instance, but
           just movable.

    Parameters:
        * `itemid`: If set, instances will be looked up on this item, as mentioned above.
        * `has_dn_fizz`: If true, enable the VScript's Think function to enable/disable fizzler
          triggers.
        * `auto_var`: This should be a 0/1 (or fixup variable containing the same) to indicate if
          the piston has automatic movement, and so cannot use the "full static" instances.
        * `source_ent`: If sounds are used, set this to the name of an entity which is used as the
          source location for the sounds.
        * `snd_start`, `snd_stop`: Soundscript / raw WAV played when the piston starts/stops moving.
        * `snd_loop`: Looping soundscript / raw WAV played while the piston moves.
        * `speed`: Speed of the piston in units per second. Defaults to 150.
        * `template`: Specifies a brush template ID used to generate the `func_movelinear`s. This
           should contain brushes for collision, each with different visgroups. This is then
           offset as required to the starting position, and tied to the appropriate entities.
           Static parts are made `func_detail`.
        * `visgroup_1`-`visgroup_3`, `visgroup_top`: Names of the visgroups in the template for each
           piston segment. Defaults to `pist_1`-`pist_4`.
    """
    # Allow reading instances direct from the ID.
    # But use direct ones first.
    item_id = res['itemid', None]
    inst_filenames = {}
    for name in INST_NAMES:
        if name in res:
            lookup = res[name]
            if lookup == '':
                # Special case, allow blank for no instance.
                inst_filenames[name] = ''
                continue
        elif item_id is not None:
            lookup = f'<{item_id}:bee2_pist_{name}>'
        else:
            raise ValueError(f'No "{name}" specified!')
        inst_filenames[name] = resolve_single(lookup, error=True)

    template = template_brush.get_template(res['template'])

    conf_visgroup_names = [
        res['visgroup_1', 'pist_1'],
        res['visgroup_2', 'pist_2'],
        res['visgroup_3', 'pist_3'],
        res['visgroup_top', 'pist_4'],
    ]

    has_dn_fizz = res.bool('has_dn_fizz')
    automatic_var = res['auto_var', '']
    source_ent = res['source_ent', '']
    snd_start = res['snd_start', '']
    snd_loop = res['snd_loop', '']
    snd_stop = res['snd_stop', '']
    speed_var = res['speed', '150']

    def modify_platform(inst: Entity) -> None:
        """Modify each platform."""
        min_pos = inst.fixup.int(FixupVars.PIST_BTM)
        max_pos = inst.fixup.int(FixupVars.PIST_TOP)
        start_up = inst.fixup.bool(FixupVars.PIST_IS_UP)
        speed = inst.fixup.substitute(speed_var)

        # Allow doing variable lookups here.
        visgroup_names = [
            conditions.resolve_value(inst, fname)
            for fname in conf_visgroup_names
        ]

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
                static_inst['file'] = fname = inst_filenames['fullstatic_' + str(position)]
                conditions.ALL_INST.add(fname)
                return

        init_script = f'SPAWN_UP <- {"true" if start_up else "false"}'

        if snd_start and snd_stop:
            packing.pack_files(vmf, snd_start, snd_stop, file_type='sound')
            init_script += f'; START_SND <- `{snd_start}`; STOP_SND <- `{snd_stop}`'
        elif snd_start:
            packing.pack_files(vmf, snd_start, file_type='sound')
            init_script += f'; START_SND <- `{snd_start}`'
        elif snd_stop:
            packing.pack_files(vmf, snd_stop, file_type='sound')
            init_script += f'; STOP_SND <- `{snd_stop}`'

        script_ent = vmf.create_ent(
            classname='info_target',
            targetname=conditions.local_name(inst, 'script'),
            vscripts='BEE2/piston/common.nut',
            vscript_init_code=init_script,
            origin=inst['origin'],
        )

        if has_dn_fizz:
            script_ent['thinkfunction'] = 'FizzThink'

        if start_up:
            st_pos, end_pos = max_pos, min_pos
        else:
            st_pos, end_pos = min_pos, max_pos

        script_ent.add_out(
            Output('OnUser1', '!self', 'RunScriptCode', f'moveto({st_pos})'),
            Output('OnUser2', '!self', 'RunScriptCode', f'moveto({end_pos})'),
        )

        origin = Vec.from_str(inst['origin'])
        orient = Matrix.from_angstr(inst['angles'])
        off = orient.up(128)
        move_ang = off.to_angle()

        # Index -> func_movelinear.
        pistons: Dict[int, Entity] = {}

        static_ent = vmf.create_ent('func_brush', origin=origin)

        for pist_ind in [1, 2, 3, 4]:
            pist_ent = inst.copy()
            vmf.add_ent(pist_ent)

            if pist_ind <= min_pos:
                # It's below the lowest position, so it can be static.
                pist_ent['file'] = fname = inst_filenames['static_' + str(pist_ind)]
                pist_ent['origin'] = brush_pos = origin + pist_ind * off
                temp_targ = static_ent
            else:
                # It's a moving component.
                pist_ent['file'] = fname = inst_filenames['dynamic_' + str(pist_ind)]
                if pist_ind > max_pos:
                    # It's 'after' the highest position, so it never extends.
                    # So simplify by merging those all.
                    # The max pos was evaluated earlier, so this must be set.
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
                        targetname=conditions.local_name(pist_ent, f'pist{pist_ind}'),
                        origin=brush_pos - off,
                        movedir=move_ang,
                        startposition=start_up,
                        movedistance=128,
                        speed=speed,
                    )
                    if pist_ind - 1 in pistons:
                        pistons[pist_ind]['parentname'] = conditions.local_name(
                            pist_ent, f'pist{pist_ind - 1}',
                        )

            if fname:
                conditions.ALL_INST.add(fname.casefold())
            else:
                # No actual instance, remove.
                pist_ent.remove()

            temp_result = template_brush.import_template(
                vmf,
                template,
                brush_pos,
                orient,
                force_type=template_brush.TEMP_TYPES.world,
                add_to_map=False,
                additional_visgroups={visgroup_names[pist_ind - 1]},
            )
            temp_targ.solids.extend(temp_result.world)

            template_brush.retexture_template(
                temp_result,
                origin,
                pist_ent.fixup,
                generator=GenCat.PANEL,
            )

        # Associate any set panel with the same entity, if it's present.
        tile_pos = origin - orient.up(128)
        panel: Optional[Panel] = None
        try:
            tiledef = TILES[tile_pos.as_tuple(), off.norm().as_tuple()]
        except KeyError:
            pass
        else:
            for panel in tiledef.panels:
                if panel.same_item(inst):
                    break
            else:  # Checked all of them.
                panel = None

        if panel is not None:
            if panel.brush_ent in vmf.entities and not panel.brush_ent.solids:
                panel.brush_ent.remove()
            panel.brush_ent = pistons[max(pistons.keys())]
            panel.offset = st_pos * off

        if not static_ent.solids and (panel is None or panel.brush_ent is not static_ent):
            static_ent.remove()

        if snd_loop:
            script_ent['classname'] = 'ambient_generic'
            script_ent['message'] = snd_loop
            script_ent['health'] = 10  # Volume
            script_ent['pitch'] = 100
            script_ent['spawnflags'] = 16  # Start silent, looped.
            script_ent['radius'] = 1024

            if source_ent:
                # Parent is irrelevant for actual entity locations, but it
                # survives for the script to read.
                script_ent['SourceEntityName'] = script_ent['parentname'] = conditions.local_name(inst, source_ent)

    return modify_platform
