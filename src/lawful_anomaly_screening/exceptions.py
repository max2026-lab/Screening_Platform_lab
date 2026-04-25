class LawfulAnomalyScreeningError(Exception):
    """Base error for the scaffold."""


class LegalGateError(LawfulAnomalyScreeningError):
    """Raised when analysis is blocked by the legal gate."""


class SourceError(LawfulAnomalyScreeningError):
    """Raised when a source endpoint or provider operation fails."""


class ReviewDecisionError(LawfulAnomalyScreeningError):
    """Raised when a review decision is invalid."""


class ReviewStateError(LawfulAnomalyScreeningError):
    """Raised when a review state transition is invalid."""


class ExportPolicyError(LawfulAnomalyScreeningError):
    """Raised when export precision rules are violated."""


class PaidFlowError(LawfulAnomalyScreeningError):
    """Base error for paid archive scaffolding."""


class PaidQuoteEligibilityError(PaidFlowError):
    """Raised when a candidate cannot enter the paid quote flow."""


class PaidQuoteStateError(PaidFlowError):
    """Raised when a paid quote state transition is invalid."""


class PaidOrderStateError(PaidFlowError):
    """Raised when a paid order state transition is invalid."""
