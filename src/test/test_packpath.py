"""Test utils.PackagePath."""
from utils import PackagePath, obj_id


def test_basic() -> None:
    """Test the constructor."""
    path = PackagePath(obj_id("BEE2_CLEAN"), "items/EditorItems.txt")
    assert path.package == "BEE2_CLEAN"
    assert path.path == "items/EditorItems.txt"

    assert path == PackagePath(obj_id("bee2_CLean"), "items/EditorItems.txt")
    assert path == "BEE2_CLEAN:items/EditorItems.txt"

    assert str(path) == "BEE2_CLEAN:items/EditorItems.txt"
    assert repr(path) == "PackagePath('BEE2_CLEAN', 'items/EditorItems.txt')"
    assert hash(path) == hash(("BEE2_CLEAN", "items/EditorItems.txt"))

    path = PackagePath(obj_id("1950"), "another\\path.bin")
    assert path.package == "1950"
    assert path.path == "another/path.bin"


def test_parse() -> None:
    """Test parsing strings."""
    assert PackagePath.parse('blah.html', obj_id('DEFAULT')) == PackagePath(obj_id('DEFAULT'), 'blah.html')
    path = PackagePath(obj_id('SOME_PACKAGE'), 'item/blah.txt')
    assert PackagePath.parse(path, obj_id('another')) is path

    path = PackagePath.parse('package:path:value/text.txt', obj_id('default'))
    assert path == PackagePath(obj_id('package'), 'path:value/text.txt')


def test_methods() -> None:
    """Test some methods."""
    pak = obj_id("some_package")

    path = PackagePath(pak, "folder/subfolder\\/").child("value.txt")
    assert path == PackagePath(pak, "folder/subfolder/value.txt")

    path = PackagePath(pak, "folder/value.txt").in_folder("parent\\/")
    assert path == PackagePath(pak, "parent/folder/value.txt")
