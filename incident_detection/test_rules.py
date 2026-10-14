import unittest

from incident_detection.models import LogEntry
from incident_detection.rules import ImpactRule, VolumeRule
from incident_detection.window import MerchantWindow


def window_with(failures, successes):
    window = MerchantWindow(30)
    window.add(LogEntry(0, "m1", 500, failures))
    window.add(LogEntry(0, "m1", 200, successes))
    return window


class VolumeRuleTest(unittest.TestCase):
    def test_threshold_is_inclusive(self):
        self.assertFalse(VolumeRule(5).is_met(window_with(4, 0), 500))
        self.assertTrue(VolumeRule(5).is_met(window_with(5, 0), 500))


class ImpactRuleTest(unittest.TestCase):
    def test_threshold_is_exclusive(self):
        self.assertFalse(ImpactRule(1).is_met(window_with(6, 600), 500))
        self.assertTrue(ImpactRule(1).is_met(window_with(6, 599), 500))

    def test_no_successes_is_full_impact(self):
        self.assertTrue(ImpactRule(1).is_met(window_with(1, 0), 500))


class CompositionTest(unittest.TestCase):
    def test_and_requires_both(self):
        rule = VolumeRule(5) & ImpactRule(1)
        self.assertFalse(rule.is_met(window_with(4, 0), 500))
        self.assertFalse(rule.is_met(window_with(6, 600), 500))
        self.assertTrue(rule.is_met(window_with(6, 599), 500))

    def test_or_requires_either(self):
        rule = VolumeRule(100) | ImpactRule(1)
        self.assertTrue(rule.is_met(window_with(6, 0), 500))
        self.assertFalse(rule.is_met(window_with(6, 600), 500))

    def test_invert_negates(self):
        self.assertTrue((~VolumeRule(5)).is_met(window_with(4, 0), 500))


if __name__ == "__main__":
    unittest.main()
