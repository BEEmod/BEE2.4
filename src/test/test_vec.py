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


class VecTest(unittest.TestCase):


    def assertVec(self, vec, x, y, z, msg=''):
        """Asserts that Vec is equal to (x,y,z)."""
        _skip_me = True
        new_msg = '{!r} != ({}, {}, {})'.format(vec, x, y, z)
        if msg:
            new_msg += ': ' + msg

        self.assertAlmostEqual(vec.x, x, msg=new_msg)
        self.assertAlmostEqual(vec.y, y, msg=new_msg)
        self.assertAlmostEqual(vec.z, z, msg=new_msg)

class VecTest(unittest.TestCase):
    def test_construction(self):
        """Check various parts of the construction."""
        for x, y, z in iter_vec(VALID_ZERONUMS):
            self.assertVec(Vec(x, y, z), x, y, z)
            self.assertVec(Vec(x, y), x, y, 0)
            self.assertVec(Vec(x), x, 0, 0)

            self.assertVec(Vec([x, y, z]), x, y, z)
            self.assertVec(Vec([x, y], z=z), x, y, z)
            self.assertVec(Vec([x], y=y, z=z), x, y, z)
            self.assertVec(Vec([x]), x, 0, 0)
            self.assertVec(Vec([x, y]), x, y, 0)
            self.assertVec(Vec([x, y, z]), x, y, z)

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
                    self.assertVec(
                        op_func(targ, num),
                        op_func(x, num),
                        op_func(y, num),
                        op_func(z, num),
                        'Forward ' + op_name,
                    )
                    self.assertVec(
                        op_func(num, targ),
                        op_func(num, x),
                        op_func(num, y),
                        op_func(num, z),
                        'Reversed ' + op_name,
                    )

                    # Ensure they haven't modified the original
                    self.assertVec(targ, x, y, z)

                    self.assertVec(
                        op_ifunc(num, targ),
                        op_func(num, x),
                        op_func(num, y),
                        op_func(num, z),
                        'Reversed ' + op_name,
                    )
    def test_scalar_zero(self):
        """Check zero behaviour with division ops."""
        for x, y, z in iter_vec(VALID_NUMS):
            self.assertVec(0 / Vec(x, y, z), 0, 0, 0)
            self.assertVec(0 // Vec(x, y, z), 0, 0, 0)
            self.assertVec(0 % Vec(x, y, z), 0, 0, 0)

    def test_order(self):
        """Test ordering operations (>, <, <=, >=, ==)."""
        comp_ops = [op.eq, op.le, op.lt, op.ge, op.gt, op.ne]

        def test(x1, y1, z1, x2, y2, z2):
            """Check a Vec pair for incorrect comparisons."""
            vec1 = Vec(x1, y1, z1)
            vec2 = Vec(x2, y2, z2)
            for op_func in comp_ops:
                if op_func is op.ne:
                    # special-case - != uses or, not and
                    corr_result = x1 != x2 or y1 != y2 or z1 != z2
                else:
                    corr_result = op_func(x1, x2) and op_func(y1, y2) and op_func(z1, z2)
                comp = (
                    'Incorrect {{}} comparison for '
                    '({} {} {}) {} ({} {} {})'.format(
                        x1, y1, z1, op_func.__name__, x2, y2, z2
                    )
                )
                self.assertEqual(
                    op_func(vec1, vec2),
                    corr_result,
                    comp.format('Vec')
                )
                self.assertEqual(
                    op_func(vec1, Vec_tuple(x2, y2, z2)),
                    corr_result,
                    comp.format('Vec_tuple')
                )
                self.assertEqual(
                    op_func(vec1, (x2, y2, z2)),
                    corr_result,
                    comp.format('tuple')
                )
                # Bare numbers compare magnitude..
                self.assertEqual(
                    op_func(vec1, x2),
                    op_func(vec1.mag(), x2),
                    comp.format('x')
                )
                self.assertEqual(
                    op_func(vec1, y2),
                    op_func(vec1.mag(), y2),
                    comp.format('y')
                )
                self.assertEqual(
                    op_func(vec1, z2),
                    op_func(vec1.mag(), z2),
                    comp.format('z')
                )

        for num in VALID_ZERONUMS:
            for num2 in VALID_ZERONUMS:
                # Test the whole comparison, then each axis pair seperately
                test(num, num, num, num2, num2, num2)
                test(0, num, num, num2, num2, num2)
                test(num, 0, num, num, num2, num2)
                test(num, num, 0, num2, num2, num2)
                test(num, num, num, 0, num2, num2)
                test(num, num, num, num, 0, num2)
                test(num, num, num, num, num, 0)


if __name__ == '__main__':
    unittest.main()
