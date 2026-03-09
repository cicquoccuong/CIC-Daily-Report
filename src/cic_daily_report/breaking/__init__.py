"""Breaking News Intelligence — event detection, dedup, classification, content."""

from cic_daily_report.breaking.content_generator import BreakingContent, generate_breaking_content
from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager, compute_hash
from cic_daily_report.breaking.event_detector import (
    BreakingEvent,
    DetectionConfig,
    detect_breaking_events,
)
from cic_daily_report.breaking.severity_classifier import (
    ClassificationConfig,
    ClassifiedEvent,
    classify_batch,
    classify_event,
)

__all__ = [
    "BreakingContent",
    "BreakingEvent",
    "ClassificationConfig",
    "ClassifiedEvent",
    "DedupEntry",
    "DedupManager",
    "DetectionConfig",
    "classify_batch",
    "classify_event",
    "compute_hash",
    "detect_breaking_events",
    "generate_breaking_content",
]
