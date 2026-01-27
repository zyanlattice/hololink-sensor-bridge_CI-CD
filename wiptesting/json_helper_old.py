
# scripts/reporting.py
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pathlib import Path
import json, time, os

def now_iso():
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Artifact:
    type: str
    path: str
    label: Optional[str] = None

@dataclass
class TestEntry:
    name: str
    status: str              # "pass" | "fail" | "skip"
    duration_ms: Optional[float] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    artifacts: List[Artifact] = field(default_factory=list)

@dataclass
class RunReport:
    run_id: str
    timestamp: str
    schema_version: str = "1.0"
    env: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=lambda: {
        "status": "pass",
        "yield_rate": None,
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "notes": ""
    })
    tests: List[TestEntry] = field(default_factory=list)
    timeseries: List[Dict[str, Any]] = field(default_factory=list)

    def add_test(self, test: TestEntry):
        self.tests.append(test)

    def finalize(self):
        total = len(self.tests)
        passed = sum(1 for t in self.tests if t.status == "pass")
        failed = sum(1 for t in self.tests if t.status == "fail")
        self.summary["total_tests"] = total
        self.summary["passed"] = passed
        self.summary["failed"] = failed
        # status: fail if any fail, else pass if all pass, else partial
        if failed > 0:
            self.summary["status"] = "fail"
        elif passed == total:
            self.summary["status"] = "pass"
        else:
            self.summary["status"] = "partial"
        self.summary["yield_rate"] = (passed / total) if total else None

    def write(self, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        # dataclass -> dict converts Artifact objects properly inside TestEntry
        (out_dir / "summary.json").write_text(json.dumps(payload, indent=2))

# Example usage in a test runner script:
if __name__ == "__main__":
    run_id = time.strftime("%Y-%m-%d_%H-%M-%S")
    report = RunReport(
        run_id=run_id,
        timestamp=now_iso(),
        env={
            "orin_image": os.getenv("ORIN_IMAGE", "r36.3"),
            "fpga_bitstream": os.getenv("FPGA_BIT", "hsb_20260125_01"),
            "git_sha": os.getenv("GIT_SHA", "unknown"),
            "branch": os.getenv("GIT_BRANCH", "unknown"),
            "dataset": "camA_1080p60"
        }
    )

    # Example: simple bool test
    t0 = time.time()
    passed = True
    report.add_test(TestEntry(
        name="link_integrity_check",
        status="pass" if passed else "fail",
        duration_ms=(time.time()-t0)*1000,
        metrics={"result": 1}
    ))

    # Example: tuple (text,bool,dict)
    msg, ok, details = ("CRC OK", True, {"crc_error_count": 0, "checked_frames": 18000})
    report.add_test(TestEntry(
        name="crc_validation",
        status="pass" if ok else "fail",
        duration_ms=250.0,
        metrics=details,
        error_message=None if ok else msg
    ))

    # Example: attach a timeseries reference
    report.timeseries.append({
        "name": "frame_gap_ms",
        "path": f"metrics/frame_gap_ms.parquet",
        "count": 18000,
        "meta": {"unit": "ms"}
    })

    report.finalize()
    out_dir = Path(f"runs/{run_id}")
    report.write(out_dir)
    print(f"Wrote {out_dir/'summary.json'}")
