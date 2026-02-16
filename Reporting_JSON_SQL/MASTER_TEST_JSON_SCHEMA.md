# Master Test Reporting Schema for HSB CI/CD

## Overview

Based on your current test infrastructure and requirements, this document defines:
1. **Individual Script Reports** - Do scripts create their own reports?
2. **Master Test Structure** - How to consolidate all tests into one run
3. **JSON Schema Design** - Optimal structure for your hardware/configuration matrix

---

## Question 1: Do Individual Scripts Create One Report Each?

**No, not necessarily.** Here's the recommended approach:

### Current Architecture (my_test.py example):
- Each **invocation** creates ONE report (`summary.json` + optional artifacts)
- Reports are **independent** and can be run separately
- All reports are **structured identically** per `json_helper.py`

### For Your Master Test:
- **One master runner** invokes all individual scripts
- **One consolidated report** captures everything
- Each individual test becomes a `TestEntry` in the consolidated report
- Individual artifacts are collected and referenced with relative paths

---

## Question 2: Foreseeable Master Report Structure

Given your setup:
- **Multiple FPGA boards** (CPNX 1G, CPNX 10G, Avant 10G/25G)
- **Different cameras** (possibly with IMX258)
- **Different hosts** (AGX Orin vs AGX Thor)
- **Different HOST_IF configurations** (1, 2, 3, 4)

Your master report should look like this:

```json
{
  "run_id": "2026-01-28_master_complete_test_20260128_143000",
  "timestamp": "2026-01-28T14:30:00.000000+00:00",
  "schema_version": "2.0",
  
  "environment": {
    "host_platform": "agx_orin",
    "orin_image": "r36.3",
    "agx_image_version": "r36.3",
    "fpga_bitstream": "hsb_1chip_avtx_top_impl_1_20260128",
    "fpga_board_type": "cpnx_versa",
    "camera_model": "imx258",
    "git_sha": "abc123def456",
    "branch": "main",
    "operator_graph_version": "v2.1.0",
    "notes": "Full CI/CD validation run for HSB board with IMX258 camera"
  },
  
  "configuration_matrix": {
    "fpga_boards": [
      {
        "board_id": "board_001",
        "board_type": "cpnx_versa",
        "variant": "10g",
        "host_if": 1,
        "status": "tested"
      }
    ],
    "cameras": [
      {
        "camera_id": "cam_front",
        "model": "imx258",
        "resolution": "1080p",
        "fps": 60,
        "status": "tested"
      }
    ],
    "hosts": [
      {
        "host_id": "agx_orin_01",
        "platform": "agx_orin",
        "image_version": "r36.3",
        "status": "tested"
      }
    ]
  },
  
  "tests": [
    {
      "name": "register_verification_cpnx_10g",
      "status": "pass",
      "duration_ms": 1234.5,
      "category": "hardware_verification",
      "tags": ["registers", "apb_bus", "cpnx_10g", "host_if_1"],
      "source_script": "verify_reg.py",
      "board_id": "board_001",
      "host_if": 1,
      "metrics": {
        "registers_checked": 4,
        "registers_passed": 4,
        "registers_failed": 0,
        "read_time_ms": 1200.0
      },
      "artifacts": [
        {
          "type": "log",
          "path": "results/master_run/verify_reg_cpnx10g_log.txt",
          "label": "Register Read Log (CPNX 10G)"
        }
      ]
    },
    {
      "name": "device_detection",
      "status": "pass",
      "duration_ms": 2340.0,
      "category": "system_integration",
      "tags": ["device_detection", "ethernet", "agx_orin"],
      "source_script": "verify_device_detection.py",
      "board_id": "board_001",
      "metrics": {
        "devices_found": 1,
        "expected_devices": 1,
        "detection_latency_ms": 500.0
      },
      "artifacts": []
    },
    {
      "name": "camera_imx258_verification",
      "status": "pass",
      "duration_ms": 5600.0,
      "category": "camera",
      "tags": ["imx258", "1080p60", "csi"],
      "source_script": "verify_camera_imx258.py",
      "board_id": "board_001",
      "camera_id": "cam_front",
      "metrics": {
        "resolution": "1920x1080",
        "fps": 60,
        "frame_count": 300,
        "dropped_frames": 0,
        "crc_pass_rate": 99.8,
        "vts_valid": true,
        "hts_valid": true
      },
      "artifacts": [
        {
          "type": "png",
          "path": "results/master_run/camera_frame_sample.png",
          "label": "Sample Frame from IMX258"
        },
        {
          "type": "log",
          "path": "results/master_run/imx258_test_log.txt",
          "label": "IMX258 Verification Log"
        }
      ]
    },
    {
      "name": "ethernet_speed_verification",
      "status": "pass",
      "duration_ms": 3200.0,
      "category": "network",
      "tags": ["ethernet", "speed", "agx_orin"],
      "source_script": "verify_eth_speed.py",
      "board_id": "board_001",
      "metrics": {
        "link_speed_mbps": 1000,
        "expected_speed_mbps": 1000,
        "packet_loss_percent": 0.0,
        "ping_latency_ms": 1.2
      },
      "artifacts": []
    },
    {
      "name": "ptp_synchronization",
      "status": "pass",
      "duration_ms": 8900.0,
      "category": "timing",
      "tags": ["ptp", "timing_sync"],
      "source_script": "verify_PTP.py",
      "board_id": "board_001",
      "metrics": {
        "ptp_offset_ns": 125,
        "ptp_offset_threshold_ns": 1000,
        "sync_locked": true,
        "sync_time_seconds": 8.5
      },
      "artifacts": [
        {
          "type": "json",
          "path": "results/master_run/ptp_metrics.json",
          "label": "PTP Statistics"
        }
      ]
    },
    {
      "name": "focus_motor_control",
      "status": "pass",
      "duration_ms": 2100.0,
      "category": "camera_control",
      "tags": ["focus_motor", "imx258"],
      "source_script": "test_focus_motor.py",
      "camera_id": "cam_front",
      "metrics": {
        "motor_steps_tested": 50,
        "motor_response_time_ms": 42.0,
        "position_accuracy_steps": 0
      },
      "artifacts": []
    },
    {
      "name": "multi_mode_imx258",
      "status": "pass",
      "duration_ms": 4500.0,
      "category": "camera",
      "tags": ["imx258", "multi_mode", "resolution_switching"],
      "source_script": "verify_multi_mode_imx258.py",
      "camera_id": "cam_front",
      "metrics": {
        "modes_tested": 4,
        "modes_passed": 4,
        "mode_switch_time_ms": 150.0,
        "frame_continuity_maintained": true
      },
      "artifacts": [
        {
          "type": "log",
          "path": "results/master_run/multi_mode_log.txt",
          "label": "Multi-Mode Test Log"
        }
      ]
    }
  ],
  
  "summary": {
    "status": "pass",
    "total_tests": 7,
    "passed": 7,
    "failed": 0,
    "skipped": 0,
    "partial": 0,
    "yield_rate": 100.0,
    "total_duration_ms": 27874.5,
    "earliest_test": "2026-01-28T14:30:00.000000+00:00",
    "latest_test": "2026-01-28T14:35:27.000000+00:00"
  },
  
  "test_breakdown_by_category": {
    "hardware_verification": {
      "total": 1,
      "passed": 1,
      "failed": 0
    },
    "system_integration": {
      "total": 1,
      "passed": 1,
      "failed": 0
    },
    "camera": {
      "total": 2,
      "passed": 2,
      "failed": 0
    },
    "network": {
      "total": 1,
      "passed": 1,
      "failed": 0
    },
    "timing": {
      "total": 1,
      "passed": 1,
      "failed": 0
    },
    "camera_control": {
      "total": 1,
      "passed": 1,
      "failed": 0
    }
  },
  
  "test_breakdown_by_board": {
    "board_001": {
      "total": 7,
      "passed": 7,
      "failed": 0
    }
  },
  
  "artifacts_summary": {
    "total_artifacts": 5,
    "by_type": {
      "log": 3,
      "png": 1,
      "json": 1
    }
  }
}
```

---

## Question 3: Recommended JSON Schema Design

### Core Principles for Your Use Case:

#### 1. **Hardware Configuration Tracking**
```json
"configuration_matrix": {
  "fpga_boards": [{"board_id": "...", "variant": "...", "host_if": 1}],
  "cameras": [{"camera_id": "...", "model": "imx258", "resolution": "..."}],
  "hosts": [{"host_id": "...", "platform": "agx_orin|agx_thor"}]
}
```

**Why:** You can run the same tests across different configurations. This tracks which combination was tested.

#### 2. **Test-Level Configuration Context**
Each test should include:
```json
{
  "name": "test_name",
  "board_id": "board_001",        // Links to configuration_matrix
  "camera_id": "cam_front",       // Optional
  "host_id": "agx_orin_01",       // Optional
  "source_script": "verify_reg.py" // Trace back to original script
}
```

**Why:** Enables filtering: "Show me all camera tests on AGX Orin that passed"

#### 3. **Metrics Are Flexible**
```json
"metrics": {
  "frame_gap_ms_mean": 16.67,
  "crc_pass_rate": 99.8,
  "ptp_offset_ns": 125,
  "registers_checked": 4
  // Add any metric your test produces
}
```

**Why:** `json_helper.py` already supports arbitrary metrics. No schema rigidity needed.

#### 4. **Artifacts with Relative Paths**
```json
"artifacts": [
  {
    "type": "log",
    "path": "results/master_run/verify_reg_cpnx10g_log.txt",
    "label": "Register Read Log"
  }
]
```

**Why:** Results stay in `results/master_run/` folder. Paths are relative, database-friendly.

#### 5. **Summary Statistics**
Include aggregations for quick insights:
```json
"summary": {
  "status": "pass",
  "total_tests": 7,
  "yield_rate": 100.0
},
"test_breakdown_by_category": {...},
"test_breakdown_by_board": {...}
```

---

## Implementation Strategy

### Step 1: Define Your Master Test Script

```python
from json_helper import create_report, Artifact
from pathlib import Path
import subprocess
import json
import time

def run_master_test():
    # Step 1: Create report
    report = create_report(env={
        "host_platform": "agx_orin",
        "orin_image": "r36.3",
        "fpga_bitstream": "hsb_1chip_avtx_top_impl_1_20260128",
        "fpga_board_type": "cpnx_versa",
        "camera_model": "imx258",
        "git_sha": "abc123def456",
        "branch": "main"
    })
    
    # Step 2: Define test suite
    test_suite = [
        {
            "script": "verify_reg.py",
            "args": ["--cpnx10", "--hostif", "1"],
            "category": "hardware_verification",
            "tags": ["registers", "cpnx_10g"],
            "board_id": "board_001"
        },
        {
            "script": "verify_device_detection.py",
            "args": ["--peer-ip", "192.168.0.2"],
            "category": "system_integration",
            "tags": ["device_detection"],
            "board_id": "board_001"
        },
        # ... more tests
    ]
    
    # Step 3: Run each test and capture results
    for test_config in test_suite:
        start = time.time()
        try:
            result = subprocess.run([...], capture_output=True)
            passed = result.returncode == 0
        except Exception as e:
            passed = False
        
        duration_ms = (time.time() - start) * 1000
        
        report.add_test(
            name=test_config["script"].replace(".py", ""),
            status="pass" if passed else "fail",
            duration_ms=duration_ms,
            category=test_config.get("category"),
            tags=test_config.get("tags", []),
            metrics={...},
            artifacts=[...]
        )
    
    # Step 4: Finalize and save
    report.finalize()
    report.write(Path("results/master_run"))
```

### Step 2: Extend json_helper (if needed)

If you want test-level configuration context, extend `TestEntry`:

```python
@dataclass
class TestEntry:
    # ... existing fields ...
    source_script: Optional[str] = None  # Which script generated this test
    board_id: Optional[str] = None       # Hardware board ID
    camera_id: Optional[str] = None      # Camera instance
    host_id: Optional[str] = None        # Host platform ID
```

### Step 3: Use Streamlit to Filter Results

The dashboard can then let you filter:
- "All tests on AGX Orin"
- "All camera tests"
- "All tests on board_001"

---

## File Organization

```
results/
├── master_run/              # One master run
│   ├── summary.json         # Main report (the JSON above)
│   ├── verify_reg_cpnx10g_log.txt
│   ├── camera_frame_sample.png
│   ├── imx258_test_log.txt
│   └── ptp_metrics.json
├── 2026-01-28_individual/   # Optional: individual reports
│   ├── verify_reg/summary.json
│   ├── verify_camera/summary.json
│   └── ...
```

---

## Summary: Answers to Your Questions

| Question | Answer |
|----------|--------|
| **Does each script create one report?** | No. Your master runner calls all scripts and creates ONE consolidated report. Optional: scripts can also output individual reports if you want audit trail. |
| **What does master report look like?** | See the JSON example above (~150 lines). One `summary.json` per master run with all tests, configuration matrix, and aggregated statistics. |
| **What should JSON structure be?** | Core: `env`, `tests[]`, `summary`. Enhanced: `configuration_matrix`, per-test `board_id`/`camera_id`/`host_id`, and breakdown statistics for filtering. |

---

## Next Steps

1. **Review** the JSON schema above
2. **Identify** which fields your scripts produce (metrics)
3. **Decide** on your configuration matrix (boards, cameras, hosts)
4. **Extend** `TestEntry` in `json_helper.py` if needed
5. **Build** the master test runner script
6. **Test** with one run locally
7. **Iterate** on the dashboard filters

This approach is **scalable, flexible, and audit-friendly** for your CI/CD needs.
