"""Test the texture application system."""
import logging

import pytest
from srctools import Keyvalues

from precomp.texturing import MaterialConf, QuarterRot


def test_rotation_parse(caplog: pytest.LogCaptureFixture) -> None:
    assert QuarterRot.parse('0') is QuarterRot.NONE
    assert QuarterRot.parse('90') is QuarterRot.CCW
    assert QuarterRot.parse('180') is QuarterRot.HALF
    assert QuarterRot.parse('270') is QuarterRot.CW

    # Modulo 360 values are allowed.
    assert QuarterRot.parse('360') is QuarterRot.NONE
    assert QuarterRot.parse('-270') is QuarterRot.CCW
    assert QuarterRot.parse('-180') is QuarterRot.HALF
    assert QuarterRot.parse('-90') is QuarterRot.CW
    assert QuarterRot.parse('810') is QuarterRot.CCW
    assert not caplog.records  # No warnings!


def test_rotation_parse_warnings(caplog: pytest.LogCaptureFixture) -> None:
    assert QuarterRot.parse('blah') is QuarterRot.NONE
    assert "Non-numeric rotation value" in caplog.text
    caplog.clear()

    assert QuarterRot.parse('12') is QuarterRot.NONE
    assert 'multiples of 90 degrees' in caplog.text
    caplog.clear()


def test_mat_parse(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValueError, match='"material"'):
        # Material is required.
        MaterialConf.parse(Keyvalues('blah', [
            Keyvalues('scale', '0.25'),
            Keyvalues('rotation', '0'),
            Keyvalues('repeat', '4'),
            Keyvalues('offset', '0 0'),
        ]))

    assert MaterialConf.parse(
        Keyvalues('name', 'tools/toolsnodraw')
    ) == MaterialConf('tools/toolsnodraw', scale=1.0, rotation=QuarterRot.NONE)
    assert MaterialConf.parse(
        Keyvalues('name', [Keyvalues('material', 'some/longer/MaTerial/with_many_chars')])
    ) == MaterialConf('some/longer/MaTerial/with_many_chars', scale=1.0, rotation=QuarterRot.NONE)
    assert MaterialConf.parse(
        Keyvalues('name', [
            Keyvalues('scale', '0.3645'),
            Keyvalues('material', 'dev/devmeasuregeneric01'),
            Keyvalues('rotation', '90'),
            Keyvalues('repeat', '4'),
            Keyvalues('offset', '8.125 -289.5')
        ])
    ) == MaterialConf(
        'dev/devmeasuregeneric01',
        off_x=8.125, off_y=-289.5, scale=0.3645,
        rotation=QuarterRot.CCW, repeat_limit=4,
    )
    assert not caplog.records


def test_mat_parse_warnings(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert MaterialConf.parse(
            Keyvalues('name', [
                Keyvalues('scale', '-0.125'),
                Keyvalues('material', 'dev/devmeasuregeneric01'),
            ])
        ) == MaterialConf('dev/devmeasuregeneric01', scale=1.0, rotation=QuarterRot.NONE)
    assert any(record.levelname == 'WARNING' for record in caplog.records)
    assert 'Material scale should be positive' in caplog.text
    caplog.clear()

    with caplog.at_level(logging.WARNING):
        assert MaterialConf.parse(
            Keyvalues('name', [
                Keyvalues('repeat', '0'),
                Keyvalues('material', 'dev/devmeasuregeneric01'),
            ])
        ) == MaterialConf('dev/devmeasuregeneric01', scale=1.0, rotation=QuarterRot.NONE, repeat_limit=1)
    assert any(record.levelname == 'WARNING' for record in caplog.records)
    assert 'Material repeat limit should be positive' in caplog.text
    caplog.clear()

    with caplog.at_level(logging.WARNING):
        assert MaterialConf.parse(
            Keyvalues('name', [
                Keyvalues('offset', 'hi'),
                Keyvalues('material', 'dev/devmeasuregeneric01'),
            ])
        ) == MaterialConf('dev/devmeasuregeneric01', scale=1.0, rotation=QuarterRot.NONE, off_x=0.0, off_y=0.0)
    assert any(record.levelname == 'WARNING' for record in caplog.records)
    assert 'Invalid offset' in caplog.text
    caplog.clear()
