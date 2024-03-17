"""Implements Glass and Grating."""
from __future__ import annotations

from typing import Callable, Dict, Final, Iterator, List, Mapping, Set, Tuple
from typing_extensions import Literal, Self, Sequence, TypeAlias, assert_never, override

from collections import defaultdict
from enum import Enum, Flag, auto as enum_auto
import math

from srctools import EmptyMapping, Keyvalues
from srctools.math import AnyMatrix, to_matrix, FrozenMatrix, Vec, FrozenVec, Angle, Matrix
from srctools.vmf import Side, VMF, Solid, Entity
import srctools.logger
import attrs

from plane import Plane
from precomp import instanceLocs, options, template_brush, conditions, collisions, connections
from precomp.grid_optim import optimise as grid_optimise
from precomp.rand import seed as rand_seed
from transtoken import TransToken
import consts
import user_errors
import utils


LOGGER = srctools.logger.get_logger(__name__)
COND_MOD_NAME: str | None = None
STRAIGHT_LEN: Final = 64  # Length of the brush for straight frame sections.
HoleTemplate: TypeAlias = Tuple[List[Solid], List[collisions.BBox]]
TRANS_VARIABLE = TransToken.untranslated('"<var>{value}</var>"')
MAX_FLOORBEAM_REPOSITIONS: Final = 10  # Number of times to reposition if the beam is bad.


class FrameOrient(Enum):
    """The kind of frame orientation."""
    HORIZ = "horizontal"
    VERT = "vertical"
    FLAT = "flat"


class Border(Flag):
    """Indicates which sides still need frames generated."""
    NONE = 0
    # We need a straight section on this side.
    STRAIGHT_N = enum_auto()
    STRAIGHT_S = enum_auto()
    STRAIGHT_E = enum_auto()
    STRAIGHT_W = enum_auto()
    # A convex corner is present, so the straight sections need to be shorter.
    CORNER_NW = enum_auto()
    CORNER_NE = enum_auto()
    CORNER_SW = enum_auto()
    CORNER_SE = enum_auto()

# IDs for the default barrier definitions. These are detected by the generated brushes, not
# from the instance (since that's the same for both).
GLASS_ID: Final = utils.parse_obj_id('VALVE_GLASS')
GRATE_ID: Final = utils.parse_obj_id('VALVE_GRATING')

ORIENT_E: Final = FrozenMatrix.from_yaw(0)
ORIENT_N: Final = FrozenMatrix.from_yaw(90)
ORIENT_W: Final = FrozenMatrix.from_yaw(180)
ORIENT_S: Final = FrozenMatrix.from_yaw(270)

ORIENTS = {
    Vec.T: FrozenMatrix.from_angle(180, 0, 0),
    Vec.B: FrozenMatrix.from_angle(0, 0, 0),
    Vec.N: FrozenMatrix.from_angle(90, 270, 0),
    Vec.S: FrozenMatrix.from_angle(90, 90, 0),
    Vec.E: FrozenMatrix.from_angle(90, 180, 0),
    Vec.W: FrozenMatrix.from_angle(90, 0, 0),
}

# Direction -> border value for that side.
NORMAL_TO_BORDER: Dict[Tuple[Literal[-1, 0, +1], Literal[-1, 0, +1]], Border] = {
    (0, +1): Border.STRAIGHT_N,
    (0, -1): Border.STRAIGHT_S,
    (+1, 0): Border.STRAIGHT_W,
    (-1, 0): Border.STRAIGHT_E,
}


FULL_SQUARE: Final[Sequence[Tuple[int, int]]] = [
    (u, v)
    for u in [-48, -16, +16, +48]
    for v in [-48, -16, +16, +48]
]
LARGE_DISALLOWED: Sequence[FrozenVec] = [
    FrozenVec(-128, 0, 0),
    FrozenVec(+128, 0, 0),
    FrozenVec(0, -128, 0),
    FrozenVec(0, +128, 0),
]


@attrs.frozen(eq=False, kw_only=True)
class HoleConfig:
    """Configuration for how to create a hole for a specific barrier."""
    id: utils.ObjectID
    # Geo used to create the brush face.
    template: HoleTemplate
    # If set, the bounds for the hole frame, used to cut P1 floor beams.
    shape: Sequence[collisions.BBox]
    # Instance to place for the prop, clips etc.
    instance: str

    @classmethod
    def parse(cls, kv: Keyvalues) -> HoleConfig:
        """Parse a configuration from a KV block."""
        conf_id = utils.parse_obj_id(kv.real_name)
        instance = kv['instance', '']

        template, shape = template_solids_and_coll(kv['template'])
        if 'templateDiagonal' in kv:
            temp_diag, _ = template_solids_and_coll(kv['templatediagonal'])
            temp_sqr, _ = template_solids_and_coll(kv['templatesquare'])
            return LargeHoleConfig(
                id=conf_id,
                instance=instance,
                template=template,
                shape=shape,

                template_diagonal=temp_diag,
                template_square=temp_sqr,
            )
        else:
            return HoleConfig(
                id=conf_id,
                instance=instance,
                template=template,
                shape=shape,
            )


@attrs.frozen(eq=False, kw_only=True, repr=False)
class LargeHoleConfig(HoleConfig):
    """Large holes are currently rather hardcoded."""
    template_diagonal: HoleTemplate  # Two holes diagonally overlapping.
    # If the corner is present, place it as part of the hole to simplify brushwork.
    template_square: HoleTemplate


@attrs.frozen(eq=False, repr=False)
class HoleType:
    """A type of hole."""
    id: utils.ObjectID
    footprint: Sequence[FrozenVec]  # Offsets occupied by the hole.
    variants: Mapping[utils.ObjectID, HoleConfig]
    is_large: bool

    @classmethod
    def parse(cls, kv: Keyvalues) -> HoleType:
        """Parse hole types from keyvalues data."""
        hole_id = utils.parse_obj_id(kv.real_name)

        # Use a template to make it easy to specify these.
        temp_id, visgroups = template_brush.parse_temp_name(kv['footprint'])
        footprint = [
            tilesetter.offset.freeze()
            for tilesetter in template_brush.get_template(temp_id).tile_setters
            if tilesetter.visgroups.issubset(visgroups)
        ]

        variants = {}
        for var_block in kv.find_children('Variants'):
            hole_conf = HoleConfig.parse(var_block)
            if hole_conf.id in variants:
                raise user_errors.UserError(user_errors.TOK_DUPLICATE_ID.format(
                    kind='Barrier Hole Variant',
                    id=f'{hole_id}:{hole_conf.id}',
                ))
            variants[hole_conf.id] = hole_conf
        variant_types = {type(conf) for conf in variants.values()}
        if len(variant_types) > 1:
            raise ValueError(
                f'Hole "{hole_id}" has both small and large variants, this must be consistent!'
            )

        return cls(hole_id, footprint, variants, LargeHoleConfig in variant_types)

    def __repr__(self) -> str:
        return f'<{type(self).__name__} {self.id!r}, variants={sorted(self.variants)}>'


@attrs.define(eq=False, kw_only=True)
class Hole:
    """A hole item placed in the map."""
    inst: Entity
    type: HoleType
    variant: HoleConfig
    plane: utils.SliceKey
    orient: FrozenMatrix
    origin: Vec
    # If true, we found a matching barrier this was inserted into.
    inserted: bool = False
    # The U/V position in the plane.
    plane_pos: tuple[float, float] = attrs.field(init=False)
    shape: Sequence[collisions.BBox] = attrs.field(init=False)

    def __attrs_post_init__(self) -> None:
        pos = self.plane.world_to_plane(self.origin)
        self.plane_pos = pos.x, pos.y
        name = self.inst['targetname']
        self.shape = [
            (shape @ self.orient + self.origin).with_attrs(name=name)
            for shape in self.variant.shape
        ]


@attrs.frozen(eq=False, kw_only=True)
class FloorbeamConf:
    """Configuration for the special P1 style floorbeam brushes."""
    distance: range
    brush: Solid
    width: float
    border: int

    @classmethod
    def parse(cls, barrier_id: utils.ObjectID, kv: Keyvalues) -> Self:
        """Parse the configuration."""
        dist_min = kv.int('min', 64)
        dist_max = kv.int('max', 256)
        dist_step = kv.int('step', 8)
        if dist_step <= 0:
            raise user_errors.UserError(user_errors.TOK_INVALID_PARAM.format(
                option='floorbeam.step',
                value=kv['step'],
                kind='Barrier Type',
                id=barrier_id,
            ))

        border_thickness = kv.int('border_width', 4)

        template = template_brush.get_template(kv['template'])

        brush: Solid
        try:
            [brush] = template.visgrouped_solids()
        except ValueError as exc:
            raise user_errors.UserError(user_errors.TOK_GLASS_FLOORBEAM_TEMPLATE) from ValueError(
                f'Floorbeam template {template.id} has multiple/zero solids!'
            ).with_traceback(exc.__traceback__)
        bbox_min, bbox_max = brush.get_bbox()

        # Strip faces marked with skip. These will be the ends, which we will replace when generating.
        brush.sides = [
            face for face in brush.sides
            if face.mat != consts.Tools.SKIP
        ]
        dimensions = bbox_max - bbox_min

        return cls(
            distance=range(dist_min, dist_max, dist_step),
            width=dimensions.y,
            brush=brush,
            border=border_thickness,
        )

    def generate(
        self, vmf: VMF,
        orient: AnyMatrix,
        start_pos: Vec | FrozenVec,
        start_normal: Vec | FrozenVec,
        end_pos: Vec | FrozenVec,
        end_normal: Vec | FrozenVec,
    ) -> Solid:
        """Generate a copy of the brush."""
        brush = self.brush.copy(vmf_file=vmf)
        brush.localise(start_pos, orient)
        brush.sides.append(Side.from_plane(vmf, start_pos, start_normal))
        brush.sides.append(Side.from_plane(vmf, end_pos, end_normal))
        return brush


@attrs.frozen(eq=False, kw_only=True)
class BarrierType:
    """Type of barrier."""
    id: utils.ObjectID | utils.SpecialID
    frames: Mapping[FrameOrient, Sequence[FrameType]] = attrs.field(default=dict.fromkeys(FrameOrient, ()), repr=False)
    error_disp: user_errors.Kind | None = None
    surfaces: Sequence[Brush | Collide] = ()
    floorbeam: FloorbeamConf | None = None
    coll_thick: float = 4.0
    # If set, the brushes for this item can be combined with others of the same type.
    mergeable: bool = False
    # Hole variants valid for this kind of barrier.
    hole_variants: Sequence[utils.ObjectID] = ()
    # Sorta a hack, force frame brushwork to be world brushes, so they don't get carved.
    # Tinted Glass needs this due to its nodraw clip.
    frame_world_brush: bool = False

    @classmethod
    def parse(cls, kv: Keyvalues) -> BarrierType:
        """Parse from keyvalues files."""
        barrier_id = utils.parse_obj_id(kv.real_name)
        frames: Dict[FrameOrient, List[FrameType]] = {orient: [] for orient in FrameOrient}
        error_disp: user_errors.Kind | None = None
        surfaces: List[Brush | Collide] = []

        for sub_kv in kv.find_all('Frame'):
            frame_id = utils.parse_obj_id(sub_kv.value)
            try:
                frame_map = FRAME_TYPES[frame_id]
            except KeyError:
                LOGGER.warning('No barrier frame named "{}"!', frame_id)
            else:
                for orient, frame in frame_map.items():
                    frames[orient].append(frame)

        for sub_kv in kv.find_all('Brush'):
            surfaces.append(Brush.parse(sub_kv))

        for sub_kv in kv.find_all('Collide'):
            surfaces.append(Collide.parse(sub_kv))

        hole_variants = [
            utils.parse_obj_id(sub_kv.value)
            for sub_kv in kv.find_all('HoleVariant')
        ]

        if 'error_tex' in kv:
            error_tex = kv['error_tex'].casefold()
            if error_tex in user_errors.TEX_SET:
                error_disp = error_tex  # type: ignore

        if 'floorbeam' in kv:
            floorbeam = FloorbeamConf.parse(barrier_id, kv.find_key('floorbeam'))
            LOGGER.info('Floorbeam: {}', floorbeam)
        else:
            floorbeam = None

        return BarrierType(
            id=barrier_id,
            frames=frames,
            error_disp=error_disp,
            surfaces=surfaces,
            floorbeam=floorbeam,
            hole_variants=hole_variants,
            coll_thick=kv.float('coll_thick', 4.0),
            mergeable=kv.bool('mergeable'),
            frame_world_brush=kv.bool('frame_world_brush'),
        )


@attrs.define(eq=False, kw_only=True)
class Barrier:
    """A glass/grating item.

    BARRIER_EMPTY is unique, but others may not be if created dynamically!
    """
    name: str
    type: BarrierType
    item: connections.Item | None = None
    instances: List[Entity] = attrs.Factory(list)
    # Set only for vanilla glass/grating items. Stores a list of the
    # original voxel positions this item took up, so changing the
    # type can overwrite this.
    original_voxels: Sequence[Tuple[utils.SliceKey, int, int]] = ()

    def __eq__(self, other: object) -> bool:
        """Two barriers are equal if are for the same instance or if mergable. The type must always match."""
        if isinstance(other, Barrier):
            if self.type is not other.type:
                return False
            return self.type.mergeable or self.name == other.name
        return NotImplemented


@attrs.frozen(eq=False, kw_only=True)
class Surface:
    """Either a brush or collision volume."""
    offset: float
    thickness: float
    carve_by_hole: bool = True  # If true, this is cut into by holes.


@attrs.frozen(eq=False, kw_only=True)
class Collide(Surface):
    """Collision volumes added to barriers."""
    contents: collisions.CollideType

    @classmethod
    def parse(cls, kv: Keyvalues) -> Collide:
        """Parse from keyvalues files."""

        thickness = kv.int('thickness', 4)
        if thickness <= 1:
            raise ValueError('Collisions must have thickness!')

        return cls(
            offset=kv.int('offset', 0),
            thickness=thickness,
            carve_by_hole=kv.bool('carve_by_hole', True),
            contents=collisions.CollideType.parse(kv['contents', 'solid'])
        )


@attrs.frozen(eq=False, kw_only=True)
class Brush(Surface):
    """Configuration for a brush generated for a barrier."""
    face_temp: template_brush.ScalingTemplate
    material: str = ''  # If set, override face_temp.
    # Texture on the sides.
    side_mat: str = consts.Tools.NODRAW
    # If vertical, use the original player clip and func-detail. Otherwise, add it inside this one.
    static_player_clip: bool = False
    world: bool = False  # If set, produce world geo, not a brush ent.

    keyvalues: Mapping[str, str] = EmptyMapping

    @classmethod
    def parse(cls, kv: Keyvalues) -> Brush:
        """Parse from keyvalues files."""
        material = kv['material', '']
        if face_temp_id := kv['template', '']:
            face_temp = template_brush.get_scaling_template(face_temp_id)
        else:
            face_temp = template_brush.ScalingTemplate.world(material or 'tools/toolsskip')

        thickness = kv.float('thickness', 4.0)
        if thickness <= 0:
            raise ValueError('Brushes must have thickness!')

        ent_kvs = {}
        for child in kv.find_children('keys'):
            ent_kvs[child.name] = child.value

        world = kv.bool('world')
        if world and ent_kvs:
            raise ValueError('Cannot set brush keyvalues for a world brush!')

        if 'side_mat' in kv:
            side_mat = kv['side_mat']
        elif kv.bool('tooltexture'):
            side_mat = material or consts.Tools.NODRAW
        else:
            side_mat = consts.Tools.NODRAW

        return cls(
            offset=kv.float('offset'),
            thickness=thickness,
            face_temp=face_temp,
            material=material,
            side_mat=side_mat,
            world=world,
            carve_by_hole=kv.bool('carve_by_hole', True),
            static_player_clip=kv.bool('staticplayerclip'),
            keyvalues=ent_kvs,
        )

    def generate(
        self, vmf: VMF,
        plane_slice: utils.SliceKey,
        solid_func: Callable[[float, float], List[Solid]],
    ) -> None:
        """Generate this brush."""
        brushes = solid_func(self.offset, self.offset + self.thickness)

        for brush in brushes:
            for face in brush.sides:
                if abs(face.normal().dot(plane_slice.normal)) > 0.99:
                    face.mat = self.material
                    self.face_temp.apply(face, change_mat=not self.material)
                else:
                    face.mat = self.side_mat

        if self.world:
            vmf.add_brushes(brushes)
            return

        ent = vmf.create_ent('func_detail')
        ent.solids = brushes
        ent.update(self.keyvalues)
        if ent['classname'] != 'func_detail':
            ent['origin'] = ent.get_origin()

        if self.static_player_clip:
            if abs(plane_slice.normal.z) > 0.5:
                ent['classname'] = 'func_brush'
                ent['solidbsp'] = '1'
                # Create an additional clip to block through portals.
                clip_ent = vmf.create_ent('func_detail')
                # Shrink by a unit, but if this is already smaller, then just halve.
                shrink = min(self.thickness / 2.0, 1.0) / 2.0
                clip_ent.solids = solid_func(self.offset + shrink, self.offset + self.thickness - shrink)
                for face in clip_ent.sides():
                    face.mat = consts.Tools.PLAYER_CLIP
            else:
                # Vertical, just make it a detail brush.
                ent['classname'] = 'func_detail'
                for face in ent.sides():
                    face.mat = consts.Tools.PLAYER_CLIP


@attrs.frozen(eq=False, kw_only=True)
class Segment:
    """Either a model or brush template, placed with an optional offset."""
    orient: FrozenMatrix = FrozenMatrix()
    offset: FrozenVec = FrozenVec()

    @classmethod
    def parse(cls, kv: Keyvalues) -> SegmentBrush | SegmentProp:
        """Parse from keyvalues configuration."""
        orient = FrozenMatrix.from_angstr(kv['angles', '0 0 0'])
        offset = FrozenVec.from_str(kv['offset', '0 0 0'])

        if 'model' in kv:
            return SegmentProp(
                model=kv['model'],
                orient=orient,
                offset=offset,
            )
        else:
            return SegmentBrush(
                brush=template_brush.get_template(kv['template']),
                orient=orient,
                offset=offset,
            )

    def place(
        self, vmf: VMF, slice_key: utils.SliceKey, lighting_origin: str,
        u: float, v: float, angles: AnyMatrix,
        frame_world_brush: bool,
    ) -> None:
        """Place the segment at the specified location."""
        rotation = to_matrix(angles) @ slice_key.orient
        origin = slice_key.plane_to_world(u, v) + self.offset @ rotation
        self._place(
            vmf, origin, self.orient @ rotation, lighting_origin, frame_world_brush,
        )

    def _place(
        self, vmf: VMF, origin: Vec, angles: FrozenMatrix,
        lighting_origin: str,
        frame_world_brush: bool,
    ) -> None:
        """Place the segment at the specified location."""
        raise NotImplementedError


@attrs.frozen(eq=False, kw_only=True)
class SegmentProp(Segment):
    """A model, placed with an optional offset."""
    model: str

    @override
    def _place(
        self, vmf: VMF, origin: Vec, angles: FrozenMatrix,
        lighting_origin: str,
        frame_world_brush: bool,
    ) -> None:
        """Place the segment at the specified location."""
        vmf.create_ent(
            'prop_static',
            origin=origin,
            angles=angles,
            model=self.model,
            skin=0,
            solid=6,
            lightingorigin=lighting_origin,
        )


@attrs.frozen(eq=False, kw_only=True)
class SegmentBrush(Segment):
    """A template brush, placed with an optional offset."""
    brush: template_brush.Template

    @override
    def _place(
        self, vmf: VMF, origin: Vec, angles: FrozenMatrix,
        lighting_origin: str,
        frame_world_brush: bool,
    ) -> None:
        """Place the segment at the specified location."""
        template_brush.import_template(
            vmf,
            self.brush,
            origin, angles,
            force_type=template_brush.TEMP_TYPES.world
            if frame_world_brush else
            template_brush.TEMP_TYPES.detail,
        )

    def place_sized(
        self,
        vmf: VMF, slice_key: utils.SliceKey,
        u: float, v: float,
        orient: FrozenMatrix,
        direction: Vec,
        length: float,
        frame_world_brush: bool,
    ) -> None:
        """Place this template, but resize it to match the specified length."""
        rotation = orient @ slice_key.orient
        origin = slice_key.plane_to_world(u, v) + self.offset @ rotation

        if frame_world_brush:
            temp = template_brush.import_template(
                vmf,
                self.brush,
                origin,
                self.orient @ rotation,
                force_type=template_brush.TEMP_TYPES.world,
                add_to_map=True,
            )
            faces = (face for brush in temp.world for face in brush.sides)
        else:
            temp = template_brush.import_template(
                vmf,
                self.brush,
                origin,
                self.orient @ rotation,
                force_type=template_brush.TEMP_TYPES.detail,
            )
            if temp.detail is None:
                return  # No brushes?
            faces = temp.detail.sides()

        diff = direction * (length - STRAIGHT_LEN)
        for face in faces:
            if face.normal().dot(direction) < -0.9:
                face.translate(diff)


@attrs.frozen(eq=False, kw_only=True)
class FrameType:
    """Configuration for a type of barrier frame."""
    # Brushes can be resized, props need to be pieced together.
    seg_straight_brush: Sequence[SegmentBrush] = ()
    seg_straight_prop: Mapping[int, Sequence[SegmentProp]] = EmptyMapping
    seg_straight_fitter: Callable[[int], Sequence[int]] = lambda x: ()

    seg_corner: Sequence[Segment] = ()
    seg_concave_corner: Sequence[Segment] = ()
    corner_size: int = 4

    @classmethod
    def parse(cls, kv: Keyvalues) -> Self:
        """Parse from keyvalues configuration."""
        seg_straight_brush = []
        seg_straight_prop: Dict[int, List[SegmentProp]] = defaultdict(list)
        seg_corner = []
        seg_concave_corner = []

        for block in kv.find_all('straight'):
            segment = Segment.parse(block)
            if isinstance(segment, SegmentProp):
                size = block.int('length')
                if size <= 0:
                    raise ValueError('Straight prop sections must have a size defined!')
                seg_straight_prop[size].append(segment)
            else:
                seg_straight_brush.append(segment)

        corner_size = kv.int('cornerSize', 4)

        for block in kv.find_all('corner'):
            seg_corner.append(Segment.parse(block))
        for block in kv.find_all('concavecorner'):
            seg_concave_corner.append(Segment.parse(block))

        return cls(
            seg_straight_brush=seg_straight_brush,
            seg_straight_prop=dict(seg_straight_prop),
            seg_straight_fitter=utils.get_piece_fitter(list(seg_straight_prop)),
            seg_corner=seg_corner,
            seg_concave_corner=seg_concave_corner,
            corner_size=corner_size,
        )


# Special barrier representing the lack of one.
BARRIER_EMPTY_TYPE = BarrierType(id=utils.ID_EMPTY, mergeable=True)
BARRIER_EMPTY = Barrier(name='', type=BARRIER_EMPTY_TYPE, item=None)
# Planar slice -> plane of barriers.
# The plane is specified as the edge of the voxel.
BARRIERS: dict[utils.SliceKey, Plane[Barrier]] = defaultdict(lambda: Plane(default=BARRIER_EMPTY))
BARRIERS_BY_NAME: dict[str, Barrier] = {}
# plane -> {position -> hole}
HOLES: dict[utils.SliceKey, dict[FrozenVec, Hole]] = defaultdict(dict)

HOLE_TYPES: Dict[utils.ObjectID, HoleType] = {}
FRAME_TYPES: Dict[utils.ObjectID, Dict[FrameOrient, FrameType]] = {}
BARRIER_TYPES: Dict[utils.ObjectID | utils.SpecialID, BarrierType] = {}


def parse_conf(kv: Keyvalues) -> None:
    """Parse frame configurations."""
    FRAME_TYPES.clear()
    for block in kv.find_children('BarrierFrames'):
        frame_id = utils.parse_obj_id(block.real_name)
        if 'horiz' in block and 'vert' in block and 'flat' in block:
            horiz_conf = FrameType.parse(block.find_key('horiz'))
            vert_conf = FrameType.parse(block.find_key('vert'))
            flat_conf = FrameType.parse(block.find_key('flat'))
        else:
            horiz_conf = vert_conf = flat_conf = FrameType.parse(block)
        if frame_id in FRAME_TYPES:
            raise user_errors.UserError(user_errors.TOK_DUPLICATE_ID.format(
                kind='Barrier Frame Type',
                id=frame_id,
            ))
        FRAME_TYPES[frame_id] = {
            FrameOrient.HORIZ: horiz_conf,
            FrameOrient.VERT: vert_conf,
            FrameOrient.FLAT: flat_conf,
        }
    for block in kv.find_children('Barriers'):
        barrier = BarrierType.parse(block)
        if barrier.id in BARRIER_TYPES:
            raise user_errors.UserError(user_errors.TOK_DUPLICATE_ID.format(
                kind='Barrier Type',
                id=barrier.id,
            ))
        BARRIER_TYPES[barrier.id] = barrier

    for block in kv.find_children('BarrierHoles'):
        hole = HoleType.parse(block)
        # Should be merged by the app, but check anyway.
        if hole.id in BARRIER_TYPES:
            raise user_errors.UserError(user_errors.TOK_DUPLICATE_ID.format(
                kind='Barrier Hole Type',
                id=hole.id,
            ))
        HOLE_TYPES[hole.id] = hole

    LOGGER.info(
        'Parsed {} barrier types, {} frame types, and {} hole types.',
        len(BARRIER_TYPES), len(FRAME_TYPES), len(HOLE_TYPES),
    )

    # Make sure a basic map sorta works even without the new configuration.
    if GLASS_ID not in BARRIER_TYPES:
        LOGGER.warning('No definition for {}!', GLASS_ID)
        BARRIER_TYPES[GLASS_ID] = BarrierType(
            id=GLASS_ID,
            error_disp='glass',
            surfaces=[
                Brush(
                    face_temp=template_brush.ScalingTemplate.world(consts.Special.GLASS),
                    side_mat=consts.Special.GLASS,
                    carve_by_hole=True,
                    offset=0.5,
                    thickness=1.0,
                    keyvalues={'classname': 'func_detail'},
                ),
                Collide(
                    offset=0,
                    thickness=4,
                    contents=collisions.CollideType.GLASS,
                ),
            ],
        )

    if GRATE_ID not in BARRIER_TYPES:
        LOGGER.warning('No definition for {}!', GRATE_ID)
        BARRIER_TYPES[GRATE_ID] = BarrierType(
            id=GRATE_ID,
            error_disp='grating',
            surfaces=[
                Collide(
                    offset=0,
                    thickness=4,
                    contents=collisions.CollideType.GLASS,
                ),
                Brush(
                    face_temp=template_brush.ScalingTemplate.world(consts.Special.GRATING),
                    side_mat=consts.Special.GRATING,
                    carve_by_hole=True,
                    offset=0.5,
                    thickness=1.0,
                    keyvalues={
                        'classname': 'func_brush',
                        'renderfx': '14', # Constant Glow
                        'solidity': '1',  # Never Solid
                    },
                ),
                Brush(
                    face_temp=template_brush.ScalingTemplate.world(consts.Tools.PLAYER_CLIP),
                    side_mat=consts.Tools.PLAYER_CLIP,
                    carve_by_hole=True,
                    offset=0,
                    thickness=4.0,
                    keyvalues={'classname': 'func_detail'},
                ),
                Brush(
                    face_temp=template_brush.ScalingTemplate.world(consts.Tools.TRIGGER),
                    side_mat=consts.Tools.TRIGGER,
                    carve_by_hole=True,
                    offset=0,
                    thickness=4.0,
                    keyvalues={
                        'classname': 'func_clip_vphysics',
                        'filtername': '@grating_filter',
                    },
                ),
            ],
        )


def parse_map(vmf: VMF, conn_items: Mapping[str, connections.Item]) -> None:
    """Find all glass/grating in the map.

    This removes the per-tile instances, and all original brushwork.
    The frames are updated with a fixup var, as appropriate.
    Requires connection items to be parsed!
    """
    frame_inst = instanceLocs.resolve_filter('[glass_frames]', silent=True)
    segment_inst = instanceLocs.resolve_filter('[glass_128]', silent=True)
    barrier_pos_lists: Dict[str, List[Tuple[utils.SliceKey, int, int]]] = {}

    for inst in vmf.by_class['func_instance']:
        filename = inst['file'].casefold()
        if not filename:
            continue
        if filename in segment_inst:
            # The vanilla segment instance is the same for glass/grating, so we don't know which
            # is which. Fill in a barrier, but don't give it a type yet.
            # Look up the barriers
            center = Vec.from_str(inst['origin']) // 128 * 128 + (64, 64, 64)
            norm = Vec(x=1) @ Angle.from_str(inst['angles'])
            center -= 64 * norm
            plane_slice = utils.SliceKey(norm, center)
            local = plane_slice.world_to_plane(center)

            inst_name = inst['targetname']

            try:
                barrier = BARRIERS_BY_NAME[inst_name]
                barrier_list = barrier_pos_lists[inst_name]
            except KeyError:
                barrier_list = barrier_pos_lists[inst_name] = []
                barrier = BARRIERS_BY_NAME[inst_name] = Barrier(
                    name=inst_name,
                    type=BARRIER_EMPTY_TYPE,
                    item=conn_items.get(inst_name),
                    instances=[],
                    original_voxels=barrier_list,
                )
            barrier.instances.append(inst)

            # Now set each 32-grid cell to be the barrier. Since this is square the orientation
            # doesn't matter.
            for u_off, v_off in FULL_SQUARE:
                BARRIERS[plane_slice][
                    (local.x + u_off) // 32,
                    (local.y + v_off) // 32,
                ] = barrier
            # Store off the voxels, for use by CustomBarrier.
            barrier_list.append((
                plane_slice,
                round((local.x - 48) // 32),
                round((local.y - 48) // 32),
            ))

        if filename in frame_inst:  # Frames are useless, we'll make our own.
            inst.remove()

    for entities, material, barrier_type, fixup_value in [
        (vmf.by_class['func_detail'], consts.Special.GLASS, BARRIER_TYPES[GLASS_ID], 'glass'),
        (vmf.by_class['func_brush'], consts.Special.GRATING, BARRIER_TYPES[GRATE_ID], 'grating'),
    ]:
        for brush_ent in entities:
            for face in brush_ent.sides():
                if face.mat != material:
                    continue  # Side face.
                # We found the face for a barrier brush. This could be either facing
                # into or out of the voxel - compute the grid center to disambiguate.
                brush_ent.remove()
                origin = face.get_origin()
                center = origin // 128 * 128 + (64, 64, 64)
                norm = (origin - center).norm()

                # Offset to be the voxel side, not center.
                center += 64 * norm
                plane_slice = utils.SliceKey(-norm, center)
                local = plane_slice.world_to_plane(center)

                # Figure out the instance this matches from above.
                # At this point all barrier definitions are whole voxel, so it doesn't matter which we pick.
                try:
                    barrier = BARRIERS[plane_slice][local.x // 32, local.y // 32]
                except KeyError:
                    LOGGER.warning('glass/grating at {}, {} has no corresponding instance?', center, norm)
                    break  # Don't check remaining faces.

                if barrier.type is BARRIER_EMPTY_TYPE:
                    # Not yet filled in, now we can set it. Also set a fixup so conditions can
                    # identify the barrier.
                    barrier.type = barrier_type
                    for inst in barrier.instances:
                        inst.fixup[consts.FixupVars.BEE_GLS_TYPE] = fixup_value
                elif barrier_type is not barrier_type:
                    LOGGER.warning(
                        'Barrier at {}, {} is both glass and grating simultaneously?',
                        center, norm, plane_slice,
                    )

                break  # Don't check the remaining faces.

    # Now, go back over the items to check they all have been matched up.
    for barrier in list(BARRIERS_BY_NAME.values()):
        if barrier.type is BARRIER_EMPTY_TYPE:
            LOGGER.warning('Barrier "{}" has no associated brushes??', barrier.name)
            # Discard.
            del BARRIERS_BY_NAME[barrier.name]
            for inst in barrier.instances:
                inst.remove()

    # Discard original lighting origins.
    for ent in vmf.by_class['info_lighting']:
        ent.remove()


def test_hole_spot(
    origin: FrozenVec,
    plane: utils.SliceKey,
    orient: FrozenMatrix,
    hole_type: HoleType,
) -> HoleConfig | None:
    """Check if the given position is valid for holes.

    We need to check that it's actually placed on glass/grating, and that
    all the parts are the same. Otherwise, it'd collide with the borders.

    This returns the variant located, or None if no barrier was found at all. In that case we want
    to try the opposite orientation.
    """
    center = plane.world_to_plane(origin)
    barrier_plane = BARRIERS[plane]

    barrier = barrier_plane[center.x // 32, center.y // 32]
    if barrier is BARRIER_EMPTY:
        # Try the other orientation.
        return None

    error_hole = user_errors.BarrierHole(
        pos=user_errors.to_threespace(origin + orient.up(64)),
        axis=orient.up().axis(),
        # TODO: Handle hole rendering better, user-specifiable?
        large=hole_type.is_large,
        small=not hole_type.is_large,
        footprint=True,
    )

    for variant_ids in barrier.type.hole_variants:
        try:
            variant = hole_type.variants[variant_ids]
            break
        except KeyError:
            pass
    else:
        if len(barrier.type.hole_variants) == 0:
            # Entirely disallowed for this barrier type.
            message = user_errors.TOK_BARRIER_HOLE_DISALLOWED.format(
                barrier=barrier.type.id,
                hole=hole_type.id,
            )
        else:
            message = user_errors.TOK_BARRIER_HOLE_NOVARIANT.format(
                barrier=barrier.type.id,
                hole=hole_type.id,
                types_barrier=TransToken.list_and([
                    TRANS_VARIABLE.format(value=variant)
                    for variant in barrier.type.hole_variants
                ]),
                types_hole=TransToken.list_or([
                    TRANS_VARIABLE.format(value=variant)
                    for variant in hole_type.variants.keys()
                ], sort=True),
            )
        raise user_errors.UserError(message, barrier_hole=error_hole)

    for offset in hole_type.footprint:
        pos = offset @ orient + origin
        local = plane.world_to_plane(pos)
        off_type = barrier_plane[local.x // 32, local.y // 32]
        if off_type != barrier:
            # Different type.
            LOGGER.warning(
                'Wrong barrier type at {}, {}: {} (expected {})',
                pos, plane, off_type, barrier,
            )
            raise user_errors.UserError(
                user_errors.TOK_BARRIER_HOLE_FOOTPRINT.format(hole=hole_type.id),
                barrier_hole=error_hole,
            )

    # In each direction, make sure a large hole isn't present.
    if isinstance(variant, LargeHoleConfig):
        for offset in LARGE_DISALLOWED:
            side_pos = plane.plane_to_world(*offset).freeze()
            try:
                other_hole = HOLES[plane][side_pos]
            except KeyError:
                pass
            else:
                if isinstance(other_hole.variant, LargeHoleConfig):
                    # TODO: Draw the other hole as well?
                    raise user_errors.UserError(
                        user_errors.TOK_BARRIER_HOLE_FOOTPRINT.format(hole=hole_type.id),
                        barrier_hole=error_hole,
                    )
    return variant


@conditions.make_result('GlassHole')
def res_glass_hole(inst: Entity, res: Keyvalues) -> None:
    """Add Glass/grating holes. The value should be 'large' or 'small'."""
    hole_type = HOLE_TYPES[utils.parse_obj_id(res.value)]

    orient = FrozenMatrix.from_angstr(inst['angles'])
    origin: FrozenVec = FrozenVec.from_str(inst['origin']) // 128 * 128 + 64
    origin += orient.up(-64.0)
    slice_key = utils.SliceKey(orient.up(-1.0), origin)

    first_variant = test_hole_spot(origin, slice_key, orient, hole_type)
    if first_variant is not None:
        sel_plane = slice_key
        sel_orient = orient
        sel_variant = first_variant
    else:
        # Test the opposite side of the glass too.
        alt_orient = FrozenMatrix.from_roll(180) @ orient
        slice_key = utils.SliceKey(alt_orient.up(-1.0), origin)

        sec_variant = test_hole_spot(origin, slice_key, alt_orient, hole_type)
        if sec_variant is not None:
            sel_orient = alt_orient
            sel_plane = slice_key
            sel_variant = sec_variant
            inst['angles'] = sel_orient.to_angle()
        else:
            raise user_errors.UserError(
                user_errors.TOK_BARRIER_HOLE_MISPLACED.format(hole=hole_type.id),
                barrier_hole=user_errors.BarrierHole(
                    pos=user_errors.to_threespace(origin + orient.up(64)),
                    axis=orient.up().axis(),
                    # TODO: Handle hole rendering better, user-specifiable?
                    large=hole_type.is_large,
                    small=not hole_type.is_large,
                    footprint=True,
                )
            )
    # Place it, or error if there's already one here.
    try:
        existing = HOLES[sel_plane][origin]
    except KeyError:
        pass
    else:
        raise user_errors.UserError(
            user_errors.TOK_BARRIER_HOLE_FOOTPRINT,
            points=[origin],
            barrier_hole=user_errors.BarrierHole(
                pos=user_errors.to_threespace(origin),
                axis=sel_plane.normal.axis(),
                large=isinstance(sel_variant, LargeHoleConfig) or isinstance(existing.variant, LargeHoleConfig),
                small=not isinstance(hole_type, LargeHoleConfig) or not isinstance(existing.variant, LargeHoleConfig),
                footprint=False,
            ),
        )
    HOLES[sel_plane][origin] = Hole(
        inst=inst,
        type=hole_type,
        variant=sel_variant,
        plane=sel_plane,
        orient=sel_orient,
        origin=origin.thaw(),
    )
    inst['origin'] = origin
    inst.fixup['$variant'] = sel_variant.id
    if sel_variant.instance:
        inst['file'] = sel_variant.instance
        conditions.ALL_INST.add(sel_variant.instance.casefold())


def template_solids_and_coll(template_id: str) -> Tuple[HoleTemplate, Sequence[collisions.BBox]]:
    """Retrieve the brushes and collision boxes for the specified visgroup.

    Holes have multiple variants, this simplifies things. We also split off boxes tagged "footprint",
    used to cut P1 floor beams.
    """
    temp_id, visgroups = template_brush.parse_temp_name(template_id)
    visgroups.add('')
    template = template_brush.get_template(temp_id)

    footprint: list[collisions.BBox] = []
    bboxes: list[collisions.BBox] = []
    for coll in template.collisions:
        if coll.visgroups.issubset(visgroups):
            if 'footprint' in coll.bbox.tags:
                footprint.append(coll.bbox)
            else:
                bboxes.append(coll.bbox)

    return (template.visgrouped_solids(visgroups), bboxes), footprint


@conditions.MetaCond.Barriers.register
def make_barriers(vmf: VMF, coll: collisions.Collisions) -> None:
    """Make barrier entities."""
    LOGGER.info('Generating barriers (glass/grating)...')

    if options.get_itemconf('BEE_PELLET:PelletGrating', False):
        # Merge together these existing filters in global_pti_ents
        vmf.create_ent(
            origin=options.GLOBAL_PTI_ENTS_LOC(),
            targetname='@grating_filter',
            classname='filter_multi',
            filtertype=0,
            negated=0,
            filter01='@not_pellet',
            filter02='@not_paint_bomb',
        )
    else:
        # Just skip paint bombs.
        vmf.create_ent(
            origin=options.GLOBAL_PTI_ENTS_LOC(),
            targetname='@grating_filter',
            classname='filter_activator_class',
            negated=1,
            filterclass='prop_paint_bomb',
        )

    debug_skin: dict[utils.ObjectID | utils.SpecialID, int] = {
        GLASS_ID: 5,
        GRATE_ID: 0,
    }
    add_debug = conditions.fetch_debug_visgroup(vmf, 'Barriers')
    group_id = 0
    for plane_slice, plane in BARRIERS.items():
        # If set, it's a floor/ceiling barrier, not a wall.
        is_flat = abs(plane_slice.normal.z) > 0.5
        hole_plane = HOLES[plane_slice]
        for barrier, group_plane in find_plane_groups(plane):
            group_id += 1

            borders = calc_borders(group_plane)

            # Place brushes that should not be carved by holes.
            for min_u, min_v, max_u, max_v, sub_barrier in grid_optimise(group_plane):
                place_planar_surfaces(vmf, coll, barrier, plane_slice, False, min_u, min_v, max_u, max_v)

            add_glass_floorbeams(vmf, barrier, plane_slice, group_plane)

            for hole in hole_plane.values():
                if not hole.inserted:
                    try_place_hole(vmf, coll, group_plane, barrier, hole)

            for (u, v) in group_plane:
                add_debug(
                    'bee2_template_tilesetter',
                    origin=plane_slice.plane_to_world(32 * u + 16, 32 * v + 16, 2),
                    angles=plane_slice.orient,
                    skin=debug_skin.get(barrier.type.id, 1),
                    targetname=f'barrier_{group_id}',
                    comment=f'Border: {borders[u, v]}, u={u}, v={v}',
                )

            lighting_origin = place_lighting_origin(vmf, barrier, plane_slice, group_plane)

            for (u, v) in group_plane:
                # Wall frame orientation is arbitrary right now, what to do?
                place_concave_corner(
                    vmf, barrier, lighting_origin, plane_slice, borders,
                    FrameOrient.FLAT if is_flat else FrameOrient.HORIZ,
                    u, v, ORIENT_W, +1, +1,
                )
                place_concave_corner(
                    vmf, barrier, lighting_origin, plane_slice, borders,
                    FrameOrient.FLAT if is_flat else FrameOrient.VERT,
                    u, v, ORIENT_S, -1, +1,
                )
                place_concave_corner(
                    vmf, barrier, lighting_origin, plane_slice, borders,
                    FrameOrient.FLAT if is_flat else FrameOrient.HORIZ,
                    u, v, ORIENT_E, -1, -1,
                )
                place_concave_corner(
                    vmf, barrier, lighting_origin, plane_slice, borders,
                    FrameOrient.FLAT if is_flat else FrameOrient.VERT,
                    u, v, ORIENT_N, +1, -1,
                )

            for (u, v), border in borders.items():
                if Border.STRAIGHT_N in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, lighting_origin, u, v,
                        Border.STRAIGHT_N, ORIENT_E, 'x', False,
                        Border.CORNER_NE, Border.CORNER_NW,
                        0, 32,
                    )
                if Border.STRAIGHT_S in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, lighting_origin, u, v,
                        Border.STRAIGHT_S, ORIENT_W, 'x', True,
                        Border.CORNER_SE, Border.CORNER_SW,
                        0, 0,
                    )
                if Border.STRAIGHT_E in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, lighting_origin, u, v,
                        Border.STRAIGHT_E, ORIENT_N, 'y', False,
                        Border.CORNER_SE, Border.CORNER_NE,
                        0, 0,
                    )
                if Border.STRAIGHT_W in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, lighting_origin, u, v,
                        Border.STRAIGHT_W, ORIENT_S, 'y', True,
                        Border.CORNER_SW, Border.CORNER_NW,
                        32, 0,
                    )

                if Border.CORNER_NW in border:
                    place_convex_corner(
                        vmf, barrier, plane_slice, lighting_origin,
                        ORIENT_W, u + 1, v + 1,
                    )
                if Border.CORNER_NE in border:
                    place_convex_corner(
                        vmf, barrier, plane_slice, lighting_origin,
                        ORIENT_S, u, v + 1,
                    )
                if Border.CORNER_SE in border:
                    place_convex_corner(
                        vmf, barrier, plane_slice, lighting_origin,
                        ORIENT_E, u, v,
                    )
                if Border.CORNER_SW in border:
                    place_convex_corner(
                        vmf, barrier, plane_slice, lighting_origin,
                        ORIENT_N, u + 1, v,
                    )

            for min_u, min_v, max_u, max_v, sub_barrier in grid_optimise(group_plane):
                if sub_barrier is BARRIER_EMPTY:
                    continue
                place_planar_surfaces(vmf, coll, barrier, plane_slice, True, min_u, min_v, max_u, max_v)

    for hole_plane in HOLES.values():
        for hole in hole_plane.values():
            if not hole.inserted:
                raise user_errors.UserError(
                    user_errors.TOK_BARRIER_HOLE_FOOTPRINT,
                    barrier_hole={
                        'pos': user_errors.to_threespace(hole.origin),
                        'axis': hole.plane.normal.axis(),
                        'large': hole.type.is_large,
                        'small': not hole.type.is_large,
                        'footprint': True,
                    }
                )


def find_plane_groups(plane: Plane[Barrier]) -> Iterator[Tuple[Barrier, Plane[Barrier]]]:
    """Yield sub-graphs of a barrier plane, containing contiguous barriers."""
    stack: Set[Tuple[int, int]] = set()
    completed: Plane[bool] = Plane.fromkeys(plane, False)
    for start, cmp_value in plane.items():
        if completed[start] or cmp_value is BARRIER_EMPTY:
            continue
        group: Plane[Barrier] = Plane()
        stack.add(start)
        mergeable = cmp_value.type.mergeable
        while stack:
            x, y = pos = stack.pop()
            if completed[pos]:
                continue
            value = plane[pos]
            if value == cmp_value or (mergeable and value.type is cmp_value.type):
                completed[pos] = True
                group[pos] = value
                stack |= {
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                }
        yield cmp_value, group


def calc_borders(plane: Plane[Barrier]) -> Plane[Border]:
    """Calculate which borders are required for each section of this plane."""
    borders = Plane(default=Border.NONE)
    for (x, y) in plane:
        border = Border.NONE
        if north := (x, y + 1) not in plane:
            border |= Border.STRAIGHT_N
        if south := (x, y - 1) not in plane:
            border |= Border.STRAIGHT_S
        if east := (x - 1, y) not in plane:
            border |= Border.STRAIGHT_E
        if west := (x + 1, y) not in plane:
            border |= Border.STRAIGHT_W
        if north and east:
            border |= Border.CORNER_NE
        if north and west:
            border |= Border.CORNER_NW
        if south and east:
            border |= Border.CORNER_SE
        if south and west:
            border |= Border.CORNER_SW
        if border is not Border.NONE:
            borders[x, y] = border
    return borders


def place_lighting_origin(
    vmf: VMF, barrier: Barrier,
    plane_slice: utils.SliceKey,
    group_plane: Plane[Barrier],
) -> str:
    """Create a lighting origin for a barrier's frame. This should be placed roughly in the centre."""
    # First, calculate the average UV position, then find the tile that's closest to that.
    # This way something like an L-shaped piece of glass doesn't put the origin in the void.
    count = avg_u = avg_v = 0
    for u, v in group_plane:
        avg_u += u
        avg_v += v
        count += 1

    avg_pos = (avg_u / count, avg_v / count)

    best_u, best_v = min(group_plane, key=lambda uv: math.dist(uv, avg_pos))
    if barrier.item is not None:
        name = conditions.local_name(barrier.item.inst, 'lighting')
    else:
        name = 'lighting'
    ent = vmf.create_ent(
        'info_lighting',
        origin=plane_slice.plane_to_world(
            best_u * 32 + 16.0,
            best_v * 32 + 16.0,
            barrier.type.coll_thick / 2,
        ),
        targetname=name,
    )
    if barrier.item is None:
        ent.make_unique()
    return name


def place_planar_surfaces(
    vmf: VMF, coll: collisions.Collisions, barrier: Barrier,
    plane_slice: utils.SliceKey, carved: bool,
    min_u: int, min_v: int, max_u: int, max_v: int,
) -> None:
    """Place brushes and collisions across the surface of the barrier."""
    def solid_func(z1: float, z2: float) -> List[Solid]:
        """Generate prism brushes."""
        prism = vmf.make_prism(
            plane_slice.plane_to_world(32.0 * min_u, 32.0 * min_v, z1),
            plane_slice.plane_to_world(32.0 * max_u + 32.0, 32.0 * max_v + 32.0, z2),
        )
        return [prism.solid]

    for surface in barrier.type.surfaces:
        if surface.carve_by_hole == carved:
            if isinstance(surface, Brush):
                surface.generate(vmf, plane_slice, solid_func)
            elif isinstance(surface, Collide):
                coll.add(collisions.BBox(
                    plane_slice.plane_to_world(32.0 * min_u, 32.0 * min_v, surface.offset),
                    plane_slice.plane_to_world(32.0 * max_u + 32.0, 32.0 * max_v + 32.0, surface.thickness),
                    name=barrier.name,
                    contents=surface.contents,
                ))
            else:
                assert_never(surface)


def place_concave_corner(
    vmf: VMF,
    barrier: Barrier,
    lighting_origin: str,
    slice_key: utils.SliceKey,
    borders: Plane[Border],
    frame_orient: FrameOrient,
    u: int,
    v: int,
    orient: FrozenMatrix,
    off_u: Literal[-1, +1],
    off_v: Literal[-1, +1],
) -> None:
    """Check if a concave corner needs to be placed at this offset."""
    if (
        NORMAL_TO_BORDER[off_u, 0] not in borders[u, v + off_v] or
        NORMAL_TO_BORDER[0, off_v] not in borders[u + off_u, v]
    ):
        return  # No convex corner required.
    for frame in barrier.type.frames[frame_orient]:
        for seg in frame.seg_concave_corner:
            seg.place(
                vmf, slice_key,
                lighting_origin,
                32. * u + 16. * off_u + 16.0,
                32. * v + 16. * off_v + 16.0,
                orient, barrier.type.frame_world_brush,
            )


def try_place_hole(
    vmf: VMF,
    coll: collisions.Collisions,
    plane: Plane[Barrier],
    barrier: Barrier,
    hole: Hole,
) -> None:
    """Try and place a hole in the barrier."""
    # First check if the footprint is present. If not, we're some other piece of glass.
    for offset in hole.type.footprint:
        local = hole.plane.world_to_plane(hole.origin + offset @ hole.orient)
        if (local.x // 32, local.y // 32) not in plane:
            return

    # Found, we're generating this.
    hole.inserted = True

    hole_temp: list[tuple[list[Solid], list[collisions.BBox], Matrix | FrozenMatrix]] = []
    hole_plane = HOLES[hole.plane]

    # This is a tricky bit. Two large templates would collide
    # diagonally, and we allow the corner glass to not be present since
    # the hole doesn't actually use that 32x32 segment.
    # So we need to determine which of 3 templates to use.
    if isinstance(hole.variant, LargeHoleConfig):
        for yaw in (0, 90, 180, 270):
            corn_mat = Matrix.from_yaw(yaw) @ hole.plane.orient

            corn_dir = Vec(x=1, y=1) @ corn_mat
            hole_off = hole.origin + 128 * corn_dir
            diag_hole = hole_plane.get(hole_off.freeze())
            corner_pos = hole.plane.world_to_plane(hole.origin + 80 * corn_dir)
            corn_u = corner_pos.x // 32
            corn_v = corner_pos.y // 32

            if diag_hole is not None and isinstance(diag_hole.variant, LargeHoleConfig):
                # There's another large template to this direction.
                # Just have 1 generate both combined, so the brushes can
                # be more optimal. To pick, arbitrarily make the upper one
                # be in charge.
                if corn_v > (hole.plane_pos[1] // 32):
                    hole_temp.append(hole.variant.template_diagonal + (corn_mat, ))
                continue
            # This bit of the glass is present, so include it in our brush, then clear.
            if (corn_u, corn_v) in plane:
                hole_temp.append(hole.variant.template_square + (corn_mat, ))
                plane[corn_u, corn_v] = BARRIER_EMPTY
            else:
                hole_temp.append(hole.variant.template + (corn_mat, ))

    else:
        hole_temp.append(hole.variant.template + (hole.plane.orient, ))

    for offset in hole.type.footprint:
        local = hole.plane.world_to_plane(hole.origin + offset @ hole.orient)
        # This is in the plane still, but marked as blank. That way diagonally overlapping holes
        # still work.
        plane[local.x // 32, local.y // 32] = BARRIER_EMPTY

    hole_origin_cell = hole.origin

    def hole_brush_func(off1: float, off2: float) -> list[Solid]:
        """Given the two thicknesses, produce the curved hole from the template."""
        off_min = min(off1, off2)
        off_max = max(off1, off2)
        new_brushes = []
        for brushes, _, matrix in hole_temp:
            for orig_brush in brushes:
                brush = orig_brush.copy(vmf_file=vmf)
                new_brushes.append(brush)
                for face in brush.sides:
                    for point in face.planes:
                        if point.z > 0:
                            point.z = off_max
                        else:
                            point.z = off_min
                    face.localise(hole_origin_cell, matrix)
                    # Increase precision, these are small detail brushes.
                    face.lightmap = 8
        return new_brushes

    for surface in barrier.type.surfaces:
        if not surface.carve_by_hole:
            continue
        if isinstance(surface, Brush):
            surface.generate(vmf, hole.plane, hole_brush_func)
        elif isinstance(surface, Collide):
            # Collisions
            for _, bbox_list, matrix in hole_temp:
                for bbox in bbox_list:
                    bbox = bbox.with_attrs(name=barrier.name, contents=surface.contents)
                    bbox = bbox.scale_to(
                        'z',
                        round(surface.offset),
                        round(surface.offset + surface.thickness),
                    )
                    bbox = bbox @ matrix + hole.origin
                    coll.add(bbox)
        else:
            assert_never(surface)


def place_straight_run(
    vmf: VMF,
    barrier: Barrier,
    slice_key: utils.SliceKey,
    borders: Plane[Border],
    lighting_origin: str,
    start_u: int,
    start_v: int,
    straight: Border,
    orient: FrozenMatrix,
    axis: Literal['x', 'y'],
    backwards: bool,
    corner_start: Border,
    corner_end: Border,
    pos_u: Literal[0, 32],
    pos_v: Literal[0, 32],
) -> None:
    """Place a straight edge side, going as far as possible.

    Parameters:
        * vmf: The map.
        * barrier: The barrier to generate frames for.
        * slice_key: Orientation of the plane.
        * borders: Computed border shapes that are yet to be placed.
        * lighting_origin: Name of the info_lighting entity to use.
        * start_u: Starting cell with this straight type.
        * start_v: ^^^^
        * straight: The kind of border we're placing.
        * orient: Rotation to apply to the straight pieces so that they fit.
        * axis: The direction to move to continue this straight piece into another cell.
        * backwards: If set, offset each piece to the end of its section instead of the start.
        * corner_start: The corner which this could connect to on the start cell.
          If present, offset forwards.
        * corner_end: The corner which this could connect to on the end cell.
          If present, offset backwards.
        * pos_u: Offset the placed straight sections by this many units at the end.
        * pos_v: ^^^^
    """
    end_u, end_v = start_u, start_v
    total_dist = 32
    if axis == 'x':
        off_u, off_v = 1, 0
    else:
        off_u, off_v = 0, 1
    direction = Vec(off_u, off_v) @ slice_key.orient
    if backwards:
        direction = -direction
    if abs(slice_key.normal.z) > 0.5:
        frame_orient = FrameOrient.FLAT
    else:
        frame_orient = FrameOrient.HORIZ if abs(direction.z) < 0.5 else FrameOrient.VERT

    while straight in borders[end_u + off_u, end_v + off_v]:
        total_dist += 32
        end_u += off_u
        end_v += off_v
    for frame in barrier.type.frames[frame_orient]:
        start_off = 0
        frame_length = total_dist
        end_off = total_dist
        # If corners are present, shrink the straight piece inwards to not overlap.
        if corner_start in borders[start_u, start_v]:
            frame_length -= frame.corner_size
            start_off += frame.corner_size
        if corner_end in borders[end_u, end_v]:
            frame_length -= frame.corner_size
            end_off -= frame.corner_size

        if frame.seg_straight_prop:
            off = start_off
            for size in frame.seg_straight_fitter(frame_length):
                # If backwards, advance before placing.
                if backwards:
                    off += size

                for piece in frame.seg_straight_prop[size]:
                    piece.place(
                        vmf, slice_key, lighting_origin,
                        32. * start_u + off_u * off + pos_u,
                        32. * start_v + off_v * off + pos_v,
                        orient,
                        barrier.type.frame_world_brush,
                    )

                if not backwards:
                    off += size

        off = end_off if backwards else start_off
        for brush_seg in frame.seg_straight_brush:
            brush_seg.place_sized(
                vmf, slice_key,
                32.0 * start_u + off_u * off + pos_u,
                32.0 * start_v + off_v * off + pos_v,
                orient, direction, frame_length,
                barrier.type.frame_world_brush,
            )
    # Only one of these has an actual length.
    for u in range(start_u, end_u + 1):
        for v in range(start_v, end_v + 1):
            borders[u, v] &= ~straight


def place_convex_corner(
    vmf: VMF,
    barrier: Barrier,
    slice_key: utils.SliceKey,
    lighting_origin: str,
    orient: FrozenMatrix,
    u: float,
    v: float,
) -> None:
    """Try to place a convex corner here."""
    for frame in barrier.type.frames[FrameOrient.HORIZ]:
        for seg in frame.seg_corner:
            seg.place(
                vmf, slice_key, lighting_origin,
                32.0 * u, 32.0 * v, orient,
                barrier.type.frame_world_brush,
            )


def add_glass_floorbeams(
    vmf: VMF,
    barrier: Barrier,
    slice_key: utils.SliceKey,
    plane: Plane[Barrier],
) -> None:
    """Add beams to separate large glass panels. This is rather special cased for P1 style."""
    conf = barrier.type.floorbeam
    # Don't add if none or defined or not flat.
    if conf is None or slice_key.normal.z == 0.0:
        return

    # Our beams align to the smallest axis.
    plane_dims_x, plane_dims_y = plane.dimensions
    if plane_dims_y > plane_dims_x:
        beam_ind = 0
        side_ind = 1
        rot = Matrix() @ slice_key.orient

        def flip_axes(beam: float, side: float) -> tuple[float, float]:
            """Flip axes if required"""
            return (beam, side)
    else:
        beam_ind = 1
        side_ind = 0
        rot = Matrix.from_yaw(90) @ slice_key.orient

        def flip_axes(beam: float, side: float) -> tuple[float, float]:
            """Flip axes if required"""
            return (side, beam)

    beam_ax = 'xyz'[beam_ind]
    side_ax = 'xyz'[side_ind]
    height = slice_key.plane_to_world(0, 0).z

    rng = rand_seed(
        b'barrier_floorbeams',
        height,
        *map(float, plane.mins), *map(float, plane.maxes),
    )

    distances = list(conf.distance)
    hole_shapes = [
        shape
        for hole in HOLES[slice_key].values()
        for shape in hole.shape
    ]
    name_to_hole = {
        hole.inst['targetname']: hole
        for hole in HOLES[slice_key].values()
    }

    min_side_offset = plane.mins[side_ind] * 32
    max_side_offset = plane.maxes[side_ind] * 32 - conf.distance.start
    min_beam_offset = plane.mins[beam_ind] * 32
    max_beam_offset = plane.maxes[beam_ind] * 32
    half_width = conf.width / 2

    def place_run(side_pos: int) -> bool:
        """Try and place a run of beams, and return if we placed some."""
        # First, check to see if we're overlapping two subvoxels. If so, error.
        if (side_pos - half_width) // 32 != (side_pos + half_width) // 32:
            return False

        brushes: List[Solid] = []
        side_grid = side_pos // 32
        forward = rot.forward(1.0)
        beam_start: float  # If hitting a hole, comes from the impact point.

        # First, search for the first point in this plane that matches, for our starting position
        for beam_start in range(min_beam_offset + conf.border, max_beam_offset, 32):
            if flip_axes(beam_start // 32, side_grid) in plane:
                break
        else:  # This entire column is missing.
            return False

        normal_start: Vec | FrozenVec = forward
        trace_against = hole_shapes
        while beam_start < max_beam_offset:
            # Find where it ends.
            beam_end = round(beam_start) // 32 * 32 + 32
            while flip_axes(beam_end // 32, side_grid) in plane:
                beam_end += 32

            # Next, check every hole to see if we overlap.
            trace_direction = Vec(flip_axes(beam_end - beam_start, 0.0)) @ slice_key.orient
            hit_left = collisions.trace_ray(
                slice_key.plane_to_world(*flip_axes(beam_start, side_pos - half_width)),
                trace_direction,
                trace_against,
            )
            if hit_left is None:
                # No holes, just produce the beam.
                brushes.append(conf.generate(
                    vmf, rot,
                    slice_key.plane_to_world(*flip_axes(beam_start, side_pos)),
                    normal_start,
                    slice_key.plane_to_world(*flip_axes(beam_end - conf.border, side_pos)),
                    rot.forward(-1.0),
                ))
                # Look forward for the next position
                for beam_start in range(beam_end + conf.border, max_beam_offset, 32):
                    if flip_axes(beam_start // 32, side_grid) in plane:
                        break
                else:  # No more.
                    break
            else:
                # We have a hole in the way.
                hole_name = hit_left.volume.name
                hole = name_to_hole[hole_name]

                # Trace the other side.
                hit_right = collisions.trace_ray(
                    slice_key.plane_to_world(*flip_axes(beam_start, side_pos + half_width)),
                    trace_direction,
                    hole.shape,
                )
                if hit_right is None or not hits_aligned(hit_left, hit_right):
                    # Only partially overlap or misaligned, can't place here.
                    return False

                # Generate the beam up to this hole.
                brushes.append(conf.generate(
                    vmf, rot,
                    slice_key.plane_to_world(*flip_axes(beam_start, side_pos)),
                    normal_start,
                    hit_left.impact,
                    -hit_left.normal,
                ))

                # Trace again, this time backwards to find out where to emerge from.
                hit_left = collisions.trace_ray(
                    slice_key.plane_to_world(*flip_axes(beam_end, side_pos - half_width)),
                    -trace_direction,
                    hole.shape,
                )
                hit_right = collisions.trace_ray(
                    slice_key.plane_to_world(*flip_axes(beam_end, side_pos + half_width)),
                    -trace_direction,
                    hole.shape,
                )
                if hit_left is None or hit_right is None or not hits_aligned(hit_left, hit_right):
                    # Incorrectly aligned on the backside.
                    return False
                # Snap to centerpoint, average
                old_start = beam_start
                beam_start = (
                    forward.dot(hit_left.impact) + forward.dot(hit_right.impact)
                ) / 2.0
                normal_start = -hit_left.normal
                # On the next iteration, disallow colliding with the same bboxes. Otherwise,
                # we'll just immediately hit it again.
                trace_against = [
                    bbox for bbox in hole_shapes
                    if bbox.name != hole_name
                ]
        if brushes:
            # Succeeded, make the entity.
            vmf.create_ent('func_detail').solids = brushes
            return True
        return False

    position = min_side_offset
    while position < max_side_offset:
        rng.shuffle(distances)
        potentials = distances[:10]

        for offset in potentials:
            if place_run(position + offset):
                position += offset
                break
        else:
            # Failed entirely, skip this section to make sure we terminate.
            position += conf.distance.start


def hits_aligned(first: collisions.Hit, second: collisions.Hit) -> bool:
    """Check whether both collisions are aligned to each other.

    If not, there must be a vertex in-between, meaning we can't have beams here.
    """
    if Vec.dot(first.normal, second.normal) < 0.99:
        return False
    return abs(Vec.dot(first.normal, first.impact) - Vec.dot(second.normal, second.impact)) < 0.125
