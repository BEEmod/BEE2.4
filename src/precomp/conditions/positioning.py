"""Various conditions related to the position/orientation of items."""
from collections.abc import Iterable
import math

from editoritems_props import PanelAnimation
from precomp import conditions, tiling, brushLoc
from srctools import Vec, FrozenVec, Angle, Matrix, conv_float, Keyvalues, Entity
from srctools.logger import get_logger

from precomp.lazy_value import LazyValue


COND_MOD_NAME = 'Positioning'
LOGGER = get_logger(__name__, alias='cond.positioning')

# Predicates for tiles.
# We optimise to a lookup table.
TILE_PREDICATES: dict[str, set[tiling.TileType]] = {}


def parse_orient(direction: str) -> FrozenVec:
    """Parse a FrozenVec, allowing DIRECTIONS constants also."""
    try:
        return conditions.DIRECTIONS[direction.casefold()]
    except KeyError:
        return FrozenVec.from_str(direction, 0, 0, 1)


@conditions.make_test(
    'rotation',
    'angle',
    'angles',
    'orient',
    'orientation',
    'dir',
    'direction',
)
def check_angles(kv: Keyvalues) -> conditions.TestCallable:
    """Check that an instance is pointed in a direction.

    The value should be either just the angle to check, or a block of
    options:

    - `direction`: A unit vector (XYZ value) pointing in a direction, or some
        keywords: `+z`, `-y`, `N`/`S`/`E`/`W`, `up`/`down`, `floor`/`ceiling`, or `walls` for any wall side.
    - `From_dir`: The direction the unrotated instance is pointed in.
        This lets the test check multiple directions.
    - `Allow_inverse`: If true, this also returns True if the instance is
        pointed the opposite direction .
    """

    if kv.has_children():
        targ_angle = kv['direction', '0 0 0']
        from_dir = LazyValue.parse(kv['from_dir', '0 0 1']).map(parse_orient)
        allow_inverse = LazyValue.parse(kv['allow_inverse', '']).as_bool()
    else:
        targ_angle = kv.value
        from_dir = LazyValue.make(FrozenVec(0, 0, 1))
        allow_inverse = LazyValue.make(False)

    if '$' in targ_angle:
        raise ValueError('Cannot use $var in "direction" key for Angles/Orient/Dir test!')

    targ_angle = targ_angle.casefold()
    if targ_angle in ('wall', 'walls'):
        def check_orient(inst: Entity) -> bool:
            """Check if the instance is facing any wall."""
            inst_normal = from_dir(inst) @ Matrix.from_angstr(inst['angles'])
            return abs(inst_normal.z) < 1e-6
    else:
        try:
            normal = conditions.DIRECTIONS[targ_angle]
        except KeyError:
            normal = FrozenVec.from_str(targ_angle)

        def check_orient(inst: Entity) -> bool:
            """Check the orientation against the instance."""
            inst_normal = from_dir(inst) @ Matrix.from_angstr(inst['angles'])

            dot = inst_normal.dot(normal)
            return dot > 0.99 or (allow_inverse(inst) and dot < -0.99)
    return check_orient


def brush_at_loc(
    inst: Entity,
    kv: Keyvalues,
) -> tuple[tiling.TileType, bool, set[tiling.TileType]]:
    """Common code for posIsSolid and ReadSurfType.

    This returns the average tiletype, if both colors were found,
    and a set of all types found.
    """
    origin = Vec.from_str(inst['origin'])
    orient = Matrix.from_angstr(inst['angles'])

    # Allow using pos1 instead, to match pos2.
    pos = kv.vec('pos1' if 'pos1' in kv else 'pos')
    pos.z -= 64  # Subtract so origin is the floor-position

    pos.localise(origin, orient)

    norm: Vec = round(kv.vec('dir', 0, 0, 1) @ orient, 6)

    result_var = kv['setVar', '']
    # RemoveBrush is the pre-tiling name.
    should_remove = kv.bool('RemoveTile', kv.bool('RemoveBrush', False))

    tile_types: set[tiling.TileType] = set()
    both_colors = False

    # Place info_targets to mark where we're checking.
    # These are hidden in a visgroup.
    debug_info = kv['debug', '']

    # In dev mode, display a visual of this location.
    debug_adder = conditions.fetch_debug_visgroup(inst.map, 'TileAtLoc')

    first_trace = debug_adder(
        'info_target',
        origin=pos,
        targetname=inst['targetname'],
        comments=debug_info,
    )

    if 'pos2' in kv:
        pos2 = kv.vec('pos2')
        pos2.z -= 64  # Subtract so origin is the floor-position
        pos2.localise(origin, orient)

        # Place a second for the bounding box, grouped with the first.
        second_trace = debug_adder(
            'info_target',
            origin=pos2,
            targetname=inst['targetname'],
            comments=debug_info,
        )

        bbox_min, bbox_max = Vec.bbox(round(pos, 6), round(pos2, 6))

        if kv.bool('gridpos'):
            # For bboxes, expand to fit the grid.
            for axis in 'xyz':
                if abs(norm[axis]) < 1e-6:
                    bbox_min[axis] = math.floor((bbox_min[axis] - 0.125) / 32) * 32 + 16
                    bbox_max[axis] = math.ceil((bbox_max[axis] + 0.125) / 32) * 32 - 16
            first_trace['origin'] = bbox_min
            second_trace['origin'] = bbox_max

        white_count = black_count = 0

        for pos in Vec.iter_grid(bbox_min, bbox_max, 32):
            try:
                tiledef, u, v = tiling.find_tile(pos, norm)
            except KeyError:
                continue

            tile_type = tiledef[u, v]
            tile_types.add(tile_type)
            if should_remove:
                tiledef[u, v] = tiling.TileType.VOID
            if tile_type.is_tile:
                if tile_type.color is tiling.Portalable.WHITE:
                    white_count += 1
                else:
                    black_count += 1

        both_colors = white_count > 0 and black_count > 0

        if white_count == black_count == 0:
            tile_type = tiling.TileType.VOID
            tile_types.add(tiling.TileType.VOID)
        elif white_count > black_count:
            tile_type = tiling.TileType.WHITE
        else:
            tile_type = tiling.TileType.BLACK
    else:
        # Single tile.
        if kv.bool('gridpos'):
            for axis in 'xyz':
                # Don't realign things in the normal's axis -
                # those are already fine.
                if abs(norm[axis]) < 1e-6:
                    pos[axis] = pos[axis] // 32 * 32 + 16

        pos2 = pos
        try:
            tiledef, u, v = tiling.find_tile(pos, norm)
        except KeyError:
            tile_type = tiling.TileType.VOID
        else:
            tile_type = tiledef[u, v]
            if should_remove:
                tiledef[u, v] = tiling.TileType.VOID
        tile_types.add(tile_type)

    LOGGER.debug('PosIsSolid check {} - {} @ {} = {}', pos, pos2, norm, tile_types)
    first_trace.comments += ' Tiles: ' + ' '.join([t.name for t in tile_types])

    if result_var:
        if tile_type.is_tile:
            # Don't distinguish between 4x4, goo sides
            inst.fixup[result_var] = tile_type.color.value
        elif tile_type is tiling.TileType.VOID:
            inst.fixup[result_var] = 'none'
        else:
            inst.fixup[result_var] = tile_type.name.casefold()

    return tile_type, both_colors, tile_types


@conditions.make_test('posIsSolid')
def check_brush_at_loc(inst: Entity, kv: Keyvalues) -> bool:
    """Checks to see if a tile is present at the given location.

    - `Pos` or `pos1` is the position of the tile, where `0 0 0` is the floor-position
       of the brush.
    - `Dir` is the normal the face is pointing. `(0 0 1)` is up.
    - `Pos2`: If set, checks all the tiles in a bounding box.
    - `Type` defines the type the brush must be:
        - `Any` requires some sort of surface.
        - `Tile` allows a black/white tile of some kind.
        - `None` means that no surface must be present.
        - `White` requires a portalable surface.
        - `Black` requires a non-portalable surface.
        - `4x4` requires a tile that forces the 4x4 size.
        - `1x1` requires a tile that does not force a size.
    - `Mode` specifies how the check is done, if `Pos2` is provided:
        - `avg`/`average` (default): The tiles will be averaged together.
        if there is an equal number of white/black tiles, black wins.
        - `and`: The check must pass on all tiles.
        - `or`: The check must pass on any tile.
        - `same`: Checks to see if all tiles are the same. `Type` is ignored.
        - `diff`/`different`: Checks to see if there are multiple tile types.
          `Type` is ignored.
    - `SetVar` defines an instvar which will be given a value of `black`,
      `white` or `none` depending on the average colour of tiles.
    - If `gridPos` is true, the position will be snapped, so it aligns with
      the 32 grid (Useful with fizzler/light strip items).
      If `pos2` is set, the bounding box is expanded to the next grid size.
    - `RemoveTile`: If set to `1`, the tile will be removed if found.
    - `Debug`: If "Developer Mode" is enabled in BEE options, the location sampled will be marked
      in the VMF. This key will be written into the comment field to assist with identifying the
      relevant condition.
    """
    avg_type, both_colors, tile_types = brush_at_loc(inst, kv)

    if 'pos2' not in kv:  # Others are useless.
        mode = 'avg'
    else:
        mode = kv['mode', 'avg'].casefold()

    if mode in ('same', 'diff', 'different'):
        # These don't need 'type', force the value to ensure it can't error out.
        des_type = 'any'
    else:
        des_type = kv['type', 'any'].casefold()

    if des_type in ('same', 'diff', 'different'):
        LOGGER.warning(
            'Using type={} in posIsSolid is deprecated, put this in mode!',
            des_type,
        )
        # Modify the properties, so it doesn't happen again.
        mode = kv['mode'] = des_type
        des_type = 'any'
        del kv['type']

    try:
        tile_pred = TILE_PREDICATES[des_type]
    except KeyError:
        LOGGER.warning(
            'Unknown tile type "{}" for posIsSolid command!',
            des_type
        )
        return False

    if mode in ('diff', 'different'):
        return both_colors
    elif mode == 'same':
        return not both_colors and all(tile.is_tile for tile in tile_types)
    elif mode == 'and':
        return all(tile in tile_pred for tile in tile_types)
    elif mode == 'or':
        return any(tile in tile_pred for tile in tile_types)
    elif mode == 'avg':
        return avg_type in tile_pred

    LOGGER.warning(
        'Unknown check mode "{}" for posIsSolid command!'
    )
    return False


def _fill_predicates() -> None:
    """Set TILE_PREDICATES."""
    WHITE = tiling.Portalable.WHITE
    BLACK = tiling.Portalable.BLACK
    TILE_4x4 = tiling.TileSize.TILE_4x4
    TILE_1x1 = tiling.TileSize.TILE_1x1

    def pred_any(tile: tiling.TileType) -> bool:
        """Any kind of surface."""
        return tile is not tiling.TileType.VOID

    def pred_none(tile: tiling.TileType) -> bool:
        """No surface present."""
        return tile is tiling.TileType.VOID

    def pred_tile(tile: tiling.TileType) -> bool:
        """A solid black/white tile."""
        return tile.is_tile

    def pred_white(tile: tiling.TileType) -> bool:
        """A portal surface."""
        return tile.is_tile and tile.color is WHITE

    def pred_black(tile: tiling.TileType) -> bool:
        """A non-portal surface."""
        return tile.is_tile and tile.color is BLACK

    def pred_1x1(tile: tiling.TileType) -> bool:
        """A tile which produces an unrestricted surface."""
        return tile.is_tile and tile.tile_size is TILE_1x1

    def pred_4x4(tile: tiling.TileType) -> bool:
        """A tile that forces a 4x4 size."""
        return tile.is_tile and tile.tile_size is TILE_4x4

    for name, func in list(locals().items()):
        if name.startswith('pred_'):
            # Collapse it down into a lookup table.
            TILE_PREDICATES[name.removeprefix('pred_')] = set(filter(
                func, tiling.TileType.__members__.values()
            ))


_fill_predicates()
del _fill_predicates


@conditions.make_result('ReadSurfType')
def res_brush_at_loc(inst: Entity, res: Keyvalues) -> None:
    """Read the type of surface at a particular location.

    - `Pos` or `pos1` is the position of the tile, where `0 0 0` is the floor-position
       of the brush.
    - `Dir` is the normal the face is pointing. `(0 0 1)` is up.
    - `Pos2`: If set, causes the check to average the tiles in a bounding box.
      If no tiles are present they're treated as a lack of them.
      Otherwise, the dominant colour wins, with ties treated as black.
    - `ResultVar` is the variable which is set. This will be set to
      `black`, `white` or `none` depending on the average colour of tiles.
    - If `gridPos` is true, the position will be snapped so it aligns with
      the 32 grid (Useful with fizzler/light strip items).
      If pos2 is set, the bounding box is expanded to the next grid size.
    - `RemoveTile`: If set to `1`, the tile will be removed if found.
    - `Debug`: If "Developer Mode" is enabled in BEE options, the location sampled will be marked
      in the VMF. This key will be written into the comment field to assist with identifying the
      relevant condition.
    """
    # Alias PosIsSolid to also be a result, for using the variable mode by itself.
    res['setVar'] = res['resultVar']
    brush_at_loc(inst, res)


@conditions.make_test('PosIsGoo')
def check_goo_at_loc(inst: Entity, kv: Keyvalues) -> bool:
    """Check to see if a given location is submerged in goo.

    `0 0 0` is the origin of the instance, values are in `128` increments.
    """
    return brushLoc.POS.lookup_world(conditions.resolve_offset(inst, kv.value, scale=128)).is_goo


@conditions.make_test('BlockType')
def check_blockpos_type(inst: Entity, kv: Keyvalues) -> bool:
    """Determine the block type at a grid position.

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

    if kv.has_children():
        pos1 = conditions.resolve_offset(inst, kv['offset', '0 0 0'], scale=128, zoff=-128)
        types = kv['type'].split()
        if 'offset2' in kv:
            pos2 = conditions.resolve_offset(inst, kv['offset2', '0 0 0'], scale=128, zoff=-128)
    else:
        types = kv.value.split()
        pos1 = Vec()

    bbox: Iterable[Vec]
    if pos2 is not None:
        bbox = Vec.iter_grid(*Vec.bbox(pos1, pos2), stride=128)
    else:
        bbox = [pos1]

    add_debug = conditions.fetch_debug_visgroup(inst.map, 'get_blocktype')

    for pos in bbox:
        block = brushLoc.POS.lookup_world(pos)
        add_debug('info_target', origin=pos, comment=block.name)
        for block_type in types:
            try:
                allowed = brushLoc.BLOCK_LOOKUP[block_type.casefold()]
            except KeyError:
                raise ValueError(f'"{block_type}" is not a valid block type!') from None
            if block in allowed:
                break  # To next position
        else:
            return False  # Didn't match any in this list.
    return True  # Matched all positions.


@conditions.make_result('SetBlock')
def res_set_block(inst: Entity, res: Keyvalues) -> None:
    """Set a block to the given value, overwriting the existing value.

    - `type` is the type of block to set:
        * `VOID` (Outside the map)
        * `SOLID` (Full wall cube)
        * `EMBED` (Hollow wall cube)
        * `AIR` (Inside the map, may be occupied by items)
        * `OCCUPIED` (Known to be occupied by items)
        * `PIT_SINGLE` (one-high)
        * `PIT_TOP`
        * `PIT_MID`
        * `PIT_BOTTOM`
        * `GOO_SINGLE` (one-deep goo)
        * `GOO_TOP` (goo surface)
        * `GOO_MID`
        * `GOO_BOTTOM` (floor)
    - `offset` is in block increments, with `0 0 0` equal to the mounting surface.
    - If 'offset2' is also provided, all positions in the bounding box will be set.
    """
    try:
        new_vals = brushLoc.BLOCK_LOOKUP[res['type'].casefold()]
    except KeyError:
        raise ValueError(f'"{res["type"]}" is not a valid block type!') from None

    try:
        [new_val] = new_vals
    except ValueError:
        # TODO: This could spread top/mid/bottom through the bbox...
        raise ValueError(
            f'Can\'t use compound block type "{res["type"]}", specify _SINGLE/TOP/MID/BOTTOM'
        ) from None

    pos1 = conditions.resolve_offset(inst, res['offset', '0 0 0'], scale=128, zoff=-128)

    if 'offset2' in res:
        pos2 = conditions.resolve_offset(inst, res['offset2', '0 0 0'], scale=128, zoff=-128)
        for pos in Vec.iter_grid(*Vec.bbox(pos1, pos2), stride=128):
            brushLoc.POS.set_world(pos, new_val)
    else:
        brushLoc.POS.set_world(pos1, new_val)


@conditions.make_result('forceUpright')
def res_force_upright(inst: Entity) -> None:
    """Position an instance to orient upwards while keeping the normal.

    The result angle will have pitch and roll set to 0. Vertical
    instances are unaffected.
    """
    normal = Vec(0, 0, 1) @ Angle.from_str(inst['angles'])
    if abs(normal.z) > 0.1:
        return
    ang = math.degrees(math.atan2(normal.y, normal.x))
    inst['angles'] = f'0 {ang % 360:g} 0'  # Don't use negatives


@conditions.make_result('switchOrientation')
def res_alt_orientation(res: Keyvalues) -> conditions.ResultCallable:
    """Apply an alternate orientation.

    "wall" makes the attaching surface in the -X direction, making obs rooms,
    corridors etc easier to build. The Z axis points in the former +X direction.
    "ceiling" flips the instance, making items such as droppers easier to build.
    The X axis remains unchanged.
    """
    val = res.value.casefold()
    if val == 'wall':
        pose = Matrix.from_angle(-90, 180, 0)
    elif val in ('ceil', 'ceiling'):
        pose = Matrix.from_roll(180)
    else:
        raise ValueError(f'Unknown orientation type "{res.value}"!')

    def swap_orient(inst: Entity) -> None:
        """Apply the new orientation."""
        inst['angles'] = pose @ Matrix.from_angstr(inst['angles'])
    return swap_orient


@conditions.make_result('setAngles')
def res_set_angles(inst: Entity, res: Keyvalues) -> None:
    """Set the orientation of an instance to a certain angle."""
    inst['angles'] = inst.fixup.substitute(res.value)


@conditions.make_result('OffsetInst', 'offsetinstance')
def res_translate_inst(inst: Entity, res: Keyvalues) -> None:
    """Translate the instance locally by the given amount.

    The special values `<piston>`, `<piston_bottom>` and `<piston_top>` can be
    used to offset it based on the starting position, bottom or top position
    of a piston platform.
    """
    inst['origin'] = conditions.resolve_offset(inst, res.value)


@conditions.make_result('OppositeWallDist')
def res_calc_opposite_wall_dist(inst: Entity, res: Keyvalues) -> None:
    """Calculate the distance between this item and the opposing wall.

    The value is stored in the `$var` specified by the property value.
    Alternately it is set by `ResultVar`, and `offset` adds or subtracts to the value.
    `GooCollide` means that it will stop when goo is found, otherwise it is
    ignored.
    `GooAdjust` means additionally if the space is GOO, the distance will
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
    normal = Matrix.from_angstr(inst['angles']).up()

    mask = [
        brushLoc.Block.SOLID,
        brushLoc.Block.EMBED,
        brushLoc.Block.PIT_BOTTOM,
        brushLoc.Block.PIT_SINGLE,
    ]

    # Only if actually downward.
    if normal.z < -0.9 and collide_goo:
        mask += [brushLoc.Block.GOO_TOP, brushLoc.Block.GOO_SINGLE]

    opposing_pos = brushLoc.POS.raycast_world(
        origin,
        normal,
        mask,
    )

    if adjust_goo and brushLoc.POS.lookup_world(opposing_pos + 128 * normal).is_goo:
        # If the top is goo, adjust so the 64 below is the top of the goo.
        dist_off += 32

    inst.fixup[result_var] = (origin - opposing_pos).mag() + dist_off


@conditions.make_result('RotateInst', 'RotateInstance')
def res_rotate_inst(inst: Entity, res: Keyvalues) -> None:
    """Rotate the instance around an axis.

    If `axis` is specified, it should be a normal vector and the instance will
    be rotated `angle` degrees around it.
    Otherwise, `angle` is a pitch-yaw-roll angle which is applied.
    `around` can be a point (local, pre-rotation) which is used as the origin.

    As a convenience, the `ramp_open_XX_deg` animations are also permitted in axis mode.

    Tip: If you want to match angled panels, rotate with an axis of `0 -1 0`
    and an around value of `0 -64 -64`.
    """
    angles = Matrix.from_angstr(inst['angles'])
    angle_str = inst.fixup.substitute(res['angle'])
    if 'axis' in res:
        try:
            anim = PanelAnimation.from_anim(angle_str)
        except LookupError:
            angle = conv_float(angle_str)
        else:
            angle = float(anim.value)
        orient = Matrix.axis_angle(
            Vec.from_str(inst.fixup.substitute(res['axis'])),
            angle,
        )
    else:
        orient = Matrix.from_angstr(angle_str)

    try:
        offset = Vec.from_str(inst.fixup.substitute(res['around']))
    except LookupError:
        pass
    else:
        origin = Vec.from_str(inst['origin'])
        inst['origin'] = origin + (-offset @ orient + offset) @ angles

    inst['angles'] = orient @ angles
