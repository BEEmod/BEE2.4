"""Test the texture application system."""
import logging

import pytest
from srctools import Property

from precomp.texturing import MaterialConf, QuarterRot


def test_rotation_parse(caplog) -> None:
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


def test_rotation_parse_warnings(caplog) -> None:
    assert QuarterRot.parse('blah') is QuarterRot.NONE
    assert "Non-numeric rotation value" in caplog.text
    caplog.clear()

    assert QuarterRot.parse('12') is QuarterRot.NONE
    assert 'multiples of 90 degrees' in caplog.text
    caplog.clear()


def test_mat_parse(caplog) -> None:
    with pytest.raises(ValueError):
        # Material is required.
        MaterialConf.parse(Property('blah', [
            Property('scale', '0.25'),
            Property('rotation', '0'),
        ]))

    assert MaterialConf.parse(
        Property('name', 'tools/toolsnodraw')
    ) == MaterialConf('tools/toolsnodraw', 0.25, QuarterRot.NONE)
    assert MaterialConf.parse(
        Property('name', [Property('material', 'some/longer/MaTerial/with_many_chars')])
    ) == MaterialConf('some/longer/MaTerial/with_many_chars', 0.25, QuarterRot.NONE)
    assert MaterialConf.parse(
        Property('name', [
            Property('scale', '0.3645'),
            Property('material', 'dev/devmeasuregeneric01'),
            Property('rotation', '90'),
        ])
    ) == MaterialConf('dev/devmeasuregeneric01', 0.3645, QuarterRot.CCW)
    assert not caplog.records


def test_mat_parse_warnings(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert MaterialConf.parse(
            Property('name', [
                Property('scale', '-0.125'),
                Property('material', 'dev/devmeasuregeneric01'),
            ])
        ) == MaterialConf('dev/devmeasuregeneric01', 0.25, QuarterRot.NONE)
    assert any(record.levelname == 'WARNING' for record in caplog.records)
    caplog.clear()
