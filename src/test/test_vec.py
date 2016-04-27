"""Test the Vector object."""
import sys

import unittest
import operator as op

from utils import Vec, Vec_tuple

VALID_NUMS = [
    1, 1.5, 1.2, 0.2827, 2346.45,
]
VALID_NUMS += [-x for x in VALID_NUMS]

VALID_ZERONUMS = VALID_NUMS + [0, -0]


def iter_vec(nums):
    for x in nums:
        for y in nums:
            for z in nums:
                yield x, y, z


def assertVec(vec, x, y, z, msg=''):
    """Asserts that Vec is equal to (x,y,z)."""
    # Trickery to get the calling method's self variable..
    self = sys._getframe(1).f_locals['self']

    msg = '{!r} != ({}, {}, {}) [{}]'.format(vec, x, y, z, msg)
    self.assertAlmostEqual(vec.x, x, msg=msg)
    self.assertAlmostEqual(vec.y, y, msg=msg)
    self.assertAlmostEqual(vec.z, z, msg=msg)


class VecTest(unittest.TestCase):
    def test_construction(self):
        """Check various parts of the construction."""
        for x, y, z in iter_vec(VALID_ZERONUMS):
            assertVec(Vec(x, y, z), x, y, z)
            assertVec(Vec(x, y), x, y, 0)
            assertVec(Vec(x), x, 0, 0)

            assertVec(Vec([x, y, z]), x, y, z)
            assertVec(Vec([x, y], z=z), x, y, z)
            assertVec(Vec([x], y=y, z=z), x, y, z)
            assertVec(Vec([x]), x, 0, 0)
            assertVec(Vec([x, y]), x, y, 0)
            assertVec(Vec([x, y, z]), x, y, z)

    def test_scalar(self):
        """Check that Vec() + 5, -5, etc does the correct thing.

        For +, -, *, /, // and % calling with a scalar should perform the
        operation on x, y, and z
        """
        operators = [
            ('+', op.add, op.iadd, VALID_ZERONUMS),
            ('-', op.sub, op.isub, VALID_ZERONUMS),
            ('*', op.mul, op.imul, VALID_ZERONUMS),
            ('//', op.floordiv, op.ifloordiv, VALID_NUMS),
            ('/', op.truediv, op.itruediv, VALID_NUMS),
            ('%', op.mod, op.imod, VALID_NUMS),
        ]

        for op_name, op_func, op_ifunc, domain in operators:
            for x, y, z in iter_vec(domain):
                for num in domain:
                    targ = Vec(x, y, z)
                    assertVec(
                        op_func(targ, num),
                        op_func(x, num),
                        op_func(y, num),
                        op_func(z, num),
                        'Forward ' + op_name,
                    )
                    assertVec(
                        op_func(num, targ),
                        op_func(num, x),
                        op_func(num, y),
                        op_func(num, z),
                        'Reversed ' + op_name,
                    )

                    # Ensure they haven't modified the original
                    assertVec(targ, x, y, z)

                    assertVec(
                        op_ifunc(num, targ),
                        op_func(num, x),
                        op_func(num, y),
                        op_func(num, z),
                        'Reversed ' + op_name,
                    )
    def test_scalar_zero(self):
        """Check zero behaviour with division ops."""
        for x, y, z in iter_vec(VALID_NUMS):
            assertVec(0 / Vec(x, y, z), 0, 0, 0)
            assertVec(0 // Vec(x, y, z), 0, 0, 0)
            assertVec(0 % Vec(x, y, z), 0, 0, 0)

    def test_eq(self):
        for x, y, z in iter_vec(VALID_ZERONUMS):
            test = Vec(x, y, z)
            self.assertEqual(test, test)
            self.assertEqual(test, Vec_tuple(x, y, z))
            self.assertEqual(test, (x, y, z))
            self.assertEqual(test, test.mag())

if __name__ == '__main__':
    unittest.main()