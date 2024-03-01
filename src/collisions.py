"""Defines the region of space items occupy and computes collisions."""
from __future__ import annotations
from typing import Iterable, Iterator, Sequence, Tuple, overload
from typing_extensions import Self, Literal

from enum import Flag, auto as enum_auto
import functools
import operator

from srctools.vmf import UVAxis, VMF, Entity, Solid, Side
from srctools.math import AnyAngle, AnyMatrix, FrozenVec, Matrix, Vec, to_matrix
from srctools import conv_bool, logger
import attrs

import consts


LOGGER = logger.get_logger(__name__)


@attrs.define
class NonBBoxError(ValueError):
    """Raised to indicate a bbox is a line or point, not a plane or bounding box."""
    min_x: int
    min_y: int
    min_z: int
    max_x: int
    max_y: int
    max_z: int

    def __str__(self) -> str:
        return (
                f'({self.min_x} {self.min_y} {self.min_z}) - '
                f'({self.max_x} {self.max_y} {self.max_z}) '
                'is not a full volume or plane!'
            )


class CollideType(Flag):
    """Type of collision."""
    NOTHING = 0
    SOLID = enum_auto()  # Regular solid walls, props etc.
    DECORATION = enum_auto()  # A location where decoration may not be placed.
    GRATING = enum_auto()  # Grating, blocks movement, but does not block energy beams.
    GLASS = enum_auto()   # Only permits lasers through.
    BRIDGE = enum_auto()
    FIZZLER = enum_auto()
    TEMPORARY = enum_auto()  # Collision is only sometimes present here.
    ANTLINES = enum_auto()  # Antlines should not pass here.
    OOB = enum_auto()  # Areas outside the puzzle, don't allow things to be placed here.

    GRATE = GRATING
    DECO = DECORATION
    ANTLINE = ANTLINES
    # Aliases matching editoritems COLLIDE_ definitions.
    PHYSICS = SOLID | TEMPORARY

    # OR all defined members from above.
    EVERYTHING = functools.reduce(
        operator.or_,
        (x for x in vars().values() if isinstance(x, int)),
    )

    @classmethod
    def parse(cls, text: str) -> CollideType:
        """Parse from a space-separated string."""
        coll = cls.NOTHING
        for word in text.split():
            try:
                coll |= cls[word.upper()]
            except KeyError:
                raise ValueError(f'Unknown collide type "{word}"!') from None
        return coll

    @classmethod
    def from_ent_kvs(cls, entity: Entity) -> CollideType:
        """Parse from a bunch of boolean keyvalues."""
        coll = cls.NOTHING
        for key, value in entity.items():
            if key.casefold().startswith('coll_') and conv_bool(value):
                coll_name = key[5:].upper()
                try:
                    coll |= cls[coll_name]
                except KeyError:
                    LOGGER.warning('Invalid collide type: "{}"!', key)
        return coll

# The types we want to write into vmfs.
EXPORT_KVALUES: Sequence[CollideType] = [
    CollideType.ANTLINES,
    CollideType.BRIDGE,
    CollideType.DECORATION,
    CollideType.FIZZLER,
    CollideType.GLASS,
    CollideType.GRATING,
    CollideType.OOB,
    CollideType.SOLID,
    CollideType.TEMPORARY,
]


@attrs.frozen(kw_only=True)
class Hit:
    """Represents the impact of a raytrace."""
    start: FrozenVec
    direction: FrozenVec
    distance: float
    impact: FrozenVec
    normal: FrozenVec  # Pointing outward at the hit location.


@attrs.frozen(init=False)
class BBox:
    """An axis aligned volume for collision.

    This may either be a solid volume, or a plane (with one axis' min=max).
    """
    min_x: int
    min_y: int
    min_z: int
    max_x: int
    max_y: int
    max_z: int
    contents: CollideType
    name: str  # Item name, or empty for definitions.
    tags: frozenset[str]

    @overload
    def __init__(
        self,
        min_x: int | float, min_y: int | float, min_z: int | float,
        max_x: int | float, max_y: int | float, max_z: int | float,
        /, *,
        contents: CollideType = CollideType.SOLID,
        tags: Iterable[str] | str = frozenset(),
        name: str = '',
    ) -> None: ...

    @overload
    def __init__(
        self,
        point1: Vec | FrozenVec, point2: Vec | FrozenVec,
        /, *,
        contents: CollideType = CollideType.SOLID,
        tags: Iterable[str] | str = frozenset(),
        name: str = '',
    ) -> None: ...

    def __init__(
        self,
        /,
        *args: Vec | FrozenVec | int | float,
        contents: CollideType = CollideType.SOLID,
        tags: Iterable[str] | str = frozenset(),
        name: str = '',
    ) -> None:
        """Allow constructing from Vec, and flip values to make them min/max."""
        min_x: int
        max_x: int
        min_y: int
        max_y: int
        min_z: int
        max_z: int
        if len(args) == 6:
            try:
                # None of these should be Vec.
                min_x, min_y, min_z, max_x, max_y, max_z = map(round, args)  # type: ignore
            except (TypeError, ValueError):
                raise TypeError(f'6 numbers must be supplied, not {args!r}') from None
        elif len(args) == 2:
            point1, point2 = args
            if isinstance(point1, (Vec, FrozenVec)) and isinstance(point2, (Vec, FrozenVec)):
                min_x, min_y, min_z = round(point1.x), round(point1.y), round(point1.z)
                max_x, max_y, max_z = round(point2.x), round(point2.y), round(point2.z)
            else:
                raise TypeError(f'Expected 2 vectors, got {type(point1).__name__} and {type(point2).__name__}')
        else:
            raise TypeError(f'Expected 2 or 6 positional args, got {len(args)}!')
        if min_x > max_x:
            min_x, max_x = max_x, min_x
        if min_y > max_y:
            min_y, max_y = max_y, min_y
        if min_z > max_z:
            min_z, max_z = max_z, min_z

        if (min_x != max_x) + (min_y != max_y) + (min_z != max_z) < 2:
            raise NonBBoxError(min_x, min_y, min_z, max_x, max_y, max_z)

        self.__attrs_init__(
            min_x, min_y, min_z,
            max_x, max_y, max_z,
            contents,
            name,
            frozenset([tags] if isinstance(tags, str) else tags),
        )

    @property
    def mins(self) -> Vec:
        """Return the minimums, as a Vector."""
        return Vec(self.min_x, self.min_y, self.min_z)

    @property
    def maxes(self) -> Vec:
        """Return the minimums, as a Vector."""
        return Vec(self.max_x, self.max_y, self.max_z)

    @property
    def center(self) -> Vec:
        """Return the center of the bounding box, as a Vector."""
        return Vec(
            (self.min_x + self.max_x) / 2.0,
            (self.min_y + self.max_y) / 2.0,
            (self.min_z + self.max_z) / 2.0,
        )

    @property
    def size(self) -> Vec:
        """Return the size of the bounding box, as a Vector."""
        return Vec(
            self.max_x - self.min_x,
            self.max_y - self.min_y,
            self.max_z - self.min_z,
        )

    @property
    def is_plane(self) -> bool:
        """Check if this is a plane, not a bounding volume."""
        return (
            self.min_x == self.max_x or
            self.min_y == self.max_y or
            self.min_z == self.max_z
        )

    @property
    def plane_normal(self) -> Vec | None:
        """If a plane, returns the normal axis."""
        if self.min_x == self.max_x:
            return Vec(1.0, 0.0, 0.0)
        elif self.min_y == self.max_y:
            return Vec(0.0, 1.0, 0.0)
        elif self.min_z == self.max_z:
            return Vec(0.0, 0.0, 1.0)
        return None

    def _with_points(self, point1: Vec | FrozenVec, point2: Vec | FrozenVec) -> BBox:
        """Return a new bounding box with the specified points, but this collision and tags."""
        return BBox(point1, point2, contents=self.contents, tags=self.tags, name=self.name)

    def with_attrs(
        self, *,
        name: str | None = None,
        contents: CollideType | None = None,
        tags: Iterable[str] | str | None = None,
    ) -> BBox:
        """Return a new bounding box with the name, contents or tags changed."""
        return BBox(
            self.min_x, self.min_y, self.min_z,
            self.max_x, self.max_y, self.max_z,
            contents=contents if contents is not None else self.contents,
            name=name if name is not None else self.name,
            tags=tags if tags is not None else self.tags,
        )

    @classmethod
    def from_ent(cls, ent: Entity) -> Iterator[Self]:
        """Parse keyvalues on a VMF entity. One bounding box is produced for each brush."""
        coll = CollideType.from_ent_kvs(ent)
        tags = frozenset(ent['tags'].split())

        for solid in ent.solids:
            mins, maxes = solid.get_bbox()
            non_skip_faces = [
                face
                for face in solid
                if face.mat != consts.Tools.SKIP
            ]
            try:
                # Only one non-skip face, "flatten" along its plane.
                face: Side
                [face] = non_skip_faces
            except ValueError:
                pass  # Regular bbox.
            else:
                plane_norm = face.normal()
                plane_point = face.planes[0]
                for point in [mins, maxes]:
                    # Get the offset from the plane, then subtract to force it onto the plane.
                    point -= plane_norm * Vec.dot(point - plane_point, plane_norm)

            yield cls(mins, maxes, contents=coll, tags=tags)

    def _to_kvs(self, vmf: VMF, classname: str) -> Entity:
        """Fill in keyvalues for an entity."""
        ent = Entity(vmf, {
            'classname': classname,
            'tags': ' '.join(sorted(self.tags)),
            'item_id': self.name,
        })
        # Exclude the aliases.
        for coll in EXPORT_KVALUES:
            assert coll.name is not None
            ent[f'coll_{coll.name.lower()}'] = (coll & self.contents) is not CollideType.NOTHING
        return ent

    def as_ent(self, vmf: VMF) -> Entity:
        """Convert back into an entity."""
        # If a plane, then we have to produce a valid brush - subtract in the negative dir, put skip
        # on all other sides.
        norm = self.plane_normal
        if norm is not None:
            prism = vmf.make_prism(self.mins - norm, self.maxes, consts.Tools.SKIP)
            if norm == (1, 0, 0):
                prism.east.mat = consts.Tools.CLIP
            elif norm == (0, 1, 0):
                prism.north.mat = consts.Tools.CLIP
            elif norm == (0, 0, 1):
                prism.top.mat = consts.Tools.CLIP
            else:
                raise AssertionError(norm)
        else:
            prism = vmf.make_prism(self.mins, self.maxes, consts.Tools.CLIP)

        ent = self._to_kvs(vmf, 'bee2_collision_bbox')
        ent.solids.append(prism.solid)
        return ent

    def intersect(self, other: BBox) -> BBox | None:
        """Check if another bbox collides with this one.

        If so, return the bbox representing the overlap.
        """
        if isinstance(other, Volume):
            # Make it do the logic.
            return other.intersect(self)

        comb = self.contents & other.contents
        if comb is CollideType.NOTHING:
            return None
        # We do each axis one at a time. First do a separating-axis test
        # on either side, if that passes we don't collide.
        if self.max_x < other.min_x or self.min_x > other.max_x:
            return None
        # They overlap, so compare the min/max pairs to get the intersection interval.
        # If that's negative, we fail also.
        min_x = max(self.min_x, other.min_x)
        max_x = min(self.max_x, other.max_x)
        if min_x > max_x:
            return None

        # Then repeat for the other axes.
        if self.max_y < other.min_y or self.min_y > other.max_y:
            return None

        min_y = max(self.min_y, other.min_y)
        max_y = min(self.max_y, other.max_y)
        if min_y > max_y:
            return None

        if self.max_z < other.min_z or self.min_z > other.max_z:
            return None

        min_z = max(self.min_z, other.min_z)
        max_z = min(self.max_z, other.max_z)
        if min_z > max_z:
            return None

        try:
            return BBox(
                min_x, min_y, min_z, max_x, max_y, max_z,
                contents=self.contents,
                tags=self.tags,
                name=self.name,
            )
        except NonBBoxError:  # Edge or corner, don't count those.
            return None

    def _rotate_bbox(self, other: AnyAngle | AnyMatrix) -> Tuple[AnyMatrix, Vec, Vec]:
        # https://gamemath.com/book/geomprims.html#transforming_aabbs
        m = to_matrix(other)
        mins = Vec()
        maxs = Vec()

        if m[0, 0] > 0.0:
            mins.x = m[0, 0] * self.min_x
            maxs.x = m[0, 0] * self.max_x
        else:
            mins.x = m[0, 0] * self.max_x
            maxs.x = m[0, 0] * self.min_x

        if m[0, 1] > 0.0:
            mins.y = m[0, 1] * self.min_x
            maxs.y = m[0, 1] * self.max_x
        else:
            mins.y = m[0, 1] * self.max_x
            maxs.y = m[0, 1] * self.min_x

        if m[0, 2] > 0.0:
            mins.z = m[0, 2] * self.min_x
            maxs.z = m[0, 2] * self.max_x
        else:
            mins.z = m[0, 2] * self.max_x
            maxs.z = m[0, 2] * self.min_x

        if m[1, 0] > 0.0:
            mins.x += m[1, 0] * self.min_y
            maxs.x += m[1, 0] * self.max_y
        else:
            mins.x += m[1, 0] * self.max_y
            maxs.x += m[1, 0] * self.min_y

        if m[1, 1] > 0.0:
            mins.y += m[1, 1] * self.min_y
            maxs.y += m[1, 1] * self.max_y
        else:
            mins.y += m[1, 1] * self.max_y
            maxs.y += m[1, 1] * self.min_y

        if m[1, 2] > 0.0:
            mins.z += m[1, 2] * self.min_y
            maxs.z += m[1, 2] * self.max_y
        else:
            mins.z += m[1, 2] * self.max_y
            maxs.z += m[1, 2] * self.min_y

        if m[2, 0] > 0.0:
            mins.x += m[2, 0] * self.min_z
            maxs.x += m[2, 0] * self.max_z
        else:
            mins.x += m[2, 0] * self.max_z
            maxs.x += m[2, 0] * self.min_z

        if m[2, 1] > 0.0:
            mins.y += m[2, 1] * self.min_z
            maxs.y += m[2, 1] * self.max_z
        else:
            mins.y += m[2, 1] * self.max_z
            maxs.y += m[2, 1] * self.min_z

        if m[2, 2] > 0.0:
            mins.z += m[2, 2] * self.min_z
            maxs.z += m[2, 2] * self.max_z
        else:
            mins.z += m[2, 2] * self.max_z
            maxs.z += m[2, 2] * self.min_z

        return m, mins, maxs

    def __matmul__(self, other: AnyAngle | AnyMatrix) -> BBox:
        """Rotate the bounding box by an angle. This should be multiples of 90 degrees."""
        matrix, mins, maxes = self._rotate_bbox(other)
        return self._with_points(mins, maxes)

    def __add__(self, other: Vec | FrozenVec | tuple[float, float, float]) -> BBox:
        """Shift the bounding box forwards by this amount."""
        if isinstance(other, BBox):  # Special-case error.
            raise TypeError('Two bounding boxes cannot be added!')
        return self._with_points(self.mins + other, self.maxes + other)

    def __sub__(self, other: Vec | FrozenVec | tuple[float, float, float]) -> BBox:
        """Shift the bounding box backwards by this amount."""
        return self._with_points(self.mins - other, self.maxes - other)

    # radd/rsub intentionally omitted. Don't allow inverting, that's nonsensical.

    def trace_ray(self, start: Vec | FrozenVec, delta: Vec | FrozenVec) -> Hit | None:
        """Trace a ray against the bbox, returning the hit position (if any).

        :parameter start: The starting point for the ray.
        :parameter delta: Both the direction and the maximum length to check.
        """
        start = FrozenVec(start)
        delta = FrozenVec(delta)
        # https://gamemath.com/book/geomtests.html#intersection_ray_aabb
        inside = True
        mins = self.mins
        maxes = self.maxes

        def check_plane(axis: Literal['x', 'y', 'z']) -> Tuple[float, float]:
            """Determine where the intersection would be for each axial face pair."""
            if start[axis] < mins[axis]:
                time = mins[axis] - start[axis]
                if time > delta[axis]:
                    raise ValueError('No hit!')
                time /= delta[axis]
                return time, -1.0
            elif start[axis] > maxes[axis]:
                time = maxes[axis] - start[axis]
                if time < delta[axis]:
                    raise ValueError('No hit!')
                time /= delta[axis]
                return time, 1.0
            else:
                return -1.0, 0.0

        try:
            xt, xn = check_plane('x')
            yt, yn = check_plane('y')
            zt, zn = check_plane('z')
        except ValueError:
            return None
        if xn == yn == zn == 0.0:
            # Inside the box. We immediately impact.
            direction = delta.norm()
            return Hit(
                start=start,
                direction=direction,
                normal=-direction,
                impact=start,
                distance=0.0,
            )

        plane: Literal['x', 'y', 'z'] = 'x'
        time = xt
        if yt > time:
            time = yt
            plane = 'y'
        if zt > time:
            time = zt
            plane = 'z'
        impact = start + delta * time

        if mins <= impact <= maxes:
            return Hit(
                start=start,
                direction=delta.norm(),
                normal=FrozenVec.with_axes(plane, FrozenVec(xn, yn, zn)),
                impact=impact,
                distance=(impact - start).mag(),
            )
        else:
            return None


@attrs.frozen
class Plane:
    """A plane, used to represent the sides of a volume."""
    normal: FrozenVec
    distance: float

    @property
    def point(self) -> FrozenVec:
        """Return an arbitary point on this plane."""
        return self.normal * self.distance


@attrs.frozen(init=False)  # __attrs_init__() is incompatible with the superclass.
class Volume(BBox):  # type: ignore[override]
    """A bounding box with additional clipping planes, allowing it to be an arbitary polyhedron."""
    planes: Sequence[Plane]

    # noinspection PyMissingConstructor
    def __init__(
        self,
        bbox_min: FrozenVec, bbox_max: FrozenVec,
        planes: Sequence[Plane],
        *,
        contents: CollideType = CollideType.SOLID,
        tags: Iterable[str] | str = frozenset(),
        name: str = '',
    ) -> None:
        self.__attrs_init__(
            round(bbox_min.x), round(bbox_min.y), round(bbox_min.z),
            round(bbox_max.x), round(bbox_max.y), round(bbox_max.z),
            contents,
            name,
            frozenset([tags] if isinstance(tags, str) else tags),
            planes,
        )

    @classmethod
    def from_ent(cls, ent: Entity) -> Iterator[Self]:
        """Parse keyvalues on a VMF entity. One volume is produced for each brush."""
        coll = CollideType.from_ent_kvs(ent)
        tags = frozenset(ent['tags'].split())

        for solid in ent.solids:
            mins, maxes = solid.get_bbox()
            yield cls(mins.freeze(), maxes.freeze(), contents=coll, tags=tags, planes=[
                Plane(norm := face.normal().freeze(), FrozenVec.dot(norm, face.planes[0]))
                for face in solid.sides
            ])

    def as_ent(self, vmf: VMF) -> Entity:
        """Convert back into an entity."""
        ent = self._to_kvs(vmf, 'bee2_collision_volume')
        solid = Solid(vmf)
        ent.solids.append(solid)

        for plane in self.planes:
            # Use this to pick two arbitrary planes for the UVs.
            orient = Matrix.from_angle(plane.normal.to_angle())
            point = plane.point.thaw()
            u = -orient.left()
            v = -orient.up()
            solid.sides.append(Side(
                vmf,
                [
                    point - 16 * u,
                    point,
                    point + 16 * v,
                ],
                mat=consts.Tools.CLIP,
                uaxis=UVAxis(*u),
                vaxis=UVAxis(*v),
            ))

        return ent

    def with_attrs(
        self, *,
        name: str | None = None,
        contents: CollideType | None = None,
        tags: Iterable[str] | str | None = None,
    ) -> Volume:
        """Return a new volume with the name, contents or tags changed."""
        return Volume(
            self.mins.freeze(), self.maxes.freeze(),
            self.planes,
            contents=contents if contents is not None else self.contents,
            name=name if name is not None else self.name,
            tags=tags if tags is not None else self.tags,
        )

    def intersect(self, other: BBox) -> BBox | None:
        raise NotImplementedError("Intersections of volumes!")

    def __matmul__(self, other: AnyAngle | AnyMatrix) -> Volume:
        """Rotate the bounding box by an angle."""
        matrix, mins, maxs = self._rotate_bbox(other)
        return Volume(
            mins.freeze(), maxs.freeze(),
            planes=[
                Plane(plane.normal @ matrix, plane.distance)
                for plane in self.planes
            ],
            contents=self.contents,
            tags=self.tags,
            name=self.name,
        )

    def __add__(self, other: Vec | FrozenVec | tuple[float, float, float]) -> Volume:
        """Shift the bounding box forwards by this amount."""
        if isinstance(other, BBox):  # Special-case error.
            raise TypeError('Two bounding boxes cannot be added!')
        other = FrozenVec(other)

        planes = [
            Plane(
                plane.normal,
                plane.distance + Vec.dot(plane.normal, other)
            )
            for plane in self.planes
        ]

        return Volume(
            self.mins.freeze() + other,
            self.maxes.freeze() + other,
            planes=planes,
            contents=self.contents,
            tags=self.tags,
            name=self.name,
        )

    def __sub__(self, other: Vec | FrozenVec | tuple[float, float, float]) -> Volume:
        """Shift the bounding box backwards by this amount."""
        if isinstance(other, BBox):  # Special-case error.
            raise TypeError('Two bounding boxes cannot be subtracted!')
        other = FrozenVec(other)

        planes = [
            Plane(
                plane.normal,
                plane.distance - Vec.dot(plane.normal, other),
            )
            for plane in self.planes
        ]

        return Volume(
            self.mins.freeze() - other,
            self.maxes.freeze() - other,
            planes=planes,
            contents=self.contents,
            tags=self.tags,
            name=self.name,
        )
