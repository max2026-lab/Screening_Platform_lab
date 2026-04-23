class LawfulAnomalyScreeningError(Exception):
    """Base error for the scaffold."""


class LegalGateError(LawfulAnomalyScreeningError):
    """Raised when analysis is blocked by the legal gate."""
