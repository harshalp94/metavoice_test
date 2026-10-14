from abc import ABC, abstractmethod


class AlertRule(ABC):
    """A condition on a merchant's window for one error status code.

    Rules compose with `&`, `|` and `~`, e.g. `VolumeRule(5) & ImpactRule(1)`.
    """

    @abstractmethod
    def is_met(self, window, status_code):
        """Return True if the condition holds for `status_code` in `window`."""

    def __and__(self, other):
        return AllOf(self, other)

    def __or__(self, other):
        return AnyOf(self, other)

    def __invert__(self):
        return Not(self)


class VolumeRule(AlertRule):
    """At least `min_failures` occurrences of the status code."""

    def __init__(self, min_failures):
        self.min_failures = min_failures

    def is_met(self, window, status_code):
        return window.count(status_code) >= self.min_failures


class ImpactRule(AlertRule):
    """Failures are more than `percent`% of the merchant's successful volume."""

    def __init__(self, percent):
        self.percent = percent

    def is_met(self, window, status_code):
        return window.count(status_code) * 100 > window.success_count * self.percent


class AllOf(AlertRule):
    def __init__(self, *rules):
        self.rules = rules

    def is_met(self, window, status_code):
        return all(rule.is_met(window, status_code) for rule in self.rules)


class AnyOf(AlertRule):
    def __init__(self, *rules):
        self.rules = rules

    def is_met(self, window, status_code):
        return any(rule.is_met(window, status_code) for rule in self.rules)


class Not(AlertRule):
    def __init__(self, rule):
        self.rule = rule

    def is_met(self, window, status_code):
        return not self.rule.is_met(window, status_code)
