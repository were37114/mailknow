"""Entity module - identity management and alignment."""

from .aligner import EntityAligner, MergeReason, MergeRecord, AlignmentResult

__all__ = [
    "EntityAligner",
    "MergeReason",
    "MergeRecord",
    "AlignmentResult",
]
