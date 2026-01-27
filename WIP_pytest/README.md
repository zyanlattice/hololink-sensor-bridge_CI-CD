# Bitstream Programming Pytest Suite

This directory contains pytest tests for the bitstream programming workflow.

## Structure

```
pytest/
├── conftest.py                      # Shared fixtures and configuration
├── pytest.ini                       # Pytest configuration (logging, markers)
├── program_bitstream_docker.py      # Docker wrapper (called by tests)
├── test_bitstream_programming.py    # Test cases
└── README.md                        # This file
```

## Running Tests

### Run all tests:
```bash
cd pytest
pytest
```

### Run with real-time output (see all logs):
```bash
pytest -s
```

### Run specific test:
```bash
pytest test_bitstream_programming.py::test_full_bitstream_programming_workflow
```

### Run only quick tests (skip slow hardware tests):
```bash
pytest -m "not slow"
```

### Run with specific configuration:
```bash
# Override device IP
HOLOLINK_IP=192.168.0.10 pytest

# Use specific bitstream
BITSTREAM_PATH=/path/to/bitstream.bit BITSTREAM_VERSION=1234 pytest

# Control image capture
MAX_SAVES=5 pytest
```

### Dry run (no hardware needed):
```bash
pytest -k "dry_run"
```

## Test Output Handling

### Question 1: How does pytest handle log output from bpw.py?

**Answer:** Pytest captures ALL output by default and only shows it if test fails. To see output:

1. **Real-time output during test:**
   ```bash
   pytest -s  # Shows everything as it happens
   ```

2. **In test results:**
   - Output is captured and shown in test summary if test fails
   - Look for "Captured stdout" and "Captured stderr" sections

3. **In log file:**
   - `pytest.ini` configures logging to `pytest_output.log`
   - Contains full debug logs from all tests

4. **Programmatic access:**
   - Tests use `caplog` fixture to access logs
   - Tests parse stdout/stderr to extract results

### Question 2: Testing program_bitstream_docker.py instead of bpw.py

**Answer:** Tests call `program_bitstream_docker.py` via subprocess:

1. **Test invokes Docker wrapper:**
   ```python
   result = subprocess.run([
       "python3", "program_bitstream_docker.py",
       "--version", "0104_2507",
       "--bitstream-path", "/path/to/bitstream.bit",
       "--peer-ip", "192.168.0.2"
   ], capture_output=True)
   ```

2. **Docker wrapper runs container:**
   - Container executes `bitstream_programmer_wrapper.py`
   - All output flows back through Docker to subprocess

3. **Test validates results:**
   - Checks exit code
   - Parses stdout for success indicators
   - Asserts on individual step results

## Test Markers

```bash
# Run only Docker tests
pytest -m docker

# Run only hardware tests  
pytest -m hardware

# Skip slow tests
pytest -m "not slow"

# Run quick smoke tests
pytest -m quick
```

## Environment Variables

Configure tests via environment:

| Variable | Description | Default |
|----------|-------------|---------|
| `HOLOLINK_IP` | Device IP address | 192.168.0.2 |
| `BITSTREAM_PATH` | Path to .bit file | /home/lattice/HSB/CI_CD/bitstream/fpga_cpnx_versa_0104_2507.bit |
| `BITSTREAM_VERSION` | Version string | 0104_2507 |
| `BITSTREAM_MD5` | MD5 checksum | (empty) |
| `MAX_SAVES` | Images to save | 1 |

## Parameterized Tests

Some tests run with multiple configurations:

```python
@pytest.mark.parametrize("max_saves", [0, 1, 3])
def test_bitstream_programming_various_image_counts(max_saves):
    # Runs 3 times with different max_saves values
```

## CI/CD Integration

### Jenkins Example:
```groovy
stage('Bitstream Programming Test') {
    steps {
        sh '''
            cd pytest
            pytest \
                --junitxml=test-results.xml \
                --html=test-report.html \
                -v
        '''
    }
    post {
        always {
            junit 'pytest/test-results.xml'
            publishHTML([
                reportDir: 'pytest',
                reportFiles: 'test-report.html',
                reportName: 'Pytest Report'
            ])
        }
    }
}
```

## Troubleshooting

### Tests not finding hardware:
```bash
# Verify device is reachable
ping 192.168.0.2

# Check Docker
docker info

# Run with verbose output
pytest -s -vv
```

### Output not showing:
```bash
# Force output display
pytest -s --log-cli-level=DEBUG
```

### Timeout issues:
```bash
# Increase timeout in pytest.ini or per-test:
@pytest.mark.timeout(7200)  # 2 hours
```

## Adding New Tests

1. Add test function to `test_bitstream_programming.py`
2. Use fixtures from `conftest.py`
3. Mark appropriately (`@pytest.mark.docker`, etc.)
4. Parse output using `test_output_parser` fixture

Example:
```python
@pytest.mark.docker
@pytest.mark.hardware
def test_my_custom_workflow(docker_available, hololink_device_ip):
    # Your test here
    pass
```
