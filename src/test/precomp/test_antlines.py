"""Test antline configs."""
import re

import pytest
from srctools import Keyvalues

# Ensure correct import order. TODO fix cycle
import vbsp  # noqa
from precomp.antlines import AntTex


def test_parse_ant_tex() -> None:
    """Test parsing antline texture definitions."""
    with pytest.raises(IndexError, match=r'No key "?tex"?'):
        # Material is required.
        AntTex.parse(Keyvalues('antline', [
            Keyvalues('scale', '0.25'),
            Keyvalues('static', '0'),
        ]))
    assert AntTex.parse(Keyvalues('antline', [
        Keyvalues('scale', '.375'),
        Keyvalues('static', '1'),
        Keyvalues('tex', 'anim_wp/framework/squarebeams'),
    ])) == AntTex('anim_wp/framework/squarebeams', 0.375, True)
    assert AntTex.parse(
        Keyvalues('ant', 'signage/INDICATOR/indicator_straight')
    ) == AntTex('signage/INDICATOR/indicator_straight', 0.25, False)
    assert AntTex.parse(
        Keyvalues('ant', '-1|signage/INDICATOR/indicator_straight')
    ) == AntTex('signage/INDICATOR/indicator_straight', -1.0, False)
    assert AntTex.parse(
        Keyvalues('ant', '0.5|signage/another|static')
    ) == AntTex('signage/another', 0.5, True)
    with pytest.raises(ValueError, match=re.escape('Invalid antline material config')):
        AntTex.parse(Keyvalues('invalid', '0.3|material|static|toomany'))
