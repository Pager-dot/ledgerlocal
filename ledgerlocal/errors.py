class LedgerLocalError(Exception):
    """Base class for every error this package raises on purpose."""


class ConfigError(LedgerLocalError):
    pass


class RenderError(LedgerLocalError):
    """A document could not be turned into something a model can read."""


class ProviderError(LedgerLocalError):
    """The local inference server was unreachable or answered unusably."""


class ExtractionError(LedgerLocalError):
    """The model answered, but not with a document we could validate."""


class OfflineViolation(LedgerLocalError):
    """Something tried to open a socket outside the local allowlist."""
