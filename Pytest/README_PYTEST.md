# Hololink Sensor Bridge Pytest Test Suite

Automated test suite for verifying Hololink Sensor Bridge functionality using pytest.

## Overview

This test suite wraps all `verify_*.py` scripts from the `scripts/` directory into pytest-compatible tests. It provides:

- **Automated test execution** with pytest
- **Detailed test reports** in JSON and Markdown formats
- **Parameterized tests** for different configurations
- **Custom markers** for selective test execution
- **Environment-based configuration** for CI/CD flexibility

## Test Coverage

### Hardware Tests
- **Device Detection** (`test_device_detection.py`) - Network interface detection
- **Ethernet Speed** (`test_eth_speed.py`) - Link speed and throughput
- **APB Registers** (`test_apb_registers.py`) - Register read/write operations
- **Camera Driver** (`test_camera_driver.py`) - IMX258 driver detection
- **Camera Functionality** (`test_camera_imx258.py`) - Frame capture and FPS
- **Multi-Mode Camera** (`test_multi_mode_camera.py`) - Mode switching tests
- **PTP Synchronization** (`test_ptp_synchronization.py`) - Clock sync and latency

### Software Tests
- **Bitstream Verification** (`test_datecode_version.py`) - Version and datecode
- **MD5 Checksum** (`test_md5_checksum.py`) - File integrity
- **UDP Loopback** (`test_host_udp.py`) - Network stack validation

## Installation

```bash
# Install pytest and plugins
pip install pytest pytest-html pytest-json-report

# Or use the requirements file
cd WIP_pytest
pip install -r requirements.txt
```

## Configuration

Tests can be configured via environment variables:

```bash
# Device configuration
export HOLOLINK_IP="192.168.0.2"
export CAMERA_ID="0"
export DEVICE_TYPE="cpnx10"  # cpnx1, cpnx10, avant10, avant25
export HOST_INTERFACE="1"     # 1-4

# Bitstream configuration
export BITSTREAM_PATH="/path/to/bitstream.bit"
export BITSTREAM_VERSION="0x2511"
export BITSTREAM_DATECODE="0x1053446"
export BITSTREAM_MD5="abc123..."

# Paths
export WORKSPACE_ROOT="/home/lattice/HSB/holoscan-sensor-bridge"
```

## Running Tests

### Run All Tests
```bash
cd WIP_pytest
pytest -v
```

### Run Specific Test Categories
```bash
# Hardware tests only
pytest -v -m hardware

# Camera tests only
pytest -v -m camera

# Network tests only
pytest -v -m network

# Fast tests only (exclude slow)
pytest -v -m "not slow"
```

### Run Specific Test Files
```bash
# Device detection
pytest test_device_detection.py -v

# Ethernet speed
pytest test_eth_speed.py -v

# Camera functionality
pytest test_camera_imx258.py -v

# PTP synchronization
pytest test_ptp_synchronization.py -v
```

### Run with HTML Report
```bash
pytest -v --html=report.html --self-contained-html
```

### Run with JSON Report
```bash
pytest -v --json-report --json-report-file=report.json
```

## Test Markers

Tests are marked with the following markers:

- `@pytest.mark.hardware` - Requires physical Hololink device
- `@pytest.mark.camera` - Requires IMX258 camera
- `@pytest.mark.network` - Requires network connectivity
- `@pytest.mark.slow` - Takes significant time (>5 minutes)
- `@pytest.mark.docker` - Requires Docker container

### Using Markers
```bash
# Run only hardware tests
pytest -m hardware

# Run hardware tests but exclude slow ones
pytest -m "hardware and not slow"

# Run camera tests
pytest -m camera

# Run everything except slow tests
pytest -m "not slow"
```

## Test Reports

After running tests, reports are generated in `test_reports/`:

- `test_results_YYYYMMDD_HHMMSS.json` - Detailed JSON results
- `test_results_YYYYMMDD_HHMMSS.md` - Markdown summary report

### Report Contents
- Test outcomes (PASS/FAIL)
- Execution timestamps
- Detailed stats for each test
- Error messages and tracebacks

## Example Test Run

```bash
# Set up environment
export HOLOLINK_IP="192.168.0.2"
export DEVICE_TYPE="cpnx10"
export BITSTREAM_VERSION="0x2511"

# Run all hardware tests with report
cd WIP_pytest
pytest -v -m hardware --html=hardware_report.html

# Check results
ls test_reports/
cat test_reports/test_results_*.md
```

## Continuous Integration

### Basic CI Pipeline
```yaml
# .gitlab-ci.yml or .github/workflows/test.yml
test:
  script:
    - cd WIP_pytest
    - pytest -v -m "not slow" --html=report.html
  artifacts:
    paths:
      - WIP_pytest/report.html
      - WIP_pytest/test_reports/
```

### Full CI Pipeline (with hardware)
```yaml
test_hardware:
  tags:
    - hardware-runner  # Runner with Hololink device
  script:
    - export HOLOLINK_IP="192.168.0.2"
    - cd WIP_pytest
    - pytest -v --html=full_report.html
  artifacts:
    paths:
      - WIP_pytest/full_report.html
      - WIP_pytest/test_reports/
```

## Debugging Tests

### Run with Verbose Output
```bash
pytest -vv test_camera_imx258.py
```

### Run with Print Statements
```bash
pytest -v -s test_device_detection.py
```

### Run Single Test Function
```bash
pytest test_camera_imx258.py::test_camera_basic_functionality -v
```

### Run with PDB on Failure
```bash
pytest --pdb test_eth_speed.py
```

## Test Development

### Adding New Tests

1. Create new test file: `test_<feature>.py`
2. Import the verify script
3. Write test functions with `test_` prefix
4. Use fixtures for configuration
5. Record results with `record_test_result` fixture

Example:
```python
import pytest

@pytest.mark.hardware
def test_my_feature(hololink_device_ip, record_test_result):
    \"\"\"Test my feature.\"\"\"
    import verify_my_feature
    
    success, message, stats = verify_my_feature.main()
    
    record_test_result({
        "success": success,
        "message": message,
        "stats": stats
    })
    
    assert success, message
```

## Troubleshooting

### Import Errors
```bash
# Make sure scripts directory is in Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)/../scripts"
pytest -v
```

### Device Not Found
```bash
# Check device IP
export HOLOLINK_IP="<correct_ip>"
# Verify device is reachable
ping $HOLOLINK_IP
```

### Tests Hang
```bash
# Run with timeout
pytest --timeout=300 -v  # 5 minute timeout per test
```

## Contributing

When adding new verify scripts:

1. Add the script to `scripts/`
2. Create corresponding `test_<name>.py` in `WIP_pytest/`
3. Add appropriate markers
4. Update this README
5. Test locally before committing

## License

See main project LICENSE file.
