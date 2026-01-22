# Radiant USB FPGA Programmer

Automated FPGA bitstream programming via Lattice Radiant Programmer over USB/JTAG.

## Overview

This tool provides a Python interface to Lattice Radiant Programmer's command-line utility (`pgrcmd.exe`) for automated FPGA programming workflows. It generates XCF project files dynamically and handles error detection, retry logic, and progress reporting.

## Features

- **Automatic XCF Generation**: Creates Radiant project files from bitstream paths
- **Multiple Operation Modes**: Full programming with verify, fast configuration, custom operations
- **Cable Configuration**: One-time manual setup, persistent configuration
- **Retry Logic**: Configurable retries on cable/connection errors (default: 3)
- **Error Interpretation**: Maps error codes to human-readable descriptions
- **Console Output**: Clear progress messages and status reporting
- **Absolute Path Handling**: Ensures reliable file references across operations

## Prerequisites

- **Lattice Radiant**: Version 2024.2 or 2025.2 installed
- **Python**: 3.7 or higher
- **PyYAML**: Install with `pip install pyyaml`
- **FPGA Hardware**: LFCPNX-100 connected via USB/JTAG cable

## Quick Start

### 1. First-Time Cable Setup

Run the interactive cable configuration (one-time only):

```powershell
python radiant_usb_programmer.py --setup-cable
```

This will prompt you to enter cable settings from Radiant Programmer GUI:
- Cable Name (e.g., `USB2`)
- Port Address (e.g., `FTUSB-0`)
- USB ID (e.g., `Dual RS232-HS A Location 22321 Serial A`)

**How to find cable settings:**
1. Open Radiant Programmer GUI
2. Go to **Cable Settings** dialog
3. Click **Detect Cable**
4. Note the detected values

Configuration is saved to `radiant_programmer_config.yaml`.

### 2. Program FPGA

#### Full Programming (Erase + Program + Verify)

```powershell
python radiant_usb_programmer.py --bitstream C:\path\to\bitstream.bit
```

#### Fast Configuration (Quick, No Verify)

```powershell
python radiant_usb_programmer.py --bitstream C:\path\to\bitstream.bit --fast
```

#### Custom Operation

```powershell
python radiant_usb_programmer.py --bitstream C:\path\to\bitstream.bit --operation "Program,Verify"
```

## Usage Examples

### Basic Programming with Default Settings

```powershell
python radiant_usb_programmer.py --bitstream .\bitstream\fpga_cpnx_versa.bit
```

Output:
```
================================================================================
  FPGA Programming
================================================================================
[INFO] Bitstream: C:\...\fpga_cpnx_versa.bit
[INFO] Operation: Erase,Program,Verify
[INFO] Device: LFCPNX-100
================================================================================
[INFO] Executing: pgrcmd.exe -infile fpga_cpnx_versa_auto.xcf -logfile ...
[INFO] Elapsed time: 57.3 seconds
[✓ SUCCESS] Programming successful!
```

### Fast Configuration (Development Workflow)

```powershell
python radiant_usb_programmer.py --bitstream .\impl_1\design.bit --fast
```

Executes "Fast Configuration" operation (~6 seconds vs ~60 seconds for full verify).

### Verbose Mode

```powershell
python radiant_usb_programmer.py --bitstream .\design.bit --verbose
```

Shows detailed execution including XCF generation, file paths, and intermediate steps.

### Custom Retry Count

```powershell
python radiant_usb_programmer.py --bitstream .\design.bit --max-retries 5
```

Increases retry attempts on cable errors from default 3 to 5.

### Custom Configuration File

```powershell
python radiant_usb_programmer.py --bitstream .\design.bit --config .\my_config.yaml
```

## Operation Types

| Operation | Description | Use Case | Time |
|-----------|-------------|----------|------|
| `Erase,Program,Verify` | Full cycle with verification | Production, critical applications | ~60s |
| `Fast Configuration` | Quick programming, no verify | Development, rapid iteration | ~6s |
| `Program,Verify` | Skip erase step | Reloading same design | ~45s |
| `Erase,Program` | No verification | Debug, testing | ~30s |

## Error Handling

### Automatic Retry on Cable Errors

Cable connection errors (ERROR 85021324) trigger automatic retry:

```
[⚠ WARNING] Cable error detected, retrying...
[⚠ WARNING] Retry attempt 2/3
```

### Error Code Interpretation

The tool maps Radiant error codes to descriptions:

| Code | Interpretation |
|------|----------------|
| 85021324 | Process Operation Failed - Check device connection and power |
| 85021372 | Operation unsuccessful - Verify bitstream compatibility |
| 85021xxx | Cable or connection error - Check USB cable |
| 85022xxx | Device not found or incorrect IDCODE |
| 85023xxx | Programming error - Verify bitstream file |

### Example Error Output

```
[✗ ERROR] Programming failed
[✗ ERROR] Errors detected:
  ERROR <85021324> - Process Operation Failed.
    → Process Operation Failed - Check device connection and power
  ERROR <85021372> - Operation: unsuccessful.
    → Operation unsuccessful - Verify bitstream compatibility
```

## Configuration File

`radiant_programmer_config.yaml`:

```yaml
radiant:
  version: '2025.2'
  programmer_path: 'c:/lscc/radiant/2025.2/programmer/bin/nt64/pgrcmd.exe'

cable:
  name: 'USB2'
  port: 'FTUSB-0'
  usb_id: 'Dual RS232-HS A Location 22321 Serial A'

device:
  family: 'LFCPNX'
  name: 'LFCPNX-100'
  idcode: '0x010f4043'

options:
  tck_delay: 3        # 0-255, higher = slower but more reliable
  timeout: 300        # Programming timeout in seconds
```

### Multiple Device Support

To support multiple FPGAs or cable configurations, create separate config files:

```powershell
python radiant_usb_programmer.py --bitstream design.bit --config cpnx_config.yaml
python radiant_usb_programmer.py --bitstream design.bit --config avtx_config.yaml
```

## XCF File Generation

XCF files and logs are auto-generated in a timestamped results folder:

```
results/
└── jtag_loc_programming_20260114_143022/
    ├── fpga_cpnx_versa_auto.xcf       # Generated
    └── fpga_cpnx_versa_auto_log.txt   # Programmer log
```

**Key Features:**
- Timestamped results folder for organization (format: `jtag_loc_programming_YYYYMMDD_HHMMSS`)
- Absolute paths for cross-directory reliability
- File timestamp preservation
- Cable settings embedded from config
- Operation type templated

## Command-Line Reference

```
usage: radiant_usb_programmer.py [-h] [--bitstream BITSTREAM]
                                  [--operation {Erase,Program,Verify,Fast Configuration,Program,Verify,Erase,Program}]
                                  [--fast] [--config CONFIG] [--setup-cable]
                                  [--max-retries MAX_RETRIES] [--verbose]

Radiant USB FPGA Programmer

optional arguments:
  -h, --help            Show this help message and exit
  --bitstream BITSTREAM
                        Path to bitstream file (.bit)
  --operation {Erase,Program,Verify,Fast Configuration,Program,Verify,Erase,Program}
                        Programming operation (default: Erase,Program,Verify)
  --fast                Use Fast Configuration (quick, no verify)
  --config CONFIG       Path to configuration file
  --setup-cable         Interactive cable setup
  --max-retries MAX_RETRIES
                        Maximum retry attempts on cable errors (default: 3)
  --verbose, -v         Verbose output
```

## Integration with CI/CD

### Return Codes

- **0**: Success
- **1**: Programming failed or error
- **130**: Interrupted by user (Ctrl+C)

### Example PowerShell Script

```powershell
$bitstream = "C:\builds\latest\fpga_design.bit"

python radiant_usb_programmer.py --bitstream $bitstream --fast

if ($LASTEXITCODE -eq 0) {
    Write-Host "FPGA programming successful" -ForegroundColor Green
    # Continue with verification tests
    python verify_camera_imx258.py --check-ethernet --max-saves 5
} else {
    Write-Host "FPGA programming failed" -ForegroundColor Red
    exit 1
}
```

### Batch Processing

```powershell
$bitstreams = @(
    ".\bitstream\cpnx_1g.bit",
    ".\bitstream\cpnx_10g.bit",
    ".\bitstream\avtx_25g.bit"
)

foreach ($bit in $bitstreams) {
    Write-Host "Programming: $bit"
    python radiant_usb_programmer.py --bitstream $bit --operation "Program,Verify"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed: $bit"
        exit 1
    }
}
```

## Troubleshooting

### "Configuration file not found"

**Solution**: Run `--setup-cable` to create initial configuration:
```powershell
python radiant_usb_programmer.py --setup-cable
```

### "Radiant Programmer not found"

**Solutions:**
1. Update `programmer_path` in config file:
   ```yaml
   radiant:
     programmer_path: 'C:\custom\path\to\pgrcmd.exe'
   ```
2. Install Radiant 2024.2 or 2025.2 to default location

### "Process Operation Failed" (Error 85021324)

**Causes:**
- USB cable disconnected mid-operation
- Device power loss
- JTAG chain communication error

**Solutions:**
- Check USB cable connection
- Verify device power supply
- Try reducing TCK frequency (increase `tck_delay` in config)
- Increase `--max-retries`

### "Operation unsuccessful" (Error 85021372)

**Causes:**
- Bitstream incompatible with device
- Incorrect device IDCODE
- Corrupted bitstream file

**Solutions:**
- Verify bitstream is for LFCPNX-100 device
- Check IDCODE in config matches device (0x010f4043)
- Regenerate bitstream from Radiant Diamond

### Programming Very Slow

**Solutions:**
- Use `--fast` for development workflows
- Reduce `tck_delay` in config (faster but less reliable)
- Check USB cable quality (use USB 2.0 port)

## Comparison: Docker vs USB Programming

| Feature | Docker (Network) | USB (This Tool) |
|---------|------------------|-----------------|
| **Platform** | Linux/Mac/Windows | Windows only |
| **Interface** | Ethernet | USB/JTAG |
| **Speed** | ~3-5 minutes | ~60s (full), ~6s (fast) |
| **Setup** | Docker image | Radiant install |
| **Remote** | Yes | No (local only) |
| **Verification** | Camera tests | JTAG verify |

## Advanced Usage

### Custom Device Configuration

Edit `radiant_programmer_config.yaml` for different FPGA families:

```yaml
device:
  family: 'CertusPro-NX'
  name: 'LFCPNX-100'
  idcode: '0x010f4043'
```

### Multiple Cable Support

For systems with multiple JTAG adapters, create separate configs:

```yaml
# cable1_config.yaml
cable:
  usb_id: 'Dual RS232-HS A Location 22321 Serial A'

# cable2_config.yaml
cable:
  usb_id: 'Dual RS232-HS B Location 12345 Serial B'
```

### Log File Analysis

Programming logs are saved in the timestamped results folder:

```powershell
# View detailed log
Get-Content .\results\usb_bitstream_programming_*\fpga_cpnx_versa_auto_log.txt

# Search for errors in all logs
Select-String -Path .\results\usb_bitstream_programming_*\*_log.txt -Pattern "ERROR"
```

## Files Generated

Each programming operation creates files in a timestamped results folder:

```
results/
└── usb_bitstream_programming_<YYYYMMDD_HHMMSS>/
    ├── <bitstream_name>_auto.xcf      # Generated project file
    └── <bitstream_name>_auto_log.txt  # Programmer output log
```

**Example:**
```
results/
└── usb_bitstream_programming_20260114_143022/
    ├── fpga_cpnx_versa_auto.xcf
    └── fpga_cpnx_versa_auto_log.txt
```

## Dependencies

```powershell
pip install pyyaml
```

Or create `requirements.txt`:
```
pyyaml>=6.0
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Programming successful |
| 1 | Programming failed, error occurred |
| 130 | User interrupted (Ctrl+C) |

## Related Scripts

- **bitstream_programmer_wrapper.py**: Network-based Docker programming
- **verify_camera_imx258.py**: Post-programming camera verification
- **control_tapo_kasa.py**: Power cycle control

## License

Internal Lattice Semiconductor tool.

## Support

For issues or questions, contact the HSB CI/CD team.
