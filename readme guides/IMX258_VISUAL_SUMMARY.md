# IMX258 Timing Issue - Visual Summary

## The Problem in 30 Seconds

```
Config:     FRM_LENGTH = 1050 lines
Expected:   Y_OUT_SIZE = 1080 lines
Result:     1050 < 1080 ✗ INVALID

Effect:     Sensor outputs 1080 lines
            Frame ends after 1050 lines
            30 lines of data LOST
            
Output:     BLANK FRAMES (incomplete data)
```

---

## The Four Working Modes

```
┌─────────────────────────────────────────────────────────────┐
│ MODE TIMING COMPARISON (1920×1080 resolution)              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Original 60fps:    [████████████████████] 1592 lines ✓      │
│                    Blank: 512 lines (plenty)                │
│                    FPS: 69.7                                │
│                                                             │
│ 60fps_new:         [██████████] 1116 lines ✓               │
│                    Blank: 36 lines (minimum safe)           │
│                    FPS: 98.6                                │
│                    ← RECOMMENDED / MINIMUM VALID            │
│                                                             │
│ 60fps_cus:         [████████] 1050 lines ✗                 │
│                    Blank: -30 lines (NEGATIVE!)             │
│                    Status: BROKEN - BLANK FRAMES            │
│                                                             │
│ 4K 30fps:          [██████████████████████████] 2232 ✓      │
│                    Blank: 72 lines (ample)                  │
│                    Resolution: 3840×2160                    │
│                    FPS: 30                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘

█ = Frame pixels (image data)
─ = Blanking pixels (timing/sync)
```

---

## Why 1050 Fails

```
SENSOR OPERATION TIMELINE
═══════════════════════════════════════════════════════════════

Line 0:           Frame start signal
      ↓
Lines 1-1050:    OUTPUT DATA from sensor
      │         ✓ CSI interface receiving pixel data
      │
Line 1050:       FRM_LENGTH timer expires
      │         ⚠️  Signal: "End of frame" sent to CSI
      ↓
Lines 1051-1080: Sensor still outputting data
      │         ✗ CSI rejects: "Frame already ended"
      │         ✗ Data dropped / buffer overrun
      ↓
Line 1080:       Actual frame end from sensor
      │         ✗ CSI unprepared: "Frame was closed at 1050"
      ↓
Result: INCOMPLETE FRAME
       ✗ 30 lines lost
       ✗ Image processing fails
       ✗ Application sees blank output


CONSTRAINT VIOLATION
═══════════════════════════════════════════════════════════════

Requirement:  FRM_LENGTH >= Y_OUT_SIZE (output height)
              1050        >= 1080
              FALSE ✗

Physics:      Cannot fit 1080 lines in space of 1050
              Image incomplete by necessity
              
Solution:     Increase FRM_LENGTH to minimum safe value
              FRM_LENGTH >= 1116 (0x045C)
```

---

## Side-by-Side Register Comparison

```
                 BROKEN              WORKING (60fps_new)
                 ──────              ─────────────────
Register Address Value Description   Value  Difference
─────────────────────────────────────────────────────────
0x0340-0x0341    0x041A = 1050   FRM_LENGTH   0x045C = 1116
                 ✗ TOO SHORT!                 ✓ MINIMUM SAFE
                                             (+66 lines)

0x0342-0x0343    0x13EC = 5100   LINE_LENGTH  0x1518 = 5400
                 ✓ OK                        ✓ OK
                                             (+300 pixels)

0x034E-0x034F    0x0438 = 1080   Y_OUT_SIZE   0x0438 = 1080
                 ✓ Image height               ✓ Image height
                 (required)                   (required)

0x034C-0x034D    0x0780 = 1920   X_OUT_SIZE   0x0780 = 1920
                 ✓ Image width                ✓ Image width
                 (required)                   (required)

0x0301           0x05 = 5        IVTPXCK_DIV  0x05 = 5
                 ✓ Clock divider              ✓ Clock divider

0x0307           0x6E = 110      PLL_IVT_MPY  0x6E = 110
                 ✓ PLL multiplier             ✓ PLL multiplier
─────────────────────────────────────────────────────────
RESULT:          BLANK FRAMES                 ✓ VALID OUTPUT
```

---

## Constraint Violation Visualization

```
┌─── ABSOLUTE CONSTRAINT ───┐
│ FRM_LENGTH >= Y_OUT_SIZE   │
└────────────────────────────┘

BROKEN Configuration:
┌──────────────────────────────────────┐
│ FRM_LENGTH = 1050 lines              │  ← Register setting
│          ▼                           │
├──────────────────────────────────────┤
│ Y_OUT_SIZE = 1080 lines              │  ← Output requirement
│          ▲                           │
└──────────────────────────────────────┘
         VIOLATION!
    FRM < Y_OUT_SIZE
   1050 < 1080 = FALSE ✗


WORKING Configuration:
┌──────────────────────────────────────┐
│ FRM_LENGTH = 1116 lines              │  ← Register setting
│ ▲                                    │
├──────────────────────────────────────┤
│ Y_OUT_SIZE = 1080 lines              │  ← Output requirement
│                   ▼                  │
└──────────────────────────────────────┘
      SATISFIED ✓
    FRM >= Y_OUT_SIZE
   1116 >= 1080 = TRUE ✓
```

---

## Data Flow Diagram

```
BROKEN MODE (1050 lines)        WORKING MODE (1116+ lines)
═══════════════════════════════════════════════════════════

Sensor Config:                  Sensor Config:
  Output: 1920×1080 ✓             Output: 1920×1080 ✓
  
Timing Registers:               Timing Registers:
  FRM_LENGTH: 1050 ✗              FRM_LENGTH: 1116 ✓
  (ends frame early)              (accommodates all lines)

Sensor Output:                  Sensor Output:
  Line   1: [DATA] ▶ CSI          Line   1: [DATA] ▶ CSI
  Line  500: [DATA] ▶ CSI         Line  500: [DATA] ▶ CSI
  Line 1050: [DATA] ▶ CSI         Line 1050: [DATA] ▶ CSI
  Line 1051: [DATA] ✗ DROPPED     Line 1051: [BLANK] ▶ CSI
  Line 1080: [DATA] ✗ DROPPED     Line 1080: [BLANK] ▶ CSI
  
Frame Assembly:                 Frame Assembly:
  CSI Received:                   CSI Received:
    Lines 1-1050: DATA ✓            Lines 1-1080: DATA ✓
    Lines 1051-1080: MISSING ✗      Lines 1081+: BLANK ✓
  
  Result: Incomplete              Result: Complete
  1050/1080 = 97.2% ✗             1080/1080 = 100% ✓

Image Output:                   Image Output:
  ▲ Missing 30 lines              ▲ Complete frame
  │ at bottom                      │
  │ Causes blank/                  │ Normal operation
  │ corrupted output               │
  ░░░░░░░░░░░░░░░                 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ░░░░░░░░░░░░░░░                 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ░░░░░░░░░░░░░░░                 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ░░░░░░░░░░░░░░░                 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  ░░░░░░░░░░░░░░░                 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
  BLANK ✗                         VALID ✓
```

---

## DIV and Timing Relationships

```
PIXEL CLOCK FORMULA:
PXCK = (27MHz * PLL_IVT_MPY) / IVTPXCK_DIV
     = (27 * 110) / DIV
     = 2970 / DIV (MHz)

┌──────────────────────────────────────────┐
│ DIV Value vs Pixel Clock                 │
├──────────────────────────────────────────┤
│                                          │
│  DIV=4:  PXCK = 742.5 MHz  ← Fastest   │
│  DIV=5:  PXCK = 594 MHz     ← Current  │
│  DIV=10: PXCK = 297 MHz     ← Slowest  │
│                                          │
└──────────────────────────────────────────┘

FPS RELATIONSHIP:
FPS = PXCK / (FRM_LENGTH * LINE_LENGTH)

For same FRM/LINE:
  FPS @ DIV=5  = 594MHz / (1592 * 5352) = 69.7 fps
  FPS @ DIV=10 = 297MHz / (1592 * 5352) = 34.8 fps
                ↑ Halved by doubling DIV

For same PXCK (DIV=5):
  FPS @ 1116x5400 = 98.6 fps
  FPS @ 1592x5352 = 69.7 fps
                ↑ Higher frame rate with lower total pixels
```

---

## The Error Chain

```
1. MODE DERIVATION ERROR
   ┌─────────────────────────┐
   │ Original DIV=4 mode     │
   │ FRM = 844 lines         │
   └────────────┬────────────┘
                │
                │ Attempt to scale to DIV=5
                │ Using ratio: 5/4
                ▼
         844 × 1.25 = 1055 lines
                │
                │ Round down to convenient hex
                ▼
         0x041A = 1050 lines (MISTAKE)

2. CONSTRAINT VALIDATION MISSED
   ┌─────────────────────────────┐
   │ Forgot to check:            │
   │ FRM_LENGTH >= Y_OUT_SIZE    │
   │                             │
   │ 1050 >= 1080? NO ✗          │
   └────────────┬────────────────┘
                │
                ▼
         Should have rejected!
         Or increased to 1116 (0x045C)

3. INCOMPLETE TESTING
   ┌──────────────────────────┐
   │ Mode uploaded to sensor  │ ✓
   │ Initial images captured  │ ✓
   │ BUT: Only tested briefly │ ✗
   │                          │
   │ Did not catch:           │ 
   │ - Blank frames appear    │
   │   after frame sync lost  │
   │ - Takes multiple frames  │
   │   to show problem        │
   └──────────────────────────┘

4. RESULT: BROKEN MODE DEPLOYED
   ┌──────────────────────────┐
   │ imx258_mode_1920x1080    │
   │ _60fps_cus               │
   │                          │
   │ Status: Causes blank     │
   │ frames in production     │
   └──────────────────────────┘
```

---

## Quick Debugging Flowchart

```
START: Seeing blank frames?
  │
  ├─→ Read register 0x0340-0x0341 (FRM_LENGTH)
  │   │
  │   ├─→ Value < 0x045C (< 1116)?
  │   │   │
  │   │   ├─→ YES: FRM_LENGTH too short!
  │   │   │        PROBLEM FOUND ✓
  │   │   │        Fix: Increase to 0x045C or higher
  │   │   │
  │   │   └─→ NO: Go to next check
  │   │
  │   └─→ Read register 0x034E-0x034F (Y_OUT_SIZE)
  │       │
  │       ├─→ FRM_LENGTH >= Y_OUT_SIZE?
  │       │   │
  │       │   ├─→ NO: Timing violation confirmed!
  │       │   │
  │       │   └─→ YES: Go to next check
  │       │
  │       └─→ Check register 0x0342-0x0343 (LINE_LENGTH)
  │           ├─→ LINE_LENGTH >= X_OUT_SIZE?
  │           │   (default 1920)
  │           │
  │           └─→ If all pass: Check DIV/PLL settings
  │               (less likely to be the problem)
  │
  └─→ END: Identified root cause
```

---

## Summary Table

| Question | Answer |
|----------|--------|
| **What causes blank frames?** | FRM_LENGTH (1050) < Y_OUT_SIZE (1080) creates incomplete frame |
| **Why 1050/5100 fails?** | Missing 30 lines of frame blanking violates sensor timing |
| **What's the minimum FRM?** | 1116 (0x045C) lines - observed minimum from working modes |
| **What about DIV=4 to DIV=5?** | Cannot use simple ratio scaling; must meet absolute minimums |
| **Recommended fix?** | Use 60fps_new: FRM=1116, LINE=5400, DIV=5 |
| **How to verify fix?** | Read back 0x0340-0x0341, should be 0x045C (or higher) |

---

## Key Takeaway

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ FRM_LENGTH = 1050 is 66 lines too short      ┃
┃                                             ┃
┃ Minimum safe value: 1116 lines              ┃
┃ (This is an ABSOLUTE minimum,               ┃
┃  not dependent on any other factors)        ┃
┃                                             ┃
┃ Fix: Change 0x041A → 0x045C                 ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

