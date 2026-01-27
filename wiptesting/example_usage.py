"""
Example Usage Patterns for json_helper_v2.py

This file demonstrates how to use the generic json_helper for various
test scenarios: single-test scripts, multi-test suites, custom metrics,
and future extensibility.
"""

from pathlib import Path
from wiptesting.json_helper import (
    create_report,
    MetricRegistry,
    Artifact,
    generate_run_id,
    TestStatus,
    MetricScope,
)


# =============================================================================
# PATTERN 1: Simple Single-Test Script (compatible with current usage)
# =============================================================================

def example_single_test_frame_gap():
    """
    Example: Standalone frame_gap_jitter test
    This mimics the current write_json.py pattern but using json_helper_v2
    """
    print("=" * 70)
    print("PATTERN 1: Single Test Script (Frame Gap Jitter)")
    print("=" * 70)

    # Create report (auto-generates run_id if not provided)
    report = create_report(
        env={
            "orin_image": "r36.3",
            "fpga_bitstream": "hsb_20260125_01",
            "git_sha": "ab12cd3",
            "branch": "main",
            "dataset": "camA_1080p60",
        }
    )

    # Simulate test execution
    frame_gap_mean = 16.67
    frame_gap_p95 = 17.4
    frame_gap_p99 = 18.1
    drops = 0

    # Add single test (status based on thresholds)
    status = "fail" if frame_gap_p99 > 18.0 else "pass"
    report.add_test(
        name="frame_gap_jitter",
        status=status,
        duration_ms=12000.0,
        metrics={
            "frame_gap_ms_mean": frame_gap_mean,
            "frame_gap_ms_p95": frame_gap_p95,
            "frame_gap_ms_p99": frame_gap_p99,
            "drops": drops,
        },
        artifacts=[
            Artifact(
                type="png",
                path="frames/frame_gap_histogram.png",
                label="Frame Gap Distribution"
            )
        ],
        category="performance",
        tags=["csi", "raw"],
    )

    # Add timeseries data
    report.add_timeseries(
        name="frame_gap_ms",
        path="metrics/frame_gap_ms.parquet",
        count=18000,
        meta={"source": "orchestrator", "unit": "ms"},
    )

    # Finalize and write
    report.finalize()
    out_dir = Path("example_pattern1")
    out_file = report.write(out_dir)

    print(f"✓ Report saved to {out_file}")
    print(f"  Run ID: {report.run_id}")
    print(f"  Status: {report.summary['status']}")
    print(f"  Yield: {report.summary['yield_rate']:.1%}")
    print()


# =============================================================================
# PATTERN 2: Multi-Test Suite with Mixed Results
# =============================================================================

def example_multi_test_suite():
    """
    Example: Complete test suite with multiple tests, categories, and artifacts.
    This shows how to build complex reports with the new schema.
    """
    print("=" * 70)
    print("PATTERN 2: Multi-Test Suite with Mixed Results")
    print("=" * 70)

    # Create metric registry and register custom metrics
    registry = MetricRegistry()
    registry.register(
        "packet_loss_rate",
        unit="percent",
        scope=MetricScope.TEST,
        description="Percentage of packets lost in transmission"
    )
    registry.register(
        "ptp_offset_ns",
        unit="ns",
        scope=MetricScope.TEST,
        description="PTP time offset from reference clock"
    )

    # Create report
    report = create_report(
        env={
            "orin_image": "r36.3",
            "fpga_bitstream": "hsb_20260125_01",
            "git_sha": "ab12cd3",
            "branch": "feature/ptp-sync",
            "dataset": "network_stress",
            "operator_graph_version": "1.2.3",
        }
    )
    report.notes = "Testing PTP sync improvements with high packet rate"

    # Performance tests
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
        artifacts=[
            Artifact(type="png", path="perf/frame_gap.png", label="Frame Gap Histogram"),
            Artifact(type="parquet", path="perf/frame_gaps_raw.parquet", label="Raw Frame Gaps"),
        ],
        category="performance",
        tags=["csi", "raw", "1080p60"],
    )

    report.add_test(
        name="latency_e2e",
        status="pass",
        duration_ms=30123.5,
        metrics={
            "latency_ms_mean": 22.5,
            "latency_ms_p95": 33.2,
            "latency_ms_p99": 44.8,
        },
        category="performance",
        tags=["csi"],
    )

    # Compliance tests
    report.add_test(
        name="crc_validation",
        status="pass",
        duration_ms=5000.0,
        metrics={"crc_pass_rate": 99.95},
        artifacts=[
            Artifact(type="json", path="compliance/crc_details.json", label="CRC Details"),
        ],
        category="compliance",
        tags=["raw"],
    )

    # Network tests
    report.add_test(
        name="eth_packet_loss",
        status="fail",
        duration_ms=60000.0,
        metrics={
            "packet_loss_rate": 2.3,
            "throughput_fps": 59.7,
        },
        error_message="Packet loss rate exceeded 2.0% threshold",
        category="networking",
        tags=["eth", "high-rate"],
    )

    # Sync tests
    report.add_test(
        name="ptp_synchronization",
        status="pass",
        duration_ms=120000.0,
        metrics={
            "ptp_offset_ns": 48.5,
            "ptp_jitter_ns": 12.3,
        },
        artifacts=[
            Artifact(type="parquet", path="sync/ptp_offsets.parquet", label="PTP Offsets"),
            Artifact(type="png", path="sync/ptp_trend.png", label="PTP Offset Trend"),
        ],
        category="synchronization",
        tags=["ptp", "eth"],
    )

    # Finalize with registry
    report.finalize(metric_registry=registry)
    out_dir = Path("example_pattern2")
    out_file = report.write(out_dir)

    print(f"✓ Report saved to {out_file}")
    print(f"  Run ID: {report.run_id}")
    print(f"  Tests: {report.summary['total_tests']} "
          f"(pass: {report.summary['passed']}, fail: {report.summary['failed']})")
    print(f"  Status: {report.summary['status']}")
    print(f"  Yield: {report.summary['yield_rate']:.1%}")
    print(f"  Categories: {set(t.category for t in report.tests)}")
    print()


# =============================================================================
# PATTERN 3: Custom Metrics for Future Test Types
# =============================================================================

def example_custom_metrics_power_and_memory():
    """
    Example: Add custom metrics for power consumption and memory usage.
    This demonstrates how the system scales to new test types without
    modifying json_helper.py.
    """
    print("=" * 70)
    print("PATTERN 3: Custom Metrics (Power & Memory)")
    print("=" * 70)

    # Create custom registry for resource monitoring
    registry = MetricRegistry()
    registry.register("power_avg_w", unit="W", scope=MetricScope.TEST, description="Average power consumption")
    registry.register("power_peak_w", unit="W", scope=MetricScope.TEST, description="Peak power consumption")
    registry.register("memory_peak_gb", unit="GB", scope=MetricScope.TEST, description="Peak memory usage")
    registry.register("temperature_max_c", unit="°C", scope=MetricScope.TEST, description="Maximum temperature")

    # Create report
    report = create_report(
        env={
            "orin_image": "r36.3",
            "fpga_bitstream": "hsb_20260125_01",
            "git_sha": "ab12cd3",
            "branch": "feature/power-opt",
            "dataset": "extended_runtime",
        }
    )

    # Add resource monitoring test
    report.add_test(
        name="power_and_thermal",
        status="pass",
        duration_ms=300000.0,  # 5 minutes
        metrics={
            "power_avg_w": 18.5,
            "power_peak_w": 24.3,
            "memory_peak_gb": 3.2,
            "temperature_max_c": 68.4,
        },
        artifacts=[
            Artifact(type="parquet", path="power/power_log.parquet", label="Power Trace"),
            Artifact(type="parquet", path="power/thermal_log.parquet", label="Thermal Trace"),
            Artifact(type="png", path="power/power_trend.png", label="Power Consumption Trend"),
            Artifact(type="png", path="power/thermal_trend.png", label="Temperature Trend"),
        ],
        category="resource-monitoring",
        tags=["power", "thermal", "5min-test"],
    )

    # Add stress test
    report.add_test(
        name="sustained_load_stability",
        status="pass",
        duration_ms=600000.0,  # 10 minutes
        metrics={
            "power_avg_w": 19.2,
            "power_peak_w": 25.1,
            "memory_peak_gb": 3.4,
            "temperature_max_c": 72.1,
            "frame_gap_ms_mean": 16.68,
            "drops": 0,
        },
        category="stability",
        tags=["sustained-load", "10min"],
    )

    report.finalize(metric_registry=registry)
    out_dir = Path("example_pattern3")
    out_file = report.write(out_dir)

    print(f"✓ Report saved to {out_file}")
    print(f"  Run ID: {report.run_id}")
    print(f"  Custom Metrics Used: {set(m for t in report.tests for m in t.metrics.keys())}")
    print()


# =============================================================================
# PATTERN 4: Test Factory / Parameterized Tests
# =============================================================================

class TestFactory:
    """
    Example: Factory pattern for creating common test configurations.
    This shows how to build reusable test templates.
    """

    def __init__(self, metric_registry: MetricRegistry):
        self.registry = metric_registry

    def create_frame_gap_test(
        self,
        name: str,
        duration_ms: float,
        mean_ms: float,
        p95_ms: float,
        p99_ms: float,
        drops: int,
        p99_threshold: float = 18.0,
        artifacts: list = None,
    ):
        """Factory method for frame gap tests"""
        status = "fail" if p99_ms > p99_threshold else "pass"
        return {
            "name": name,
            "status": status,
            "duration_ms": duration_ms,
            "metrics": {
                "frame_gap_ms_mean": mean_ms,
                "frame_gap_ms_p95": p95_ms,
                "frame_gap_ms_p99": p99_ms,
                "drops": drops,
            },
            "artifacts": artifacts or [],
            "category": "performance",
            "tags": ["frame-gap"],
        }

    def create_latency_test(
        self,
        name: str,
        duration_ms: float,
        mean_ms: float,
        p95_ms: float,
        p99_ms: float,
        p99_threshold: float = 45.0,
    ):
        """Factory method for latency tests"""
        status = "fail" if p99_ms > p99_threshold else "pass"
        return {
            "name": name,
            "status": status,
            "duration_ms": duration_ms,
            "metrics": {
                "latency_ms_mean": mean_ms,
                "latency_ms_p95": p95_ms,
                "latency_ms_p99": p99_ms,
            },
            "error_message": f"p99 exceeded {p99_threshold} ms" if status == "fail" else None,
            "category": "performance",
            "tags": ["latency"],
        }


def example_parameterized_tests():
    """
    Example: Use factory pattern to create multiple test variants
    """
    print("=" * 70)
    print("PATTERN 4: Parameterized Tests with Factory Pattern")
    print("=" * 70)

    registry = MetricRegistry()
    factory = TestFactory(registry)

    report = create_report(
        env={
            "orin_image": "r36.3",
            "fpga_bitstream": "hsb_20260125_01",
            "git_sha": "ab12cd3",
            "branch": "main",
        }
    )

    # Test multiple resolutions
    resolutions = [
        ("720p30", 16.67, 17.0, 17.8),
        ("1080p30", 16.67, 17.1, 17.9),
        ("1080p60", 16.67, 17.4, 18.1),
        ("2160p30", 16.67, 17.3, 18.0),
    ]

    for res_name, mean, p95, p99 in resolutions:
        test_spec = factory.create_frame_gap_test(
            name=f"frame_gap_{res_name}",
            duration_ms=12000.0,
            mean_ms=mean,
            p95_ms=p95,
            p99_ms=p99,
            drops=0,
        )
        test_spec["tags"].append(res_name)
        report.add_test(**test_spec)

    report.finalize(metric_registry=registry)
    out_dir = Path("example_pattern4")
    out_file = report.write(out_dir)

    print(f"✓ Report saved to {out_file}")
    print(f"  Run ID: {report.run_id}")
    print(f"  Tests: {report.summary['total_tests']} resolution variants")
    print(f"  Status: {report.summary['status']}")
    print()


# =============================================================================
# Run All Examples
# =============================================================================

if __name__ == "__main__":
    example_single_test_frame_gap()
    example_multi_test_suite()
    example_custom_metrics_power_and_memory()
    example_parameterized_tests()

    print("=" * 70)
    print("All examples complete! Check example_pattern* directories.")
    print("=" * 70)
