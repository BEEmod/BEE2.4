"""Test Editoritems syntax."""
from srctools import Vec
from editoritems import (
    Item, ItemClass,
    OccupiedVoxel, Coord, OccuType, DesiredFacing, FSPath, Sound, Handle, ConnSide, InstCount,
)

from app.localisation import TransToken


# Definition for a simple item, with 'exporting' open.
START_EXPORTING = '''
Item
{
    "Type"		"SOME_ITEM"
    "Editor"
    {
        "SubType"
        {
            "Name"		"instance item"
        }
    }
    "Exporting"
    {
    "TargetName"		"goo"
'''


def test_parse_goo() -> None:
    """Verify all the values in a goo item definition are correct."""
    [[item], _] = Item.parse('''
    Item
    {
        "Type"		"ITEM_GOO"
        "ItemClass"	"ItemGoo"
        "Editor"
        {
            "SubType"
            {
                "Name"		"PORTAL2_PuzzleEditor_Item_goo"
                "Model"
                {
                    "ModelName"		"goo_man.3ds"
                }
                "Model"
                {
                    "ModelName"		"goo_man_water.mdl"
                }
                "Palette"
                {
                    "Tooltip"	"PORTAL2_PuzzleEditor_Palette_goo"
                    "Image"		"palette/goo.png"
                    "Position"	"2 6 0"
                }
                "Sounds"
                {
                    "SOUND_CREATED"					"P2Editor.PlaceOther"
                    "SOUND_EDITING_ACTIVATE"		"P2Editor.ExpandOther"
                    "SOUND_EDITING_DEACTIVATE"		"P2Editor.CollapseOther"
                    "SOUND_DELETED"					"P2Editor.RemoveOther"
                }
            }
            "MovementHandle"	"HANDLE_NONE"
            "DesiredFacing"		"DESIRES_UP"
        }
        "Exporting"
        {
            "TargetName"		"goo"
            "Offset"		"64 64 64"
            "OccupiedVoxels"
            {
                "Voxel"
                {
                    "Pos"				"0 0 0"
                    "CollideType"		"COLLIDE_NOTHING"
                    "CollideAgainst"	"COLLIDE_NOTHING"
    
                    "Surface"
                    {
                        "Normal"	"0 0 1"
                    }
                }
            }
        }
    }
    ''')
    assert item.id == "ITEM_GOO"
    assert item.cls is ItemClass.GOO
    assert len(item.subtypes) == 1
    [subtype] = item.subtypes
    assert subtype.name == TransToken.from_valve("PORTAL2_PuzzleEditor_Item_goo")
    assert subtype.models == [
        # Regardless of original extension, both become .mdl since that's more
        # correct.
        FSPath("goo_man.mdl"),
        FSPath("goo_man_water.mdl"),
    ]
    assert subtype.pal_name == TransToken.from_valve("PORTAL2_PuzzleEditor_Palette_goo")
    assert subtype.pal_icon == FSPath("palette/goo.vtf")
    assert subtype.pal_pos == (2, 6)

    assert subtype.sounds == {
        Sound.CREATE: "P2Editor.PlaceOther",
        Sound.PROPS_OPEN: "P2Editor.ExpandOther",
        Sound.PROPS_CLOSE: "P2Editor.CollapseOther",
        Sound.DELETE: "P2Editor.RemoveOther",
        # Default values.
        Sound.SELECT: '',
        Sound.DESELECT: '',
    }
    assert item.handle is Handle.NONE
    assert item.facing is DesiredFacing.UP
    assert item.targetname == "goo"
    assert item.offset == Vec(64, 64, 64)

    assert len(item.occupy_voxels) == 1
    occupation: OccupiedVoxel
    [occupation] = item.occupy_voxels
    assert occupation.type is OccuType.NOTHING
    assert occupation.against is OccuType.NOTHING
    assert occupation.pos == Coord(0, 0, 0)
    assert occupation.normal == Coord(0, 0, 1)
    assert occupation.subpos is None

    # Check these are default.
    assert item.occupies_voxel is False
    assert item.copiable is True
    assert item.deletable is True
    assert item.anchor_goo is False
    assert item.anchor_barriers is False
    assert item.pseudo_handle is False
    assert item.force_input is False
    assert item.force_output is False
    assert item.antline_points == {
        ConnSide.UP: [],
        ConnSide.DOWN: [],
        ConnSide.LEFT: [],
        ConnSide.RIGHT: [],
    }
    assert item.animations == {}
    assert item.properties == {}
    assert item.invalid_surf == set()
    assert item.cust_instances == {}
    assert item.instances == []
    assert item.embed_voxels == set()
    assert item.embed_faces == []
    assert item.overlays == []
    assert item.conn_inputs == {}
    assert item.conn_outputs == {}
    assert item.conn_config is None


def test_instances() -> None:
    """Test instance definitions."""
    [[item], renderables] = Item.parse(START_EXPORTING + '''
    "Instances"
        {
        "0" // Full PeTI style definition
            {
            "Name"				"instances/p2editor/something.vmf"
            "EntityCount"		"30" 
            "BrushCount"		"28"
            "BrushSideCount"	"4892"
            }
        "another_name" "instances/more_custom.vmf"
        "bee2_second_CUst" "instances/even_more.vmf"
        "1" 
            {
            "Name" "instances/somewhere_else/item.vmf"
            }
        "5" "instances/skipping_indexes.vmf"
        "2" "instances/direct_path.vmf"
        "cust_name"
            {
            "Name" "instances/a_custom_item.vmf"
            "EntityCount"		"327" 
            "BrushCount"		"1"
            "BrushSideCount"	"32"
            }
        }
    }} // End exporting + item
    ''')
    assert len(item.instances) == 6
    assert item.instances[0] == InstCount(FSPath("instances/p2editor/something.vmf"), 30, 28, 4892)
    assert item.instances[1] == InstCount(FSPath("instances/somewhere_else/item.vmf"), 0, 0, 0)
    assert item.instances[2] == InstCount(FSPath("instances/direct_path.vmf"), 0, 0, 0)
    assert item.instances[3] == InstCount(FSPath(), 0, 0, 0)
    assert item.instances[4] == InstCount(FSPath(), 0, 0, 0)
    assert item.instances[5] == InstCount(FSPath("instances/skipping_indexes.vmf"), 0, 0, 0)
    # Counts discarded for custom items, and casefolded.
    assert item.cust_instances == {
        "another_name": FSPath("instances/more_custom.vmf"),
        "second_cust": FSPath("instances/even_more.vmf"),
        "cust_name": FSPath("instances/a_custom_item.vmf"),
    }
