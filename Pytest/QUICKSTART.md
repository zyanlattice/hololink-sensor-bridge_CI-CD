# Quick Start Guide - Hololink Sensor Bridge Pytest Suite

## Installation (One-time setup)

```bash
cd WIP_pytest
pip install -r requirements.txt
```

## Basic Usage

### 1. Run All Tests
```bash
./run_tests.sh
```

### 2. Run Fast Tests Only (Skip Slow Camera Tests)
```bash
./run_tests.sh --fast
```

### 3. Run Hardware Tests
```bash
./run_tests.sh --hardware
```

### 4. Run Software Tests (No Hardware Needed)
```bash
./run_tests.sh --software
```

### 5. Run with HTML Report
```bash
./run_tests.sh --html
# Open test_report_*.html in browser
```

## Common Test Scenarios

### Check Device Connection
```bash
pytest test_device_detection.py -v
```

### Verify Bitstream Version
```bash
export BITSTREAM_VERSION="0x2511"
export BITSTREAM_DATECODE="0x1053446"
pytest test_datecode_version.py -v
```

### Test Camera Functionality
```bash
pytest test_camera_imx258.py -v
```

### Test PTP Synchronization
```bash
pytest test_ptp_synchronization.py -v
```

### Run Everything with Reports
```bash
./run_tests.sh --html --json
```

## Configuration

Set environment variables before running:

```bash
# Device IP (default: 192.168.0.2)
export HOLOLINK_IP="192.168.0.10"

# Device type (default: cpnx10)
export DEVICE_TYPE="avant10"

# Camera ID (default: 0)
export CAMERA_ID="0"

# Then run tests
./run_tests.sh
```

## Viewing Results

After tests run, check:
- **Console output** - Live test results
- **test_reports/** - JSON and Markdown summaries
- **test_report_*.html** - HTML report (if --html used)

Example:
```bash
# View latest markdown report
cat test_reports/test_results_*.md | tail

# View latest JSON
cat test_reports/test_results_*.json | jq
```

## Troubleshooting

### Tests Can't Find Device
```bash
# Check IP is correct
ping $HOLOLINK_IP

# Run device detection test
pytest test_device_detection.py -v -s
```

### Import Errors
```bash
# Make sure you're in WIP_pytest directory
cd WIP_pytest
./run_tests.sh
```

### Tests Hang
```bash
# Use timeout
pytest --timeout=300 -v  # 5 min timeout
```

## Need Help?

See full documentation:
```bash
cat README_PYTEST.md
```

Or show help:
```bash
./run_tests.sh --help
```
