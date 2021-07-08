"""Test Editoritems syntax."""
from srctools import Vec
from editoritems import (
    Item, ItemClass, OccupiedVoxel,
    CollType, DesiredFacing, FSPath, Sound, Handle, ConnSide)
import pytest


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
    assert subtype.name == "PORTAL2_PuzzleEditor_Item_goo"
    assert subtype.models == [
        # Regardless of original extension, both become .mdl since that's more
        # correct.
        FSPath("goo_man.mdl"),
        FSPath("goo_man_water.mdl"),
    ]
    assert subtype.pal_name == "PORTAL2_PuzzleEditor_Palette_goo"
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
    assert occupation.type is CollType.NOTHING
    assert occupation.against is CollType.NOTHING
    assert occupation.pos == Vec(0, 0, 0)
    assert occupation.normal == Vec(0, 0, 1)
    assert occupation.subpos is None

    # Check these are default.
    assert item.occupies_voxel is False
    assert item.copiable is True
    assert item.deletable is True
    assert item.anchor_goo is False
    assert item.anchor_barriers is False
    assert item.pseduo_handle is False
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
