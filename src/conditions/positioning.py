import math

from conditions import (
    make_flag, make_result,
    DIRECTIONS, SOLIDS, GOO_LOCS,
)
import brushLoc
from srctools import Vec, Entity, Property
import srctools


@make_flag(
    'rotation',
    'angle',
    'angles',
    'orient',
    'orientation',
    'dir',
    'direction',
)
def flag_angles(inst: Entity, flag: Property):
    """Check that a instance is pointed in a direction.

    The value should be either just the angle to check, or a block of
    options:
    - Angle: A unit vector (XYZ value) pointing in a direction, or some
        keywords: +z, -y, N/S/E/W, up/down, floor/ceiling, or walls
    - From_dir: The direction the unrotated instance is pointed in.
        This lets the flag check multiple directions
    - Allow_inverse: If true, this also returns True if the instance is
        pointed the opposite direction .
    """
    angle = inst['angles', '0 0 0']

    if flag.has_children():
        targ_angle = flag['direction', '0 0 0']
        from_dir = flag['from_dir', '0 0 1']
        if from_dir.casefold() in DIRECTIONS:
            from_dir = Vec(DIRECTIONS[from_dir.casefold()])
        else:
            from_dir = Vec.from_str(from_dir, 0, 0, 1)
        allow_inverse = srctools.conv_bool(flag['allow_inverse', '0'])
    else:
        targ_angle = flag.value
        from_dir = Vec(0, 0, 1)
        allow_inverse = False

    normal = DIRECTIONS.get(targ_angle.casefold(), None)
    if normal is None:
        return False  # If it's not a special angle,
        # so it failed the exact match

    inst_normal = from_dir.rotate_by_str(angle)

    if normal == 'WALL':
        # Special case - it's not on the floor or ceiling
        return not (inst_normal == (0, 0, 1) or inst_normal == (0, 0, -1))
    else:
        return inst_normal == normal or (
            allow_inverse and -inst_normal == normal
        )


@make_flag('posIsSolid')
def flag_brush_at_loc(inst: Entity, flag: Property):
    """Checks to see if a wall is present at the given location.

    - Pos is the position of the brush, where `0 0 0` is the floor-position
       of the brush.
    - Dir is the normal the face is pointing. (0 0 -1) is 'up'.
    - Type defines the type the brush must be:
      - "Any" requires either a black or white brush.
      - "None" means that no brush must be present.
      - "White" requires a portalable surface.
      - "Black" requires a non-portalable surface.
    - SetVar defines an instvar which will be given a value of "black",
      "white" or "none" to allow the result to be reused.
    - If gridPos is true, the position will be snapped so it aligns with
      the 128 brushes (Useful with fizzler/light strip items).
    - RemoveBrush: If set to 1, the brush will be removed if found.
      Only do this to EmbedFace brushes, since it will remove the other
      sides as well.
    """
    from conditions import VMF
    pos = Vec.from_str(flag['pos', '0 0 0'])
    pos.z -= 64  # Subtract so origin is the floor-position
    pos = pos.rotate_by_str(inst['angles', '0 0 0'])

    # Relative to the instance origin
    pos += Vec.from_str(inst['origin', '0 0 0'])

    norm = flag['dir', None]
    if norm is not None:
        norm = Vec.from_str(norm).rotate_by_str(
            inst['angles', '0 0 0'],
        )

    if srctools.conv_bool(flag['gridpos', '0']) and norm is not None:
        for axis in 'xyz':
            # Don't realign things in the normal's axis -
            # those are already fine.
            if norm[axis] == 0:
                pos[axis] = pos[axis] // 128 * 128 + 64

    result_var = flag['setVar', '']
    should_remove = srctools.conv_bool(flag['RemoveBrush', False], False)
    des_type = flag['type', 'any'].casefold()

    brush = SOLIDS.get(pos.as_tuple(), None)

    if brush is None or (norm is not None and abs(brush.normal) != abs(norm)):
        br_type = 'none'
    else:
        br_type = str(brush.color)
        if should_remove:
            VMF.remove_brush(
                brush.solid,
            )

    if result_var:
        inst.fixup[result_var] = br_type

    if des_type == 'any' and br_type != 'none':
        return True

    return des_type == br_type


@make_flag('PosIsGoo')
def flag_goo_at_loc(inst: Entity, flag: Property):
    """Check to see if a given location is submerged in goo.

    0 0 0 is the origin of the instance, values are in 128 increments.
    """
    pos = Vec.from_str(flag.value).rotate_by_str(inst['angles', '0 0 0'])
    pos *= 128
    pos += Vec.from_str(inst['origin'])

    # Round to 128 units, then offset to the center
    pos = pos // 128 * 128 + 64  # type: Vec
    val = pos.as_tuple() in GOO_LOCS
    return val


@make_flag('BlockType')
def flag_blockpos_type(inst: Entity, flag: Property):
    """Determine the type of a grid position.

    If the value is single value, that should be the type.
    Otherwise, the value should be a block with 'offset' and 'type' values.
    The offset is in block incrments, with 0 0 0 equal to the mounting surface.

    The type should be a space-seperated list of locations:
    * VOID (Outside the map)
    * SOLID (Full wall cube)
    * EMBED (Hollow wall cube)
    * AIR (Inside the map, may be occupied by items)
    * OCCUPIED (Known to be occupied by items)
    * PIT (Bottomless pits, any)
      * PIT_SINGLE (one-high)
      * PIT_TOP
      * PIT_MID
      * PIT_BOTTOM
    * GOO
      * GOO_SINGLE (one-deep goo)
      * GOO_TOP (goo surface)
      * GOO_MID
      * GOO_BOTTOM (floor)
    """
    if flag.has_children():
        pos = flag.vec('offset') * 128
        types = flag['type'].split()
    else:
        types = flag.value.split()
        pos = Vec()
    pos.z -= 128
    pos.localise(
        Vec.from_str(inst['origin']),
        Vec.from_str(inst['angles']),
    )
    block = brushLoc.POS['world': pos]
    for block_type in types:
        try:
            allowed = brushLoc.BLOCK_LOOKUP[block_type.casefold()]
        except KeyError:
            raise ValueError('"{}" is not a valid block type!'.format(block_type))
        if block in allowed:
            return True
    return False


@make_result('SetBlock')
def res_set_block(inst: Entity, res: Property):
    """Set a block to the given value.

    This should be used only if you know what is in the position.
    The offset is in block increments, with 0 0 0 equal to the mounting surface.
    """
    pos = res.vec('offset') * 128
    try:
        new_vals = brushLoc.BLOCK_LOOKUP[res['type'].casefold()]
    except KeyError:
        raise ValueError('"{}" is not a valid block type!'.format(res['type']))

    try:
        [new_val] = new_vals
    except ValueError:
        raise ValueError("Can't use compound block types ({})!".format(res['type']))

    pos.z -= 128
    pos.localise(
        Vec.from_str(inst['origin']),
        Vec.from_str(inst['angles']),
    )
    brushLoc.POS['world': pos] = new_val


@make_result('forceUpright')
def res_force_upright(inst: Entity):
    """Position an instance to orient upwards while keeping the normal.

    The result angle will have pitch and roll set to 0. Vertical
    instances are unaffected.
    """
    normal = Vec(0, 0, 1).rotate_by_str(inst['angles'])
    if normal.z != 0:
        return
    ang = math.degrees(math.atan2(normal.y, normal.x))
    inst['angles'] = '0 {:g} 0'.format(ang % 360)  # Don't use negatives


@make_result('setAngles')
def res_set_angles(inst: Entity, res: Property):
    """Set the orientation of an instance to a certain angle."""
    inst['angles'] = res.value


@make_result('OffsetInst', 'offsetinstance')
def res_translate_inst(inst: Entity, res: Property):
    """Translate the instance locally by the given amount.

    The special values <piston>, <piston_bottom> and <piston_top> can be
    used to offset it based on the starting position, bottom or top position
    of a piston platform.
    """
    folded_val = res.value.casefold()
    if folded_val == '<piston>':
        folded_val = (
            '<piston_top>' if
            srctools.conv_bool(inst.fixup['$start_up'])
            else '<piston_bottom>'
        )

    if folded_val == '<piston_top>':
        val = Vec(z=128 * srctools.conv_int(inst.fixup['$top_level', '1'], 1))
    elif folded_val == '<piston_bottom>':
        val = Vec(z=128 * srctools.conv_int(inst.fixup['$bottom_level', '0'], 0))
    else:
        val = Vec.from_str(res.value)

    offset = val.rotate_by_str(inst['angles'])
    inst['origin'] = (offset + Vec.from_str(inst['origin'])).join(' ')


@make_result('OppositeWallDist')
def res_calc_opposite_wall_dist(inst: Entity, res: Property):
    """Calculate the distance between this item and the opposing wall.

    The value is stored in the $var specified by the property value.
    Alternately it is set by `ResultVar`, and `offset` adds or subtracts to the value.
    `GooCollide` means that it will stop when goo is found, otherwise it is
    ignored.
    `GooAdjust` means additionally if the space is goo, the distance will
    be modified so that it specifies the surface of the goo.
    """
    if res.has_children():
        result_var = res['ResultVar']
        dist_off = res.float('offset')
        collide_goo = res.bool('GooCollide')
        adjust_goo = res.bool('GooAdjust')
    else:
        result_var = res.value
        dist_off = 0
        collide_goo = adjust_goo = False

    origin = Vec.from_str(inst['origin'])
    normal = Vec(z=1).rotate_by_str(inst['angles'])

    mask = [
        brushLoc.Block.SOLID,
        brushLoc.Block.EMBED,
        brushLoc.Block.PIT_BOTTOM,
        brushLoc.Block.PIT_SINGLE,
    ]

    # Only if actually downward.
    if normal == (0, 0, -1) and collide_goo:
        mask.append(brushLoc.Block.GOO_TOP)
        mask.append(brushLoc.Block.GOO_SINGLE)

    opposing_pos = brushLoc.POS.raycast_world(
        origin,
        normal,
        mask,
    )

    if adjust_goo and brushLoc.POS['world': opposing_pos].is_goo:
        # If the top is goo, adjust so the 64 below is the top of the goo.
        dist_off += 32

    inst.fixup[result_var] = (origin - opposing_pos).mag() + dist_off
