# Auto-Exposure Feature Guide

## 🎯 Overview

The `linux_AE_player_imx258.py` script includes a sophisticated automatic exposure control system that continuously analyzes frame brightness and adjusts camera exposure in real-time.

## 📊 Algorithm Architecture

### Three-Level Hierarchical Decision Making

The auto-exposure system uses a priority-based approach:

```
┌─────────────────────────────────────────────────────────────┐
│ PRIORITY 1: Prevent Clipping (URGENT)                       │
│  • Saturation > 2% → Decrease 30% (aggressive)              │
│  • Saturation > 1% → Decrease 10% (warning zone)            │
└─────────────────────────────────────────────────────────────┘
                          ↓ (if no clipping)
┌─────────────────────────────────────────────────────────────┐
│ PRIORITY 2: Optimize High Percentiles (COARSE)             │
│  • p99 < 180 → Increase 10%                                 │
│  • p99 > 240 → Decrease 10%                                 │
└─────────────────────────────────────────────────────────────┘
                          ↓ (if in range)
┌─────────────────────────────────────────────────────────────┐
│ PRIORITY 3: Fine-tune Median (SUBTLE)                      │
│  • p50 < 100 → Increase 5%                                  │
│  • p50 > 140 → Decrease 5%                                  │
└─────────────────────────────────────────────────────────────┘
```

### Bonus: Shadow Detail Protection
```
If p01 < 10 AND p50 < 120:
    Increase exposure by 8% (lift crushed shadows)
```

---

## 🚀 Quick Start

### Basic Usage
```bash
# Auto-exposure enabled by default
python linux_AE_player_imx258.py

# Fullscreen mode
python linux_AE_player_imx258.py --fullscreen

# Disable auto-exposure (manual control only)
python linux_AE_player_imx258.py --no-auto-exposure
```

### Monitor Output
Auto-exposure prints status every 10 seconds:
```
[AE Stats] p99=215.3, p50=118.7, p01=8.2, sat=0.45%, adjustments=12
```

- **p99**: 99th percentile brightness (bright regions)
- **p50**: Median brightness (overall scene)
- **p01**: 1st percentile brightness (dark regions)
- **sat**: Saturation ratio (% of clipped pixels)
- **adjustments**: Total exposure changes made

---

## 🎛️ Tuning Parameters

### Scene-Specific Optimization

#### Bright Scenes (Outdoor, Well-Lit)
```bash
python linux_AE_player_imx258.py \
    --ae-target-p99-low 200 \
    --ae-target-p99-high 250 \
    --ae-target-median-low 120 \
    --ae-target-median-high 160
```

#### Dark Scenes (Indoor, Low-Light)
```bash
python linux_AE_player_imx258.py \
    --ae-target-p99-low 140 \
    --ae-target-p99-high 200 \
    --ae-target-median-low 70 \
    --ae-target-median-high 110 \
    --ae-saturation-threshold 0.03  # More tolerant of clipping
```

#### High-Contrast Scenes (Backlit, Mixed Lighting)
```bash
python linux_AE_player_imx258.py \
    --ae-target-p99-low 160 \
    --ae-target-p99-high 220 \
    --ae-target-median-low 80 \
    --ae-target-median-high 120 \
    --ae-smoothing-window 7  # More smoothing to handle transitions
```

### Adjustment Speed

#### Fast Adaptation (Dynamic Scenes)
```bash
python linux_AE_player_imx258.py \
    --ae-adjustment-interval 3 \
    --ae-smoothing-window 3
```
- Adjusts every 3 frames
- Less smoothing = faster response

#### Slow/Stable (Static Scenes)
```bash
python linux_AE_player_imx258.py \
    --ae-adjustment-interval 10 \
    --ae-smoothing-window 10
```
- Adjusts every 10 frames
- More smoothing = stable, no jitter

### Exposure Limits

#### Conservative Range (Prevent Motion Blur)
```bash
python linux_AE_player_imx258.py \
    --ae-min-exposure 0x0100 \
    --ae-max-exposure 0x0800
```

#### Aggressive Range (Maximize Light)
```bash
python linux_AE_player_imx258.py \
    --ae-min-exposure 0x0080 \
    --ae-max-exposure 0x1800
```

---

## 📈 Performance Optimization

### Default Settings (Recommended)
```bash
python linux_AE_player_imx258.py --ae-downsample 4
```
- Analyzes every 4th pixel (16x faster)
- Negligible accuracy loss
- Maintains 60 FPS visualization

### High-Accuracy (Slower)
```bash
python linux_AE_player_imx258.py --ae-downsample 2
```
- Analyzes every 2nd pixel (4x faster)
- Better for small ROI or critical scenes

### Ultra-Fast (Lowest Accuracy)
```bash
python linux_AE_player_imx258.py --ae-downsample 8
```
- Analyzes every 8th pixel (64x faster)
- Use for initial calibration or stress testing

---

## 🔍 Troubleshooting

### Problem: Exposure oscillates (too unstable)
**Solution:**
```bash
--ae-smoothing-window 10 \
--ae-adjustment-interval 8
```
Increase smoothing and adjustment interval.

### Problem: Exposure adjusts too slowly
**Solution:**
```bash
--ae-smoothing-window 3 \
--ae-adjustment-interval 3
```
Decrease smoothing and adjustment interval.

### Problem: Image too dark even with auto-exposure
**Solution 1:** Lower target thresholds
```bash
--ae-target-p99-low 140 \
--ae-target-median-low 70
```

**Solution 2:** Increase max exposure
```bash
--ae-max-exposure 0x2000
```

### Problem: Image overexposed (clipping)
**Solution:**
```bash
--ae-saturation-threshold 0.01  # React at 1% clipping
```
Lower the saturation threshold for earlier reaction.

### Problem: Shadows too dark
The algorithm already includes shadow protection (p01 monitoring). If still too dark:
```bash
--ae-target-median-low 100  # Higher median target
```

---

## 🧪 Testing & Validation

### Test Scenario 1: Step Response (Dark → Bright)
1. Start with camera covered
2. Uncover camera suddenly
3. Observe convergence speed

**Expected:** Exposure decreases within 1-2 seconds

### Test Scenario 2: Tracking (Moving Light Source)
1. Point camera at moving flashlight
2. Observe jitter and stability

**Expected:** Smooth tracking, no oscillation

### Test Scenario 3: High-Contrast (Window Scene)
1. Frame window with indoor foreground
2. Check if foreground is visible

**Expected:** Balanced exposure, neither clipped nor crushed

---

## 📊 Metrics Interpretation

### Ideal Ranges
| Metric | Ideal Range | Meaning |
|--------|-------------|---------|
| **p99** | 180-240 | Bright regions well-exposed |
| **p50** | 100-140 | Overall scene balanced |
| **p01** | 10-50 | Shadows have detail |
| **sat** | <1% | Minimal clipping |

### Warning Signs
- **p99 > 250**: Highlights clipping
- **p50 < 80**: Overall too dark
- **p01 < 5**: Shadows crushed (no detail)
- **sat > 5%**: Severe overexposure

---

## 🔧 Advanced Customization

### Modify Algorithm Behavior

Edit `AutoExposureOp._calculate_exposure()` in the script:

```python
# Example: Add more aggressive shadow lifting
if metrics['p01'] < 15:  # Changed from 10
    new = int(current * 1.12)  # Changed from 1.08
    logging.info(f"[AE] Lifting shadows aggressively...")
    return new
```

### Add Custom Metrics

```python
# In _analyze_brightness():
return {
    # ... existing metrics ...
    'p95': np.percentile(luminance, 95),  # Less extreme than p99
    'std': luminance.std(),  # Contrast measure
}
```

### Region-Based Metering (Center-Weighted)

```python
# In compute(), before _analyze_brightness():
h, w = luminance.shape
center_h, center_w = h//2, w//2
roi = luminance[center_h-h//4:center_h+h//4, center_w-w//4:center_w+w//4]
metrics = self._analyze_brightness(roi)  # Analyze center only
```

---

## 📝 Best Practices

1. **Start with defaults** - They work well for most scenes
2. **Tune incrementally** - Change one parameter at a time
3. **Monitor stats** - Watch the periodic output for patterns
4. **Scene-specific profiles** - Save tuned parameters as presets
5. **Validate results** - Use test patterns or known references

---

## 🎓 Example Workflow

```bash
# Step 1: Baseline test (defaults)
python linux_AE_player_imx258.py --fullscreen

# Step 2: Observe stats, identify issues
# Example output: "p50=65.2" (too dark)

# Step 3: Adjust targets
python linux_AE_player_imx258.py --fullscreen \
    --ae-target-median-low 80 \
    --ae-target-median-high 120

# Step 4: Fine-tune speed if needed
python linux_AE_player_imx258.py --fullscreen \
    --ae-target-median-low 80 \
    --ae-target-median-high 120 \
    --ae-adjustment-interval 5

# Step 5: Save working parameters as script/alias
```

---

## 📞 Support

For issues or questions:
1. Check troubleshooting section above
2. Enable verbose logging: `--log-level 10`
3. Monitor auto-exposure stats output
4. Review algorithm documentation in code comments

---

## 🔬 Technical Details

### Pipeline Integration
```
LinuxReceiverOperator 
    → CsiToBayerOp 
    → ImageProcessorOp 
    → BayerDemosaicOp 
    → AutoExposureOp ← (HERE: Analyzes RGB data)
    → HolovizOp
```

### Why After Demosaic?
- RGB data easier for luminance calculation
- Optical black correction already applied
- Accurate representation of final output
- Minimal pipeline impact (pass-through design)

### Performance Impact
- GPU→CPU transfer: ~2-5ms (downsampled)
- Analysis time: ~1-2ms (numpy operations)
- Camera I2C write: ~0.5ms
- **Total overhead: <10ms every 5 frames = <2ms/frame average**
- **FPS impact: <3% (60 FPS → 58-59 FPS)**

---

**Happy auto-exposing! 📸**
