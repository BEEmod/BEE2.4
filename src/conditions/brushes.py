"""Results relating to brushwork."""
import random
from collections import defaultdict

import brushLoc
import conditions
import srctools.logger
import template_brush
import vbsp
import vbsp_options
import comp_consts as const
import instance_traits
from conditions import (
    make_result, make_result_setup, SOLIDS
)
from srctools import Property, NoKeyError, Vec, Output, Entity, Side, conv_bool

from typing import Dict, Tuple

COND_MOD_NAME = 'Brushes'

LOGGER = srctools.logger.get_logger(__name__)


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
def res_fix_rotation_axis(ent: Entity, res: Property):
    """Generate a `func_rotating`, `func_door_rotating` or any similar entity.

    This uses the orientation of the instance to detemine the correct
    spawnflags to make it rotate in the correct direction. The brush
    will be 2x2x2 units large, and always set to be non-solid.
    - `Pos` and `name` are local to the
      instance, and will set the `origin` and `targetname` respectively.
    - `Keys` are any other keyvalues to be be set.
    - `Flags` sets additional spawnflags. Multiple values may be
       separated by `+`, and will be added together.
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
    reverse = srctools.conv_bool(res['reversed', '0'])
    door_type = res['classname', 'func_door_rotating']

    # Extra stuff to apply to the flags (USE, toggle, etc)
    flags = sum(map(
        # Add together multiple values
        srctools.conv_int,
        res['flags', '0'].split('+')
    ))

    name = conditions.local_name(ent, res['name', ''])

    axis = Vec(**{des_axis: 1}).rotate_by_str(ent['angles', '0 0 0'])

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
        door_ent.add_out(Output(
            out=output['Output', 'OnUse'],
            inp=output['Input', 'Use'],
            targ=output['Target', ''],
            inst_in=output['Inst_targ', None],
            param=output['Param', ''],
            delay=srctools.conv_float(output['Delay', '']),
            times=(
                1 if
                srctools.conv_bool(output['OnceOnly', False])
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
def res_set_texture(inst: Entity, res: Property):
    """Set the brush face at a location to a particular texture.

    pos is the position, relative to the instance
      (0 0 0 is the floor-surface).
    dir is the normal of the texture.
    If gridPos is true, the position will be snapped so it aligns with
     the 128 brushes (Useful with fizzler/light strip items).

    tex is the texture used.
    If tex begins and ends with `<>`, certain
    textures will be used based on style:
    - `<delete>` will remove the brush entirely (it should be hollow).
      Caution should be used to ensure no leaks occur.
    - `<special>` the brush will be given a special texture
      like angled and flip panels.
    - `<white>` and `<black>` will use the regular textures for the
      given color.
    - `<white-2x2>`, `<white-4x4>`, `<black-2x2>`, `<black-4x4>` will use
      the given wall-sizes. If on floors or ceilings these always use 4x4.
    - `<2x2>` or `<4x4>` will force to the given wall-size, keeping color.
    - `<special-white>` and `<special-black>` will use a special texture
       of the given color.
    If tex begins and ends with `[]`, it is an option in the `Textures` list.
    These are composed of a group and texture, separated by `.`. `white.wall`
    are the white wall textures; `special.goo` is the goo texture.

    If `template` is set, the template should be an axis aligned cube. This
    will be rotated by the instance angles, and then the face with the same
    orientation will be applied to the face (with the rotation and texture).
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

    if srctools.conv_bool(res['gridpos', '0']):
        for axis in 'xyz':
            # Don't realign things in the normal's axis -
            # those are already fine.
            if not norm[axis]:
                pos[axis] //= 128
                pos[axis] *= 128
                pos[axis] += 64

    brush = SOLIDS.get(pos.as_tuple(), None)

    if not brush or brush.normal != norm:
        return

    face_to_mod = brush.face  # type: Side

    # Don't allow this to get overwritten later.
    vbsp.IGNORED_FACES.add(face_to_mod)

    temp = res['template', None]
    if temp:
        # Grab the scaling template and apply it to the brush.
        template_brush.get_scaling_template(temp).rotate(
            Vec.from_str(inst['angles']),
            Vec.from_str(inst['origin']),
        ).apply(face_to_mod)
        return

    tex = res['tex']

    if tex.startswith('[') and tex.endswith(']'):
        face_to_mod.mat = vbsp.get_tex(tex[1:-1])
    elif tex.startswith('<') and tex.endswith('>'):
        # Special texture names!
        tex = tex[1:-1].casefold()
        if tex == 'delete':
            vbsp.VMF.remove_brush(brush)
            return

        if tex == 'white':
            face_to_mod.mat = 'tile/white_wall_tile003a'
        elif tex == 'black':
            face_to_mod.mat = 'metal/black_wall_metal_002c'

        if tex == 'black' or tex == 'white':
            # For these two, run the regular logic to apply textures
            # correctly.
            vbsp.alter_mat(
                face_to_mod,
                vbsp.face_seed(face_to_mod),
                vbsp_options.get(bool, 'tile_texture_lock'),
            )

        if tex == 'special':
            vbsp.set_special_mat(face_to_mod, str(brush.color))
        elif tex == 'special-white':
            vbsp.set_special_mat(face_to_mod, 'white')
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
            orient = vbsp.get_face_orient(face_to_mod)
            if orient == vbsp.ORIENT.wall:
                face_to_mod.mat = vbsp.get_tex(
                    color + '.' + tex[-3:]
                )
            else:
                face_to_mod.mat = vbsp.get_tex(
                    color + '.' + str(orient)
                )
    else:
        face_to_mod.mat = tex


@make_result('AddBrush')
def res_add_brush(inst: Entity, res: Property):
    """Spawn in a brush at the indicated points.

    - `point1` and `point2` are locations local to the instance, with `0 0 0`
      as the floor-position.
    - `type` is either `black` or `white`.
    - detail should be set to `1/0`. If true the brush will be a
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

    if srctools.conv_bool(res['detail', False], False):
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
def res_import_template_setup(res: Property):
    temp_id = res['id']

    force = res['force', ''].casefold().split()
    if 'white' in force:
        force_colour = template_brush.MAT_TYPES.white
    elif 'black' in force:
        force_colour = template_brush.MAT_TYPES.black
    elif 'invert' in force:
        force_colour = 'INVERT'
    else:
        force_colour = None

    if 'world' in force:
        force_type = template_brush.TEMP_TYPES.world
    elif 'detail' in force:
        force_type = template_brush.TEMP_TYPES.detail
    else:
        force_type = template_brush.TEMP_TYPES.default

    for size in ('2x2', '4x4', 'wall', 'special'):
        if size in force:
            force_grid = size
            break
    else:
        force_grid = None

    invert_var = res['invertVar', '']
    color_var = res['colorVar', '']

    replace_tex = defaultdict(list)
    for prop in res.find_key('replace', []):
        replace_tex[prop.name].append(prop.value)

    rem_replace_brush = True
    additional_ids = set()
    transfer_overlays = '1'
    try:
        replace_brush = res.find_key('replaceBrush')
    except NoKeyError:
        replace_brush_pos = None
    else:
        if replace_brush.has_children():
            replace_brush_pos = replace_brush['Pos', '0 0 0']
            additional_ids = set(map(
                srctools.conv_int,
                replace_brush['additionalIDs', ''].split(),
            ))
            rem_replace_brush = replace_brush.bool('removeBrush', True)
            transfer_overlays = replace_brush['transferOverlay', '1']
        else:
            replace_brush_pos = replace_brush.value  # type: str

        replace_brush_pos = Vec.from_str(replace_brush_pos)
        replace_brush_pos.z -= 64  # 0 0 0 defaults to the floor.

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
        force_type = template_brush.TEMP_TYPES.detail
        outputs = [
            Output.parse(prop)
            for prop in
            res.find_children('Outputs')
        ]
    else:
        keys = None
        outputs = []
    visgroup_mode = res['visgroup', 'none'].casefold()
    if visgroup_mode not in ('none', 'choose'):
        visgroup_mode = srctools.conv_float(visgroup_mode.rstrip('%'), 0.00)
        if visgroup_mode == 0:
            visgroup_mode = 'none'

    # Generate the function which picks which visgroups to add to the map.
    if visgroup_mode == 'none':
        def visgroup_func(_):
            """none = don't add any visgroups."""
            return ()
    elif visgroup_mode == 'choose':
        def visgroup_func(groups):
            """choose = add one random group."""
            return [random.choice(groups)]
    else:
        def visgroup_func(groups):
            """Number = percent chance for each to be added"""
            for group in groups:
                val = random.uniform(0, 100)
                if val <= visgroup_mode:
                    yield group

    # If true, force visgroups to all be used.
    visgroup_force_var = res['forceVisVar', '']

    return (
        temp_id,
        dict(replace_tex),
        force_colour,
        force_grid,
        force_type,
        replace_brush_pos,
        rem_replace_brush,
        transfer_overlays,
        additional_ids,
        invert_var,
        color_var,
        visgroup_func,
        visgroup_force_var,
        keys,
        outputs,
    )


@make_result('TemplateBrush')
def res_import_template(inst: Entity, res: Property):
    """Import a template VMF file, retexturing it to match orientation.

    It will be placed overlapping the given instance.  
    Options:  
    - ID: The ID of the template to be inserted. Add visgroups to additionally
            add after a colon, comma-seperated (temp_id:vis1,vis2)
    - force: a space-seperated list of overrides. If 'white' or 'black' is
             present, the colour of tiles will be overridden. If `invert` is
            added, white/black tiles will be swapped. If a tile size
            ('2x2', '4x4', 'wall', 'special') is included, all tiles will
            be switched to that size (if not a floor/ceiling). If 'world' or
            'detail' is present, the brush will be forced to that type.
    - replace: A block of template material -> replacement textures.
            This is case insensitive - any texture here will not be altered
            otherwise. If the material starts with a '#', it is instead a
            face ID.
    - replaceBrush: The position of a brush to replace (0 0 0=the surface).
            This brush will be removed, and overlays will be fixed to use
            all faces with the same normal. Can alternately be a block:
            - Pos: The position to replace.
            - additionalIDs: Space-separated list of face IDs in the template
              to also fix for overlays. The surface should have close to a
              vertical normal, to prevent rescaling the overlay.
            - removeBrush: If true, the original brush will not be removed.
            - transferOverlay: Allow disabling transferring overlays to this
              template. The IDs will be removed instead. (This can be an instvar).
    - keys/localkeys: If set, a brush entity will instead be generated with
            these values. This overrides force world/detail.
            Specially-handled keys:
            - "origin", offset automatically.
            - "movedir" on func_movelinear - set a normal surrounded by <>,
              this gets replaced with angles.
    - colorVar: If this fixup var is set
            to `white` or `black`, that colour will be forced.
            If the value is `<editor>`, the colour will be chosen based on
            the color of the surface for ItemButtonFloor, funnels or
            entry/exit frames.
    - invertVar: If this fixup value is true, tile colour will be
            swapped to the opposite of the current force option. This applies
            after colorVar.
    - visgroup: Sets how visgrouped parts are handled. If 'none' (default),
            they are ignored. If 'choose', one is chosen. If a number, that
            is the percentage chance for each visgroup to be added.
    - visgroup_force_var: If set and True, visgroup is ignored and all groups
            are added.
    - outputs: Add outputs to the brush ent. Syntax is like VMFs, and all names
            are local to the instance.
    """
    (
        orig_temp_id,
        replace_tex,
        force_colour,
        force_grid,
        force_type,
        replace_brush_pos,
        rem_replace_brush,
        transfer_overlays,
        additional_replace_ids,
        invert_var,
        color_var,
        visgroup_func,
        visgroup_force_var,
        key_block,
        outputs,
    ) = res.value

    if ':' in orig_temp_id:
        # Split, resolve each part, then recombine.
        temp_id, visgroup = orig_temp_id.split(':', 1)
        temp_id = (
            conditions.resolve_value(inst, temp_id) + ':' +
            conditions.resolve_value(inst, visgroup)
        )
    else:
        temp_id = conditions.resolve_value(inst, orig_temp_id)

    if srctools.conv_bool(conditions.resolve_value(inst, visgroup_force_var)):
        def visgroup_func(group):
            """Use all the groups."""
            yield from group

    temp_name, visgroups = template_brush.parse_temp_name(temp_id)
    try:
        template = template_brush.get_template(temp_name)
    except template_brush.InvalidTemplateName:
        # If we did lookup, display both forms.
        if temp_id != orig_temp_id:
            LOGGER.warning(
                '{} -> "{}" is not a valid template!',
                orig_temp_id,
                temp_name
            )
        else:
            LOGGER.warning(
                '"{}" is not a valid template!',
                temp_name
            )
        # We don't want an error, just quit.
        return

    if color_var.casefold() == '<editor>':
        # Check traits for the colour it should be.
        traits = instance_traits.get(inst)
        if 'white' in traits:
            force_colour = template_brush.MAT_TYPES.white
        elif 'black' in traits:
            force_colour = template_brush.MAT_TYPES.black
        else:
            LOGGER.warning(
                '"{}": Instance "{}" '
                "isn't one with inherent color!",
                temp_id,
                inst['file'],
            )
    elif color_var:
        color_val = conditions.resolve_value(inst, color_var).casefold()

        if color_val == 'white':
            force_colour = template_brush.MAT_TYPES.white
        elif color_val == 'black':
            force_colour = template_brush.MAT_TYPES.black
    # else: no color var

    if srctools.conv_bool(conditions.resolve_value(inst, invert_var)):
        force_colour = template_brush.TEMP_COLOUR_INVERT[force_colour]
    # else: False value, no invert.

    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles', '0 0 0'])
    temp_data = template_brush.import_template(
        template,
        origin,
        angles,
        targetname=inst['targetname', ''],
        force_type=force_type,
        visgroup_choose=visgroup_func,
        add_to_map=True,
        additional_visgroups=visgroups,
    )

    if key_block is not None:
        conditions.set_ent_keys(temp_data.detail, inst, key_block)
        br_origin = Vec.from_str(key_block.find_key('keys')['origin'])
        br_origin.localise(origin, angles)
        temp_data.detail['origin'] = br_origin

        move_dir = temp_data.detail['movedir', '']
        if move_dir.startswith('<') and move_dir.endswith('>'):
            move_dir = Vec.from_str(move_dir).rotate(*angles)
            temp_data.detail['movedir'] = move_dir.to_angle()

        for out in outputs:  # type: Output
            out = out.copy()
            out.target = conditions.local_name(inst, out.target)
            temp_data.detail.add_out(out)

        # Add it to the list of ignored brushes, so vbsp.change_brush() doesn't
        # modify it.
        vbsp.IGNORED_BRUSH_ENTS.add(temp_data.detail)

    try:
        # This is the original brush the template is replacing. We fix overlay
        # face IDs, so this brush is replaced by the faces in the template
        # pointing
        # the same way.
        if replace_brush_pos is None:
            raise KeyError  # Not set, raise to jump out of the try block

        pos = Vec(replace_brush_pos).rotate(angles.x, angles.y, angles.z)
        pos += origin
        brush_group = SOLIDS[pos.as_tuple()]
    except KeyError:
        # Not set or solid group doesn't exist, skip..
        pass
    else:
        LOGGER.info('IDS: {}', additional_replace_ids | template.overlay_faces)
        conditions.steal_from_brush(
            temp_data,
            brush_group,
            rem_replace_brush,
            map(int, additional_replace_ids | template.overlay_faces),
            conv_bool(conditions.resolve_value(inst, transfer_overlays), True),
        )

    template_brush.retexture_template(
        temp_data,
        origin,
        inst.fixup,
        replace_tex,
        force_colour,
        force_grid,
        # Don't allow clumping if using custom keyvalues - then it won't be edited.
        no_clumping=key_block is not None,
    )


@make_result('HollowBrush')
def res_hollow_brush(inst: Entity, res: Property):
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
        remove_orig_face=srctools.conv_bool(res['RemoveFace', False])
    )

# Position -> entity
# We merge ones within 3 blocks of our item.
CHECKPOINT_TRIG = {}  # type: Dict[Tuple[float, float, float], Entity]

# Approximately a 3-distance from
# the center.
#   x
#  xxx
# xx xx
#  xxx
#   x
CHECKPOINT_NEIGHBOURS = list(Vec.iter_grid(
    Vec(-128, -128, 0),
    Vec(128, 128, 0),
    stride=128,
))
CHECKPOINT_NEIGHBOURS.extend([
    Vec(-256, 0, 0),
    Vec(256, 0, 0),
    Vec(0, -256, 0),
    Vec(0, 256, 0),
])
# Don't include ourself..
CHECKPOINT_NEIGHBOURS.remove(Vec(0, 0, 0))


@make_result('CheckpointTrigger')
def res_checkpoint_trigger(inst: Entity, res: Property):
    """Generate a trigger underneath coop checkpoint items

    """

    if vbsp.GAME_MODE == 'SP':
        # We can't have a respawn dropper in singleplayer.
        # Not generating the trigger means it's not going to
        # do anything.
        return

    pos = brushLoc.POS.raycast_world(
        Vec.from_str(inst['origin']),
        direction=(0, 0, -1),
    )
    bbox_min = pos - (192, 192, 64)
    bbox_max = pos + (192, 192, 64)

    # Find triggers already placed next to ours, and
    # merge with them if that's the case
    for offset in CHECKPOINT_NEIGHBOURS:
        near_pos = pos + offset
        try:
            trig = CHECKPOINT_TRIG[near_pos.as_tuple()]
            break
        except KeyError:
            pass
    else:
        # None found, make one.
        trig = inst.map.create_ent(
            classname='trigger_playerteam',
            origin=pos,
        )
        trig.solids = []
        CHECKPOINT_TRIG[pos.as_tuple()] = trig

    trig.solids.append(inst.map.make_prism(
        bbox_min,
        bbox_max,
        mat=const.Tools.TRIGGER,
    ).solid)

    for prop in res:
        out = Output.parse(prop)
        out.target = conditions.local_name(inst, out.target)
        trig.add_out(out)
