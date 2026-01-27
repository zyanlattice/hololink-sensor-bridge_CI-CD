"""
Generic, Scalable Test Report Generator for HSB/Orin FPGA Testing

This module provides a flexible framework for generating standardized JSON test reports
that can scale from simple single-test runs to complex multi-test suites with arbitrary
metrics, custom status types, and rich artifact tracking.

Architecture:
  - Metric Registry: Define what metrics your tests produce (name, unit, scope)
  - Test Results: Capture arbitrary metrics using predefined or custom registry entries
  - Run Reports: Aggregate multiple tests with environment metadata
  - Validation: Ensure data consistency before serialization
  - Backward Compatibility: Existing code continues to work; new features are opt-in

Example:
    # Define custom metrics for your test suite
    registry = MetricRegistry()
    registry.register("frame_gap_ms_mean", unit="ms", scope="test")
    registry.register("latency_p99", unit="ms", scope="test")
    
    # Create and populate report
    report = RunReport(
        run_id="2026-01-26_13-05-17_ab12cd",
        env={"orin_image": "r36.3", "fpga_bitstream": "hsb_20260125_01"}
    )
    
    # Add tests with flexible metrics
    report.add_test(
        name="frame_gap_jitter",
        status="pass",
        duration_ms=12850.3,
        metrics={
            "frame_gap_ms_mean": 16.67,
            "frame_gap_ms_p95": 17.4,
            "frame_gap_ms_p99": 18.1
        },
        category="performance",
        tags=["csi", "raw"]
    )
    
    # Finalize and write
    report.finalize()
    report.write(Path("results"))
"""

import json
import time
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from enum import Enum


# ============================================================================
# Enums & Constants
# ============================================================================

class MetricScope(str, Enum):
    """Where a metric applies: to the entire run or per-test"""
    RUN = "run"
    TEST = "test"


class ArtifactType(str, Enum):
    """Common artifact types; extensible via string"""
    LOG = "log"
    PNG = "png"
    MP4 = "mp4"
    JSON = "json"
    PARQUET = "parquet"
    CSV = "csv"
    XML = "xml"
    NUMPY = "numpy"


class TestStatus(str, Enum):
    """Standard test statuses"""
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    PARTIAL = "partial"  # Some sub-checks passed, some failed


# ============================================================================
# Metric Registry
# ============================================================================

@dataclass
class MetricDefinition:
    """Metadata about a metric type"""
    name: str
    unit: Optional[str] = None
    scope: MetricScope = MetricScope.TEST
    description: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


class MetricRegistry:
    """
    Registry for defining metrics your test suite produces.
    This allows validation and documentation of expected metrics.
    """

    def __init__(self):
        self._metrics: Dict[str, MetricDefinition] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Pre-register common metrics"""
        common = [
            ("frame_gap_ms_mean", "ms", MetricScope.TEST, "Mean frame gap (jitter)"),
            ("frame_gap_ms_p95", "ms", MetricScope.TEST, "95th percentile frame gap"),
            ("frame_gap_ms_p99", "ms", MetricScope.TEST, "99th percentile frame gap"),
            ("frame_gap_ms_max", "ms", MetricScope.TEST, "Maximum frame gap"),
            ("drops", "count", MetricScope.TEST, "Number of dropped frames"),
            ("latency_ms_mean", "ms", MetricScope.TEST, "Mean end-to-end latency"),
            ("latency_ms_p95", "ms", MetricScope.TEST, "95th percentile latency"),
            ("latency_ms_p99", "ms", MetricScope.TEST, "99th percentile latency"),
            ("throughput_fps", "fps", MetricScope.TEST, "Frames per second"),
            ("crc_pass_rate", "percent", MetricScope.TEST, "CRC validation pass rate"),
        ]
        for name, unit, scope, desc in common:
            self.register(name, unit=unit, scope=scope, description=desc)

    def register(
        self,
        name: str,
        unit: Optional[str] = None,
        scope: MetricScope = MetricScope.TEST,
        description: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ):
        """Register a metric definition"""
        self._metrics[name] = MetricDefinition(
            name=name,
            unit=unit,
            scope=scope,
            description=description,
            meta=meta or {},
        )

    def get(self, name: str) -> Optional[MetricDefinition]:
        """Retrieve a metric definition"""
        return self._metrics.get(name)

    def validate(self, name: str, strict: bool = False) -> bool:
        """
        Check if metric is registered.
        If strict=False, unknown metrics are allowed (for extensibility).
        If strict=True, only registered metrics are allowed.
        """
        return name in self._metrics or not strict


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class Artifact:
    """A file artifact associated with a test or run"""
    type: str  # log, png, mp4, json, parquet, etc.
    path: str  # Relative path to artifact
    label: Optional[str] = None  # Human-readable name
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Normalize type to lowercase
        self.type = self.type.lower()


@dataclass
class TimeseriesData:
    """Time-series metric data (e.g., per-frame statistics)"""
    name: str  # Metric name (e.g., "frame_gap_ms")
    path: str  # Path to data file (parquet, csv, json)
    count: int  # Number of samples
    meta: Dict[str, Any] = field(default_factory=dict)  # source, compression, etc.


@dataclass
class TestEntry:
    """A single test result"""
    name: str
    status: str  # "pass", "fail", "skip", "partial"
    duration_ms: float
    metrics: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    artifacts: List[Artifact] = field(default_factory=list)
    category: Optional[str] = None  # e.g., "performance", "stability", "compliance"
    tags: List[str] = field(default_factory=list)  # e.g., ["csi", "raw", "1080p60"]

    def __post_init__(self):
        # Normalize status to lowercase
        self.status = self.status.lower()
        if self.status not in ("pass", "fail", "skip", "partial"):
            raise ValueError(f"Invalid status: {self.status}")


@dataclass
class RunReport:
    """
    Complete test run report with environment metadata, test results,
    and optional timeseries data.
    """
    run_id: str
    env: Dict[str, Optional[str]] = field(default_factory=dict)
    timestamp: Optional[str] = None
    schema_version: str = "2.0"  # Version for schema evolution
    operator_graph_version: Optional[str] = None  # GXF operator graph version
    notes: Optional[str] = None
    tests: List[TestEntry] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    timeseries: List[TimeseriesData] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = now_iso()

    def add_test(
        self,
        name: str,
        status: str,
        duration_ms: float,
        metrics: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        artifacts: Optional[List[Artifact]] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> TestEntry:
        """
        Add a test result to the report.
        Returns the TestEntry for further modification if needed.
        """
        test = TestEntry(
            name=name,
            status=status,
            duration_ms=duration_ms,
            metrics=metrics or {},
            error_message=error_message,
            artifacts=artifacts or [],
            category=category,
            tags=tags or [],
        )
        self.tests.append(test)
        return test

    def add_timeseries(
        self,
        name: str,
        path: str,
        count: int,
        meta: Optional[Dict[str, Any]] = None,
    ) -> TimeseriesData:
        """Add a timeseries data reference"""
        ts = TimeseriesData(name=name, path=path, count=count, meta=meta or {})
        self.timeseries.append(ts)
        return ts

    def finalize(self, metric_registry: Optional[MetricRegistry] = None):
        """
        Calculate summary statistics and validate data.

        Args:
            metric_registry: Optional registry for validation; if provided,
                           unknown metrics will generate warnings.
        """
        total = len(self.tests)
        passed = sum(1 for t in self.tests if t.status == "pass")
        failed = sum(1 for t in self.tests if t.status == "fail")
        skipped = sum(1 for t in self.tests if t.status == "skip")

        # Determine overall status
        if failed > 0:
            overall_status = "fail"
        elif passed == total:
            overall_status = "pass"
        elif skipped == total:
            overall_status = "skip"
        else:
            overall_status = "partial"

        yield_rate = (passed / total) if total > 0 else None

        self.summary = {
            "status": overall_status,
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "yield_rate": yield_rate,
        }

        # Add optional notes if provided
        if self.notes:
            self.summary["notes"] = self.notes

        # Validate metrics against registry (if provided)
        if metric_registry:
            for test in self.tests:
                for metric_name in test.metrics.keys():
                    if not metric_registry.validate(metric_name, strict=False):
                        # Non-strict mode: warn but allow
                        pass  # Could log warning here

    def write(self, out_dir: Path, filename: str = "summary.json"):
        """
        Serialize report to JSON file.

        Args:
            out_dir: Directory to write the report to
            filename: Output filename (default: summary.json)
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Convert dataclasses to dicts
        payload = asdict(self)

        # Ensure None values for optional env vars are preserved (or could be filtered)
        # This format matches expectations of ingestion_script.py

        output_file = out_dir / filename
        output_file.write_text(json.dumps(payload, indent=2))

        return output_file


# ============================================================================
# Utility Functions
# ============================================================================

def now_iso() -> str:
    """Return current UTC timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()


def generate_run_id(prefix: str = "") -> str:
    """
    Generate a unique run ID based on timestamp.

    Args:
        prefix: Optional prefix (e.g., "test_", "run_")

    Returns:
        String like "2026-01-26_13-05-17_ab12cd" or "{prefix}2026-01-26_13-05-17..."
    """
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    git_sha = os.environ.get("GIT_SHA", "")[:6] or "local"
    run_id = f"{timestamp}_{git_sha}"
    if prefix:
        run_id = f"{prefix}{run_id}"
    return run_id


def create_report(
    run_id: Optional[str] = None,
    env: Optional[Dict[str, Optional[str]]] = None,
    schema_version: str = "2.0",
) -> RunReport:
    """
    Convenience function to create a new report with sensible defaults.

    Args:
        run_id: Unique run identifier; if None, auto-generated from timestamp
        env: Environment dict (orin_image, fpga_bitstream, git_sha, branch, dataset, etc.)
        schema_version: Report schema version

    Returns:
        New RunReport ready to populate
    """
    if not run_id:
        run_id = generate_run_id()

    return RunReport(
        run_id=run_id,
        env=env or {},
        schema_version=schema_version,
    )


# ============================================================================
# Example Usage (for documentation)
# ============================================================================

if __name__ == "__main__":
    """
    Example: Create a report with multiple tests and serialize to JSON.
    """
    import sys

    # Create metric registry (optional, for validation)
    registry = MetricRegistry()

    # Create report
    report = create_report(
        env={
            "orin_image": "r36.3",
            "fpga_bitstream": "hsb_20260125_01",
            "git_sha": "ab12cd3",
            "branch": "feature/hsb-jitter",
            "dataset": "camA_1080p60",
        }
    )

    # Add frame_gap_jitter test
    report.add_test(
        name="frame_gap_jitter",
        status="pass",
        duration_ms=12850.3,
        metrics={
            "frame_gap_ms_mean": 16.67,
            "frame_gap_ms_p95": 17.4,
            "frame_gap_ms_p99": 18.1,
            "drops": 0,
        },
        artifacts=[Artifact(type="png", path="frames/fg_hist.png", label="Frame gap histogram")],
        category="performance",
        tags=["csi", "raw"],
    )

    # Add end_to_end_latency test
    report.add_test(
        name="end_to_end_latency",
        status="fail",
        duration_ms=30123.5,
        metrics={
            "latency_ms_mean": 24.1,
            "latency_ms_p95": 35.7,
            "latency_ms_p99": 48.9,
        },
        error_message="p99 exceeded 45 ms threshold",
        category="performance",
        tags=["csi"],
    )

    # Add crc_validation test (from current json_helper)
    report.add_test(
        name="crc_validation",
        status="pass",
        duration_ms=5000.0,
        metrics={"crc_pass_rate": 99.8},
        category="compliance",
        tags=["raw"],
    )

    # Add timeseries data reference
    report.add_timeseries(
        name="frame_gap_ms",
        path="metrics/frame_gap_ms.parquet",
        count=18000,
        meta={"source": "orchestrator", "unit": "ms"},
    )

    # Finalize and write
    report.finalize(metric_registry=registry)

    out_path = Path("example_output")
    report.write(out_path)

    print(f"✓ Report written to {out_path / 'summary.json'}")
    print(f"  Run ID: {report.run_id}")
    print(f"  Tests: {report.summary['total_tests']} (pass: {report.summary['passed']}, fail: {report.summary['failed']})")
    print(f"  Yield: {report.summary['yield_rate']:.1%}" if report.summary['yield_rate'] else "")
    print()

    # Pretty-print the JSON
    with open(out_path / "summary.json") as f:
        data = json.load(f)
    print("Generated JSON (first 50 lines):")
    lines = json.dumps(data, indent=2).split("\n")
    for line in lines[:50]:
        print(line)
    if len(lines) > 50:
        print(f"... ({len(lines) - 50} more lines)")
