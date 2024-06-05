"""Test gameinfo conversion."""
import shutil
from pathlib import Path

import pytest
from pytest_regressions.file_regression import FileRegressionFixture

from exporting import gameinfo


@pytest.mark.parametrize('source', ['old_path', 'new_path', 'vanilla'])
@pytest.mark.parametrize('should_mod', [False, True], ids=['unmod', 'mod'])
def test_conversions(
    source: str, should_mod: bool,
    tmp_path: Path,
    datadir: Path,
    file_regression: FileRegressionFixture,
) -> None:
    """Test all conversion combinations with sample files."""
    ginfo_path = tmp_path / 'gameinfo.txt'
    shutil.copy2(datadir / f'ginfo_{source}.txt', ginfo_path)

    gameinfo.edit_gameinfo(str(ginfo_path), should_mod)

    file_regression.check(
        ginfo_path.read_bytes(),
        binary=True,
    )
