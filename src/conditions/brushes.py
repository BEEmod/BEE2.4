"""Results relating to brushwork."""
from collections import defaultdict
import random

from conditions import (
    make_result, make_result_setup, RES_EXHAUSTED,
    SOLIDS, MAT_TYPES, TEMPLATES, TEMP_TYPES
)
from property_parser import Property
from utils import Vec
import utils
import conditions
import vmfLib as VLib
import vbsp

LOGGER = utils.getLogger(__name__)


# The spawnflags that we need to toggle for each classname
FLAG_ROTATING = {
    'func_rotating': {
        'rev': 2,  # Spin counterclockwise
        'x': 4,  # Spinning in X axis
        'y': 8,  # Spin in Y axis
        'solid_flags': 64,  # 'Not solid'
    },
    'func_door_rotating': {
        'rev': 2,
        'x': 64,
        'y': 128,
        'solid_flags': 8 | 4,  # 'Non-solid to player', 'passable'
    },
    'func_rot_button': {
        'rev': 2,
        'x': 64,
        'y': 128,
        'solid_flags': 1,  # 'Not solid'
    },
    'momentary_rot_button': {
        'x': 64,
        'z': 128,
        # Reversed is set by keyvalue
        'solid_flags': 1,  # 'Not solid'
    },
    'func_platrot': {
        'x': 64,
        'y': 128,
        'solid_flags': 0,  # There aren't any
    }
}


@make_result('GenRotatingEnt')
def res_fix_rotation_axis(ent, res):
    """Generate a `func_rotating`, `func_door_rotating` or any similar entity.

    This uses the orientation of the instance to detemine the correct
    spawnflags to make it rotate in the correct direction. The brush
    will be 2x2x2 units large, and always set to be non-solid.
    - `Pos` and `name` are local to the
      instance, and will set the `origin` and `targetname` respectively.
    - `Keys` are any other keyvalues to be be set.
    - `Flags` sets additional spawnflags. Multiple values may be
       separated by '+', and will be added together.
    - `Classname` specifies which entity will be created, as well as
       which other values will be set to specify the correct orientation.
    - `AddOut` is used to add outputs to the generated entity. It takes
       the options `Output`, `Target`, `Input`, `Param` and `Delay`. If
       `Inst_targ` is defined, it will be used with the input to construct
       an instance proxy input. If `OnceOnly` is set, the output will be
       deleted when fired.

    Permitted entities:
     * `func_rotating`
     * `func_door_rotating`
     * `func_rot_button`
     * `func_platrot`
    """
    des_axis = res['axis', 'z'].casefold()
    reverse = utils.conv_bool(res['reversed', '0'])
    door_type = res['classname', 'func_door_rotating']

    # Extra stuff to apply to the flags (USE, toggle, etc)
    flags = sum(map(
        # Add together multiple values
        utils.conv_int,
        res['flags', '0'].split('+')
    ))

    name = res['name', '']
    if not name.startswith('@'):
        # If a local name is given, add it to the instance targetname.
        # It the name given is '', set to the instance's name.
        # If it has an @, don't change it!
        name = ent['targetname', ''] + (('-' + name) if name else '')

    axis = Vec(
        x=int(des_axis == 'x'),
        y=int(des_axis == 'y'),
        z=int(des_axis == 'z'),
    ).rotate_by_str(ent['angles', '0 0 0'])

    pos = Vec.from_str(
        res['Pos', '0 0 0']
    ).rotate_by_str(ent['angles', '0 0 0'])
    pos += Vec.from_str(ent['origin', '0 0 0'])

    door_ent = vbsp.VMF.create_ent(
        classname=door_type,
        targetname=name,
        origin=pos.join(' '),
    )

    conditions.set_ent_keys(door_ent, ent, res)

    for output in res.find_all('AddOut'):
        door_ent.add_out(VLib.Output(
            out=output['Output', 'OnUse'],
            inp=output['Input', 'Use'],
            targ=output['Target', ''],
            inst_in=output['Inst_targ', None],
            param=output['Param', ''],
            delay=utils.conv_float(output['Delay', '']),
            times=(
                1 if
                utils.conv_bool(output['OnceOnly', False])
                else -1),
        ))

    # Generate brush
    door_ent.solids = [vbsp.VMF.make_prism(pos - 1, pos + 1).solid]

    if axis.x > 0 or axis.y > 0 or axis.z > 0:
        # If it points forward, we need to reverse the rotating door
        reverse = not reverse

    flag_values = FLAG_ROTATING[door_type]
    # Make the door always non-solid!
    flags |= flag_values.get('solid_flags', 0)
    # Add or remove flags as needed.
    # flags |= bit sets it to 1.
    # flags |= ~bit sets it to 0.
    if axis.x != 0:
        flags |= flag_values.get('x', 0)
    else:
        flags &= ~flag_values.get('x', 0)

    if axis.y != 0:
        flags |= flag_values.get('y', 0)
    else:
        flags &= ~flag_values.get('y', 0)

    if axis.z != 0:
        flags |= flag_values.get('z', 0)
    else:
        flags &= ~flag_values.get('z', 0)

    if door_type == 'momentary_rot_button':
        door_ent['startdirection'] = '1' if reverse else '-1'
    else:
        if reverse:
            flags |= flag_values.get('rev', 0)
        else:
            flags &= ~flag_values.get('rev', 0)
    door_ent['spawnflags'] = str(flags)


@make_result('AlterTexture', 'AlterTex', 'AlterFace')
def res_set_texture(inst, res):
    """Set the brush face at a location to a particular texture.

    pos is the position, relative to the instance
      (0 0 0 is the floor-surface).
    dir is the normal of the texture.
    If gridPos is true, the position will be snapped so it aligns with
     the 128 brushes (Useful with fizzler/light strip items).

    tex is the texture used.
    If tex begins and ends with '<>', certain
    textures will be used based on style:
    - If tex is '<special>', the brush will be given a special texture
      like angled and clear panels.
    - '<white>' and '<black>' will use the regular textures for the
      given color.
    - '<white-2x2>', '<white-4x4>', '<black-2x2>', '<black-4x4'> will use
      the given wall-sizes. If on floors or ceilings these always use 4x4.
    - '<2x2>' or '<4x4>' will force to the given wall-size, keeping color.
    - '<special-white>' and '<special-black>' will use a special texture
       of the given color.
    If tex begins and ends with '[]', it is an option in the 'Textures' list.
    These are composed of a group and texture, separated by '.'. 'white.wall'
    are the white wall textures; 'special.goo' is the goo texture.
    """
    import vbsp
    pos = Vec.from_str(res['pos', '0 0 0'])
    pos.z -= 64  # Subtract so origin is the floor-position
    pos = pos.rotate_by_str(inst['angles', '0 0 0'])

    # Relative to the instance origin
    pos += Vec.from_str(inst['origin', '0 0 0'])

    norm = Vec.from_str(res['dir', '0 0 -1']).rotate_by_str(
        inst['angles', '0 0 0']
    )

    if utils.conv_bool(res['gridpos', '0']):
        for axis in 'xyz':
            # Don't realign things in the normal's axis -
            # those are already fine.
            if not norm[axis]:
                pos[axis] //= 128
                pos[axis] *= 128
                pos[axis] += 64

    brush = SOLIDS.get(pos.as_tuple(), None)
    ':type brush: solidGroup'

    if not brush or brush.normal != norm:
        return

    tex = res['tex']

    if tex.startswith('[') and tex.endswith(']'):
        brush.face.mat = vbsp.get_tex(tex[1:-1])
        brush.face.mat = tex
    elif tex.startswith('<') and tex.endswith('>'):
        # Special texture names!
        tex = tex[1:-1].casefold()
        if tex == 'white':
            brush.face.mat = 'tile/white_wall_tile003a'
        elif tex == 'black':
            brush.face.mat = 'metal/black_wall_metal_002c'

        if tex == 'black' or tex == 'white':
            # For these two, run the regular logic to apply textures
            # correctly.
            vbsp.alter_mat(
                brush.face,
                vbsp.face_seed(brush.face),
                vbsp.get_bool_opt('tile_texture_lock', True),
            )

        if tex == 'special':
            vbsp.set_special_mat(brush.face, str(brush.color))
        elif tex == 'special-white':
            vbsp.set_special_mat(brush.face, 'white')
            return
        elif tex == 'special-black':
            vbsp.set_special_mat(brush.face, 'black')

        # Do <4x4>, <white-2x4>, etc
        color = str(brush.color)
        if tex.startswith('black') or tex.endswith('white'):
            # Override the color used for 2x2/4x4 brushes
            color = tex[:5]
        if tex.endswith('2x2') or tex.endswith('4x4'):
            # 4x4 and 2x2 instructions are ignored on floors and ceilings.
            orient = vbsp.get_face_orient(brush.face)
            if orient == vbsp.ORIENT.wall:
                brush.face.mat = vbsp.get_tex(
                    color + '.' + tex[-3:]
                )
            else:
                brush.face.mat = vbsp.get_tex(
                    color + '.' + str(orient)
                )
    else:
        brush.face.mat = tex

    # Don't allow this to get overwritten later.
    vbsp.IGNORED_FACES.add(brush.face)


@make_result('AddBrush')
def res_add_brush(inst, res):
    """Spawn in a brush at the indicated points.

    - point1 and point2 are locations local to the instance, with '0 0 0'
      as the floor-position.
    - type is either 'black' or 'white'.
    - detail should be set to True/False. If true the brush will be a
      func_detail instead of a world brush.

    The sides will be textured with 1x1, 2x2 or 4x4 wall, ceiling and floor
    textures as needed.
    """
    import vbsp

    point1 = Vec.from_str(res['point1'])
    point2 = Vec.from_str(res['point2'])

    point1.z -= 64  # Offset to the location of the floor
    point2.z -= 64

    # Rotate to match the instance
    point1.rotate_by_str(inst['angles'])
    point2.rotate_by_str(inst['angles'])

    origin = Vec.from_str(inst['origin'])
    point1 += origin  # Then offset to the location of the instance
    point2 += origin

    tex_type = res['type', None]
    if tex_type not in ('white', 'black'):
        LOGGER.warning(
            'AddBrush: "{}" is not a valid brush '
            'color! (white or black)',
            tex_type,
        )
        tex_type = 'black'

    dim = point2 - point1
    dim.max(-dim)

    # Figure out what grid size and scale is needed
    # Check the dimensions in two axes to figure out the largest
    # tile size that can fit in it.
    x_maxsize = min(dim.y, dim.z)
    y_maxsize = min(dim.x, dim.z)
    if x_maxsize <= 32:
        x_grid = '4x4'
    elif x_maxsize <= 64:
        x_grid = '2x2'
    else:
        x_grid = 'wall'

    if y_maxsize <= 32:
        y_grid = '4x4'
    elif y_maxsize <= 64:
        y_grid = '2x2'
    else:
        y_grid = 'wall'

    grid_offset = origin // 128  # type: Vec

    # All brushes in each grid have the same textures for each side.
    random.seed(grid_offset.join(' ') + '-partial_block')

    solids = vbsp.VMF.make_prism(point1, point2)
    ':type solids: VLib.PrismFace'

    # Ensure the faces aren't re-textured later
    vbsp.IGNORED_FACES.update(solids.solid.sides)

    solids.north.mat = vbsp.get_tex(tex_type + '.' + y_grid)
    solids.south.mat = vbsp.get_tex(tex_type + '.' + y_grid)
    solids.east.mat = vbsp.get_tex(tex_type + '.' + x_grid)
    solids.west.mat = vbsp.get_tex(tex_type + '.' + x_grid)
    solids.top.mat = vbsp.get_tex(tex_type + '.floor')
    solids.bottom.mat = vbsp.get_tex(tex_type + '.ceiling')

    if utils.conv_bool(res['detail', False], False):
        # Add the brush to a func_detail entity
        vbsp.VMF.create_ent(
            classname='func_detail'
        ).solids = [
            solids.solid
        ]
    else:
        # Add to the world
        vbsp.VMF.add_brush(solids.solid)


@make_result_setup('TemplateBrush')
def res_import_template_setup(res):
    temp_id = res['id'].casefold()

    force = res['force', ''].casefold().split()
    if 'white' in force:
        force_colour = MAT_TYPES.white
    elif 'black' in force:
        force_colour = MAT_TYPES.black
    elif 'invert' in force:
        force_colour = 'INVERT'
    else:
        force_colour = None

    if 'world' in force:
        force_type = TEMP_TYPES.world
    elif 'detail' in force:
        force_type = TEMP_TYPES.detail
    else:
        force_type = TEMP_TYPES.default

    for size in ('2x2', '4x4', 'wall', 'special'):
        if size in force:
            force_grid = size
            break
    else:
        force_grid = None

    invert_var = res['invertVar', '']

    replace_tex = defaultdict(list)
    for prop in res.find_key('replace', []):
        replace_tex[prop.name].append(prop.value)

    replace_brush = res['replaceBrush', None]
    if replace_brush:
        replace_brush_pos = Vec.from_str(replace_brush)
        replace_brush_pos.z -= 64  # 0 0 0 defaults to the floor.
    else:
        replace_brush_pos = None

    key_values = res.find_key("Keys", [])
    if key_values:
        keys = Property("", [
            key_values,
            res.find_key("LocalKeys", []),
        ])
        # Ensure we have a 'origin' keyvalue - we automatically offset that.
        if 'origin' not in key_values:
            key_values['origin'] = '0 0 0'

        # Spawn everything as detail, so they get put into a brush
        # entity.
        force_type = TEMP_TYPES.detail
    else:
        keys = None

    return (
        temp_id,
        dict(replace_tex),
        force_colour,
        force_grid,
        force_type,
        replace_brush_pos,
        invert_var,
        keys,
    )


@make_result('TemplateBrush')
def res_import_template(inst, res):
    """Import a template VMF file, retexturing it to match orientatation.

    It will be placed overlapping the given instance.
    Options:
    - ID: The ID of the template to be inserted.
    - force: a space-seperated list of overrides. If 'white' or 'black' is
             present, the colour of tiles will be overriden. If 'invert' is
            added, white/black tiles will be swapped. If a tile size
            ('2x2', '4x4', 'wall', 'special') is included, all tiles will
            be switched to that size (if not a floor/ceiling). If 'world' or
            'detail' is present, the brush will be forced to that type.
    - replace: A block of template material -> replacement textures.
            This is case insensitive - any texture here will not be altered
            otherwise.
    - replaceBrush: The position of a brush to replace (0 0 0=the surface).
            This brush will be removed, and overlays will be fixed to use
            all faces with the same normal.
    - keys/localkeys: If set, a brush entity will instead be generated with
            these values. This overrides force world/detail. The origin is
            set automatically.
    - invertVar: If this fixup value is true, tile colour will be swapped to
            the opposite of the current force option.
    """
    (
        temp_id,
        replace_tex,
        force_colour,
        force_grid,
        force_type,
        replace_brush_pos,
        invert_var,
        key_block,
    ) = res.value

    if temp_id not in TEMPLATES:
        # The template map is read in after setup is performed, so
        # it must be checked here!
        # We don't want an error, just quit
        LOGGER.warning('"{}" not a valid template!', temp_id)
        return

    if invert_var != '' and utils.conv_bool(inst.fixup[invert_var]):
        force_colour = conditions.TEMP_COLOUR_INVERT[force_colour]

    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles', '0 0 0'])
    temp_data = conditions.import_template(
        temp_id,
        origin,
        angles,
        targetname=inst['targetname', ''],
        force_type=force_type,
    )
    conditions.retexture_template(
        temp_data,
        origin,
        replace_tex,
        force_colour,
        force_grid,
    )

    if key_block is not None:
        conditions.set_ent_keys(temp_data.detail, inst, key_block)
        br_origin = Vec.from_str(key_block.find_key('keys')['origin'])
        br_origin.localise(origin, angles)
        temp_data.detail['origin'] = br_origin
        # Add it to the list of ignored brushes, so vbsp.change_brush() doesn't
        # modify it.
        vbsp.IGNORED_BRUSH_ENTS.add(temp_data.detail)

    # This is the original brush the template is replacing. We fix overlay
    # face IDs, so this brush is replaced by the faces in the template pointing
    # the same way.
    if replace_brush_pos is None:
        return

    pos = Vec(replace_brush_pos).rotate(angles.x, angles.y, angles.z)
    pos += origin

    try:
        brush_group = SOLIDS[pos.as_tuple()]
    except KeyError:
        return

    vbsp.VMF.remove_brush(brush_group.solid)
    new_ids = []

    all_brushes = temp_data.world
    # Overlays can't be applied to entities (other than func_detail).
    if temp_data.detail is not None and key_block is None:
        all_brushes.extend(temp_data.detail.solids)

    for brush in all_brushes:  # type: VLib.Solid
        for face in brush.sides:
            # Only faces pointing the same way!
            if face.normal() == brush_group.normal:
                # Skip tool brushes (nodraw, player clips..)
                if face.mat.casefold().startswith('tools/'):
                    continue
                new_ids.append(str(face.id))

    if new_ids:
        conditions.reallocate_overlays({
            str(brush_group.face.id): new_ids,
        })


@make_result('HollowBrush')
def res_hollow_brush(inst, res):
    """Hollow out the attached brush, as if EmbeddedVoxel was set.

    This just removes the surface if it's already an embeddedVoxel. This allows
    multiple items to embed thinly in the same block without affecting each
    other.
    """
    loc = Vec(0, 0, -64).rotate_by_str(inst['angles'])
    loc += Vec.from_str(inst['origin'])

    try:
        group = SOLIDS[loc.as_tuple()]
    except KeyError:
        LOGGER.warning('No brush for hollowing at ({})', loc)
        return  # No brush here?

    conditions.hollow_block(
        group,
        remove_orig_face=utils.conv_bool(res['RemoveFace', False])
    )
