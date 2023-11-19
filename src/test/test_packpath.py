"""Test utils.PackagePath."""
from utils import PackagePath


def test_basic() -> None:
    """Test the constructor."""
    path = PackagePath("BEE2_CLEAN", "items/EditorItems.txt")
    assert path.package == "bee2_clean"
    assert path.path == "items/EditorItems.txt"

    assert path == PackagePath("bee2_CLean", "items/EditorItems.txt")
    assert path == "BEE2_clean:items/EditorItems.txt"

    assert str(path) == "bee2_clean:items/EditorItems.txt"
    assert repr(path) == "PackagePath('bee2_clean', 'items/EditorItems.txt')"
    assert hash(path) == hash(("bee2_clean", "items/EditorItems.txt"))

    path = PackagePath("1950","another\\path.bin")
    assert path.package == "1950"
    assert path.path == "another/path.bin"


def test_parse() -> None:
    """Test parsing strings."""
    assert PackagePath.parse('blah.html', 'DEFAULT') == PackagePath('DEFAULT', 'blah.html')
    path = PackagePath('some_package', 'item/blah.txt')
    assert PackagePath.parse(path, 'another') is path
    assert PackagePath.parse('package:path:value/text.txt', 'default') == PackagePath('package', 'path:value/text.txt')


def test_methods() -> None:
    """Test some methods."""
    path = PackagePath("some_package", "folder/subfolder").child("value.txt")
    assert path == PackagePath("some_package", "folder/subfolder/value.txt")
    path = PackagePath("some_package", "folder/value.txt").in_folder("parent")
    assert path == PackagePath("some_package", "parent/folder/value.txt")
