"""Results relating to brushwork."""
import random
from collections import defaultdict

from srctools import Property, NoKeyError, Vec, Output, Entity, VMF
import srctools.logger

from precomp import (
    instance_traits, tiling, brushLoc, texturing,
    faithplate,
    template_brush,
    conditions,
)
import vbsp
import consts
from precomp.conditions import make_result, make_result_setup

from typing import Dict, Tuple, Optional, Callable, Set, Iterable, List


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
def res_fix_rotation_axis(vmf: VMF, ent: Entity, res: Property):
    """Properly setup rotating brush entities to match the instance.

    This uses the orientation of the instance to determine the correct
    spawnflags to make it rotate in the correct direction.

    This can either modify an existing entity (which may be in an instance),
    or generate a new one. The generated brush will be 2x2x2 units large,
    and always set to be non-solid.

    For both modes:
    - `Axis`: specifies the rotation axis local to the instance.
    - `Reversed`: If set, flips the direction around.
    - `Classname`: Specifies which entity, since the spawnflags required varies.

    For application to an existing entity:
    - `ModifyTarget`: The local name of the entity to modify.

    For brush generation mode:

    - `Pos` and `name` are local to the
      instance, and will set the `origin` and `targetname` respectively.
    - `Keys` are any other keyvalues to be be set.
    - `Flags` sets additional spawnflags. Multiple values may be
       separated by `+`, and will be added together.
    - `Classname` specifies which entity will be created, as well as
       which other values will be set to specify the correct orientation.
    - `AddOut` is used to add outputs to the generated entity. It takes
       the options `Output`, `Target`, `Input`, `Inst_targ`, `Param` and `Delay`. If
       `Inst_targ` is defined, it will be used with the input to construct
       an instance proxy input. If `OnceOnly` is set, the output will be
       deleted when fired.

    Permitted entities:

       * [`func_door_rotating`](https://developer.valvesoftware.com/wiki/func_door_rotating)
       * [`func_platrot`](https://developer.valvesoftware.com/wiki/func_platrot)
       * [`func_rot_button`](https://developer.valvesoftware.com/wiki/func_rot_button)
       * [`func_rotating`](https://developer.valvesoftware.com/wiki/func_rotating)
       * [`momentary_rot_button`](https://developer.valvesoftware.com/wiki/momentary_rot_button)
    """
    des_axis = res['axis', 'z'].casefold()
    reverse = res.bool('reversed')
    door_type = res['classname', 'func_door_rotating']

    axis = Vec.with_axes(des_axis, 1).rotate_by_str(ent['angles', '0 0 0'])

    if axis.x > 0 or axis.y > 0 or axis.z > 0:
        # If it points forward, we need to reverse the rotating door
        reverse = not reverse

    try:
        flag_values = FLAG_ROTATING[door_type]
    except KeyError:
        LOGGER.warning('Unknown rotating brush type "{}"!', door_type)
        return

    name = res['ModifyTarget', '']
    if name:
        name = conditions.local_name(ent, name)
        setter_loc = ent['origin']
    else:
        # Generate a brush.
        name = conditions.local_name(ent, res['name', ''])

        pos = res.vec('Pos').rotate_by_str(ent['angles', '0 0 0'])
        pos += Vec.from_str(ent['origin', '0 0 0'])
        setter_loc = str(pos)

        door_ent = vmf.create_ent(
            classname=door_type,
            targetname=name,
            origin=pos.join(' '),
            # Extra stuff to apply to the flags (USE, toggle, etc)
            spawnflags=sum(map(
                # Add together multiple values
                srctools.conv_int,
                res['flags', '0'].split('+')
                # Make the door always non-solid!
            )) | flag_values.get('solid_flags', 0),
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
        door_ent.solids = [vmf.make_prism(pos - 1, pos + 1).solid]

    # Add or remove flags as needed by creating KV setters.

    for flag, value in zip(
        ('x', 'y', 'z', 'rev'),
        [axis.x != 0, axis.y != 0, axis.z != 0, reverse],
    ):
        if flag in flag_values:
            vmf.create_ent(
                'comp_kv_setter',
                origin=setter_loc,
                target=name,
                mode='flags',
                kv_name=flag_values[flag],
                kv_value_local=value,
            )

    # This ent uses a keyvalue for reversing...
    if door_type == 'momentary_rot_button':
        vmf.create_ent(
            'comp_kv_setter',
            origin=setter_loc,
            target=name,
            mode='kv',
            kv_name='StartDirection',
            kv_value_local='1' if reverse else '-1',
        )


@make_result('AlterTexture', 'AlterTex', 'AlterFace')
def res_set_texture(inst: Entity, res: Property):
    """Set the tile at a particular place to use a specific texture.

    This can only be set for an entire voxel side at once.

    `pos` is the position, relative to the instance (0 0 0 is the floor-surface).
    `dir` is the normal of the texture (pointing out)
    If `gridPos` is true, the position will be snapped so it aligns with
     the 128 brushes (Useful with fizzler/light strip items).

    `tex` is the texture to use.

    If `template` is set, the template should be an axis aligned cube. This
    will be rotated by the instance angles, and then the face with the same
    orientation will be applied to the face (with the rotation and texture).
    """
    angles = Vec.from_str(inst['angles'])
    origin = Vec.from_str(inst['origin'])

    pos = Vec.from_str(res['pos', '0 0 0'])
    pos.z -= 64  # Subtract so origin is the floor-position
    pos.localise(origin, angles)

    norm = Vec.from_str(res['dir', '0 0 1']).rotate(*angles)

    if srctools.conv_bool(res['gridpos', '0']):
        for axis in 'xyz':
            # Don't realign things in the normal's axis -
            # those are already fine.
            if not norm[axis]:
                pos[axis] //= 128
                pos[axis] *= 128
                pos[axis] += 64

    try:
        # The user expects the tile to be at it's surface pos, not the
        # position of the voxel.
        tile = tiling.TILES[(pos - 64 * norm).as_tuple(), norm.as_tuple()]
    except KeyError:
        LOGGER.warning(
            '"{}": Could not find tile at {} with orient {}!',
            inst['targetname'],
            pos, norm,
        )
        return

    temp_id = res['template', None]
    if temp_id:
        temp = template_brush.get_scaling_template(temp_id).rotate(angles, origin)
    else:
        temp = template_brush.ScalingTemplate.world()

    tex = res['tex', '']

    if tex.startswith('<') and tex.endswith('>'):
        LOGGER.warning(
            'Special <lookups> for AlterTexture are '
            'no longer usable! ("{}")',
            tex
        )
    elif tex.startswith('[') and tex.endswith(']'):
        gen, name = texturing.parse_name(tex[1:-1])
        tex = gen.get(pos - 64 * norm, name)

    tile.override = (tex, temp)


@make_result('AddBrush')
def res_add_brush(vmf: VMF, inst: Entity, res: Property) -> None:
    """Spawn in a brush at the indicated points.

    - `point1` and `point2` are locations local to the instance, with `0 0 0`
      as the floor-position.
    - `type` is either `black` or `white`.
    - detail should be set to `1/0`. If true the brush will be a
      func_detail instead of a world brush.

    The sides will be textured with 1x1, 2x2 or 4x4 wall, ceiling and floor
    textures as needed.
    """
    point1 = Vec.from_str(res['point1'])
    point2 = Vec.from_str(res['point2'])

    point1.z -= 64  # Offset to the location of the floor
    point2.z -= 64

    # Rotate to match the instance
    point1 = point1.rotate_by_str(inst['angles'])
    point2 = point2.rotate_by_str(inst['angles'])

    origin = Vec.from_str(inst['origin'])
    point1 += origin  # Then offset to the location of the instance
    point2 += origin

    try:
        tex_type = texturing.Portalable(res['type', 'black'])
    except ValueError:
        LOGGER.warning(
            'AddBrush: "{}" is not a valid brush '
            'color! (white or black)',
            res['type'],
        )
        tex_type = texturing.Portalable.BLACK

    dim = point2 - point1
    dim.max(-dim)

    # Figure out what grid size and scale is needed
    # Check the dimensions in two axes to figure out the largest
    # tile size that can fit in it.
    tile_grids = {
        'x': tiling.TileSize.TILE_4x4,
        'y': tiling.TileSize.TILE_4x4,
        'z': tiling.TileSize.TILE_4x4,
    }

    for axis in 'xyz':
        u, v = Vec.INV_AXIS[axis]
        max_size = min(dim[u], dim[v])
        if max_size % 128 == 0:
            tile_grids[axis] = tiling.TileSize.TILE_1x1
        elif dim[u] % 64 == 0 and dim[v] % 128 == 0:
            tile_grids[axis] = tiling.TileSize.TILE_2x1
        elif max_size % 64 == 0:
            tile_grids[axis] = tiling.TileSize.TILE_2x2
        else:
            tile_grids[axis] = tiling.TileSize.TILE_4x4

    grid_offset = origin // 128  # type: Vec

    # All brushes in each grid have the same textures for each side.
    random.seed(grid_offset.join(' ') + '-partial_block')

    solids = vmf.make_prism(point1, point2)

    solids.north.mat = texturing.gen(
        texturing.GenCat.NORMAL,
        Vec(Vec.N),
        tex_type,
    ).get(solids.north.get_origin(), tile_grids['y'])
    solids.south.mat = texturing.gen(
        texturing.GenCat.NORMAL,
        Vec(Vec.S),
        tex_type,
    ).get(solids.north.get_origin(), tile_grids['y'])
    solids.east.mat = texturing.gen(
        texturing.GenCat.NORMAL,
        Vec(Vec.E),
        tex_type,
    ).get(solids.north.get_origin(), tile_grids['x'])
    solids.west.mat = texturing.gen(
        texturing.GenCat.NORMAL,
        Vec(Vec.W),
        tex_type,
    ).get(solids.north.get_origin(), tile_grids['x'])
    solids.top.mat = texturing.gen(
        texturing.GenCat.NORMAL,
        Vec(Vec.T),
        tex_type,
    ).get(solids.north.get_origin(), tile_grids['z'])
    solids.bottom.mat = texturing.gen(
        texturing.GenCat.NORMAL,
        Vec(Vec.B),
        tex_type,
    ).get(solids.north.get_origin(), tile_grids['z'])

    if res.bool('detail'):
        # Add the brush to a func_detail entity
        vmf.create_ent(
            classname='func_detail'
        ).solids = [solids.solid]
    else:
        # Add to the world
        vmf.add_brush(solids.solid)


@make_result_setup('TemplateBrush')
def res_import_template_setup(res: Property):
    if res.has_children():
        temp_id = res['id']
    else:
        temp_id = res.value
        res = Property('TemplateBrush', [])

    force = res['force', ''].casefold().split()
    if 'white' in force:
        force_colour = texturing.Portalable.white
    elif 'black' in force:
        force_colour = texturing.Portalable.black
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

    force_grid: Optional[texturing.TileSize]
    size: texturing.TileSize
    for size in texturing.TileSize:
        if size in force:
            force_grid = size
            break
    else:
        force_grid = None

    if 'bullseye' in force:
        surf_cat = texturing.GenCat.BULLSEYE
    elif 'special' in force or 'panel' in force:
        surf_cat = texturing.GenCat.PANEL
    else:
        surf_cat = texturing.GenCat.NORMAL

    replace_tex = defaultdict(list)
    for prop in res.find_key('replace', []):
        replace_tex[prop.name].append(prop.value)

    if 'replaceBrush' in res:
        LOGGER.warning(
            'replaceBrush command used for template "{}", which is no '
            'longer used.',
            temp_id,
        )
    bind_tile_pos = [
        # So it's the floor block location.
        Vec.from_str(value) - (0, 0, 128)
        for value in
        res.find_key('BindOverlay', []).as_array()
    ]

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

    visgroup_func: Callable[[Set[str]], Iterable[str]]

    def visgroup_func(groups):
        """none = don't add any visgroups."""
        return ()

    visgroup_prop = res.find_key('visgroup', 'none')
    if visgroup_prop.has_children():
        visgroup_vars = list(visgroup_prop)
    else:
        visgroup_vars = []
        visgroup_mode = res['visgroup', 'none'].casefold()
        # Generate the function which picks which visgroups to add to the map.
        if visgroup_mode == 'none':
            pass
        elif visgroup_mode == 'choose':
            def visgroup_func(groups):
                """choose = add one random group."""
                return [random.choice(groups)]
        else:
            percent = srctools.conv_float(visgroup_mode.rstrip('%'), 0.00)
            if percent > 0.0:
                def visgroup_func(groups):
                    """Number = percent chance for each to be added"""
                    for group in groups:
                        val = random.uniform(0, 100)
                        if val <= percent:
                            yield group

    picker_vars = [
        (prop.real_name, prop.value)
        for prop in res.find_children('pickerVars')
    ]

    return (
        temp_id,
        dict(replace_tex),
        force_colour,
        force_grid,
        force_type,
        surf_cat,
        bind_tile_pos,
        res['invertVar', ''],
        res['colorVar', ''],
        visgroup_func,
        # If true, force visgroups to all be used.
        res['forceVisVar', ''],
        visgroup_vars,
        keys,
        picker_vars,
        outputs,
        res.vec('senseOffset'),
    )


@make_result('TemplateBrush')
def res_import_template(vmf: VMF, inst: Entity, res: Property):
    """Import a template VMF file, retexturing it to match orientation.

    It will be placed overlapping the given instance. If no block is used, only
    ID can be specified.
    Options:

    - `ID`: The ID of the template to be inserted. Add visgroups to additionally
            add after a colon, comma-seperated (`temp_id:vis1,vis2`).
            Either section, or the whole value can be a `$fixup`.
    - `force`: a space-seperated list of overrides. If 'white' or 'black' is
             present, the colour of tiles will be overridden. If `invert` is
            added, white/black tiles will be swapped. If a tile size
            (`2x2`, `4x4`, `wall`, `special`) is included, all tiles will
            be switched to that size (if not a floor/ceiling). If 'world' or
            'detail' is present, the brush will be forced to that type.
    - `replace`: A block of template material -> replacement textures.
            This is case insensitive - any texture here will not be altered
            otherwise. If the material starts with a `#`, it is instead a
            list of face IDs separated by spaces. If the result evaluates
            to "", no change occurs. Both can be $fixups (parsed first).
    - `bindOverlay`: Bind overlays in this template to the given surface, and
            bind overlays on a surface to surfaces in this template.
            The value specifies the offset to the surface, where 0 0 0 is the
            floor position. It can also be a block of multiple positions.
    - `keys`/`localkeys`: If set, a brush entity will instead be generated with
            these values. This overrides force world/detail.
            Specially-handled keys:
            - `"origin"`, offset automatically.
            - `"movedir"` on func_movelinear - set a normal surrounded by `<>`,
              this gets replaced with angles.
    - `colorVar`: If this fixup var is set
            to `white` or `black`, that colour will be forced.
            If the value is `<editor>`, the colour will be chosen based on
            the color of the surface for ItemButtonFloor, funnels or
            entry/exit frames.
    - `invertVar`: If this fixup value is true, tile colour will be
            swapped to the opposite of the current force option. This applies
            after colorVar.
    - `visgroup`: Sets how visgrouped parts are handled. Several values are possible:
            - A property block: Each name should match a visgroup, and the
              value should be a block of flags that if true enables that group.
            - 'none' (default): All extra groups are ignored.
            - 'choose': One group is chosen randomly.
            - a number: The percentage chance for each visgroup to be added.
    - `visgroup_force_var`: If set and True, visgroup is ignored and all groups
            are added.
    - `pickerVars`:
            If this is set, the results of colorpickers can be read
            out of the template. The key is the name of the picker, the value
            is the fixup name to write to. The output is either 'white',
            'black' or ''.
    - `outputs`: Add outputs to the brush ent. Syntax is like VMFs, and all names
            are local to the instance.
    - `senseOffset`: If set, colorpickers and tilesetters will be treated
            as being offset by this amount.
    """
    (
        orig_temp_id,
        replace_tex,
        force_colour,
        force_grid,
        force_type,
        surf_cat,
        bind_tile_pos,
        invert_var,
        color_var,
        visgroup_func,
        visgroup_force_var,
        visgroup_instvars,
        key_block,
        picker_vars,
        outputs,
        sense_offset,
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

    # Special case - if blank, just do nothing silently.
    if not temp_id:
        return

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

    for vis_flag_block in visgroup_instvars:
        if all(conditions.check_flag(vmf, flag, inst) for flag in vis_flag_block):
            visgroups.add(vis_flag_block.real_name)

    if color_var.casefold() == '<editor>':
        # Check traits for the colour it should be.
        traits = instance_traits.get(inst)
        if 'white' in traits:
            force_colour = texturing.Portalable.white
        elif 'black' in traits:
            force_colour = texturing.Portalable.black
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
            force_colour = texturing.Portalable.white
        elif color_val == 'black':
            force_colour = texturing.Portalable.black
    # else: no color var

    if srctools.conv_bool(conditions.resolve_value(inst, invert_var)):
        force_colour = template_brush.TEMP_COLOUR_INVERT[force_colour]
    # else: False value, no invert.

    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles', '0 0 0'])
    temp_data = template_brush.import_template(
        vmf,
        template,
        origin,
        angles,
        targetname=inst['targetname', ''],
        force_type=force_type,
        visgroup_choose=visgroup_func,
        add_to_map=True,
        additional_visgroups=visgroups,
        bind_tile_pos=bind_tile_pos,
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

    template_brush.retexture_template(
        temp_data,
        origin,
        inst.fixup,
        replace_tex,
        force_colour,
        force_grid,
        surf_cat,
        sense_offset,
    )

    for picker_name, picker_var in picker_vars:
        picker_val = temp_data.picker_results.get(
            picker_name, None,
        )  # type: Optional[texturing.Portalable]
        if picker_val is not None:
            inst.fixup[picker_var] = picker_val.value
        else:
            inst.fixup[picker_var] = ''


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
def res_checkpoint_trigger(inst: Entity, res: Property) -> None:
    """Generate a trigger underneath coop checkpoint items.

    """

    if vbsp.GAME_MODE == 'SP':
        # We can't have a respawn dropper in singleplayer.
        # Not generating the trigger means it's not going to
        # do anything.
        return

    pos = brushLoc.POS.raycast_world(
        Vec.from_str(inst['origin']),
        direction=Vec(0, 0, -1),
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
        mat=consts.Tools.TRIGGER,
    ).solid)

    for prop in res:
        out = Output.parse(prop)
        out.target = conditions.local_name(inst, out.target)
        trig.add_out(out)


@make_result('SetTile', 'SetTiles')
def res_set_tile(inst: Entity, res: Property) -> None:
    """Set 4x4 parts of a tile to the given values.

    `Offset` defines the position of the upper-left tile in the grid.
    Each `Tile` section defines a row of the positions to edit like so:
        "Tile" "bbbb"
        "Tile" "b..b"
        "Tile" "b..b"
        "Tile" "bbbb"
    If `Force` is true, the specified tiles will override any existing ones
    and create the tile if necessary.
    Otherwise they will be merged in - white/black tiles will not replace
    tiles set to nodraw or void for example.
    `chance`, if specified allows producing irregular tiles by randomly not
    changing the tile.

    If you need less regular placement (other orientation, precise positions)
    use a bee2_template_tilesetter in a template.

    Allowed tile characters:
    - `W`: White tile.
    - `w`: White 4x4 only tile.
    - `B`: Black tile.
    - `b`: Black 4x4 only tile.
    - `g`: The side/bottom of goo pits.
    - `n`: Nodraw surface.
    - `i`: Invert the tile surface, if black/white.
    - `1`: Convert to a 1x1 only tile, if a black/white tile.
    - `4`: Convert to a 4x4 only tile, if a black/white tile.
    - `.`: Void (remove the tile in this position).
    - `_` or ` `: Placeholder (don't modify this space).
    - `x`: Cutout Tile (Broken)
    - `o`: Cutout Tile (Partial)
    """
    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles'])

    offset = (res.vec('offset', -48, 48) - (0, 0, 64)).rotate(*angles)
    offset += origin

    norm = Vec(0, 0, 1).rotate(*angles)

    force_tile = res.bool('force')

    tiles: List[str] = [
        row.value
        for row in res
        if row.name in ('tile', 'tiles')
    ]
    if not tiles:
        raise ValueError('No "tile" parameters in SetTile!')

    chance = srctools.conv_float(res['chance', '100'].rstrip('%'), 100.0)
    if chance < 100.0:
        conditions.set_random_seed(inst, 'tile' + res['seed', ''])

    for y, row in enumerate(tiles):
        for x, val in enumerate(row):
            if val in '_ ':
                continue

            if chance < 100.0 and random.uniform(0, 100) > chance:
                continue

            pos = Vec(32 * x, -32 * y, 0).rotate(*angles) + offset

            if val == '4':
                size = tiling.TileSize.TILE_4x4
            elif val == '1':
                size = tiling.TileSize.TILE_1x1
            elif val == 'i':
                size = None
            else:
                try:
                    new_tile = tiling.TILETYPE_FROM_CHAR[val]  # type: tiling.TileType
                except KeyError:
                    LOGGER.warning('Unknown tiletype "{}"!', val)
                else:
                    tiling.edit_quarter_tile(pos, norm, new_tile, force_tile)
                continue

            # Edit the existing tile.
            try:
                tile, u, v = tiling.find_tile(pos, norm, force_tile)
            except KeyError:
                LOGGER.warning(
                    'Expected tile, but none found: {}, {}',
                    pos,
                    norm,
                )
                continue

            if size is None:
                # Invert the tile.
                tile[u, v] = tile[u, v].inverted
                continue

            # Unless forcing is enabled don't alter the size of GOO_SIDE.
            if tile[u, v].is_tile and tile[u, v] is not tiling.TileType.GOO_SIDE:
                tile[u, v] = tiling.TileType.with_color_and_size(
                    size,
                    tile[u, v].color
                )
            elif force_tile:
                # If forcing, make it black. Otherwise no need to change.
                tile[u, v] = tiling.TileType.with_color_and_size(
                    size,
                    tiling.Portalable.BLACK
                )


@make_result('addPlacementHelper')
def res_add_placement_helper(inst: Entity, res: Property):
    """Add a placement helper to a specific tile.

    `Offset` and `normal` specify the position and direction out of the surface
    the helper should be added to. If `upDir` is specified, this is the
    direction of the top of the portal.
    """
    angles = Vec.from_str(inst['angles'])

    pos = conditions.resolve_offset(inst, res['offset', '0 0 0'], zoff=-64)
    normal = res.vec('normal', 0, 0, 1).rotate(*angles)

    up_dir: Optional[Vec]
    try:
        up_dir = Vec.from_str(res['upDir']).rotate(*angles)
    except LookupError:
        up_dir = None

    try:
        tile = tiling.TILES[(pos - 64 * normal).as_tuple(), normal.as_tuple()]
    except KeyError:
        LOGGER.warning('No tile at {} @ {}', pos, normal)
        return

    tile.add_portal_helper(up_dir)


@make_result('SetPanelOptions', *[
    alter + pan + opts  # All the combinations
    for alter in ['Set', 'Alter']
    for pan in ['Panel', 'Pan']
    for opts in ['Options', 'Opts']
])
def res_set_panel_options(vmf: VMF, inst: Entity, props: Property) -> None:
    """Modify an existing panel associated with this instance.

    See `CreatePanel` to add new ones.
    This is used for panel-type items, allowing them to generate the correct
    brushwork regardless of the kind of tiles used on the surface.
    It can also be used to generate some flat "slabs" protruding from a surface.
    All parameters are optional, using existing values if not set.

    Options:

    - `normal`: The direction facing out of the surface. This defaults to "up".
    - `pos1`, `pos2`: The position of the tile on two diagnonally opposite
       corners. This allows only modifying some of the tiles. These default to
        a full tile.
    - `point`: Alternatively, individually specify each point to to produce
       irregular shapes.
    - `type`: Change the specially handled behaviours set for the panel.
       Available options:
        - `NORMAL`: No special behaviour.
        - `FLIP_BLACK`: Apply black tiles to the backside of the panel,
          doubling it in thickness.
        - `FLIP_INVERT`: Apply the inverse colour to the backside of the panel,
          doubling it in thickness.
        - `ANGLED_30`, `ANGLED_45`, `ANGLED_60`: Rotate the panel to match
          an extended panel of these angles.
    - `thickness`: The thickness of the surface. Must be 2, 4 or 8.
    - `bevel`: If true, angle the sides. Otherwise leave them straight.
    - `nodraw_sides`: If true, apply nodraw to the sides and back instead of
      squarebeams/backpanels materials.
    - `seal`: If enabled, nodraw tiles will be generated at the original
      position to seal in the map.
    - `move_bullseye`: If set, this will move any bullseye target on the tile.
      This only affects the actual trajectory, not the visual
      (which always appears).
    - `template`: If set, additionally insert this template at the instance's
      location, merging the brushes into this entity. This can be used for
      irregularly-shaped tiles, clips or other extra brushes you wish to include.
      Don't include the sections of panel you're planning to template in the
      panel's points, or it will generate those tiles as well. Instead use a
      tile_setter or color_picker to remove them through the template.
    - `offset`: Offset the brush in any direction. It starts flush where a
      normal surface would be.
    - `keys`, `localkeys`: Make the panel use a brush entity with these options.
      If not provided or the classname is set to '', the panel is generated as
      a world brush.
    """
    edit_panel(vmf, inst, props, create=False)


@make_result('CreatePanel')
def res_create_panel(vmf: VMF, inst: Entity, props: Property) -> None:
    """Convert a set of tiles into a dynamic entity.

    See `SetPanelOptions` to add new ones.
    This is used for panel-type items, allowing them to generate the correct
    brushwork regardless of the kind of tiles used on the surface.
    It can also be used to generate some flat "slabs" protruding from a surface.
    All parameters are optional.

    Options:

    - `normal`: The direction facing out of the surface. This defaults to "up".
    - `pos1`, `pos2`: The position of the tile on two diagnonally opposite
       corners. This allows only modifying some of the tiles. These default to
        a full tile.
    - `type`: Instructs the panel to use some specially handled behaviours.
       Available options:
        - `NORMAL`: No special behaviour.
        - `FLIP_BLACK`: Apply black tiles to the backside of the panel,
          doubling it in thickness.
        - `FLIP_INVERT`: Apply the inverse colour to the backside of the panel,
          doubling it in thickness.
        - `ANGLED_30`, `ANGLED_45`, `ANGLED_60`: Rotate the panel to match
          an extended panel of these angles.
    - `thickness`: The thickness of the surface. Must be 2, 4 or 8.
    - `bevel`: If true, angle the sides. Otherwise leave them straight.
    - `nodraw_sides`: If true, apply nodraw to the sides and back instead of
      squarebeams/backpanels materials.
    - `seal`: If enabled, nodraw tiles will be generated at the original
      position to seal in the map.
    - `move_bullseye`: If set, this will move any bullseye target on the tile.
      This only affects the actual trajectory, not the visual
      (which always appears).
    - `template`: If set, additionally insert this template at the instance's
      location, merging the brushes into this entity. This can be used for
      irregularly-shaped tiles, clips or other extra brushes you wish to include.
      Don't include the sections of panel you're planning to template in the
      panel's points, or it will generate those tiles as well. Instead use a
      tile_setter or color_picker to remove them through the template.
    - `offset`: Offset the brush in any direction. It starts flush where a
      normal surface would be.
    - `keys`, `localkeys`: Make the panel use a brush entity with these options.
      If not provided the panel is generated as a world brush.
    """
    edit_panel(vmf, inst, props, create=True)


def edit_panel(vmf: VMF, inst: Entity, props: Property, create: bool) -> None:
    """Implements SetPanelOptions and CreatePanel."""
    normal = props.vec('normal', 0, 0, 1).rotate_by_str(inst['angles'])
    origin = Vec.from_str(inst['origin'])
    uaxis, vaxis = Vec.INV_AXIS[normal.axis()]

    points: Set[Tuple[float, float, float]] = set()

    if 'point' in props:
        for prop in props.find_all('point'):
            points.add(conditions.resolve_offset(inst, prop.value, zoff=-64).as_tuple())
    elif 'pos1' in props and 'pos2' in props:
        pos1, pos2 = Vec.bbox(
            conditions.resolve_offset(inst, props['pos1', '-48 -48 0'], zoff=-64),
            conditions.resolve_offset(inst, props['pos2', '48 48 0'], zoff=-64),
        )
        points.update(map(Vec.as_tuple, Vec.iter_grid(pos1, pos2, 32)))
    else:
        # Default to the full tile.
        points.update({
            (Vec(u, v, -64.0).rotate_by_str(inst['angles']) + origin).as_tuple()
            for u in [-48.0, -16.0, 16.0, 48.0]
            for v in [-48.0, -16.0, 16.0, 48.0]
        })

    tiles_to_uv: Dict[tiling.TileDef, Set[Tuple[int, int]]] = defaultdict(set)
    for pos in points:
        try:
            tile, u, v = tiling.find_tile(Vec(pos), normal, force=create)
        except KeyError:
            continue
        tiles_to_uv[tile].add((u, v))

    if not tiles_to_uv:
        LOGGER.warning('"{}": No tiles found for panels!', inst['targetname'])
        return

    # If bevels is provided, parse out the overall world positions.
    bevel_world: Optional[Set[Tuple[int, int]]]
    try:
        bevel_prop = props.find_key('bevel')
    except NoKeyError:
        bevel_world = None
    else:
        bevel_world = set()
        if bevel_prop.has_children():
            # Individually specifying offsets.
            for bevel_str in bevel_prop.as_array():
                bevel_point = Vec.from_str(bevel_str).rotate_by_str(inst['angles']) + origin
                bevel_world.add((int(bevel_point[uaxis]), int(bevel_point[vaxis])))
        elif srctools.conv_bool(bevel_prop.value):
            # Fill the bounding box.
            bbox_min, bbox_max = Vec.bbox(map(Vec, points))
            off = Vec.with_axes(uaxis, 32, vaxis, 32)
            bbox_min -= off
            bbox_max += off
            for pos in Vec.iter_grid(bbox_min, bbox_max, 32):
                if pos.as_tuple() not in points:
                    bevel_world.add((pos[uaxis], pos[vaxis]))
        # else: No bevels.
    panels: List[tiling.Panel] = []

    for tile, uvs in tiles_to_uv.items():
        if create:
            panel = tiling.Panel(
                None, inst, tiling.PanelType.NORMAL,
                thickness=4,
                bevels=(),
            )
            panel.points = uvs
            tile.panels.append(panel)
        else:
            for panel in tile.panels:
                if panel.same_item(inst) and panel.points == uvs:
                    break
            else:
                LOGGER.warning(
                    'No panel to modify found for "{}"!',
                    inst['targetname']
                )
                continue
        panels.append(panel)

        pan_type = '<nothing?>'
        try:
            pan_type = conditions.resolve_value(inst, props['type'])
            panel.pan_type = tiling.PanelType(pan_type.lower())
        except LookupError:
            pass
        except ValueError:
            raise ValueError('Unknown panel type "{}"!'.format(pan_type))

        if 'thickness' in props:
            panel.thickness = srctools.conv_int(
                conditions.resolve_value(inst, props['thickness'])
            )
            if panel.thickness not in (2, 4, 8):
                raise ValueError(
                    '"{}": Invalid panel thickess {}!\n'
                    'Must be 2, 4 or 8.',
                    inst['targetname'],
                    panel.thickness,
                )

        if bevel_world is not None:
            panel.bevels.clear()
            for u, v in bevel_world:
                # Convert from world points to UV positions.
                u = (u - tile.pos[uaxis] + 48) / 32
                v = (v - tile.pos[vaxis] + 48) / 32
                # Cull outside here, we wont't use them.
                if -1 <= u <= 4 and -1 <= v <= 4:
                    panel.bevels.add((u, v))

        if 'offset' in props:
            panel.offset = conditions.resolve_offset(inst, props['offset'])
            panel.offset -= Vec.from_str(inst['origin'])
        if 'template' in props:
            # We only want the template inserted once. So remove it from all but one.
            if len(panels) == 1:
                panel.template = conditions.resolve_value(inst, props['template'])
            else:
                panel.template = ''
        if 'nodraw' in props:
            panel.nodraw = srctools.conv_bool(
                conditions.resolve_value(inst, props['nodraw'])
            )
        if 'seal' in props:
            panel.seal = srctools.conv_bool(
                conditions.resolve_value(inst, props['seal'])
            )
        if 'move_bullseye' in props:
            panel.steals_bullseye = srctools.conv_bool(
                conditions.resolve_value(inst, props['move_bullseye'])
            )
    if 'keys' in props or 'localkeys' in props:
        # First grab the existing ent, so we can edit it.
        # These should all have the same value, unless they were independently
        # edited with mismatching point sets. In that case destroy all those existing ones.
        existing_ents: Set[Optional[Entity]] = {panel.brush_ent for panel in panels}
        try:
            [brush_ent] = existing_ents
        except ValueError:
            LOGGER.warning(
                'Multiple independent panels for "{}" were made, then the '
                'brush entity was edited as a group! Discarding '
                'individual ents...',
                inst['targetname']
            )
            for brush_ent in existing_ents:
                if brush_ent is not None and brush_ent in vmf.entities:
                    brush_ent.remove()
            brush_ent = None

        if brush_ent is None:
            brush_ent = vmf.create_ent('')

        old_pos = brush_ent.keys.pop('origin', None)

        conditions.set_ent_keys(brush_ent, inst, props)
        if not brush_ent['classname']:
            if create:  # This doesn't make sense, you could just omit the prop.
                LOGGER.warning(
                    'No classname provided for panel "{}"!',
                    inst['targetname'],
                )
            # Make it a world brush.
            brush_ent.remove()
            brush_ent = None
        else:
            # We want to do some post-processing.
            # Localise any origin value.
            if 'origin' in brush_ent.keys:
                pos = Vec.from_str(brush_ent['origin'])
                pos.localise(
                    Vec.from_str(inst['origin']),
                    Vec.from_str(inst['angles']),
                )
                brush_ent['origin'] = pos
            elif old_pos is not None:
                brush_ent['origin'] = old_pos

            # If it's func_detail, clear out all the keys.
            # Particularly `origin`, but the others are useless too.
            if brush_ent['classname'] == 'func_detail':
                brush_ent.clear_keys()
                brush_ent['classname'] = 'func_detail'
        for panel in panels:
            panel.brush_ent = brush_ent


def _fill_norm_rotations() -> Dict[
    Tuple[Tuple[float, float, float], Tuple[float, float, float]],
    Tuple[float, float, float]
]:
    """Given a norm->norm rotation, return the angles producing that."""
    rotations = {}
    for norm_ax in 'xyz':
        for norm_mag in [-1, +1]:
            norm = Vec.with_axes(norm_ax, norm_mag)
            for angle_ax in 'xyz':
                for angle_mag in (-90, 90):
                    angle = Vec.with_axes(angle_ax, angle_mag)
                    new_norm = norm.copy().rotate(*angle)
                    if new_norm != norm:
                        rotations[tuple(norm), tuple(new_norm)] = angle.as_tuple()
            # Assign a null rotation as well.
            rotations[tuple(norm), tuple(norm)] = (0.0, 0.0, 0.0)
            rotations[tuple(norm), tuple(-norm)] = (0.0, 0.0, 0.0)
    return rotations


NORM_ROTATIONS = _fill_norm_rotations()
del _fill_norm_rotations


@make_result("TransferBullseye")
def res_transfer_bullseye(inst: Entity, props: Property):
    """Transfer catapult targets and placement helpers from one tile to another."""
    start_pos = conditions.resolve_offset(inst, props['start_pos', ''])
    end_pos = conditions.resolve_offset(inst, props['end_pos', ''])
    start_norm = props.vec('start_norm', 0, 0, 1).rotate_by_str(inst['angles'])
    end_norm = props.vec('end_norm', 0, 0, 1).rotate_by_str(inst['angles'])

    try:
        start_tile = tiling.TILES[
            (start_pos - 64 * start_norm).as_tuple(),
            start_norm.as_tuple()
        ]
    except KeyError:
        LOGGER.warning('"{}": Cannot find tile to transfer from at {}, {}!'.format(
            inst['targetname'],
            start_pos,
            start_norm
        ))
        return

    end_tile = tiling.TileDef.ensure(
        end_pos - 64 * end_norm,
        end_norm,
    )
    # Now transfer the stuff.
    if start_tile.has_oriented_portal_helper:
        # We need to rotate this.
        orient = start_tile.portal_helper_orient.copy()
        # If it's directly opposite, just mirror - we have no clue what the
        # intent is.
        if Vec.dot(start_norm, end_norm) != -1.0:
            # Use the dict to compute the rotation to apply.
            orient.rotate(*NORM_ROTATIONS[
                start_norm.as_tuple(),
                end_norm.as_tuple()
            ])
        end_tile.add_portal_helper(orient)
    elif start_tile.has_portal_helper:
        # Non-oriented, don't orient.
        end_tile.add_portal_helper()
    start_tile.remove_portal_helper(all=True)

    if start_tile.bullseye_count:
        end_tile.bullseye_count = start_tile.bullseye_count
        start_tile.bullseye_count = 0
        # Then transfer the targets across.
        for plate in faithplate.PLATES.values():
            if getattr(plate, 'target', None) is start_tile:
                plate.target = end_tile


