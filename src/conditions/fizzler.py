"""Results for custom fizzlers."""
from conditions import (
    make_result,
)
from vbsp import TEX_FIZZLER
from utils import Vec
import conditions
import utils
import vmfLib as VLib
import vbsp

LOGGER = utils.getLogger(__name__, alias='cond.fizzler')


@make_result('custFizzler')
def res_cust_fizzler(base_inst, res):
    """Customises the various components of a custom fizzler item.

    This should be executed on the base instance. Brush and MakeLaserField
    are ignored on laserfield barriers.
    Options:
        * ModelName: sets the targetname given to the model instances.
        * UniqueModel: If true, each model instance will get a suffix to
            allow unique targetnames.
        * Brush: A brush entity that will be generated (the original is
         deleted.)
            * Name is the instance name for the brush
            * Left/Right/Center/Short/Nodraw are the textures used
            * Keys are a block of keyvalues to be set. Targetname and
              Origin are auto-set.
            * Thickness will change the thickness of the fizzler if set.
              By default it is 2 units thick.
        * MakeLaserField generates a brush stretched across the whole
          area.
            * Name, keys and thickness are the same as the regular Brush.
            * Texture/Nodraw are the textures.
            * Width is the pixel width of the laser texture, used to
              scale it correctly.
    """
    model_name = res['modelname', None]
    make_unique = utils.conv_bool(res['UniqueModel', '0'])
    fizz_name = base_inst['targetname', '']

    # search for the model instances
    model_targetnames = (
        fizz_name + '_modelStart',
        fizz_name + '_modelEnd',
        )
    is_laser = False
    for inst in vbsp.VMF.by_class['func_instance']:
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
        LOGGER.warning('CustFizzler excecuted on LaserField!')
        return

    for orig_brush in (
            vbsp.VMF.by_class['trigger_portal_cleanser'] &
            vbsp.VMF.by_target[fizz_name + '_brush']):
        orig_brush.remove()
        for config in new_brush_config:
            new_brush = orig_brush.copy()
            vbsp.VMF.add_ent(new_brush)
            new_brush.clear_keys()  # Wipe the original keyvalues
            new_brush['origin'] = orig_brush['origin']
            new_brush['targetname'] = (
                fizz_name +
                '-' +
                config['name', 'brush']
            )
            # All ents must have a classname!
            new_brush['classname'] = 'trigger_portal_cleanser'

            conditions.set_ent_keys(
                new_brush, base_inst,
                config,
            )

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

            widen_amount = utils.conv_float(config['thickness', '2'], 2.0)
            if widen_amount != 2:
                for brush in new_brush.solids:
                    conditions.widen_fizz_brush(
                        brush,
                        thickness=widen_amount,
                    )


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


@make_result('fizzlerModelPair')
def res_fizzler_pair(begin_inst, res):
    """Modify the instance of a fizzler to link with its pair.

    Each pair will be given a name along the lines of "fizz_name-model1334".
    Values:
        - StartInst, EndInst: The instances used for each end
        - MidInst: An instance placed every 128 units between emitters.
    """
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

    direction = Vec(0, 0, 1).rotate_by_str(begin_inst['angles'])

    begin_pos = Vec.from_str(begin_inst['origin'])
    axis_1, axis_2, main_axis = PAIR_AXES[direction.as_tuple()]
    for end_inst in vbsp.VMF.by_class['func_instance']:
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
        LOGGER.warning('No matching pair for {}!!', orig_target)
        return
    end_inst['targetname'] = pair_name
    end_inst['file'] = end_file

    if mid_file != '':
        # Go 64 from each side, and always have at least 1 section
        # A 128 gap will have length = 0
        for dis in range(0, abs(length) + 1, 128):
            new_pos = begin_pos + direction*dis
            vbsp.VMF.create_ent(
                classname='func_instance',
                targetname=pair_name,
                angles=begin_inst['angles'],
                file=mid_file,
                origin=new_pos.join(' '),
            )