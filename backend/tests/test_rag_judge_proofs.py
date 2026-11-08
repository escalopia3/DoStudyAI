import unittest
from tools.grade_rag_round2_separated import grounded,critical_unit_readable


class JudgeProofTests(unittest.TestCase):
    def test_formula_blanks_cannot_pass_as_readable_reference_evidence(self):
        self.assertFalse(grounded(r'-\pi<\theta\le\pi','把满足    的称为主值'))
        self.assertFalse(grounded('','原文'))
        self.assertTrue(grounded('连续的 三要素','连续的\n三要素'))
        self.assertTrue(grounded('没有重点的连续曲线C称为简单曲线。','没有重点的连续曲线C称为简单曲线.'))
        self.assertTrue(grounded(r'$$\operatorname{Arg}z=\arg z+2k\pi$$',r'$$\operatorname{Arg}z=\arg z+2k\pi\quad(k\in Z)$$'))
        self.assertFalse(critical_unit_readable('principal_interval','把满足的称为主值'))
        self.assertTrue(critical_unit_readable('principal_interval',r'-\pi<\theta_0\le\pi'))
        self.assertFalse(critical_unit_readable('general_arguments','有无穷多个辐角，全部辐角为'))
        self.assertTrue(critical_unit_readable('general_arguments',r'\theta+2k\pi'))
        self.assertFalse(critical_unit_readable('notation','称为主值，记作'))
        self.assertTrue(critical_unit_readable('notation',r'\operatorname{Arg}z=\arg z+2k\pi'))
        self.assertFalse(critical_unit_readable('component_limits','充分必要条件是和'))


if __name__=='__main__':unittest.main()
