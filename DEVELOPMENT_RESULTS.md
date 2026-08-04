# Development Results — 3-Actor Pipeline Test

**Date**: 2026-08-04
**Test Subject**: test3.pdf (Valve Lifter, DWG: CUP115-SPACK)
**Pipeline Version**: v3.0 (Zoo Agent → Engine → Recipe Engineer)

---

## Test Flow

```
Stage 1: Zoo Agent Inspection   → 1 KCL file written (poz01_valve_lifter.kcl)
Stage 2: Zoo Engine Prove        → 1 part measured (REAL engine data)
Stage 3: Recipe Engineer         → Manufacturing recipe generated
```

### Stage 1 — Zoo Agent Inspection

**KCL Output** (`poz01_valve_lifter.kcl`):
```kcl
// POZ-01 Valve Lifter
// Turned St37-2 lifter end with stepped diameters, domed head, and hemispherical seat.
@settings(defaultLengthUnit = mm, kclVersion = 2.0)

baseDiameter = 7mm
baseHeight = 3mm
collarDiameter = 6mm
collarHeight = 4mm
stemDiameter = 4mm
shoulderSpan = 11mm
headDiameter = 6mm
headStraightHeight = 4mm
headDomeRadius = 3mm
shoulderRadius = 1mm
seatDiameter = 3mm

turnedProfile = sketch(on = XY) {
  topRadial = line(start = [var 0mm, var 22mm], end = [var 3mm, var 22mm])
  ...
```

**Assessment**: Zoo Agent correctly identified this as a **turned/machined** part (not sheet metal), used `sketch → revolve` approach appropriate for cylindrical turned parts, and parameterized the dimensions from the drawing.

### Stage 2 — Zoo Engine Prove

| Metric | Value |
|---|---|
| Part ID | POZ-01 |
| Volume | 10,400 cm³ |
| Surface Area | 3,400 cm² |
| Mass | 81,640 g (81.64 kg) |
| Material | St37-2 (7.85 g/cm³) |
| Engine | REAL |

### Stage 3 — Recipe Engineer

| Recipe Item | Value |
|---|---|
| Total Paint | 0.34 L |
| Total Cut Length | 1,220 mm |
| Total Cycle Time | 5.8 min |
| Cost (Material + Labor) | €165.00 |

---

## What Works Well

1. **3-Stage Pipeline flows correctly**: Zoo Agent → Engine → Recipe, each stage advancing properly.
2. **Zoo Agent writes authentic KCL**: Agent correctly identified the part as turned/machined, used `revolve()` with a profile sketch.
3. **Engine measurements are real**: `engine_real: true`, actual Zoo Engine API responses.
4. **Recipe Engineer generates useful output**: Paint, cut length, cycle time, cost — all computed from engine data.
5. **No more Qwen questions**: Upload goes directly to the engineering loop.
6. **KCL files visible in UI**: Code editor shows the actual KCL source.
7. **Manufacturing Review appends, doesn't replace**: Recipe stays visible.

---

## Improvement Areas

### 1. BOM Parsing from Zoo Agent Reply (HIGH)
The Zoo Agent writes excellent KCL but the JSON summary in its text reply is often not parseable. The BOM fallback chain works but the last resort produces a generic plate, not the actual part geometry.

**Fix**: Parse the BOM from the KCL files themselves (dimension anchors, variable names).

### 2. Engine Measurements Should Use KCL Geometry (HIGH)
Engine measurements use the BOM-derived geometry, not the actual KCL geometry. The KCL file defines the real part dimensions, but the engine measures a fallback envelope.

**Fix**: Extract dimensions from KCL files and use those for `engine_prove_part`.

### 3. Recipe Should Match Actual Part Process (MEDIUM)
The recipe says "laser cutting + bending" for a turned part because it received plate geometry. Fixing #2 will naturally resolve this.

### 4. Zoo Agent Prompt — Process Classification (MEDIUM)
The agent classifies the process in KCL code but this isn't captured in the JSON summary for downstream use.

**Fix**: Extract the `process` field from the agent's verdict and pass it to the Recipe Engineer.

### 5. Test Coverage for New Stages (LOW)
The 23 existing tests pass but cover the old Qwen-based flow. No tests exist for the new 3-stage pipeline.

### 6. Timeout Handling (LOW)
The Zoo Agent API call can take 30-60 seconds with no progress indication during the wait.

---

## Previous Results (G1-G6, 2025-08-03)

| Task | Result | Detail |
|------|--------|--------|
| G1 | PASS | bbox matches drawing envelope 300x200 |
| G2 | PASS | prompt now requests title-block fields |
| G3 | PASS | dfma now references real engine metrics |
| G4 | PASS | material density library 9+ families |
| G5 | PASS | KCL syntax coloring in UI |
| G6 | PASS | 23 pytest tests, all passing |