"""Results relating to brushwork."""
from __future__ import annotations
from collections.abc import Callable, Iterable
from collections import defaultdict
from random import Random

from srctools import Keyvalues, NoKeyError, Output, Entity, VMF
from srctools.math import Vec, Angle, Matrix, FrozenVec
import srctools.logger

from precomp import (
    conditions, tiling, texturing, rand, corridor, collisions,
    instance_traits, brushLoc, faithplate, template_brush,
)
from editoritems_props import PanelAnimation
import utils
import consts
from precomp.lazy_value import LazyValue
from precomp.texturing import MaterialConf, QuarterRot
from quote_pack import QuoteInfo


COND_MOD_NAME = 'Brushes'
LOGGER = srctools.logger.get_logger(__name__)
PANEL_TYPES: dict[str, tiling.PanelType] = {
    typ.value.casefold(): typ
    for typ in tiling.PanelType
}
PANEL_TYPES.update({
    PanelAnimation[ang].animation: tiling.PanelType[ang]
    for ang in ['ANGLE_30', 'ANGLE_45', 'ANGLE_60']
})
PANEL_TYPES[PanelAnimation.ANGLE_90.animation] = tiling.PanelType.NORMAL
LAZY_MATRIX_IDENTITY = LazyValue.make(Matrix())

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


@conditions.make_result('GenRotatingEnt')
def res_fix_rotation_axis(vmf: VMF, ent: Entity, res: Keyvalues) -> None:
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
    - `Keys` are any other keyvalues to be set.
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
    orient = Matrix.from_angstr(ent['angles'])

    axis = round(Vec.with_axes(des_axis, 1) @ orient, 6)

    if axis.x > 0 or axis.y > 0 or axis.z > 0:
        # If it points forward, we need to reverse the rotating door
        reverse = not reverse
    axis = abs(axis)

    try:
        flag_values = FLAG_ROTATING[door_type]
    except KeyError:
        LOGGER.warning('Unknown rotating brush type "{}"!', door_type)
        return

    name = res['ModifyTarget', '']
    door_ent: Entity | None
    if name:
        name = conditions.local_name(ent, name)
        setter_loc = ent['origin']
        door_ent = None
        spawnflags = 0
    else:
        # Generate a brush.
        name = conditions.local_name(ent, res['name', ''])

        pos = res.vec('Pos') @ Angle.from_str(ent['angles', '0 0 0'])
        pos += Vec.from_str(ent['origin', '0 0 0'])
        setter_loc = str(pos)

        door_ent = vmf.create_ent(
            classname=door_type,
            targetname=name,
            origin=pos.join(' '),
        )
        # Extra stuff to apply to the flags (USE, toggle, etc)
        spawnflags = sum(
            # Add together multiple values
            srctools.conv_int(num)
            for num in res['flags', '0'].split('+')
            # Make the door always non-solid!
        ) | flag_values.get('solid_flags', 0)

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

    # Add or remove flags as needed
    for flag, value in zip(
        ('x', 'y', 'z', 'rev'),
        [axis.x > 1e-6, axis.y > 1e-6, axis.z > 1e-6, reverse],
        strict=True,
    ):
        if flag not in flag_values:
            continue
        if door_ent is not None:
            if value:
                spawnflags |= flag_values[flag]
            else:
                spawnflags &= ~flag_values[flag]
        else:  # Place a KV setter to set this.
            vmf.create_ent(
                'comp_kv_setter',
                origin=setter_loc,
                target=name,
                mode='flags',
                kv_name=flag_values[flag],
                kv_value_global=value,
            )
    if door_ent is not None:
        door_ent['spawnflags'] = spawnflags

    # This ent uses a keyvalue for reversing...
    if door_type == 'momentary_rot_button':
        vmf.create_ent(
            'comp_kv_setter',
            origin=setter_loc,
            target=name,
            mode='kv',
            kv_name='StartDirection',
            kv_value_global='1' if reverse else '-1',
        )


@conditions.make_result('AlterTexture', 'AlterTex', 'AlterFace')
def res_set_texture(inst: Entity, res: Keyvalues) -> None:
    """Set the tile at a particular place to use a specific texture.

    This can only be set for an entire voxel side at once.

    `pos` is the position, relative to the instance (0 0 0 is the floor-surface).
    `dir` is the normal of the texture (pointing out)
    If `gridPos` is true, the position will be snapped, so it aligns with
     the 128 brushes (Useful with fizzler/light strip items).

    `tex` is the texture to use.
    `scale` allows you to scale up/down the material - this is a multiplier, not the actual value.

    If `template` is set, the template should be an axis aligned cube. This
    will be rotated by the instance angles, and then the face with the same
    orientation will be applied to the face (with the rotation and texture).
    """
    angles = Angle.from_str(inst['angles'])
    origin = Vec.from_str(inst['origin'])

    pos = Vec.from_str(res['pos', '0 0 0'])
    pos.z -= 64  # Subtract so origin is the floor-position
    pos.localise(origin, angles)

    norm = round(Vec.from_str(res['dir', '0 0 1']) @ angles, 6)

    scale = res.float('scale', 1.0)
    if scale <= 0.0:
        LOGGER.warning('Material scale should be positive, not {}!', scale)
        scale = 1.0
    try:
        rotation = QuarterRot.parse(res['rotation'])
    except LookupError:
        rotation = QuarterRot.NONE

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

    temp_id = inst.fixup.substitute(res['template', ''])
    if temp_id:
        temp = template_brush.get_scaling_template(temp_id).rotate(angles, origin)
    else:
        temp = template_brush.ScalingTemplate.world()

    tex = inst.fixup.substitute(res['tex', ''])

    if tex.startswith('<') and tex.endswith('>'):
        LOGGER.warning(
            'Special <lookups> for AlterTexture are '
            'no longer usable! ("{}")',
            tex
        )

    if tex.startswith('[') and tex.endswith(']'):
        gen, name = texturing.parse_name(tex[1:-1])
        mat_conf = gen.get(pos - 64 * norm, name)
    else:
        mat_conf = MaterialConf(tex, scale=scale, rotation=rotation)

    tile.override = (mat_conf, temp)


@conditions.make_result('AddBrush')
def res_add_brush(vmf: VMF, inst: Entity, res: Keyvalues) -> None:
    """Spawn in a brush at the indicated points.

    - `point1` and `point2` are locations local to the instance, with `0 0 0`
      as the floor-position.
    - `type` is either `black` or `white`.
    - detail should be set to `1/0`. If true the brush will be a
      func_detail instead of a world brush.

    The sides will be textured with 1x1, 2x2 or 4x4 wall, ceiling and floor
    textures as needed.
    """
    origin = Vec.from_str(inst['origin'])
    angles = Angle.from_str(inst['angles'])

    point1 = Vec.from_str(res['point1'])
    point2 = Vec.from_str(res['point2'])

    point1.z -= 64  # Offset to the location of the floor
    point2.z -= 64

    # Rotate to match the instance
    point1 = point1 @ angles + origin
    point2 = point2 @ angles + origin

    try:
        tex_type = texturing.Portalable(res['type', 'black'])
    except ValueError:
        LOGGER.warning(
            'AddBrush: "{}" is not a valid brush '
            'color! (white or black)',
            res['type'],
        )
        tex_type = texturing.Portalable.BLACK

    dim = round(point2 - point1, 6)
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

    solids = vmf.make_prism(point1, point2)
    center = (point1 + point2) / 2

    wall_gen = texturing.gen(
        texturing.GenCat.NORMAL,
        texturing.Orient.WALL,
        tex_type,
    )

    wall_gen.get(center, tile_grids['y']).apply(solids.north)
    wall_gen.get(center, tile_grids['y']).apply(solids.south)
    wall_gen.get(center, tile_grids['x']).apply(solids.east)
    wall_gen.get(center, tile_grids['x']).apply(solids.west)
    texturing.gen(
        texturing.GenCat.NORMAL,
        texturing.Orient.FLOOR,
        tex_type,
    ).get(center, tile_grids['z']).apply(solids.top)
    texturing.gen(
        texturing.GenCat.NORMAL,
        texturing.Orient.CEILING,
        tex_type,
    ).get(center, tile_grids['z']).apply(solids.bottom)

    if res.bool('detail'):
        # Add the brush to a func_detail entity
        vmf.create_ent(
            classname='func_detail'
        ).solids = [solids.solid]
    else:
        # Add to the world
        vmf.add_brush(solids.solid)


def parse_tempbrush_force(value: str) -> tuple[
    template_brush.ForceColour,
    template_brush.TEMP_TYPES,
    texturing.TileSize | None,
    texturing.GenCat,
]:
    """Parse the 'force' option for TemplateBrush."""
    colour: template_brush.ForceColour
    grid: texturing.TileSize | None

    force = value.casefold().split()
    if 'white' in force:
        colour = texturing.Portalable.white
    elif 'black' in force:
        colour = texturing.Portalable.black
    elif 'invert' in force:
        colour = template_brush.AppliedColour.INVERT
    else:
        colour = template_brush.AppliedColour.MATCH

    if 'world' in force:
        ent_type = template_brush.TEMP_TYPES.world
    elif 'detail' in force:
        ent_type = template_brush.TEMP_TYPES.detail
    else:
        ent_type = template_brush.TEMP_TYPES.default

    size: texturing.TileSize
    for size in texturing.TileSize:
        if size in force:
            grid = size
            break
    else:
        grid = None

    if 'bullseye' in force:
        surf_cat = texturing.GenCat.BULLSEYE
    elif 'special' in force or 'panel' in force:
        surf_cat = texturing.GenCat.PANEL
    else:
        surf_cat = texturing.GenCat.NORMAL

    return colour, ent_type, grid, surf_cat


@conditions.make_result('TemplateBrush', 'BrushTemplate')
def res_import_template(
    vmf: VMF,
    coll: collisions.Collisions,
    info: corridor.Info,
    voice: QuoteInfo,
    res: Keyvalues,
) -> conditions.ResultCallable:
    """Import a template VMF file, retexturing it to match orientation.

    It will be placed overlapping the given instance. If no block is used, only
    the ID can be specified.
    Options:

    - `ID`: The ID of the template to be inserted. Visgroups can be specified after
            a colon, comma-seperated (`temp_id:vis1,vis2`).
            `$fixup` variables can be used for any part. As a convenience, if the
            ID is totally blank this will do nothing.
    - `angles`: Override the instance rotation, so it is always rotated this much.
    - `rotation`: Apply the specified rotation before the instance's rotation.
    - `offset`: Offset the template from the instance's position.
    - `force`: a space-seperated list of overrides. If 'white' or 'black' is
             present, the colour of tiles will be overridden. If `invert` is
            added, white/black tiles will be swapped. If a tile size
            (`2x2`, `4x4`, `wall`, `special`) is included, all tiles will
            be switched to that size (if not a floor/ceiling). If 'world' or
            'detail' is present, the brush will be forced to that type.
    - `replace`: A block of template material -> replacement textures.
            This is case-insensitive - any texture here will not be altered
            otherwise. If the material starts with a `#`, it is instead a
            list of face IDs separated by spaces. If the result evaluates
            to "", no change occurs. Both can be $fixups (parsed first).
    - `bindOverlay`: Bind overlays in this template to the given surface, and
            bind overlays on a surface to surfaces in this template.
            The value specifies the offset to the surface, where 0 0 0 is the
            floor position. It can also be a block of multiple positions.
    - `alignBindOverlay`: If set, align the bindOverlay offsets to the grid.
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
            - A keyvalues block: Each name should match a visgroup, and the
              value should be a block of condition tests that if true enables that group.
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
    if res.has_children():
        orig_temp_id = res['id']
    else:
        orig_temp_id = res.value
        res = Keyvalues('TemplateBrush', [])

    force_opts = LazyValue.parse(res['force', '']).map(parse_tempbrush_force)
    replace_tex: dict[str, list[str]] = {}
    for kv in res.find_block('replace', or_blank=True):
        replace_tex.setdefault(kv.name, []).append(kv.value)

    if 'replaceBrush' in res:
        LOGGER.warning(
            'replaceBrush command used for template "{}", which is no '
            'longer used.',
            orig_temp_id,
        )
    bind_tile_pos = [
        # Offset so that 0 0 0 is the floor block location.
        LazyValue.parse(value).as_vec().map(lambda v: v - (0, 0, 128))
        for child in res.find_all('BindOverlay')
        for value in child.as_array()
    ]
    align_bind_overlay = LazyValue.parse(res['alignBindOverlay', '']).as_bool()

    key_values = res.find_block("Keys", or_blank=True)
    if key_values:
        key_block = Keyvalues("", [
            key_values,
            res.find_block("LocalKeys", or_blank=True),
        ])
        # Ensure we have a 'origin' keyvalue - we automatically offset that.
        if 'origin' not in key_values:
            key_values['origin'] = '0 0 0'

        outputs = [
            LazyValue.bimap(
                lambda name, val: Output.parse(Keyvalues(name, val)),
                LazyValue.parse(kv.real_name), LazyValue.parse(kv.value),
                'Output.parse',
            )
            for kv in
            res.find_children('Outputs')
        ]
    else:
        key_block = None
        outputs = []

    # None = don't add any more.
    visgroup_func: Callable[[Random, list[str]], Iterable[str]] | None = None

    try:  # allow both spellings.
        visgroup_kv = res.find_key('visgroups')
    except NoKeyError:
        visgroup_kv = res.find_key('visgroup', 'none')
    if visgroup_kv.has_children():
        visgroup_instvars = list(visgroup_kv)
    else:
        visgroup_instvars = []
        # TODO: Support fixups for this.
        visgroup_mode = visgroup_kv.value.casefold()
        # Generate the function which picks which visgroups to add to the map.
        if visgroup_mode == 'none':
            pass
        elif visgroup_mode == 'choose':
            def visgroup_func(rng: Random, groups: list[str]) -> Iterable[str]:
                """choose = add one random group."""
                return [rng.choice(groups)]
        else:
            percent = srctools.conv_float(visgroup_mode.rstrip('%'), 0.00)
            if percent > 0.0:
                def visgroup_func(rng: Random, groups: list[str]) -> Iterable[str]:
                    """Number = percent chance for each to be added"""
                    for group in sorted(groups):
                        if rng.uniform(0, 100) <= percent:
                            yield group

    picker_vars = [
        (LazyValue.parse(prop.real_name), prop.value)
        for prop in res.find_children('pickerVars')
    ]
    try:
        ang_override = LazyValue.parse(res['angles']).as_matrix()
    except LookupError:
        ang_override = None
    try:
        rotation = LazyValue.parse(res['rotation']).as_matrix()
    except LookupError:
        rotation = LAZY_MATRIX_IDENTITY

    offset = LazyValue.parse(res['offset', '0 0 0']).as_offset()
    invert_var = LazyValue.parse(res['invertVar', '']).as_bool()
    color_var = LazyValue.parse(res['colorVar', '']).casefold()

    # If true, force visgroups to all be used.
    visgroup_force = LazyValue.parse(res['forceVisVar', '']).as_bool()
    sense_offset = LazyValue.parse(res['senseOffset', '']).as_vec()

    def place_template(inst: Entity) -> None:
        """Place a template."""
        # Special case - if blank, just do nothing silently.
        if not orig_temp_id:
            return
        temp_id = inst.fixup.substitute(orig_temp_id)

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

        force_colour, force_type, force_grid, surf_cat = force_opts(inst)

        if key_block is not None:
            # Spawn everything as detail, so they get put into a brush
            # entity.
            force_type = template_brush.TEMP_TYPES.detail

        for vis_test_block in visgroup_instvars:
            if all(conditions.check_test(test, coll, info, voice, inst) for test in vis_test_block):
                visgroups.add(vis_test_block.real_name)
            if utils.DEV_MODE and vis_test_block.real_name not in template.visgroups:
                LOGGER.warning('"{}" may use missing visgroup "{}"!', template.id, vis_test_block.real_name)

        match color_var(inst):
            case '<editor>':
                # Check traits for the colour it should be.
                traits = instance_traits.get(inst)
                if 'white' in traits:
                    force_colour = texturing.Portalable.white
                elif 'black' in traits:
                    force_colour = texturing.Portalable.black
                else:
                    LOGGER.warning(
                        '"{}": Instance "{}" ' "isn't one with inherent colour!",
                        temp_id,
                        inst['file'],
                    )
            case 'white':
                force_colour = texturing.Portalable.white
            case 'black':
                force_colour = texturing.Portalable.black
            case '':
                pass  # no color var
            case invalid:
                LOGGER.warning('"{}": Invalid colour type "{}"!', temp_id, invalid)

        if invert_var(inst):
            force_colour = template_brush.TEMP_COLOUR_INVERT[force_colour]
        # else: False value, no invert.

        if ang_override is not None:
            orient = ang_override(inst)
        else:
            orient = rotation(inst) @ Angle.from_str(inst['angles', '0 0 0'])
        origin = offset(inst)

        # If this var is set, it forces all to be included.
        if visgroup_force(inst):
            visgroups.update(template.visgroups)
        elif visgroup_func is not None:
            visgroups.update(visgroup_func(
                rand.seed(b'temp', template.id, origin, orient),
                list(template.visgroups),
            ))

        LOGGER.debug(
            'Placing template "{}" at ({} @ {}) with visgroups {}',
            template.id, origin, orient.to_angle(), visgroups,
        )

        temp_data = template_brush.import_template(
            vmf,
            template,
            origin,
            orient,
            targetname=inst['targetname'],
            force_type=force_type,
            add_to_map=True,
            coll=coll,
            additional_visgroups=visgroups,
            bind_tile_pos=[value(inst) for value in bind_tile_pos],
            align_bind=align_bind_overlay(inst),
        )

        if key_block is not None and temp_data.detail is not None:
            conditions.set_ent_keys(temp_data.detail, inst, key_block)
            br_origin = Vec.from_str(key_block.find_key('keys')['origin'])
            br_origin.localise(origin, orient)
            temp_data.detail['origin'] = br_origin

            move_dir = temp_data.detail['movedir', '']
            if move_dir.startswith('<') and move_dir.endswith('>'):
                temp_data.detail['movedir'] = (Vec.from_str(move_dir) @ orient).to_angle()

            for lazy_out in outputs:
                out = lazy_out(inst)
                out.target = conditions.local_name(inst, out.target)
                temp_data.detail.add_out(out)

        template_brush.retexture_template(
            temp_data,
            origin,
            inst,
            replace_tex,
            force_colour,
            force_grid,
            surf_cat,
            sense_offset(inst),
        )

        for picker_name, picker_var in picker_vars:
            picker_val = temp_data.picker_results.get(picker_name(inst), None)
            if picker_val is not None:
                inst.fixup[picker_var] = picker_val.value
            else:
                inst.fixup[picker_var] = ''
    return place_template


# Position -> entity
# We merge ones within 3 blocks of our item.
CHECKPOINT_TRIG: dict[FrozenVec, Entity] = {}

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


@conditions.make_result('CheckpointTrigger')
def res_checkpoint_trigger(info: conditions.MapInfo, inst: Entity, res: Keyvalues) -> None:
    """Generate a trigger underneath coop checkpoint items.

    """

    if info.is_sp:
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
            trig = CHECKPOINT_TRIG[near_pos.freeze()]
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
        CHECKPOINT_TRIG[pos.freeze()] = trig

    trig.solids.append(inst.map.make_prism(
        bbox_min,
        bbox_max,
        mat=consts.Tools.TRIGGER,
    ).solid)

    for prop in res:
        out = Output.parse(prop)
        out.target = conditions.local_name(inst, out.target)
        trig.add_out(out)


@conditions.make_result('SetTile', 'SetTiles')
def res_set_tile(inst: Entity, res: Keyvalues) -> None:
    """Set 4x4 parts of a tile to the given values.

    `Offset` defines the position of the upper-left tile in the grid.
    Each `Tile` section defines a row of the positions to edit like so:
    ```c
    "SetTile"
        {
        "Offset" "-48 48 0"
        "Tile" "BBBB"
        "Tile" "B..B"
        "Tile" "B..B"
        "Tile" "BBBB"
        }
    ```
    * `Force`, if true, will make the specified tiles override any existing ones and
      create the tile if necessary. Otherwise, they will be merged in - `white`/`black`
      tiles will not replace tiles set to `nodraw` or `void` for example.
    * `chance`, if specified allows producing irregular tiles by randomly not
    changing the tile.

    If you need less regular placement (other orientation, precise positions)
    use a `bee2_template_tilesetter` in a template.

    Allowed tile characters:
    - `W`: White tile.
    - `w`: White 4x4 only tile.
    - `B`: Black tile.
    - `b`: Black 4x4 only tile.
    - `g`: The side/bottom of goo pits.
    - `G`: White goo side, if available.
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
    orient = Matrix.from_angstr(inst['angles'])

    offset = (res.vec('offset', -48, 48) - (0, 0, 64)) @ orient + origin

    norm = round(orient.up(), 6)

    force_tile = res.bool('force')

    tiles: list[str] = [
        row.value
        for row in res
        if row.name in ('tile', 'tiles')
    ]
    if not tiles:
        raise ValueError('No "tile" parameters in SetTile!')

    chance = srctools.conv_float(res['chance', '100'].rstrip('%'), 100.0)
    if chance < 100.0:
        rng = rand.seed(b'tile', inst, res['seed', ''])
    else:
        rng = None

    debug_add = conditions.fetch_debug_visgroup(inst.map, 'SetTile')

    for y, row in enumerate(tiles):
        for x, val in enumerate(row):
            if val in '_ ':
                continue

            if rng is not None and rng.uniform(0, 100) > chance:
                continue

            pos = Vec(32 * x, -32 * y, 0) @ orient + offset

            try:
                skin = template_brush.TILETYPE_TO_SKIN[tiling.TILETYPE_FROM_CHAR[val]]
            except KeyError:
                skin = 0
            debug_add(
                'bee2_template_tilesetter',
                origin=pos,
                angles=orient.to_angle(),
                force=force_tile,
                targetname=inst['targetname'],
                skin=skin,
                comment=f'This tile char [{x}, {y}] = {val}.',
            )

            if val == '4':
                size = tiling.TileSize.TILE_4x4
            elif val == '1':
                size = tiling.TileSize.TILE_1x1
            elif val == 'i':
                size = None
            else:
                try:
                    new_tile = tiling.TILETYPE_FROM_CHAR[val]
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
            existing = tile[u, v]

            if size is None:
                # Invert the tile.
                tile[u, v] = existing.inverted
                continue

            # Goo tiles and non-tiles must be forced to be changed.
            # If forcing, keep goo colour, non-tiles become black.
            if existing.is_tile and not existing.is_goo_side:
                tile[u, v] = tiling.TileType.with_color_and_size(
                    size,
                    existing.color
                )
            elif force_tile:
                tile[u, v] = tiling.TileType.with_color_and_size(
                    size,
                    existing.color if existing.is_goo_side else tiling.Portalable.BLACK,
                )


@conditions.make_result('addPlacementHelper')
def res_add_placement_helper(inst: Entity, res: Keyvalues) -> None:
    """Add a placement helper to a specific tile.

    `Offset` and `normal` specify the position and direction out of the surface
    the helper should be added to. If `upDir` is specified, this is the
    direction of the top of the portal.
    """
    orient = Matrix.from_angstr(inst['angles'])

    pos = conditions.resolve_offset(inst, res['offset', '0 0 0'], zoff=-64)
    normal = res.vec('normal', 0, 0, 1) @ orient

    up_dir: Vec | None
    try:
        up_dir = Vec.from_str(res['upDir']) @ orient
    except LookupError:
        up_dir = None

    try:
        tile = tiling.TILES[(pos - 64 * normal).as_tuple(), normal.as_tuple()]
    except KeyError:
        LOGGER.warning('No tile at {} @ {}', pos, normal)
        return

    tile.add_portal_helper(up_dir)


@conditions.make_result('SetPanelOptions', *[
    alter + pan + opts  # All the combinations
    for alter in ['Set', 'Alter']
    for pan in ['Panel', 'Pan']
    for opts in ['Options', 'Opts']
])
def res_set_panel_options(vmf: VMF, inst: Entity, kv: Keyvalues) -> None:
    """Modify an existing panel associated with this instance.

    See `CreatePanel` to add new ones.
    This is used for panel-type items, allowing them to generate the correct
    brushwork regardless of the kind of tiles used on the surface.
    It can also be used to generate some flat "slabs" protruding from a surface.
    This first finds panels, then applies the various options below if specified.

    Search parameters:
    - `normal`: The direction facing out of the surface. This defaults to "up".
    - `pos1`, `pos2`: Search for a panel covering the rectangle covering two
       diagnonally opposite corners. These default to a full tile.
    - `point`: Alternatively, individually specify each point to search for panels
       with irregular shapes.
    - `exact`: If true, only panels exactly matching the points will be found. If
      false, any panel overlapping these will be modified.

    Options:
    - `type`: Change the specially handled behaviours set for the panel.
       Available options:
        - `NORMAL`: No special behaviour.
        - `FLIP_BLACK`: Apply black tiles to the backside of the panel,
          doubling it in thickness.
        - `FLIP_INVERT`: Apply the inverse colour to the backside of the panel,
          doubling it in thickness.
        - `ANGLED_30`, `ANGLED_45`, `ANGLED_60`: Rotate the panel to match
          an extended panel of these angles.
        As a convenience, the `ramp_open_XX_deg` animation values will also be accepted.
    - `thickness`: The thickness of the surface. Must be 2, 4 or 8.
    - `bevel`: If true, angle the sides. Otherwise, leave them straight.
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
    edit_panel(vmf, inst, kv, create=False)


@conditions.make_result('CreatePanel')
def res_create_panel(vmf: VMF, inst: Entity, kv: Keyvalues) -> None:
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
        As a convenience, the `ramp_open_XX_deg` animation values will also be accepted.
    - `thickness`: The thickness of the surface. Must be 2, 4 or 8.
    - `bevel`: If true, angle the sides. Otherwise, leave them straight.
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
    edit_panel(vmf, inst, kv, create=True)


def edit_panel(vmf: VMF, inst: Entity, props: Keyvalues, create: bool) -> None:
    """Implements SetPanelOptions and CreatePanel."""
    orient = Matrix.from_angstr(inst['angles'])
    normal: Vec = round(props.vec('normal', 0, 0, 1) @ orient, 6)
    origin = Vec.from_str(inst['origin'])
    uaxis, vaxis = Vec.INV_AXIS[normal.axis()]
    inst_name = inst['targetname']

    add_debug_points = conditions.fetch_debug_visgroup(vmf, 'EditPanel - Point')
    add_debug_bevel = conditions.fetch_debug_visgroup(vmf, 'EditPanel - Bevel')
    add_debug_template = conditions.fetch_debug_visgroup(vmf, 'EditPanel - Template')

    points: set[FrozenVec] = set()
    brush_ent: Entity | None

    if 'point' in props:
        points |= {
            conditions.resolve_offset(inst, prop.value, zoff=-64).freeze()
            for prop in props.find_all('point')
        }
    elif 'pos1' in props and 'pos2' in props:
        pos1, pos2 = Vec.bbox(
            conditions.resolve_offset(inst, props['pos1', '-48 -48 0'], zoff=-64),
            conditions.resolve_offset(inst, props['pos2', '48 48 0'], zoff=-64),
        )
        points.update(FrozenVec.iter_grid(pos1, pos2, 32))
    else:
        # Default to the full tile.
        points.update({
            (FrozenVec(u, v, -64.0) @ orient + origin)
            for u in [-48.0, -16.0, 16.0, 48.0]
            for v in [-48.0, -16.0, 16.0, 48.0]
        })

    tiles_to_uv: dict[tiling.TileDef, set[tuple[int, int]]] = defaultdict(set)
    normal_ang = normal.to_angle()
    for fpos in points:
        try:
            tile, u, v = tiling.find_tile(fpos, normal, force=create)
        except KeyError:
            add_debug_points('info_null', origin=fpos, angles=normal_ang, targetname=inst_name)
            continue
        add_debug_points('info_target', origin=fpos, angles=normal_ang, targetname=inst_name)
        tiles_to_uv[tile].add((u, v))

    if not tiles_to_uv:
        LOGGER.warning('"{}": No tiles found for panels!', inst_name)
        return

    # If bevels is provided, parse out the overall world positions.
    bevel_world: set[tuple[int, int]] | None
    try:
        bevel_prop = props.find_key('bevel')
    except NoKeyError:
        bevel_world = None
    else:
        bevel_world = set()
        if bevel_prop.has_children():
            # Individually specifying offsets.
            for bevel_str in bevel_prop.as_array():
                bevel_point = Vec.from_str(bevel_str) @ orient + origin
                add_debug_bevel('info_target', origin=bevel_point, targetname=inst_name)
                bevel_world.add((int(bevel_point[uaxis]), int(bevel_point[vaxis])))
        elif srctools.conv_bool(bevel_prop.value):
            # Fill the bounding box.
            bbox_min, bbox_max = Vec.bbox(map(Vec, points))
            off = Vec.with_axes(uaxis, 32, vaxis, 32)
            bbox_min -= off
            bbox_max += off
            for fpos in FrozenVec.iter_grid(bbox_min, bbox_max, 32):
                add_debug_bevel('info_target', origin=fpos, targetname=inst_name)
                if fpos not in points:
                    bevel_world.add((int(fpos[uaxis]), int(fpos[vaxis])))
        # else: No bevels.
    panels: list[tuple[tiling.Panel, tiling.TileDef]] = []

    # If editing, allow specifying a subset of points to mean the same panel.
    exact = props.bool('exact', True)

    for tile, uvs in tiles_to_uv.items():
        if create:
            panel = tiling.Panel(
                None, inst, tiling.PanelType.NORMAL,
            )
            panel.points = uvs
            tile.panels.append(panel)
        else:
            for panel in tile.panels:
                if panel.same_item(inst) and (
                    panel.points == uvs
                    if exact else
                    not panel.points.isdisjoint(uvs)
                ):
                    break
            else:
                LOGGER.warning('No panel to modify found for "{}"!', inst_name)
                continue
        panels.append((panel, tile))

        if 'type' in props:
            pan_type = props['type']
            try:
                panel.pan_type = PANEL_TYPES[inst.fixup.substitute(pan_type).casefold()]
            except (KeyError, ValueError):
                raise ValueError(f'Unknown panel type "{pan_type}"!') from None

        if 'thickness' in props:
            thickness = srctools.conv_int(inst.fixup.substitute(props['thickness']))
            if thickness not in (2, 4, 8):
                raise ValueError(
                    '"{}": Invalid panel thickess {}!\n'
                    'Must be 2, 4 or 8.',
                    inst_name,
                    thickness,
                )
            panel.thickness = thickness

        if bevel_world is not None:
            panel.bevels.clear()
            for u, v in bevel_world:
                # Convert from world points to UV positions.
                u = round((u - tile.pos[uaxis] + 48) // 32)
                v = round((v - tile.pos[vaxis] + 48) // 32)
                # Cull outside here, we won't use them.
                if -1 <= u <= 4 and -1 <= v <= 4:
                    panel.bevels.add((u, v))

        if 'offset' in props:
            panel.offset = conditions.resolve_offset(inst, props['offset'])
            panel.offset -= Vec.from_str(inst['origin'])
        if 'nodraw' in props:
            panel.nodraw = srctools.conv_bool(inst.fixup.substitute(props['nodraw'], allow_invert=True))
        if 'seal' in props:
            panel.seal = srctools.conv_bool(inst.fixup.substitute(props['seal'], allow_invert=True))
        if 'move_bullseye' in props:
            panel.steals_bullseye = srctools.conv_bool(inst.fixup.substitute(props['move_bullseye'], allow_invert=True))

    if not panels:
        return  # Didn't match anything?

    if 'keys' in props or 'localkeys' in props:
        # First grab the existing ent, so we can edit it.
        # These should all have the same value, unless they were independently
        # edited with mismatching point sets. In that case destroy all those existing ones.
        existing_ents: set[Entity | None] = {panel.brush_ent for panel, tile in panels}
        try:
            [brush_ent] = existing_ents
        except ValueError:
            LOGGER.warning(
                'Multiple independent panels for "{}" were made, then the '
                'brush entity was edited as a group! Discarding '
                'individual ents...',
                inst_name
            )
            for brush_ent in existing_ents:
                if brush_ent is not None and brush_ent in vmf.entities:
                    brush_ent.remove()
            brush_ent = None

        if brush_ent is None:
            brush_ent = vmf.create_ent('')

        old_pos = brush_ent.pop('origin', None)

        conditions.set_ent_keys(brush_ent, inst, props)
        if not brush_ent['classname']:
            if create:  # This doesn't make sense, you could just omit the prop.
                LOGGER.warning(
                    'No classname provided for panel "{}"!',
                    inst_name,
                )
            # Make it a world brush.
            brush_ent.remove()
            brush_ent = None
        else:
            # We want to do some post-processing.
            # Localise any origin value.
            if 'origin' in brush_ent:
                pos = Vec.from_str(brush_ent['origin'])
                pos.localise(
                    Vec.from_str(inst['origin']),
                    Angle.from_str(inst['angles']),
                )
                brush_ent['origin'] = pos
            elif old_pos is not None:
                brush_ent['origin'] = old_pos

            # If it's func_detail, clear out all the keys.
            # Particularly `origin`, but the others are useless too.
            if brush_ent['classname'] == 'func_detail':
                brush_ent.clear_keys()
                brush_ent['classname'] = 'func_detail'
        for panel, tile in panels:
            panel.brush_ent = brush_ent

    template_kv = props.find_key('template', or_blank=True)
    if template_kv:
        # This is tricky, todo need to redesign.
        # Templates must be inserted only once. If there's one panel, we're fine, just assign it to that.
        # But if there's multiple panels, users need to specify which tiledef they apply to.
        # If they don't, fall back to picking the tiledef closest to the instance origin.
        if template_kv.has_children():
            template_pos = {
                (
                    (FrozenVec.from_str(child.real_name) - (0, 0, 64))
                    @ orient + origin
                ): inst.fixup.substitute(child.value)
                for child in template_kv
            }
            for fpos in template_pos:
                add_debug_template('bee2_template_conf', origin=fpos)
            for panel, tile in panels:
                try:
                    panel.template = template_pos[tile.pos_front.freeze()]
                except KeyError:
                    add_debug_template(
                        'info_null',
                        targetname=inst_name,
                        origin=tile.pos_front,
                    )
                else:
                    add_debug_template(
                        'info_target',
                        targetname=inst_name,
                        origin=tile.pos_front,
                        comment=panel.template,
                    )
        else:  # One template name.
            if len(panels) == 1:
                [(panel, tile)] = panels
            else:
                # One template, multiple panels.
                LOGGER.warning(
                    'A panel instance "{}" straddles multiple voxels, and has a template '
                    'defined. The template needs to specify which tile it should apply to.\nSub-panels: {}',
                    inst_name,
                    panels,
                )
                # Pick the one with the closest origin.
                panel, tile = min(panels, key=lambda tup: (tup[1].pos - origin).mag_sq())
            panel.template = inst.fixup.substitute(template_kv.value)


def _fill_norm_rotations() -> dict[tuple[FrozenVec, FrozenVec], Matrix]:
    """Given a norm->norm rotation, return the angles producing that."""
    rotations: dict[tuple[FrozenVec, FrozenVec], Matrix] = {}
    for norm_ax in 'xyz':
        for norm_mag in [-1, +1]:
            norm = FrozenVec.with_axes(norm_ax, norm_mag)
            for angle_ax in ('pitch', 'yaw', 'roll'):
                for angle_mag in (-90, 90):
                    angle = Matrix.from_angle(Angle.with_axes(angle_ax, angle_mag))
                    new_norm = norm @ angle
                    if new_norm != norm:
                        rotations[norm, new_norm] = angle
            # Assign a null rotation as well.
            rotations[norm, norm] = Matrix()
            rotations[norm, -norm] = Matrix()
    return rotations


NORM_ROTATIONS = _fill_norm_rotations()
del _fill_norm_rotations


@conditions.make_result("TransferBullseye")
def res_transfer_bullseye(inst: Entity, kv: Keyvalues) -> None:
    """Transfer catapult targets and placement helpers from one tile to another."""
    start_pos = conditions.resolve_offset(inst, kv['start_pos', ''])
    end_pos = conditions.resolve_offset(inst, kv['end_pos', ''])
    angles = Angle.from_str(inst['angles'])
    start_norm: Vec = kv.vec('start_norm', 0, 0, 1) @ angles
    end_norm: Vec = kv.vec('end_norm', 0, 0, 1) @ angles

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
        if Vec.dot(start_norm, end_norm) > -0.999:
            # Use the dict to compute the rotation to apply.
            orient @= NORM_ROTATIONS[start_norm.freeze(), end_norm.freeze()]
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
            if not isinstance(plate, faithplate.StraightPlate) and plate.target is start_tile:
                plate.target = end_tile


@conditions.make_result("RotateToPanel")
def res_rotate_to_panel(kv: Keyvalues) -> conditions.ResultCallable:
    """Find a panel on the specified surface, then rotate the instance if required to match."""
    conf_pos = LazyValue.parse(kv['pos', '0 0 0']).as_offset(zoff=-64)
    conf_norm = LazyValue.parse(kv['normal', '0 0 1']).as_vec(0, 0, 1)
    ignore_missing = LazyValue.parse(kv['ignoreMissing', '0']).as_bool()

    def rotate_inst(inst: Entity) -> None:
        """Rotate the item."""
        orient = Matrix.from_angstr(inst['angles'])

        tile_pos = conf_pos(inst)
        tile_norm = conf_norm(inst) @ orient
        try:
            tile = tiling.TILES[(tile_pos - 64 * tile_norm).as_tuple(), tile_norm.as_tuple()]
        except KeyError:
            if not ignore_missing(inst):
                LOGGER.warning('"{}": Cannot find tile at {}, {}!'.format(
                    inst['targetname'], tile_pos, tile_norm,
                ))
            return
        if len(tile.panels) == 0:
            if not ignore_missing(inst):
                LOGGER.warning('"{}": Cannot find panel at {}, {}!'.format(
                    inst['targetname'], tile_pos, tile_norm,
                ))
            return
        origin = Vec.from_str(inst['origin'])
        panel = tile.panels[0]

        if panel.pan_type.is_angled:
            panel_orient = Matrix.from_angstr(panel.inst['angles'])
            panel_pos = Vec.from_str(panel.inst['origin'])
            rotation = Matrix.axis_angle(
                -panel_orient.left(),
                panel.pan_type.angle,
            )

            panel_anchor = panel_pos + Vec(-64, 0, -64) @ panel_orient

            # Shift so the rotation anchor is 0 0 0, then shift back to rotate correctly.
            origin -= panel_anchor
            orient @= rotation
            origin @= rotation
            origin += panel_anchor
            inst['angles'] = orient

        origin += panel.offset
        inst['origin'] = origin

    return rotate_inst
