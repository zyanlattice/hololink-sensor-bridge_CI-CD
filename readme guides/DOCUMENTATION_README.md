# Hololink Documentation - Getting Started

**Updated:** January 2026

This folder contains comprehensive documentation for the Hololink sensor bridge camera system and related verification tools.

---

## 📖 Documentation Files

### Essential Reading

| File | Purpose | Read Time |
|------|---------|-----------|
| [**QUICK_REFERENCE_CARD.md**](QUICK_REFERENCE_CARD.md) | Critical commands, fixes, and parameters | 5 min |
| [**DOCUMENTATION_INDEX.md**](DOCUMENTATION_INDEX.md) | Navigation guide and task reference | 10 min |
| [**DOCUMENTATION_CONSOLIDATION_SUMMARY.md**](DOCUMENTATION_CONSOLIDATION_SUMMARY.md) | What's new and how to use it | 5 min |

### Detailed Guides

| File | For | Pages |
|------|-----|-------|
| [**IMX258_CAMERA_VERIFICATION_GUIDE.md**](IMX258_CAMERA_VERIFICATION_GUIDE.md) | Camera setup, modes, verification | 15 |
| [**HOLOLINK_CORE_API_REFERENCE.md**](HOLOLINK_CORE_API_REFERENCE.md) | API documentation and examples | 14 |
| [**HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md**](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md) | Protocol, packets, registers | 16 |
| [**IMPLEMENTATION_BEST_PRACTICES.md**](IMPLEMENTATION_BEST_PRACTICES.md) | Design patterns, optimization | 20 |
| [**TROUBLESHOOTING_AND_FAQ.md**](TROUBLESHOOTING_AND_FAQ.md) | Common issues, solutions, FAQ | 18 |

---

## 🚀 Quick Start

### First Time Using Hololink?

1. **Read:** [QUICK_REFERENCE_CARD.md](QUICK_REFERENCE_CARD.md) (5 minutes)
   - Get critical commands and expectations
   - See what success looks like

2. **Reference:** [IMX258_CAMERA_VERIFICATION_GUIDE.md](IMX258_CAMERA_VERIFICATION_GUIDE.md)
   - Understand camera modes
   - Set up your mode

3. **Test:** Run verification
   ```bash
   python3 verify_camera_imx258.py --camera-mode 4 --frame-limit 300
   ```

4. **Verify:** Check results match [expected performance](QUICK_REFERENCE_CARD.md#expected-performance)

### Something Broken?

1. **Consult:** [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md)
2. **Find:** Your issue in "Quick Diagnostic Flowchart"
3. **Apply:** The solution from the table

### Building Something New?

1. **Learn:** [IMPLEMENTATION_BEST_PRACTICES.md](IMPLEMENTATION_BEST_PRACTICES.md)
2. **Reference:** [HOLOLINK_CORE_API_REFERENCE.md](HOLOLINK_CORE_API_REFERENCE.md)
3. **Check:** Examples and patterns

---

## 📋 What Gets You Going

### Essential Commands

```bash
# Single mode test (1920×1080@60fps)
python3 verify_camera_imx258.py --camera-mode 4 --frame-limit 300

# With visualization
python3 verify_camera_imx258.py --camera-mode 4 --holoviz --frame-limit 300

# Multi-mode test (recommended)
python3 verify_multi_mode_imx258.py

# With visualization
python3 verify_multi_mode_imx258.py --holoviz
```

### Expected Results (Mode 4)

```
Frame count: 300/300
Average FPS: 59.87
Max gap: 16.67ms
Dropped frames: 0
```

### Network Setup

```bash
# Configure host IP
sudo ip addr add 192.168.0.1/24 dev eth0

# Verify connectivity
ping 192.168.0.2
```

---

## 🎯 Documentation by Task

### I want to...

**Configure the camera for the first time**
→ [IMX258_CAMERA_VERIFICATION_GUIDE.md](IMX258_CAMERA_VERIFICATION_GUIDE.md) → "Camera Modes" + "Register Configuration"

**Verify my camera is working**
→ [IMX258_CAMERA_VERIFICATION_GUIDE.md](IMX258_CAMERA_VERIFICATION_GUIDE.md) → "Verification Procedures"

**Visualize camera output fullscreen**
→ [IMX258_CAMERA_VERIFICATION_GUIDE.md](IMX258_CAMERA_VERIFICATION_GUIDE.md) → "Verification Procedures" + [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md) → "Issue 2: Black Screen"

**Access registers (I2C/SPI)**
→ [HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md) → "Register Read/Write Operations"

**Test multiple camera modes**
→ [IMPLEMENTATION_BEST_PRACTICES.md](IMPLEMENTATION_BEST_PRACTICES.md) → "Multi-Mode Operation"

**Optimize performance**
→ [IMPLEMENTATION_BEST_PRACTICES.md](IMPLEMENTATION_BEST_PRACTICES.md) → "Performance Optimization" + [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md) → "Performance Troubleshooting"

**Debug a specific problem**
→ [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md) → "Quick Diagnostic Flowchart"

**Understand the API**
→ [HOLOLINK_CORE_API_REFERENCE.md](HOLOLINK_CORE_API_REFERENCE.md)

---

## ⚡ Critical Information

### Camera Modes
- **Mode 4:** 1920×1080@60fps ✓ Use this
- **Mode 5:** 4K@30fps ✓ Use this
- **Modes 2-3:** BROKEN ✗ Never use
- **Modes 0-1:** Valid but older

### Critical Cleanup Sequence (MUST be in order!)

```python
hololink.stop()                    # Step 1
app_thread.join(timeout=5.0)       # Step 2
Hololink.reset_framework()         # Step 3 - CRITICAL!
cuda.cuCtxDestroy(cu_context)     # Step 4
```

Wrong order → frame contamination to next run

### Fullscreen Visualization (Black Screen Fix)

```python
# MUST have BOTH:
generate_alpha=True          # Not False
alpha_value=65535           # Must be set
pool_size=width*height*4*2  # RGBA not RGB
```

### Expected Performance

| Mode | FPS | Frames | Max Gap |
|------|-----|--------|---------|
| 4 | 59.87 | 300/300 | <20ms |
| 5 | 29.94 | 300/300 | <40ms |

---

## 🔍 Troubleshooting in 30 Seconds

| Problem | Fix |
|---------|-----|
| **Can't detect device** | `ping 192.168.0.2` + check firewall |
| **Black screen** | `generate_alpha=True, alpha_value=65535` |
| **Low FPS** | Check network load + check reset_framework() |
| **Frame drops** | Increase socket buffer + verify cleanup |
| **Device hangs** | Add `socket.settimeout(5.0)` |
| **Image too dark** | `camera.set_exposure(0x0800)` |
| **Image too bright** | `camera.set_exposure(0x0400)` |

More details: [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md)

---

## 📚 Documentation Structure

```
Documentation (This Folder)
│
├─ Quick Start (Read First)
│  ├─ QUICK_REFERENCE_CARD.md ← Essential info
│  ├─ DOCUMENTATION_INDEX.md ← Navigation
│  └─ DOCUMENTATION_CONSOLIDATION_SUMMARY.md ← What's new
│
├─ Technical Guides (Deep Dives)
│  ├─ IMX258_CAMERA_VERIFICATION_GUIDE.md
│  ├─ HOLOLINK_CORE_API_REFERENCE.md
│  ├─ HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md
│  └─ IMPLEMENTATION_BEST_PRACTICES.md
│
└─ Problem Solving
   └─ TROUBLESHOOTING_AND_FAQ.md

Legend:
├─ Guides are cross-referenced
├─ Each guide has table of contents
├─ Contains code examples
└─ Includes diagnostic procedures
```

---

## 🔗 Document Cross-References

All documents link to each other. Common navigation:

- Start → [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)
- Problem → [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md)
- API → [HOLOLINK_CORE_API_REFERENCE.md](HOLOLINK_CORE_API_REFERENCE.md)
- Camera → [IMX258_CAMERA_VERIFICATION_GUIDE.md](IMX258_CAMERA_VERIFICATION_GUIDE.md)
- Implementation → [IMPLEMENTATION_BEST_PRACTICES.md](IMPLEMENTATION_BEST_PRACTICES.md)
- Protocol → [HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md)

---

## ✅ Pre-Deployment Checklist

- [ ] Read [QUICK_REFERENCE_CARD.md](QUICK_REFERENCE_CARD.md)
- [ ] Test Mode 4 → ≥300 frames, ≥59 FPS
- [ ] Test Mode 5 → ≥300 frames, ≥29 FPS
- [ ] Run [verify_multi_mode_imx258.py](verify_multi_mode_imx258.py) → all pass
- [ ] Fullscreen viz working (if needed)
- [ ] Image brightness acceptable
- [ ] Network stable (<50% utilization)
- [ ] Cleanup procedure verified
- [ ] No dropped frames (>1%)

See complete checklist: [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md#debugging-checklist)

---

## 📊 Documentation Statistics

- **Total guides:** 7 files
- **Total lines:** ~2000 lines
- **Code examples:** 20+
- **Tables/diagrams:** 15+
- **Covered topics:**
  - ✓ Camera configuration
  - ✓ Verification procedures
  - ✓ API documentation
  - ✓ Protocol and packets
  - ✓ Common issues (8 detailed)
  - ✓ Design patterns
  - ✓ Optimization techniques
  - ✓ Troubleshooting guide
  - ✓ FAQ (8 questions)

---

## 🆘 Getting Help

### For Setup Issues
→ [IMX258_CAMERA_VERIFICATION_GUIDE.md](IMX258_CAMERA_VERIFICATION_GUIDE.md)

### For API Questions
→ [HOLOLINK_CORE_API_REFERENCE.md](HOLOLINK_CORE_API_REFERENCE.md)

### For Communication Issues
→ [HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md)

### For Bugs/Errors
→ [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md)

### For Implementation Help
→ [IMPLEMENTATION_BEST_PRACTICES.md](IMPLEMENTATION_BEST_PRACTICES.md)

### For Navigation
→ [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)

---

## 💡 Tips

1. **Bookmark [QUICK_REFERENCE_CARD.md](QUICK_REFERENCE_CARD.md)** - Access critical info instantly
2. **Use [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)** for "By Task" navigation
3. **Keep [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md) handy** for quick fixes
4. **Copy code examples** from relevant guides
5. **Follow cleanup sequence exactly** - order matters!

---

## 📝 Version Information

| Document | Date | Status |
|----------|------|--------|
| QUICK_REFERENCE_CARD | Jan 2026 | ✓ Ready |
| DOCUMENTATION_INDEX | Jan 2026 | ✓ Ready |
| IMX258_CAMERA_VERIFICATION_GUIDE | Jan 2026 | ✓ Ready |
| HOLOLINK_CORE_API_REFERENCE | Jan 2026 | ✓ Ready |
| HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE | Jan 2026 | ✓ Ready |
| IMPLEMENTATION_BEST_PRACTICES | Jan 2026 | ✓ Ready |
| TROUBLESHOOTING_AND_FAQ | Jan 2026 | ✓ Ready |

---

## 🎯 Next Steps

1. **Read:** [QUICK_REFERENCE_CARD.md](QUICK_REFERENCE_CARD.md) (5 min)
2. **Navigate:** Use [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)
3. **Test:** Run `verify_camera_imx258.py --camera-mode 4`
4. **Refer:** Check relevant guide if you hit issues

---

**Questions?** Check [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) → "Quick Troubleshooting by Situation"

**All set?** Start with: `python3 verify_camera_imx258.py --camera-mode 4 --frame-limit 300`

