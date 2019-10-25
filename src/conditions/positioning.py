import math

from conditions import (
    make_flag, make_result, resolve_offset,
    DIRECTIONS,
)
import tiling
import brushLoc
from srctools import Vec, Entity, Property


COND_MOD_NAME = 'Positioning'


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

    - `Angle`: A unit vector (XYZ value) pointing in a direction, or some
        keywords: `+z`, `-y`, `N`/`S`/`E`/`W`, `up`/`down`, `floor`/`ceiling`, or `walls` for any wall side.
    - `From_dir`: The direction the unrotated instance is pointed in.
        This lets the flag check multiple directions.
    - `Allow_inverse`: If true, this also returns True if the instance is
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
        allow_inverse = flag.bool('allow_inverse')
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
    """Checks to see if a tile is present at the given location.

    - `Pos` is the position of the tile, where `0 0 0` is the floor-position
       of the brush.
    - `Dir` is the normal the face is pointing. `(0 0 1)` is up.
    - `Pos2`: If set, causes the check to average the tiles in a bounding box.
      If no tiles are present they're treated as a lack of them.
      Otherwise the dominant colour wins, with ties treated as black.
    - `Type` defines the type the brush must be:
      - `Any` requires some sort of surface.
      - `Tile` allows a black/white tile of some kind.
      - `None` means that no surface must be present.
      - `White` requires a portalable surface.
      - `Black` requires a non-portalable surface.
    - `SetVar` defines an instvar which will be given a value of `black`,
      `white` or `none` to allow the result to be reused.
    - If `gridPos` is true, the position will be snapped so it aligns with
      the 128 grid (Useful with fizzler/light strip items).
    - `RemoveTile`: If set to `1`, the tile will be removed if found.
    """
    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles'])

    pos = flag.vec('pos')
    pos.z -= 64  # Subtract so origin is the floor-position

    pos.localise(origin, angles)

    norm = flag.vec('dir', 0, 0, 1).rotate(*angles)

    if flag.bool('gridpos') and norm is not None:
        for axis in 'xyz':
            # Don't realign things in the normal's axis -
            # those are already fine.
            if norm[axis] == 0:
                pos[axis] = pos[axis] // 128 * 128 + 64

    result_var = flag['setVar', '']
    # RemoveBrush is the pre-tiling name.
    should_remove = flag.bool('RemoveTile', flag.bool('RemoveBrush', False))

    des_type = flag['type', 'any'].casefold()

    if 'pos2' in flag:
        pos2 = flag.vec('pos2')
        pos2.z -= 64  # Subtract so origin is the floor-position
        pos2.localise(origin, angles)

        bbox_min, bbox_max = Vec.bbox(pos, pos2)

        white_count = black_count = 0

        for pos in Vec.iter_grid(bbox_min, bbox_max, 32):
            try:
                tiledef, u, v = tiling.find_tile(pos, norm)
            except KeyError:
                continue

            tile_type = tiledef[u, v]
            if should_remove:
                tiledef[u, v] = tiling.TileType.VOID
            if tile_type.is_tile:
                if tile_type.color is tiling.Portalable.WHITE:
                    white_count += 1
                else:
                    black_count += 1

        if white_count == black_count == 0:
            tile_type = tiling.TileType.VOID
        elif white_count > black_count:
            tile_type = tiling.TileType.WHITE
        else:
            tile_type = tiling.TileType.BLACK
    else:
        # Single tile.
        try:
            tiledef, u, v = tiling.find_tile(pos, norm)
        except KeyError:
            tile_type = tiling.TileType.VOID
        else:
            tile_type = tiledef[u, v]
            if should_remove:
                tiledef[u, v] = tiling.TileType.VOID

    if result_var:
        if tile_type.is_tile:
            # Don't distinguish between 4x4, goo sides
            inst.fixup[result_var] = tile_type.color.value
        elif tile_type is tiling.TileType.VOID:
            inst.fixup[result_var] = 'none'
        else:
            inst.fixup[result_var] = tile_type.name.casefold()

    return (
        # Exact match
        (des_type == tile_type.name.casefold()) or
        (des_type == 'any' and tile_type is not tiling.TileType.VOID) or
        (des_type == 'tile' and tile_type.is_tile) or
        (des_type == 'none' and tile_type is tiling.TileType.VOID) or
        # white/black matches the other tile types too.
        (tile_type.is_tile and des_type == tile_type.color.name)
    )


@make_result('ReadSurfType')
def res_brush_at_loc(inst: Entity, res: Property):
    """Read the type of surface at a particular location.

    - `Pos` is the position of the tile, where `0 0 0` is the floor-position
       of the brush.
    - `Dir` is the normal the face is pointing. `(0 0 1)` is up.
    - `Pos2`: If set, causes the check to average the tiles in a bounding box.
      If no tiles are present they're treated as a lack of them.
      Otherwise the dominant colour wins, with ties treated as black.
    - `ResultVar` is the variable which is set. This will be set to
      `black`, `white` or `none`.
    - If `gridPos` is true, the position will be snapped so it aligns with
      the 128 grid (Useful with fizzler/light strip items).
    - `RemoveTile`: If set to `1`, the tile will be removed if found.
    """
    # Alias PosIsSolid to also be a result, for using the variable mode by itself.
    res['setVar'] = res['resultVar']
    flag_brush_at_loc(inst, res)


@make_flag('PosIsGoo')
def flag_goo_at_loc(inst: Entity, flag: Property):
    """Check to see if a given location is submerged in goo.

    `0 0 0` is the origin of the instance, values are in `128` increments.
    """
    offset = resolve_offset(inst, flag.value, scale=128)
    block = brushLoc.POS['world': offset]
    return block.is_goo


@make_flag('BlockType')
def flag_blockpos_type(inst: Entity, flag: Property):
    """Determine the type of a grid position.

    If the value is single value, that should be the type.
    Otherwise, the value should be a block with 'offset' and 'type' values.
    The offset is in block increments, with 0 0 0 equal to the mounting voxel.
    If 'offset2' is also provided, all positions in the bounding box will
    be checked.

    The type should be a space-seperated list of locations:

    * `VOID` (Outside the map)
    * `SOLID` (Full wall cube)
    * `EMBED` (Hollow wall cube)
    * `AIR` (Inside the map, may be occupied by items)
    * `OCCUPIED` (Known to be occupied by items)
    * `PIT` (Bottomless pits, any)
        * `PIT_SINGLE` (one-high)
        * `PIT_TOP`
        * `PIT_MID`
        * `PIT_BOTTOM`
    * `GOO`
        * `GOO_SINGLE` (one-deep goo)
        * `GOO_TOP` (goo surface)
        * `GOO_MID`
        * `GOO_BOTTOM` (floor)
    """
    pos2 = None

    if flag.has_children():
        pos1 = resolve_offset(inst, flag['offset', '0 0 0'], scale=128, zoff=-128)
        types = flag['type'].split()
        if 'offset2' in flag:
            pos2 = resolve_offset(inst, flag['offset2', '0 0 0'], scale=128, zoff=-128)
    else:
        types = flag.value.split()
        pos1 = Vec()

    if pos2 is not None:
        bbox = Vec.iter_grid(*Vec.bbox(pos1, pos2), stride=128)
    else:
        bbox = [pos1]

    for pos in bbox:
        block = brushLoc.POS['world': pos]
        for block_type in types:
            try:
                allowed = brushLoc.BLOCK_LOOKUP[block_type.casefold()]
            except KeyError:
                raise ValueError('"{}" is not a valid block type!'.format(block_type))
            if block in allowed:
                break  # To next position
        else:
            return False  # Didn't match any in this list.
    return True  # Matched all positions.


@make_result('SetBlock')
def res_set_block(inst: Entity, res: Property):
    """Set a block to the given value.

    This should be used only if you know what is in the position.
    The offset is in block increments, with `0 0 0` equal to the mounting surface.
    """
    try:
        new_vals = brushLoc.BLOCK_LOOKUP[res['type'].casefold()]
    except KeyError:
        raise ValueError('"{}" is not a valid block type!'.format(res['type']))

    try:
        [new_val] = new_vals
    except ValueError:
        raise ValueError("Can't use compound block types ({})!".format(res['type']))

    pos = resolve_offset(inst, res['offset', '0 0 0'], scale=128, zoff=-128)
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

    The special values `<piston>`, `<piston_bottom>` and `<piston_top>` can be
    used to offset it based on the starting position, bottom or top position
    of a piston platform.
    """
    inst['origin'] = resolve_offset(inst, res.value)


@make_result('OppositeWallDist')
def res_calc_opposite_wall_dist(inst: Entity, res: Property):
    """Calculate the distance between this item and the opposing wall.

    The value is stored in the `$var` specified by the property value.
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

    if adjust_goo and brushLoc.POS['world': opposing_pos + 128*normal].is_goo:
        # If the top is goo, adjust so the 64 below is the top of the goo.
        dist_off += 32

    inst.fixup[result_var] = (origin - opposing_pos).mag() + dist_off
