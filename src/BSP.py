"""Read and write lumps in Source BSP files.

"""
import struct

from enum import Enum

P2_BSP_VERSION = 21  # The BSP version used in Portal 2.
BSP_MAGIC = b'VBSP'  # All BSP files start with this


def get_struct(file, format):
    """Get a structure from a file."""
    length = struct.calcsize(format)
    data = file.read(length)
    return struct.unpack_from(format, data)


class BSP_LUMPS(Enum):
    """All the lumps in a BSP file.

    The values represent the order lumps appear in the index.
    """
    ENTITIES = 0
    PLANES = 1
    TEXDATA = 2
    VERTEXES = 3
    VISIBILITY = 4
    NODES = 5
    TEXINFO = 6
    FACES = 7
    LIGHTING = 8
    OCCLUSION = 9
    LEAFS = 10
    FACEIDS = 11
    EDGES = 12
    SURFEDGES = 13
    MODELS = 14
    WORLDLIGHTS = 15
    LEAFFACES = 16
    LEAFBRUSHES = 17
    BRUSHES = 18
    BRUSHSIDES = 19
    AREAS = 20
    AREAPORTALS = 21

    PORTALS = 22
    UNUSED0 = 22
    PROPCOLLISION = 22

    CLUSTERS = 23
    UNUSED1 = 23
    PROPHULLS = 23

    PORTALVERTS = 24
    UNUSED2 = 24
    PROPHULLVERTS = 24

    CLUSTERPORTALS = 25
    UNUSED3 = 25
    PROPTRIS = 25

    DISPINFO = 26
    ORIGINALFACES = 27
    PHYSDISP = 28
    PHYSCOLLIDE = 29
    VERTNORMALS = 30
    VERTNORMALINDICES = 31
    DISP_LIGHTMAP_ALPHAS = 32
    DISP_VERTS = 33
    DISP_LIGHTMAP_SAMPLE_POSITIONS = 34
    GAME_LUMP = 35
    LEAFWATERDATA = 36
    PRIMITIVES = 37
    PRIMVERTS = 38
    PRIMINDICES = 39
    PAKFILE = 40
    CLIPPORTALVERTS = 41
    CUBEMAPS = 42
    TEXDATA_STRING_DATA = 43
    TEXDATA_STRING_TABLE = 44
    OVERLAYS = 45
    LEAFMINDISTTOWATER = 46
    FACE_MACRO_TEXTURE_INFO = 47
    DISP_TRIS = 48
    PHYSCOLLIDESURFACE = 49
    PROP_BLOB = 49
    WATEROVERLAYS = 50

    LIGHTMAPPAGES = 51
    LEAF_AMBIENT_INDEX_HDR = 51

    LIGHTMAPPAGEINFOS = 52
    LEAF_AMBIENT_INDEX = 52
    LIGHTING_HDR = 53
    WORLDLIGHTS_HDR = 54
    LEAF_AMBIENT_LIGHTING_HDR = 55
    LEAF_AMBIENT_LIGHTING = 56
    XZIPPAKFILE = 57
    FACES_HDR = 58
    MAP_FLAGS = 59
    OVERLAY_FADES = 60
    OVERLAY_SYSTEM_LEVELS = 61
    PHYSLEVEL = 62
    DISP_MULTIBLEND = 63

LUMP_COUNT = max(lump.value for lump in BSP_LUMPS) + 1  # 64 normally


class BSP:
    """A BSP file."""
    def __init__(self, filename):
        self.filename = filename
        self.map_revision = -1  # The map's revision count
        self.lumps = {}
        self.header_off = 0

    def read_header(self):
        """Read through the BSP header to find the lumps.

        This allows locating any data in the BSP.
        """
        with open(self.filename, mode='br') as file:
            # BSP files start with 'VBSP', then a version number.
            magic_name, bsp_version = get_struct(file, '4si')
            assert magic_name == BSP_MAGIC, 'Not a BSP file!'

            assert bsp_version == P2_BSP_VERSION, 'Non-Portal 2 BSP!'

            # Read the index describing each BSP lump.
            for index in range(LUMP_COUNT):
                lump = Lump.from_bytes(index, file)
                self.lumps[lump.type] = lump

            # Remember how big this is, so we can remake it later when needed.
            self.header_off = file.tell()

    def get_lump(self, lump):
        """Read a lump from the BSP."""
        if isinstance(lump, BSP_LUMPS):
            lump = self.lumps[lump]
        with open(self.filename, 'rb') as file:
            file.seek(lump.offset)
            return file.read(lump.length)

    def replace_lump(self, new_name, lump, new_data: bytes):
        """Write out the BSP file, replacing a lump with the given bytes.

        """
        if isinstance(lump, BSP_LUMPS):
            lump = self.lumps[lump]
        with open(self.filename, 'rb') as file:
            data = file.read()

        before_lump = data[self.header_off:lump.offset]
        after_lump = data[lump.offset + lump.length:]
        del data

        # Adjust the length to match the new data block.
        lump.length = len(new_data)

        with open(new_name, 'wb') as file:
            self.write_header(file)
            file.write(before_lump)
            file.write(new_data)
            file.write(after_lump)

    def write_header(self, file):
        """Write the BSP file header into the given file."""
        file.write(BSP_MAGIC)
        file.write(struct.pack('i', P2_BSP_VERSION))
        for lump_name in BSP_LUMPS:
            # Write each header
            lump = self.lumps[lump_name]
            file.write(lump.as_bytes())
        # The map revision would follow, but we never change that value!


class Lump:
    """Represents a lump header in a BSP file.

    These indicate the location and size of each component.
    """
    def __init__(self, index, offset, length, version, ident):
        self.type = BSP_LUMPS(index)
        self.offset = offset
        self.length = length
        self.version = version
        self.ident = [int(x) for x in ident]

    @classmethod
    def from_bytes(cls, index, file):
        """Decode this header from the file."""
        offset, length, version, ident = get_struct(
            file,
            # 4 ints and a 4-long char array
            '<3i4s',
        )
        return cls(
            index=index,
            offset=offset,
            length=length,
            version=version,
            ident=ident,
        )

    def as_bytes(self):
        """Get the binary version of this lump header."""
        return struct.pack(
            '<3i4s',
            self.offset,
            self.length,
            self.version,
            bytes(self.ident),
        )

    def __len__(self):
        return self.length

    def __repr__(self):
        return (
            'Lump({s.type}, {s.offset}, '
            '{s.length}, {s.version}, {s.ident})'.format(
                s=self
            )
        )


if __name__ == '__main__':
    from zipfile import ZipFile
    from io import BytesIO
    test_file = BSP(
        r'F:\SteamLibrary\Steam'
        r'Apps\common\Portal 2\portal2_'
        r'dlc2\maps\sp_a2_crushed_gel.bsp'
    )
    test_file.read_header()
    print('Read header')

    zip_data = BytesIO()
    zip_data.write(test_file.get_lump(BSP_LUMPS.PAKFILE))
    zipfile = ZipFile(zip_data, mode='a')
    with zipfile:
        zipfile.testzip()
        print('Read zip')
        zipfile.write(
            r'F:\SteamLibrary\SteamApps\common\Portal 2\bee2_'
            r'dev\scripts\vscripts\BEE2\video_splitter_rand.nut',
            arcname=r'scripts\vscripts\BEE2\video_splitter_rand.nut',
        )
        print('Added file')
    with open(r'C:\packfile.zip', 'wb') as zip:
        zip.write(zip_data.getvalue())

    test_file.replace_lump(
        r'C:\new_crushed_gel.bsp',
        BSP_LUMPS.PAKFILE,
        zip_data.getvalue(),
    )