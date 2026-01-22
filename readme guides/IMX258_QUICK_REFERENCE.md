# IMX258 60fps Timing Quick Reference

## Problem
**1050/5100 register configuration causes blank/white frame output**

---

## Root Cause (One Line)
**FRM_LENGTH=1050 is LESS than Y_OUT_SIZE=1080 → frame timing too short → sensor outputs 30 missing lines → blank frames**

---

## The Violation

```
Constraint: FRM_LENGTH must be >= Y_OUT_SIZE

Reality:    1050 < 1080  ✗ INVALID
            |      |
            |      └─ Required output height
            └────────── Set register value

Deficit: 1080 - 1050 = 30 MISSING LINES
```

---

## Why This Breaks the Sensor

1. Sensor configured to output: **1080 lines**
2. Timing register says frame ends after: **1050 lines**  
3. CSI Interface expects: **1920×1080 pixels**
4. Result: **30 lines of data lost** → incomplete frame → blank output

---

## Quick Fix

Replace 1050/5100 with **1116/5400** (60fps_new mode):
```python
# WRONG:
("0340", "04"),  # FRM_LENGTH = 0x041A = 1050  ✗ TOO SHORT
("0341", "1A"),
("0342", "13"),  # LINE_LENGTH = 0x13EC = 5100
("0343", "EC"),

# CORRECT:
("0340", "04"),  # FRM_LENGTH = 0x045C = 1116  ✓ OK
("0341", "5C"),
("0342", "15"),  # LINE_LENGTH = 0x1518 = 5400
("0343", "18"),
```

---

## All Valid 1920×1080 @ 60fps Configurations

| Mode | FRM | LINE | Blank Frm | Blank Line | Status |
|------|-----|------|-----------|-----------|--------|
| Original 60fps | 1592 | 5352 | +512 | +3432 | ✓ Works |
| **60fps_new (RECOMMENDED)** | **1116** | **5400** | **+36** | **+3480** | **✓ Best** |
| 60fps_cus (BROKEN) | 1050 | 5100 | **-30** | +3180 | **✗ FAILS** |

---

## Key Formula

```
FRM_LENGTH must satisfy:
  FRM_LENGTH >= Y_OUT_SIZE + 36

For 1920×1080 output:
  FRM_LENGTH >= 1080 + 36 = 1116 (MINIMUM)
```

---

## Frame Rate Calculation

```
FPS = (INCK * PLL_IVT_MPY) / (IVTPXCK_DIV * FRM_LENGTH * LINE_LENGTH)

Example with DIV=5, PLL_IVT_MPY=110:
FPS = (27MHz * 110) / (5 * 1116 * 5400)
    = 2970MHz / 30,132,000
    = 98.6 fps
```

---

## Impact of IVTPXCK_DIV Changes

| Change | DIV | Result | Solution |
|--------|-----|--------|----------|
| Keep DIV=5 | 5 | ~70-100 fps | Use FRM≥1116 |
| Double to DIV=10 | 10 | ~35-50 fps | Keep same FRM/LINE |
| **Critical** | **5→4** | **Much faster** | **Must decrease FRM/LINE carefully** |

**Warning**: Simply scaling timing registers by DIV ratio doesn't work!
- Must maintain absolute minimum FRM_LENGTH ≥ 1116
- Cannot use mathematical scaling alone

---

## Blank Timing Margins

```
Frame blanking = FRM_LENGTH - Y_OUT_SIZE
Line blanking = LINE_LENGTH - X_OUT_SIZE

Configuration Analysis:
┌─ Valid (Original 60fps)
│  FRM_blank = 1592 - 1080 = 512 lines ✓
│  
├─ Valid (60fps_new) 
│  FRM_blank = 1116 - 1080 = 36 lines ✓ (MINIMUM)
│
└─ INVALID (60fps_cus)
   FRM_blank = 1050 - 1080 = -30 lines ✗ NEGATIVE!
```

---

## Register Summary for 1920×1080 @ 60fps

### Option 1: Original (Safe)
```
0x0340: 0x06  (FRM_LENGTH high)
0x0341: 0x38  (= 0x0638 = 1592 lines)
0x0342: 0x14  (LINE_LENGTH high)
0x0343: 0xE8  (= 0x14E8 = 5352 pixels)
0x0301: 0x05  (IVTPXCK_DIV = 5)
```

### Option 2: Optimized (Recommended)
```
0x0340: 0x04  (FRM_LENGTH high)
0x0341: 0x5C  (= 0x045C = 1116 lines) [MINIMUM SAFE]
0x0342: 0x15  (LINE_LENGTH high)
0x0343: 0x18  (= 0x1518 = 5400 pixels)
0x0301: 0x05  (IVTPXCK_DIV = 5)
```

### Option 3: BROKEN (Do Not Use)
```
0x0340: 0x04  (FRM_LENGTH high)
0x0341: 0x1A  (= 0x041A = 1050 lines) ✗ TOO SHORT!
0x0342: 0x13  (LINE_LENGTH high)
0x0343: 0xEC  (= 0x13EC = 5100 pixels)
0x0301: 0x05  (IVTPXCK_DIV = 5)
```

---

## Debugging Tips

If you see blank frames:
1. ✓ Check FRM_LENGTH register (0x0340-0x0341)
2. ✓ Verify: FRM_LENGTH >= Y_OUT_SIZE (output height)
3. ✓ For 1920×1080 mode: FRM_LENGTH must be ≥ 1116
4. ✓ Check LINE_LENGTH register (0x0342-0x0343)  
5. ✓ Verify: LINE_LENGTH >= X_OUT_SIZE (output width)
6. ✓ Read back actual register values from sensor
7. ✓ Confirm DIV value (0x0301) matches expected mode

---

## Related Modes

### 30fps Mode (DIV=10)
```
# Can use SAME timing registers as 60fps with DIV=5
0x0340: 0x06  (FRM_LENGTH = 1592)
0x0341: 0x38
0x0342: 0x14  (LINE_LENGTH = 5352)
0x0343: 0xE8
0x0301: 0x0A  (DIV=10, DOUBLED from 60fps)
→ Result: FPS is halved (69.7 → 34.8 fps)
```

### 4K Mode (2160×3840)
```
0x0340: 0x08  (FRM_LENGTH = 2232)
0x0341: 0xB8
0x0342: 0x2A  (LINE_LENGTH = 10800)
0x0343: 0x30
0x0301: 0x05  (Same DIV=5)
→ Result: ~30 fps due to higher pixel count
```

---

## References

- **File**: `imx258.py` modes: imx258_mode_1920x1080_60fps_new (CORRECT)
- **Analysis**: Extracted from all 6 mode definitions in sensor driver
- **Constraint Source**: IMX258 datasheet timing requirements
- **Validation**: Working modes confirm minimum FRM=1116

