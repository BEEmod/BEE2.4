"""Test functions in utils."""
import unittest

import utils


class FalseObject:
    def __bool__(self):
        return False


class TrueObject:
    def __bool__(self):
        return True

true_vals = [1, 1.0, True, 'test', [2], (-1, ), TrueObject(), object()]
false_vals = [0, 0.0, False, '', [], (), FalseObject()]

ints = [
    ('0', 0),
    ('-0', -0),
    ('1', 1),
    ('12352343783', 12352343783),
    ('24', 24),
    ('-4784', -4784),
    ('28', 28),
    (1, 1),
    (-2, -2),
    (3783738378, 3783738378),
    (-23527, -23527),
]

floats = [
    ('0.0', 0.0),
    ('-0.0', -0.0),
    ('-4.5', -4.5),
    ('4.5', 4.5),
    ('1.2', 1.2),
    ('12352343783.189', 12352343783.189),
    ('24.278', 24.278),
    ('-4784.214', -4784.214),
    ('28.32', 28.32),
    (1.35, 1.35),
    (-2.26767, -2.26767),
    (338378.3246, 338378.234),
    (-23527.9573, -23527.9573),
]

false_strings = ['0', 'false', 'no', 'faLse', 'False', 'No', 'NO', 'nO']
true_strings = ['1', 'true', 'yes', 'True', 'trUe', 'Yes', 'yEs', 'yeS']

non_ints = ['-23894.0', '', 'hello', '5j', '6.2', '0.2', '6.9', None, object()]

def_vals = [
    1, 0, True, False, None, object(),
    TrueObject(), FalseObject(), 456.9,
    -4758.97
]


class TestConvFunc(unittest.TestCase):
    def test_bool_as_int(self):
        for val in true_vals:
            self.assertEqual(utils.bool_as_int(val), '1', repr(val))
        for val in false_vals:
            self.assertEqual(utils.bool_as_int(val), '0', repr(val))

    def test_conv_int(self):
        for string, result in ints:
            self.assertEqual(utils.conv_int(string), result)

        # Check that float values fail
        marker = object()
        for string, result in floats:
            if isinstance(string, str): # We don't want to check float-rounding
                self.assertIs(
                    utils.conv_int(string, marker),
                    marker,
                    msg=string,
                )

        for string in non_ints:
            self.assertEqual(utils.conv_int(string), 0)
            for default in def_vals:
                # Check all default values pass through unchanged
                self.assertIs(utils.conv_int(string, default), default)

    def test_conv_bool(self):
        for val in true_strings:
            self.assertTrue(utils.conv_bool(val))
        for val in false_strings:
            self.assertFalse(utils.conv_bool(val))

        # Check that bools pass through
        self.assertTrue(utils.conv_bool(True))
        self.assertFalse(utils.conv_bool(False))

        # None passes through the default
        for val in def_vals:
            self.assertIs(utils.conv_bool(None, val), val)

    def test_conv_float(self):
        # Float should convert integers too
        for string, result in ints:
            self.assertEqual(utils.conv_float(string), float(result))
            self.assertEqual(utils.conv_float(string), result)


if __name__ == '__main__':
    unittest.main()
