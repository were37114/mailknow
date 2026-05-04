"""Entity module - identity management and alignment."""

from .aligner import AlignmentResult, EntityAligner, MergeReason, MergeRecord

__all__ = [
    "EntityAligner",
    "MergeReason",
    "MergeRecord",
    "AlignmentResult",
]
