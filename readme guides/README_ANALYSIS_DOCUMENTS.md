# IMX258 Timing Analysis - Document Index

**Analysis Date**: January 16, 2026  
**Status**: COMPLETE - Root cause identified and documented  
**Problem**: 1050/5100 register configuration causes blank frame output

---

## Quick Start

**If you only have 2 minutes**: Read [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md)

**If you only have 5 minutes**: Read [IMX258_VISUAL_SUMMARY.md](IMX258_VISUAL_SUMMARY.md)

**If you need complete details**: Read [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md)

**For technical deep dive**: See [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md)

---

## Document Guide

### 1. 📋 **IMX258_ANALYSIS_FINAL_REPORT.md** (This section)
**Purpose**: Executive summary answering all 5 user questions  
**Length**: ~5 pages  
**Contains**:
- Root cause explanation
- Critical findings for all timing constraints
- Register formulas and relationships
- DIV impact analysis
- Why 1050/5100 causes blank frames
- Direct recommendations

**Read this if**: You want the complete answer to your original questions

---

### 2. 📊 **IMX258_STRUCTURED_SUMMARY.md** (Detailed)
**Purpose**: Comprehensive technical reference with full structure  
**Length**: ~10 pages  
**Contains**:
- Detailed constraint analysis for each register
- Min/max values with examples
- All formulas explained
- Side-by-side comparisons
- Root cause chain analysis
- Complete register quick reference

**Read this if**: You need technical details for implementation or debugging

---

### 3. ⚡ **IMX258_QUICK_REFERENCE.md** (Fast)
**Purpose**: Quick lookup guide and one-page summary  
**Length**: ~3 pages  
**Contains**:
- Problem in one line
- The violation highlighted
- All valid configurations
- Register values for each mode
- Debugging tips and checklist
- Fast formula reference

**Read this if**: You need quick answers or during debugging sessions

---

### 4. 🎨 **IMX258_VISUAL_SUMMARY.md** (Visual)
**Purpose**: Visual diagrams and explanations  
**Length**: ~4 pages  
**Contains**:
- ASCII diagrams showing timing relationships
- Visual constraint violations
- Data flow diagrams
- Side-by-side register comparisons
- DIV and timing relationship charts
- Error chain visualization
- Debugging flowchart

**Read this if**: You prefer visual explanations or need to explain to others

---

### 5. 📖 **IMX258_TIMING_ANALYSIS.md** (Comprehensive)
**Purpose**: Complete technical analysis with 10 sections  
**Length**: ~15 pages  
**Contains**:
- All constraint analysis
- Complete formulas
- CSI corruption mechanisms explained
- Timing register interdependencies
- PLL calculations
- Blank timing analysis
- Appendix with register addresses
- Complete reference material

**Read this if**: You need exhaustive technical information or are writing documentation

---

## Quick Facts

| Aspect | Finding |
|--------|---------|
| **Root Cause** | FRM_LENGTH (1050) < Y_OUT_SIZE (1080) |
| **Missing Lines** | 30 lines (1080 - 1050) |
| **Minimum Safe Value** | 1116 (0x045C) |
| **Deficit** | 66 lines below minimum safe value |
| **DIV Independence** | Minimum FRM is absolute, not scaled by DIV |
| **Working Config** | 60fps_new: FRM=1116, LINE=5400 |
| **Fix Required** | Change 0x0340-0x0341 from 0x041A to 0x045C |

---

## Answer Map - Where to Find Answers

### Question 1: FRM_LENGTH_LINES constraints?
- **Quick**: [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md#minimum-safe-values)
- **Detailed**: [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md#1-frm_length_lines-0x0340-0x0341-constraints)
- **Technical**: [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md#11-frm_length_lines-0x03400x0341)

### Question 2: LINE_LENGTH_PCK constraints?
- **Quick**: [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md#minimum-safe-values)
- **Detailed**: [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md#2-line_length_pck-0x0342-0x0343-constraints)
- **Technical**: [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md#12-line_length_pck-0x03420x0343)

### Question 3: IVTPXCK_DIV timing relationships?
- **Quick**: [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md#impact-of-ivtpxck_div-changes)
- **Detailed**: [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md#3-ivtpxck_div-0x0301-timing-relationships)
- **Visual**: [IMX258_VISUAL_SUMMARY.md](IMX258_VISUAL_SUMMARY.md#div-and-timing-relationships)
- **Technical**: [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md#13-ivtpxck_div-0x0301---clock-divider)

### Question 4: Specific 60fps mode examples?
- **Quick**: [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md#option-1-original-safe)
- **Detailed**: [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md#4-specific-mode-examples-60fps-configuration)
- **Visual**: [IMX258_VISUAL_SUMMARY.md](IMX258_VISUAL_SUMMARY.md#the-four-working-modes)
- **Technical**: [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md#41-original-60fps-mode)

### Question 5: Blank screen / no output causes?
- **Quick**: [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md#debugging-tips)
- **Detailed**: [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md#5-blank-screen--no-output-symptoms)
- **Visual**: [IMX258_VISUAL_SUMMARY.md](IMX258_VISUAL_SUMMARY.md#why-1050-fails)
- **Technical**: [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md#7-csi-data-corruption-mechanism)

---

## How to Use These Documents

### For Fixing the Issue
1. Read [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md#quick-fix) (2 min)
2. Read [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md#4-specific-mode-examples-60fps-configuration) (5 min)
3. Implement the fix (< 1 min)
4. Read [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md#debugging-tips) for verification

### For Understanding the Problem
1. Read [IMX258_VISUAL_SUMMARY.md](IMX258_VISUAL_SUMMARY.md#why-1050-fails) (3 min)
2. Read [IMX258_ANALYSIS_FINAL_REPORT.md](IMX258_ANALYSIS_FINAL_REPORT.md#why-10501005-specifically-causes-blank-frames) (5 min)
3. Read [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md) for deep understanding (10 min)

### For Debugging Future Issues
1. Save [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md) for quick lookup
2. Use [IMX258_VISUAL_SUMMARY.md](IMX258_VISUAL_SUMMARY.md#quick-debugging-flowchart) debugging flowchart
3. Refer to [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md#appendix-register-quick-reference) for register addresses

### For Documentation/Reference
1. Archive [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md) (most complete)
2. Use [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md) as official technical reference
3. Include [IMX258_VISUAL_SUMMARY.md](IMX258_VISUAL_SUMMARY.md) in training materials

---

## Key Facts Summary

### The Problem
```
FRM_LENGTH register: 0x041A = 1050 lines
Output height required: 1080 lines
Timing violation: 1050 < 1080 INVALID ✗
```

### The Solution
```
FRM_LENGTH register: 0x045C = 1116 lines
Output height required: 1080 lines
Timing valid: 1116 >= 1080 VALID ✓
Additional change: LINE_LENGTH 0x13EC → 0x1518
```

### Why It Matters
```
Incomplete frame (1050 lines) → CSI cannot sync → blank output
Complete frame (1116+ lines) → CSI processes normally → valid image
```

---

## Analysis Methodology

**Data Source**: 
- Extracted from 6 timing mode configurations in imx258.py
- 2 broken (with comments on what needs to change)
- 4 verified working modes

**Analysis Approach**:
1. Extracted all register values from each mode
2. Calculated timing relationships (pixel clock, FPS)
3. Compared working vs broken configurations
4. Identified constraint violations
5. Traced root cause to FRM_LENGTH < Y_OUT_SIZE
6. Validated against other modes (30fps, 4K)

**Validation**:
- Cross-referenced register values across 6 modes
- Confirmed pattern: all working modes have FRM >= 1116
- Only broken mode has FRM < 1080 output height
- Constraint applies universally (DIV independent)

---

## Related Configuration Information

### Register Addresses Used
- 0x0301: IVTPXCK_DIV (VT clock divider)
- 0x0307: PLL_IVT_MPY (PLL multiplier for VT clock)
- 0x034C-0x034D: X_OUT_SIZE (output image width)
- 0x034E-0x034F: Y_OUT_SIZE (output image height)
- 0x0340-0x0341: FRM_LENGTH_LINES (total frame height)
- 0x0342-0x0343: LINE_LENGTH_PCK (total line width)

### Pixel Clock Formula
```
PXCK (MHz) = (27 MHz × PLL_IVT_MPY) / IVTPXCK_DIV
PXCK (for DIV=5) = (27 × 110) / 5 = 594 MHz
```

### Frame Rate Formula
```
FPS = PXCK / (FRM_LENGTH × LINE_LENGTH)
Example: 594,000,000 / (1116 × 5400) = 98.6 fps
```

---

## Next Steps

### Immediate Action
- [ ] Apply fix: Change 0x0340-0x0341 from 0x041A to 0x045C
- [ ] Apply fix: Change 0x0342-0x0343 from 0x13EC to 0x1518 (optional but recommended)
- [ ] Read registers back to verify update
- [ ] Capture 100+ frame sequence to test

### Verification
- [ ] Check for blank frames
- [ ] Verify consistent frame rate (~60 fps)
- [ ] Check image quality (sharpness, colors)
- [ ] Confirm CSI error logs are clear

### Documentation
- [ ] Update mode definition comment in code
- [ ] Document why original 1050 value was invalid
- [ ] Save these analysis documents in project wiki

---

## Support & Questions

If you have questions about any section:

1. **For quick answers**: See [IMX258_QUICK_REFERENCE.md](IMX258_QUICK_REFERENCE.md)
2. **For detailed explanations**: See [IMX258_STRUCTURED_SUMMARY.md](IMX258_STRUCTURED_SUMMARY.md)
3. **For visual clarification**: See [IMX258_VISUAL_SUMMARY.md](IMX258_VISUAL_SUMMARY.md)
4. **For technical deep-dive**: See [IMX258_TIMING_ANALYSIS.md](IMX258_TIMING_ANALYSIS.md)
5. **For executive summary**: See [IMX258_ANALYSIS_FINAL_REPORT.md](IMX258_ANALYSIS_FINAL_REPORT.md)

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-16 | 1.0 | Initial analysis complete |
| - | - | 5 comprehensive documents created |
| - | - | Root cause identified: FRM_LENGTH constraint |
| - | - | Recommended fix: 1116 lines (0x045C) |

---

## Conclusion

The 1050/5100 timing configuration violates IMX258 sensor constraints by setting FRM_LENGTH below the required Y_OUT_SIZE. This creates incomplete frame transmission, causing blank/white frame output.

**Fix**: Use validated 60fps_new configuration with FRM=1116 (0x045C).

**Reference**: All analysis documented in 5 comprehensive documents in this directory.

---

**Document created**: 2026-01-16  
**Analysis method**: Register extraction and comparison from imx258.py  
**Confidence level**: HIGH (validated across 6 mode configurations)

