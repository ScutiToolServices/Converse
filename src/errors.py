"""Stable, coded failures. Messages are safe to show a user: no paths, no URLs, no upstream text."""


class ConverseError(Exception):
    code = "converse_error"


class NotConnected(ConverseError):
    code = "not_connected"


class StepFailed(ConverseError):
    code = "step_failed"


class IdentityRequired(ConverseError):
    code = "identity_required"
