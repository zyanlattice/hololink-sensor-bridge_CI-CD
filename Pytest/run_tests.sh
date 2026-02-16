#!/bin/bash
# Comprehensive test runner script for Hololink Sensor Bridge verification tests

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# CI/CD root is parent of Pytest folder
CI_CD_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

# Default configuration
HOLOLINK_IP="${HOLOLINK_IP:-192.168.0.2}"
DEVICE_TYPE="${DEVICE_TYPE:-}"  # Required - no default
CAMERA_ID="${CAMERA_ID:-0}"
BITSTREAM_PATH="${BITSTREAM_PATH:-}"
BITSTREAM_VERSION="${BITSTREAM_VERSION:-}"  # Required - no default
BITSTREAM_DATECODE="${BITSTREAM_DATECODE:-}"  # Required - no default
EXPECTED_MD5="${EXPECTED_MD5:-}"
TEST_REPORT_DIR="$CI_CD_ROOT/test_reports"
HTML_REPORT="test_report_$(date +%Y%m%d_%H%M%S).html"

# Parse command line arguments
MARKERS=""
TEST_FILES=""
VERBOSE="-v"
EXTRA_ARGS=""

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help           Show this help message"
    echo "  -m, --markers MARKS  Run tests with specific markers (e.g., 'hardware', 'not slow')"
    echo "  -t, --tests FILES    Run specific test files (space-separated)"
    #echo "  -f, --fast           Skip slow tests"
    #echo "  -s, --software       Run only software tests (no hardware required)"
    #echo "  -hw, --hardware      Run only hardware tests"
    #echo "  -c, --camera         Run only camera tests"
    echo "  -vv, --very-verbose  Very verbose output"
    #echo "  --ip IP              Set Hololink device IP (default: 192.168.0.2)"
    echo "  --device DEVICE      Set device type (cpnx1, cpnx10, avant10, avant25)"
    echo "  --camera-id ID       Set camera ID (default: 0)"
    echo "  --bitstream PATH     Set bitstream file path"
    echo "  --version VER        Set expected bitstream version (e.g., 2511 or 0x2511)"
    echo "  --datecode DATE      Set expected bitstream datecode (e.g., 01053446 or 0x1053446)"
    echo "  --md5 HASH           Set expected MD5 checksum"
    echo "  --html               Generate HTML report"
    echo ""
    echo "Examples:"
    echo "  $0                           # Run all tests"
    #echo "  $0 -f                        # Run fast tests only"
    #echo "  $0 -m hardware               # Run hardware tests"
    #echo "  $0 -m 'hardware and not slow' # Hardware tests, skip slow"
    echo "  $0 -t test_device_detection.py # Run specific test file"
    #echo "  $0 --ip 192.168.0.10 -hw     # Hardware tests with custom IP"
    echo "  $0 --device avant10 --version 2511 --datecode 3446  # Full config"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            print_usage
            exit 0
            ;;
        -m|--markers)
            MARKERS="$2"
            shift 2
            ;;
        -t|--tests)
            TEST_FILES="$2"
            shift 2
            ;;
        -vv|--very-verbose)
            VERBOSE="-vv"
            shift
            ;;
        --ip)
            HOLOLINK_IP="$2"
            shift 2
            ;;
        --device)
            DEVICE_TYPE="$2"
            shift 2
            ;;
        --camera-id)
            CAMERA_ID="$2"
            shift 2
            ;;
        --bitstream)
            BITSTREAM_PATH="$2"
            shift 2
            ;;
        --version)
            BITSTREAM_VERSION="$2"
            shift 2
            ;;
        --datecode)
            BITSTREAM_DATECODE="$2"
            shift 2
            ;;
        --md5)
            EXPECTED_MD5="$2"
            shift 2
            ;;
        --html)
            EXTRA_ARGS="$EXTRA_ARGS --html=$HTML_REPORT --self-contained-html"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

# Validate required parameters
if [[ -z "$DEVICE_TYPE" ]]; then
    echo -e "${RED}Error: Device type is required${NC}"
    echo "Please specify device type using --device option"
    echo "Valid options: cpnx1, cpnx10, avant10, avant25"
    echo ""
    print_usage
    exit 1
fi

if [[ -z "$BITSTREAM_VERSION" ]]; then
    echo -e "${RED}Error: Bitstream version is required${NC}"
    echo "Please specify version using --version option"
    echo "Example: --version 0302"
    echo ""
    print_usage
    exit 1
fi

if [[ -z "$BITSTREAM_DATECODE" ]]; then
    echo -e "${RED}Error: Bitstream datecode is required${NC}"
    echo "Please specify datecode using --datecode option"
    echo "Example: --datecode 2511"
    echo ""
    print_usage
    exit 1
fi

# Normalize hex format: add "0x" prefix if not present
if [[ -n "$BITSTREAM_VERSION" ]] && [[ ! "$BITSTREAM_VERSION" =~ ^0x ]]; then
    BITSTREAM_VERSION="0x${BITSTREAM_VERSION}"
fi

if [[ -n "$BITSTREAM_DATECODE" ]] && [[ ! "$BITSTREAM_DATECODE" =~ ^0x ]]; then
    BITSTREAM_DATECODE="0x${BITSTREAM_DATECODE}"
fi

# Print configuration
echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}Hololink Sensor Bridge Test Suite${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Hololink IP:       $HOLOLINK_IP"
echo "  Device Type:       $DEVICE_TYPE"
echo "  Camera ID:         $CAMERA_ID"
echo "  Bitstream Path:    ${BITSTREAM_PATH:-not set}"
echo "  Bitstream Version: ${BITSTREAM_VERSION:-not set}"
echo "  Bitstream Datecode:${BITSTREAM_DATECODE:-not set}"
echo "  Expected MD5:      ${EXPECTED_MD5:-not set}"
echo "  Test Markers:      ${MARKERS:-all}"
echo "  Test Files:        ${TEST_FILES:-all}"
echo "  Report Dir:        $TEST_REPORT_DIR"
echo ""

# Export environment variables
export HOLOLINK_IP
export DEVICE_TYPE
export CAMERA_ID
export BITSTREAM_PATH
export BITSTREAM_VERSION
export BITSTREAM_DATECODE
export EXPECTED_MD5
export PYTHONPATH="${PYTHONPATH}:${SCRIPT_DIR}/../scripts"

# Create report directory
mkdir -p "$TEST_REPORT_DIR"

# Create logs subdirectory with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_LOG_DIR="$TEST_REPORT_DIR/logs_$TIMESTAMP"
mkdir -p "$TEST_LOG_DIR"
LOG_FILE="$TEST_LOG_DIR/pytest_run.log"

# Export TEST_LOG_DIR so pytest can access it
export TEST_LOG_DIR

# Clear pytest cache to avoid stale test discovery
echo -e "${YELLOW}Clearing pytest cache...${NC}"
rm -rf .pytest_cache __pycache__ 2>/dev/null || true
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}Cache cleared${NC}"
echo ""

# Build pytest command
PYTEST_CMD="pytest $VERBOSE"

# Override log file location to put it in the timestamped log directory
PYTEST_CMD="$PYTEST_CMD -o log_file=$TEST_LOG_DIR/pytest_output.log"

if [[ -n "$MARKERS" ]]; then
    PYTEST_CMD="$PYTEST_CMD -m \"$MARKERS\""
fi

if [[ -n "$TEST_FILES" ]]; then
    PYTEST_CMD="$PYTEST_CMD $TEST_FILES"
fi

PYTEST_CMD="$PYTEST_CMD $EXTRA_ARGS"

# Print command
echo -e "${YELLOW}Running command:${NC}"
echo "  $PYTEST_CMD"
echo ""

# Write header for pytest_run.log (console output capture)
cat > "$LOG_FILE" << EOF
==================================================================
Hololink Sensor Bridge - Pytest Execution Log
==================================================================
Test Run Information:
  Date/Time:         $(date '+%Y-%m-%d %H:%M:%S')
  Log Directory:     $TEST_LOG_DIR
  Working Directory: $SCRIPT_DIR

Configuration:
  Hololink IP:       $HOLOLINK_IP
  Device Type:       $DEVICE_TYPE
  Camera ID:         $CAMERA_ID
  Bitstream Path:    ${BITSTREAM_PATH:-not set}
  Bitstream Version: $BITSTREAM_VERSION
  Bitstream Datecode:$BITSTREAM_DATECODE
  Expected MD5:      ${EXPECTED_MD5:-not set}

Test Selection:
  Markers:           ${MARKERS:-all}
  Test Files:        ${TEST_FILES:-all}
  Extra Args:        ${EXTRA_ARGS:-none}

Command:
  $PYTEST_CMD

==================================================================
Pytest Output:
==================================================================

EOF

# Write header for pytest_output.log (pytest internal logging)
cat > "$TEST_LOG_DIR/pytest_output.log" << EOF
==================================================================
Hololink Sensor Bridge - Pytest Debug Log
==================================================================
Test Run Information:
  Date/Time:         $(date '+%Y-%m-%d %H:%M:%S')
  Log Directory:     $TEST_LOG_DIR
  Working Directory: $SCRIPT_DIR

Configuration:
  Hololink IP:       $HOLOLINK_IP
  Device Type:       $DEVICE_TYPE
  Camera ID:         $CAMERA_ID
  Bitstream Path:    ${BITSTREAM_PATH:-not set}
  Bitstream Version: $BITSTREAM_VERSION
  Bitstream Datecode:$BITSTREAM_DATECODE
  Expected MD5:      ${EXPECTED_MD5:-not set}

Test Selection:
  Markers:           ${MARKERS:-all}
  Test Files:        ${TEST_FILES:-all}
  Extra Args:        ${EXTRA_ARGS:-none}

Command:
  $PYTEST_CMD

==================================================================
Pytest Debug Logs:
==================================================================

EOF

# Run tests
echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}Starting Tests${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""

# Execute pytest
set +e  # Don't exit on error, we want to process results
# Use sed to strip ANSI color codes from log file while preserving them on console
eval $PYTEST_CMD 2>&1 | tee >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE")
EXIT_CODE=${PIPESTATUS[0]}  # Get exit code from pytest, not tee
set -e

echo ""
echo -e "${BLUE}==================================================================${NC}"
if [[ $EXIT_CODE -eq 0 ]]; then
    echo -e "${GREEN}ALL TESTS PASSED${NC}"
    TEST_RESULT="PASSED"
else
    echo -e "${RED}SOME TESTS FAILED${NC}"
    TEST_RESULT="FAILED"
fi
echo -e "${BLUE}==================================================================${NC}"
echo ""

# Write log file footer with summary
cat >> "$LOG_FILE" << EOF

==================================================================
Test Run Summary
==================================================================
Result:     $TEST_RESULT
Exit Code:  $EXIT_CODE
End Time:   $(date '+%Y-%m-%d %H:%M:%S')
Duration:   Run completed

Reports:
  Log Directory: $TEST_LOG_DIR
  Full Log:      $LOG_FILE
EOF

# Add report file locations if they exist
if [[ -d "$TEST_REPORT_DIR" ]]; then
    LATEST_REPORT=$(ls -t "$TEST_REPORT_DIR"/test_results_*.md 2>/dev/null | head -1)
    if [[ -n "$LATEST_REPORT" ]]; then
        echo "  Summary:       $LATEST_REPORT" >> "$LOG_FILE"
    fi
    
    LATEST_JSON=$(ls -t "$TEST_REPORT_DIR"/test_results_*.json 2>/dev/null | head -1)
    if [[ -n "$LATEST_JSON" ]]; then
        echo "  Details:       $LATEST_JSON" >> "$LOG_FILE"
    fi
    
    # Add structured report if json_helper was used
    if [[ "$ENABLE_JSON_REPORT" == "1" ]]; then
        STRUCTURED_REPORT=$(ls -t "$TEST_REPORT_DIR"/structured_report_*.json 2>/dev/null | head -1)
        if [[ -n "$STRUCTURED_REPORT" ]]; then
            echo "  Structured:    $STRUCTURED_REPORT" >> "$LOG_FILE"
        fi
    fi
fi

if [[ "$EXTRA_ARGS" == *"--html"* ]]; then
    echo "  HTML Report:   $HTML_REPORT" >> "$LOG_FILE"
fi

echo "==================================================================" >> "$LOG_FILE"

# Show report locations
echo -e "${YELLOW}Reports generated:${NC}"
echo "  Test Log Dir:  $TEST_LOG_DIR"
echo "  Full Log:      $LOG_FILE"

# Show structured report if enabled
if [[ "$ENABLE_JSON_REPORT" == "1" ]] && [[ -d "$TEST_REPORT_DIR" ]]; then
    STRUCTURED_REPORT=$(ls -t "$TEST_REPORT_DIR"/structured_report_*.json 2>/dev/null | head -1)
    if [[ -n "$STRUCTURED_REPORT" ]]; then
        echo "  Structured JSON: $STRUCTURED_REPORT"
    fi
fi

if [[ -d "$TEST_REPORT_DIR" ]]; then
    LATEST_REPORT=$(ls -t "$TEST_REPORT_DIR"/test_results_*.md 2>/dev/null | head -1)
    if [[ -n "$LATEST_REPORT" ]]; then
        echo "  Summary: $LATEST_REPORT"
    fi
    
    LATEST_JSON=$(ls -t "$TEST_REPORT_DIR"/test_results_*.json 2>/dev/null | head -1)
    if [[ -n "$LATEST_JSON" ]]; then
        echo "  Details: $LATEST_JSON"
    fi
fi

if [[ "$EXTRA_ARGS" == *"--html"* ]]; then
    echo "  HTML:    $HTML_REPORT"
fi

echo ""

# Exit with pytest exit code
exit $EXIT_CODE
