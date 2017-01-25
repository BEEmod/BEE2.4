"""Results for custom fizzlers."""
import conditions
import srctools
import utils
import vbsp
import instanceLocs
import comp_consts as const
import template_brush
from conditions import (
    make_result, meta_cond,
    ITEM_CLASSES, CONNECTIONS
)
from srctools import Vec, Property, VMF, Entity, Solid, Output
from vbsp import TEX_FIZZLER

from typing import List, Dict

LOGGER = utils.getLogger(__name__, alias='cond.fizzler')

FIZZ_BRUSH_ENTS = {}  # The brush entities we generated, used when merging.
# Key = (conf id, targetname)


@make_result('custFizzler', 'custFizz', 'customFizzler', 'customFizz')
def res_cust_fizzler(base_inst: Entity, res: Property):
    """Customises the various components of a custom fizzler item.

    This should be executed on the base instance. Brush and MakeLaserField
    are not permitted on laserfield barriers.
    When executed, the $is_laser variable will be set on the base.
    Options:
        * ModelName: sets the targetname given to the model instances.
        * UniqueModel: If true, each model instance will get a suffix to
            allow unique targetnames.
        * Brush: A brush entity that will be generated (the original is
         deleted.) This cannot be used on laserfields.
            * Name is the instance name for the brush
            * Left/Right/Center/Short/Nodraw are the textures used
            * Keys are a block of keyvalues to be set. Targetname and
              Origin are auto-set.
            * Thickness will change the thickness of the fizzler if set.
              By default it is 2 units thick.
            * Outputs is a block of outputs (laid out like in VMFs). The
              targetnames will be localised to the instance.
            * MergeBrushes, if true will merge this brush set into one
              entity for each fizzler. This is useful for non-fizzlers to
              reduce the entity count.
            * SimplifyBrush, if true will merge the three parts into one brush.
              All sides will receive the "nodraw" texture at 0.25 scale.
            * MaterialModify generates material_modify_controls to control
              the brush. One is generated for each texture used in the brush.
              This has subkeys 'name' and 'var' - the entity name and shader
              variable to be modified. MergeBrushes must be enabled if this
              is present.
        * MakeLaserField generates a brush stretched across the whole
          area.
            * Name, keys and thickness are the same as the regular Brush.
            * Texture/Nodraw are the textures.
            * Width is the pixel width of the laser texture, used to
              scale it correctly.
    """
    model_name = res['modelname', None]
    make_unique = res.bool('UniqueModel')
    fizz_name = base_inst['targetname', '']

    # search for the model instances
    model_targetnames = (
        fizz_name + '_modelStart',
        fizz_name + '_modelEnd',
        )
    is_laser = False
    for inst in vbsp.VMF.by_class['func_instance']:
        if inst['targetname'] in model_targetnames:
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

    base_inst.fixup['$is_laser'] = is_laser

    new_brush_config = list(res.find_all('brush'))
    if len(new_brush_config) == 0:
        return  # No brush modifications

    if is_laser:
        # This is a laserfield! We can't edit those brushes!
        LOGGER.warning('CustFizzler executed on LaserField!')
        return

    # Record which materialmodify controls are used, so we can add if needed.
    # Conf id -> (brush_name, conf, [textures])
    modify_controls = {}

    for orig_brush in (
            vbsp.VMF.by_class['trigger_portal_cleanser'] &
            vbsp.VMF.by_target[fizz_name + '_brush']):
        orig_brush.remove()
        for config in new_brush_config:

            new_brush = orig_brush.copy()
            # Unique to the particular config property & fizzler name
            conf_key = (id(config), fizz_name)

            if config.bool('SimplifyBrush'):
                # Replace the brush with a simple one of the same size.
                bbox_min, bbox_max = new_brush.get_bbox()
                new_brush.solids = [vbsp.VMF.make_prism(
                    bbox_min, bbox_max,
                    mat=const.Tools.NODRAW,
                ).solid]

            should_merge = config.bool('MergeBrushes')
            if should_merge and conf_key in FIZZ_BRUSH_ENTS:
                # These are shared by both ents, but new_brush won't be added to
                # the map. (We need it though for the widening code to work).
                FIZZ_BRUSH_ENTS[conf_key].solids.extend(new_brush.solids)
            else:
                vbsp.VMF.add_ent(new_brush)
                # Don't allow restyling it
                vbsp.IGNORED_BRUSH_ENTS.add(new_brush)

                new_brush.clear_keys()  # Wipe the original keyvalues
                new_brush['origin'] = orig_brush['origin']
                new_brush['targetname'] = conditions.local_name(
                    base_inst,
                    config['name'],
                )
                # All ents must have a classname!
                new_brush['classname'] = 'trigger_portal_cleanser'

                conditions.set_ent_keys(
                    new_brush, base_inst,
                    config,
                )

                for out_prop in config.find_children('Outputs'):
                    out = Output.parse(out_prop)
                    out.comma_sep = False
                    out.target = conditions.local_name(
                        base_inst,
                        out.target
                    )
                    new_brush.add_out(out)

                if should_merge:  # The first brush...
                    FIZZ_BRUSH_ENTS[conf_key] = new_brush

            mat_mod_conf = config.find_key('MaterialModify', [])
            if mat_mod_conf:
                try:
                    used_materials = modify_controls[id(mat_mod_conf)][2]
                except KeyError:
                    used_materials = set()
                    modify_controls[id(mat_mod_conf)] = (
                        new_brush['targetname'],
                        mat_mod_conf,
                        used_materials
                    )
                # It can only parent to one brush, so it can't attach
                # to them all properly.
                if not should_merge:
                    raise Exception(
                        "MaterialModify won't work without MergeBrushes!"
                    )
            else:
                used_materials = None

            laserfield_conf = config.find_key('MakeLaserField', None)
            if laserfield_conf.value is not None:
                # Resize the brush into a laserfield format, without
                # the 128*64 parts. If the brush is 128x128, we can
                # skip the resizing since it's already correct.
                laser_tex = laserfield_conf['texture', const.Special.LASERFIELD]
                nodraw_tex = laserfield_conf['nodraw', const.Tools.NODRAW]
                tex_width = laserfield_conf.int('texwidth', 512)
                is_short = False
                for side in new_brush.sides():
                    if side == const.Fizzler.SHORT:
                        is_short = True
                        break

                if is_short:
                    for side in new_brush.sides():
                        if side == const.Fizzler.SHORT:
                            side.mat = laser_tex

                            side.uaxis.offset = 0
                            side.scale = 0.25
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
                if used_materials is not None:
                    used_materials.add(laser_tex.casefold())
            else:
                # Just change the textures
                for side in new_brush.sides():
                    try:
                        tex_cat = TEX_FIZZLER[side.mat.casefold()]
                        side.mat = config[tex_cat]
                    except (KeyError, IndexError):
                        # If we fail, just use the original textures
                        pass
                    else:
                        if used_materials is not None and tex_cat != 'nodraw':
                            used_materials.add(side.mat.casefold())

            widen_amount = config.float('thickness', 2.0)
            if widen_amount != 2:
                for brush in new_brush.solids:
                    conditions.widen_fizz_brush(
                        brush,
                        thickness=widen_amount,
                    )

    for brush_name, config, textures in modify_controls.values():
        skip_if_static = config.bool('dynamicOnly', True)
        if skip_if_static and base_inst.fixup['$connectioncount'] == '0':
            continue
        mat_mod_name = config['name', 'modify']
        var = config['var', '$outputintensity']
        if not var.startswith('$'):
            var = '$' + var
        for tex in textures:
            vbsp.VMF.create_ent(
                classname='material_modify_control',
                origin=base_inst['origin'],
                targetname=conditions.local_name(base_inst, mat_mod_name),
                materialName='materials/' + tex + '.vmt',
                materialVar=var,
                parentname=brush_name,
            )



def convert_to_laserfield(
        brush: Entity,
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

            size = 0
            offset = 0
            for i, wid in enumerate(dimensions):
                if wid > size:
                    size = int(wid)
                    offset = int(bounds_min[i])
            # texture offset to fit properly
            side.uaxis.offset= tex_width/size * -offset
            side.uaxis.scale= size/tex_width  # scaling

            # heightwise it's always the same
            side.vaxis.offset = 256
            side.vaxis.scale = 0.25

# For each direction, the two perpendicular axes and the axis it is pointing in.
PAIR_AXES = {
    (1, 0, 0):  'yz' 'x',
    (-1, 0, 0): 'yz' 'x',
    (0, 1, 0):  'xz' 'y',
    (0, -1, 0): 'xz' 'y',
    (0, 0, 1):  'xy' 'z',
    (0, 0, -1): 'xy' 'z',
}

# For singleBrush in fizzlermodelpair
PAIR_FIZZ_BRUSHES = {}  # type: Dict[str, Solid]

@make_result('fizzlerModelPair')
def res_fizzler_pair(vmf: VMF, begin_inst: Entity, res: Property):
    """Modify the instance of a fizzler to link with its pair.

    Each pair will be given a name along the lines of "fizz_name-model1334".
    Values:
        - StartInst, EndInst: The instances used for each end
        - MidInst: An instance placed every 128 units between emitters.
        - SingleInst: If the models are 1 block apart, replace both with this
            instance.
        - BrushKeys, LocalBrushKeys: If specified, a brush entity will be
           generated from some templates at the position of the models.
        - StartTemp, EndTemp, SingleTemp: Templates for the above.
        - SingleBrush: If true, the brush will be shared among the entirety
           of this fizzler.
        - uniqueName: If true, all pairs get a unique name for themselves.
          if False, all instances use the base instance name.
    """
    orig_target = begin_inst['targetname']

    if 'modelEnd' in orig_target:
        return  # We only execute starting from the start side.

    orig_target = orig_target[:-11]  # remove "_modelStart"
    end_name = orig_target + '_modelEnd'  # What we search for

    # The name all these instances get
    if srctools.conv_bool(res['uniqueName', '1'], True):
        pair_name = orig_target + '-model' + str(begin_inst.id)
    else:
        pair_name = orig_target

    orig_file = begin_inst['file']

    begin_inst['file'] = res['StartInst', orig_file]
    end_file = res['EndInst', orig_file]
    mid_file = res['MidInst', '']
    single_file = res['SingleInst', '']

    begin_inst['targetname'] = pair_name

    brush = None
    if 'brushkeys' in res:
        begin_temp = res['StartTemp', '']
        end_temp = res['EndTemp', '']
        single_temp = res['SingleTemp']

        if res.bool('SingleBrush'):
            try:
                brush = PAIR_FIZZ_BRUSHES[orig_target]
            except KeyError:
                pass
        if not brush:
            brush = vmf.create_ent(
                classname='func_brush',  # default
                origin=begin_inst['origin'],
            )
            conditions.set_ent_keys(
                brush,
                begin_inst,
                res,
                'BrushKeys',
            )
            if res.bool('SingleBrush'):
                PAIR_FIZZ_BRUSHES[orig_target] = brush
    else:
        begin_temp = end_temp = single_temp = None

    direction = Vec(0, 0, 1).rotate_by_str(begin_inst['angles'])

    begin_pos = Vec.from_str(begin_inst['origin'])
    axis_1, axis_2, main_axis = PAIR_AXES[direction.as_tuple()]
    for end_inst in vbsp.VMF.by_class['func_instance']:
        if end_inst['targetname', ''] != end_name:
            # Only examine this barrier hazard's instances!
            continue
        if end_inst['file'] != orig_file:
            # Allow adding overlays or other instances at the ends.
            continue
        end_pos = Vec.from_str(end_inst['origin'])
        if (
                begin_pos[axis_1] == end_pos[axis_1] and
                begin_pos[axis_2] == end_pos[axis_2]
        ):
            length = int(end_pos[main_axis] - begin_pos[main_axis])
            break
    else:
        LOGGER.warning('No matching pair for {}!!', orig_target)
        return

    if length == 0:
        if single_temp:
            temp_brushes = template_brush.import_template(
                single_temp,
                Vec.from_str(begin_inst['origin']),
                Vec.from_str(begin_inst['angles']),
                force_type=template_brush.TEMP_TYPES.world,
                add_to_map=False,
            )
            brush.solids.extend(temp_brushes.world)

        if single_file:
            end_inst.remove()
            begin_inst['file'] = single_file
            # Don't do anything else with end instances.
            return
    else:
        if begin_temp:
            temp_brushes = template_brush.import_template(
                begin_temp,
                Vec.from_str(begin_inst['origin']),
                Vec.from_str(begin_inst['angles']),
                force_type=template_brush.TEMP_TYPES.world,
                add_to_map=False,
            )
            brush.solids.extend(temp_brushes.world)

        if end_temp:
            temp_brushes = template_brush.import_template(
                end_temp,
                Vec.from_str(end_inst['origin']),
                Vec.from_str(end_inst['angles']),
                force_type=template_brush.TEMP_TYPES.world,
                add_to_map=False,
            )
            brush.solids.extend(temp_brushes.world)

    end_inst['targetname'] = pair_name
    end_inst['file'] = end_file

    if mid_file != '' and length:
        # Go 64 from each side, and always have at least 1 section
        # A 128 gap will have length = 0
        for dis in range(0, abs(length) + 1, 128):
            new_pos = begin_pos + direction * dis
            vbsp.VMF.create_ent(
                classname='func_instance',
                targetname=pair_name,
                angles=begin_inst['angles'],
                file=mid_file,
                origin=new_pos,
            )


@meta_cond(priority=-200, only_once=True)
def fizzler_out_relay():
    """Link fizzlers with a relay item so they can be given outputs."""
    relay_file = instanceLocs.resolve('<ITEM_BEE2_FIZZLER_OUT_RELAY>')
    if not relay_file:
        # No relay item - deactivated most likely.
        return

    # instances
    fizz_models = set()
    # base -> connections
    fizz_bases = {}

    LOGGER.info('Item classes: {}', ITEM_CLASSES)

    for fizz_id in ITEM_CLASSES['itembarrierhazard']:
        base, model = instanceLocs.resolve(
            '<{}: fizz_base, fizz_model>'.format(fizz_id)
        )
        fizz_bases[base.casefold()] = CONNECTIONS[fizz_id]
        fizz_models.add(model.casefold())

    # targetname -> base inst, connections
    fizz_by_name = {}

    # origin, normal -> targetname
    pos_to_name = {}

    marker_inst = []  # type: List[Entity]

    LOGGER.info('Fizzler data: {}', locals())

    for inst in vbsp.VMF.by_class['func_instance']:
        filename = inst['file'].casefold()
        name = inst['targetname']
        if filename in fizz_bases:
            fizz_by_name[inst['targetname']] = inst, fizz_bases[filename]
        elif filename in fizz_models:
            if inst['targetname'].endswith(('_modelStart', '_modelEnd')):
                name = inst['targetname'].rsplit('_', 1)[0]

        elif filename in relay_file:
            marker_inst.append(inst)
            # Remove the marker, we don't need that...
            inst.remove()
            continue
        else:
            continue

        pos_to_name[
            Vec.from_str(inst['origin']).as_tuple(),
            Vec(0, 0, 1).rotate_by_str(inst['angles']).as_tuple()
        ] = name

    for inst in marker_inst:
        try:
            fizz_name = pos_to_name[
                Vec.from_str(inst['origin']).as_tuple(),
                Vec(0, 0, 1).rotate_by_str(inst['angles']).as_tuple()
            ]
        except KeyError:
            # Not placed on a fizzler...
            continue
        base_inst, connections = fizz_by_name[fizz_name]

        # Copy over fixup values
        for key, val in inst.fixup.items():
            base_inst.fixup[key] = val

        for out in inst.outputs:
            new_out = out.copy()
            if out.output == 'ON':
                new_out.inst_out, new_out.output = connections.out_act
            elif out.output == 'OFF':
                new_out.inst_out, new_out.output = connections.out_deact
            else:
                # Not the marker's output somehow?
                continue
            base_inst.add_out(new_out)
