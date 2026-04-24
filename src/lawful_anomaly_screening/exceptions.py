class LawfulAnomalyScreeningError(Exception):
    """Base error for the scaffold."""


class LegalGateError(LawfulAnomalyScreeningError):
    """Raised when analysis is blocked by the legal gate."""


class ReviewDecisionError(LawfulAnomalyScreeningError):
    """Raised when a review decision is invalid."""


class ReviewStateError(LawfulAnomalyScreeningError):
    """Raised when a review state transition is invalid."""


class ExportPolicyError(LawfulAnomalyScreeningError):
    """Raised when export precision rules are violated."""
