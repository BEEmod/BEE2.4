"""Test parsing voiceline configurations."""
import re

import pytest
from srctools import Keyvalues

import utils
from quote_pack import Line


PAK_ID = utils.obj_id('SAMPLE_QUOTES')


def test_parse_line_common() -> None:
    """Check the basic common options."""
    line = Line.parse(PAK_ID, Keyvalues('Line', [
        Keyvalues('id', 'some_line'),
        Keyvalues('trans', 'Actor1: Hi'),
        Keyvalues('trans', '[no actor here]'),
        Keyvalues('onlyonce', '0'),
        Keyvalues('atomic', '1'),
        Keyvalues('cc_emit', 'test'),
        Keyvalues('bullseye', [
            Keyvalues('', 'another'),
        ]),
        Keyvalues('snd', 'snd_1.wav'),

        Keyvalues('setstylevar', 'styleVar1'),
        Keyvalues('bullseye', '@bully'),
        Keyvalues('setStyleVar', 'catapult'),

        Keyvalues('snd', [
            Keyvalues('ignore', 'snd_2.wav'),
            Keyvalues('', 'snd_3.wav'),
        ]),
        Keyvalues('snd', 'snd_4.wav'),
    ]), False)
    assert line.id == 'some_line'
    assert line.name.namespace == PAK_ID
    assert line.name.token == ''
    assert line.set_stylevars == {'catapult', 'stylevar1'}
    assert line.bullseyes == {'@bully', 'another'}
    assert line.sounds == ['snd_1.wav', 'snd_2.wav', 'snd_3.wav', 'snd_4.wav']

    assert line.transcript[0][0] == 'Actor1'
    assert str(line.transcript[0][1]) == ': "Hi"'
    assert line.transcript[1][0] == ''
    assert str(line.transcript[1][1]) == '"[no actor here]"'


def test_parse_line_no_id() -> None:
    """Lines must have either an ID or name defined."""
    with pytest.raises(ValueError, match=re.escape("no ID or name defined")):
        Line.parse(PAK_ID, Keyvalues('Line', []), False)
