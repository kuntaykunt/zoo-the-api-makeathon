import io
import json
import re
import threading
import uuid

import fitz
import requests
from PIL import Image

from app.services.zoo_service import zoo_service
from app.services.zookeeper_service import zookeeper, run_parallel_part_tasks
from app.services.qwen_service import qwen_service

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
MAX_ITERATIONS = 3
BBOX_TOLERANCE = 0.20


def _parse_bbox(text) -> list:
    """Parse '496 x 260 x 132' / '496x260x132' / [496,260,132] into [L,W,H] floats."""
    if isinstance(text, (list, tuple)):
        nums = [float(x) for x in text[:3]]
        return nums if len(nums) == 3 else None
    if not text:
        return None
    text = str(text)
    nums = [float(x) for x in re.findall(r"[0-9]+(?:\.[0-9]+)?", text)]
    return nums[:3] if len(nums) >= 3 else None


def _parse_kcl_dimensions(kcl_source: str) -> dict:
    """Extract key dimensions from KCL variable assignments.

    Returns a dict with shape, L_mm, W_mm, T_mm, radius_mm, etc.
    """
    dims = {}
    diameters = []
    heights = []
    lengths = []
    widths = []
    thicknesses = []

    # Match variable = number (with optional unit suffix like mm)
    for m in re.finditer(r'(\w+)\s*=\s*([\d.]+)\s*mm?', kcl_source):
        name = m.group(1).lower()
        val = float(m.group(2))
        dims[f'_kcl_{name}'] = val

        # Collect by semantic category
        if any(kw in name for kw in ('diameter', 'dia', 'radius')):
            if 'radius' in name:
                dims['radius_mm'] = max(dims.get('radius_mm', 0), val)
            else:
                diameters.append(val)
        elif any(kw in name for kw in ('height', 'span', 'length', 'len')):
            if 'span' in name or 'length' in name or 'len' in name:
                lengths.append(val)
            else:
                heights.append(val)
        elif any(kw in name for kw in ('width', 'w')):
            widths.append(val)
        elif any(kw in name for kw in ('thickness', 'thick', 't')):
            thicknesses.append(val)

    # Compute derived dimensions
    if diameters:
        max_dia = max(diameters)
        dims['radius_mm'] = max(dims.get('radius_mm', 0), max_dia / 2.0)
    if heights:
        dims['T_mm'] = max(dims.get('T_mm', 0), sum(heights))
    if lengths:
        dims['L_mm'] = max(dims.get('L_mm', 0), max(lengths))
    if widths:
        dims['W_mm'] = max(dims.get('W_mm', 0), max(widths))
    if thicknesses:
        dims['T_mm'] = max(dims.get('T_mm', 0), max(thicknesses))

    # Detect shape: if radius found, likely cylinder/turned; otherwise plate
    if 'radius_mm' in dims:
        dims['shape'] = 'cylinder'
        dims.setdefault('L_mm', dims.get('radius_mm', 10) * 2)
        dims.setdefault('W_mm', dims.get('radius_mm', 10) * 2)
        dims.setdefault('T_mm', max(heights + lengths + [20]))
    else:
        dims['shape'] = 'plate'
        dims.setdefault('L_mm', max(lengths + [100]))
        dims.setdefault('W_mm', max(widths + [100]))
        dims.setdefault('T_mm', max(thicknesses + heights + [10]))

    return dims


def _extract_json(text: str) -> dict:
    """Pull the first balanced {...} JSON object out of an agent reply."""
    text = text.replace("```json", "```").replace("```", "")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    blob = text[start:end + 1]
    try:
        return json.loads(blob)
    except Exception:
        pass
    # fallback: try the last brace-group
    m = re.search(r"\{[^{}]*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def _pdf_page_png(file_path: str, dpi: int = 90) -> bytes:
    doc = fitz.open(file_path)
    pix = doc[0].get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _union_bbox(parts: list) -> list:
    """Bounding envelope of the assembly = max footprint + stacked thickness."""
    if not parts:
        return [0.0, 0.0, 0.0]
    max_x = 0.0
    max_y = 0.0
    sum_z = 0.0
    for p in parts:
        if p.get("shape") == "cylinder":
            r = float(p.get("radius_mm", 0.0))
            x, y, z = 2 * r, 2 * r, float(p.get("T_mm", 0.0))
        else:
            x = float(p.get("L_mm", 0.0))
            y = float(p.get("W_mm", 0.0))
            z = float(p.get("T_mm", 0.0))
        max_x = max(max_x, x)
        max_y = max(max_y, y)
        sum_z += z
    return [max_x, max_y, sum_z]


def _pct_err(measured: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return abs(measured - target) / target


def _json_safe(obj):
    """Recursively strip bytes / non-JSON values so sessions serialize cleanly."""
    if isinstance(obj, bytes):
        return None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


class EngineeringLoop:
    """Agentic engineering loop with three specialised actors:
    Zoo Agent (ML Copilot) — drawing inspection, BOM, KCL authoring
    Zoo Engine API — constraint check, debug, assembly
    Qwen (Reçete Mühendisi) — manufacturing recipe reasoning"""

    def create_session(self, initial_eval: dict, user_answers: dict, upload_path: str, file_bytes: bytes = b"") -> str:
        session_id = uuid.uuid4().hex[:12]
        vision = initial_eval.get("detected_parameters", {})
        tb = initial_eval.get("title_block", {})
        with SESSIONS_LOCK:
            SESSIONS[session_id] = {
                "id": session_id,
                "status": "idle",
                "iteration": 0,
                "max_iterations": MAX_ITERATIONS,
                "stage": "init",
                "stage_index": 0,
                "stages": [
                    "ZOO AGENT INSPECTION",
                    "ZOO ENGINE PROVE + DEBUG",
                    "RECIPE ENGINEER",
                ],
                "initial_eval": initial_eval,
                "user_answers": user_answers,
                "upload_path": upload_path,
                "file_bytes": file_bytes,
                "drawing_png": None,
                "classification": None,
                "target_bbox": _parse_bbox(vision.get("overall_dimensions")),
                "target_part_count": None,
                "material": user_answers.get("material") or tb.get("material_spec") or "St37-2",
                "thickness": float(user_answers.get("thickness", vision.get("thickness_mm") or 2.0)),
                "zookeeper_conv": None,
                "trace": [],
                "proposal": None,
                "measurements": [],
                "critic": None,
                "drawings": [],
                "final": False,
                "kcl_files": {},
                "recipe": None,
            }
        return session_id

    def get_state(self, session_id: str) -> dict:
        with SESSIONS_LOCK:
            s = SESSIONS.get(session_id)
            return _json_safe(dict(s) if s else None)

    def _trace(self, s: dict, event: str, detail: str, data: dict = None) -> None:
        s["trace"].append({
            "iteration": s["iteration"],
            "event": event,
            "detail": detail,
            "data": data or {},
        })

    def _propose(self, s: dict, feedback: str = None) -> dict:
        """Ask the Zookeeper design engineer for (or a revision of) the part plan."""
        session = zookeeper.open(s["zookeeper_conv"] or None)
        s["zookeeper_conv"] = session.conversation_id
        tb = s["initial_eval"].get("title_block", {})
        vision = s["initial_eval"].get("detected_parameters", {})
        kind = "assembly" if s["initial_eval"].get("is_assembly") else "part"
        target = s["target_bbox"] or [400.0, 260.0, 100.0]

        if not feedback:
            if s["drawing_png"] is None:
                s["drawing_png"] = _pdf_page_png(s["upload_path"])
            base = f"""
You are the lead design engineer for '{tb.get('part_name', 'Drawing')}' (DWG {tb.get('drawing_number', 'N/A')}).
Material: {s['material']} | Sheet thickness: {s['thickness']}mm | Drawing target envelope: {target} mm (L x W x H).

Look at the attached technical drawing image. Decompose this {kind} into its
welded / laser-cut / turned parts (plates, caps, cylinders). The UNION of the
parts must reproduce the target envelope {target} closely.

Return ONLY this JSON (no prose, no markdown):
{{
  "parts": [
    {{"id":"POZ-01","name":"<part name>","shape":"plate","L_mm":<mm>,"W_mm":<mm>,"T_mm":<mm>,"qty":1}},
    {{"id":"POZ-02","name":"<part name>","shape":"cylinder","radius_mm":<mm>,"T_mm":<mm>,"qty":1}}
  ],
  "assembly_bbox_mm": [<L>,<W>,<H>],
  "manufacturing_notes": "welding/laser-cut/bend ..."
}}
Rules:
- shape is "plate" (rectangle footprint L x W, thickness T) or "cylinder" (radius r, height T).
- Use sheet thickness {s['thickness']}mm for plates unless the drawing shows a thicker plate.
- 2..8 parts, realistic industrial sizes in mm.
- Numbers only; JSON only.
"""
            content = base
        else:
            content = feedback

        result = session.prompt(content, files=(
            [{"name": "drawing.png", "mimetype": "image/png", "data": list(s["drawing_png"])}] if not feedback else []
        ), mode="thoughtful")
        session.close()

        proposal = _extract_json(result["reply"])
        if not proposal or not proposal.get("parts"):
            proposal = self._bom_part_plan(s)
        self._trace(s, "engineer", "Zookeeper engineer proposal received", {
            "raw": result["reply"][:600],
            "proposal": proposal,
        })
        return proposal

    def _bom_part_plan(self, s: dict) -> dict:
        """Fallback part plan built from the Qwen classify_drawing BOM.

        Used when the Zookeeper engineer returns no parseable JSON so the
        engineering loop can still progress on assembly drawings.
        """
        verdict = s.get("classification") or {}
        bom = verdict.get("bom") or []
        # If Zoo Agent verdict has no BOM, fall back to Qwen initial_eval
        if not bom:
            bom = s["initial_eval"].get("title_block", {}).get("bom") or []
        if not bom:
            bom = s["initial_eval"].get("detected_parameters", {}).get("bom") or []
        target = s.get("target_bbox") or [400.0, 260.0, 100.0]
        try:
            thickness = float(s.get("thickness") or 2.0)
        except (TypeError, ValueError):
            thickness = 2.0

        def _num(val, default):
            try:
                v = float(str(val).replace(",", ".").strip())
                return v if v > 0 else default
            except (TypeError, ValueError):
                return default

        parts = []
        for i, entry in enumerate(bom, 1):
            entry = entry if isinstance(entry, dict) else {}
            poz = str(entry.get("poz") or entry.get("id") or f"POZ-{i:02d}").strip() or f"POZ-{i:02d}"
            name = str(entry.get("name") or entry.get("description") or f"Part {i}").strip()
            qty = int(_num(entry.get("qty") or entry.get("quantity") or 1, 1))
            parts.append({
                "id": poz,
                "name": name,
                "shape": "plate",
                "L_mm": round(_num(entry.get("L_mm") or entry.get("length_mm"), float(target[0]) / 2.0), 2),
                "W_mm": round(_num(entry.get("W_mm") or entry.get("width_mm"), float(target[1]) / 2.0), 2),
                "T_mm": round(_num(entry.get("T_mm") or entry.get("thickness_mm"), thickness), 2),
                "qty": max(1, qty),
            })
        if not parts:
            return {}
        return {
            "parts": parts,
            "assembly_bbox_mm": [float(target[0]), float(target[1]), float(target[2])],
            "manufacturing_notes": "Fallback plan derived from Qwen OCR BOM; laser-cut plates, welded assembly.",
        }

    def _write_kcl(self, s: dict) -> str:
        """Ask the Zoo KCL agent (Zookeeper edit_kcl_code tool) to write the
        authentic, engine-valid KittyCAD KCL for the final assembly. The tool's
        `outputs` come back already compiled by Zoo's own engine."""
        tb = s["initial_eval"].get("title_block", {})
        parts = (s.get("proposal") or {}).get("parts") or []
        plan_lines = []
        for i, p in enumerate(parts, 1):
            if p.get("shape") == "cylinder":
                plan_lines.append(
                    f"POZ-{i:02d} {p.get('name', '')}: cylinder radius {p.get('radius_mm', 0)}mm, height {p.get('T_mm', 0)}mm")
            else:
                plan_lines.append(
                    f"POZ-{i:02d} {p.get('name', '')}: plate {p.get('L_mm', 0)}mm x {p.get('W_mm', 0)}mm x {p.get('T_mm', 0)}mm")
        bbox = [round(x, 1) for x in (s.get("assembly_bbox_mm") or [0, 0, 0])]

        prompt = (
            f"You are the Zoo KCL agent for '{tb.get('part_name', 'Assembly')}' (DWG {tb.get('drawing_number', 'N/A')}), "
            f"material {s['material']}, sheet thickness {s['thickness']}mm, assembly envelope {bbox} mm (L x W x H).\n"
            "Part plan:\n" + "\n".join(plan_lines) + "\n\n"
            "Using the edit_kcl_code tool, write the complete KittyCAD KCL for the PRIMARY structural part "
            "(POZ-01, the main housing body) into main.kcl. Use sketch/region/extrude, mm units, "
            "@settings(defaultLengthUnit = mm, kclVersion = 2.0). The KCL must compile. "
            "Then reply with a one-line summary of what you wrote."
        )
        session = zookeeper.open(s["zookeeper_conv"])
        result = session.prompt(prompt, forced_tools=["edit_kcl_code"], mode="thoughtful")
        session.close()

        kcl = ""
        for name, src in (result.get("kcl_files") or {}).items():
            if name.endswith(".kcl"):
                kcl = src
                break
        if not kcl:
            kcl = result.get("reply", "")
        kcl = kcl.strip()
        if kcl.startswith("```"):
            kcl = kcl.strip("`").replace("kcl", "", 1).strip()
        s["kcl_code"] = kcl
        self._trace(s, "kcl_agent", "Zoo KCL agent (edit_kcl_code) wrote authentic KCL",
                    {"kcl_length": len(kcl), "kcl_preview": kcl[:200]})
        return kcl

    def _critic(self, s: dict, measured: list, proposal: dict) -> dict:
        target = s["target_bbox"]
        if not target:
            target = _parse_bbox(proposal.get("assembly_bbox_mm")) or measured
        errs = {d: _pct_err(measured[i], target[i]) for i, d in enumerate(["L", "W", "H"])}
        tol = BBOX_TOLERANCE
        failed = [d for d, e in errs.items() if e > tol]
        pass_ = not failed
        feedback = None
        if not pass_:
            feedback = f"""
The proposed assembly is INCONSISTENT with the drawing. Measured assembly bbox
= {[round(m, 1) for m in measured]} mm but drawing target = {[round(t, 1) for t in target]} mm.
Dimension errors: L {errs['L']*100:.0f}%, W {errs['W']*100:.0f}%, H {errs['H']*100:.0f}%.
Adjust the part dimensions (and count) so the UNION of parts reproduces the
target {[round(t, 1) for t in target]}. Respond with ONLY the revised JSON (same schema)."""
        return {
            "pass": pass_,
            "target_bbox": target,
            "measured_bbox": [round(m, 1) for m in measured],
            "errors": {d: round(e * 100, 1) for d, e in errs.items()},
            "tolerance_pct": tol * 100,
            "feedback": feedback,
        }

    def run_iteration(self, session_id: str) -> dict:
        with SESSIONS_LOCK:
            s = SESSIONS.get(session_id)
            if s is None:
                return {"error": "session not found"}
            if s["final"]:
                return {"done": True, "state": _json_safe(s)}
            s["status"] = "running"
            s["iteration"] += 1

        stage = s.get("stage", "init")
        try:
            if stage in ("init", "inspect"):
                return self._stage_zoo_inspect(s)
            if stage == "engine":
                return self._stage_engine_prove(s)
            if stage == "recipe":
                return self._stage_qwen_recipe(s)
        except Exception as e:
            s["status"] = "error"
            s["trace"].append({"iteration": s["iteration"], "event": "error", "detail": str(e)})
            return {"done": True, "error": str(e), "state": _json_safe(s)}
        return {"done": True, "error": "unknown stage", "state": _json_safe(s)}

    # ---- Stage 1: Zoo Agent inspection — BOM, classification, KCL per part ----
    def _stage_zoo_inspect(self, s: dict) -> dict:
        s["stage"] = "inspect"
        s["stage_index"] = 1
        if s["drawing_png"] is None:
            s["drawing_png"] = _pdf_page_png(s["upload_path"])

        tb = s["initial_eval"].get("title_block", {})
        target = s["target_bbox"] or [400.0, 260.0, 100.0]

        prompt = f"""You are a senior CAD manufacturing engineer. Inspect this technical drawing.

Part name: {tb.get('part_name', 'Drawing')}
Drawing number: {tb.get('drawing_number', 'N/A')}
Material: {s['material']}

Step 1 — CLASSIFY: Is this a single part, an assembly, or non-manufacturable?
  Also identify the MANUFACTURING PROCESS: sheet-metal (laser-cut/bend/weld), machined (turned/milled),
  cast, forged, or a combination. This determines how we model the parts.

Step 2 — BOM: Extract every POZ (part position) with its name, qty, and dominant process
  (laser-cut, turn, mill, cast, weld, bend, etc.).

Step 3 — KCL: For each POZ, write a valid KittyCAD KCL file using the edit_kcl_code tool.
  - Name files: poz01_<name>.kcl, poz02_<name>.kcl, etc.
  - Use sketch/region/extrude/revolve, mm units, @settings(defaultLengthUnit = mm, kclVersion = 2.0)
  - Each file: ONE solid, no piping of extruded solids
  - For turned/machined cylindrical parts: use revolve() with a profile sketch
  - For cast parts: model as solid blocks with appropriate fillets
  - Start from origin, we'll position parts in assembly later

Step 4 — ASSEMBLY KCL: Write a main.kcl that imports all POZ KCL files and positions them.

Step 5 — Return a JSON summary:
{{
  "classification": "single" | "assembly" | "non_manufacturable",
  "manufacturable": true | false,
  "process": "sheet-metal" | "machined" | "cast" | "forged" | "mixed",
  "bom": [{{"poz":"POZ-01","name":"...","qty":1,"process":"turn"}}, ...],
  "assembly_bbox_mm": [L, W, H],
  "notes": "<one line summary>"
}}

IMPORTANT: Use edit_kcl_code for EVERY KCL file. Write ALL parts before returning the JSON summary."""
        sess = zookeeper.open(s["zookeeper_conv"] or None)
        s["zookeeper_conv"] = sess.conversation_id
        result = sess.prompt(
            prompt,
            files=[{"name": "drawing.png", "mimetype": "image/png", "data": list(s["drawing_png"])}],
            mode="thoughtful",
            forced_tools=["edit_kcl_code"],
        )
        sess.close()

        s["kcl_files"] = result.get("kcl_files") or {}
        reply_raw = result.get("reply", "")
        s["trace"].append({
            "iteration": s["iteration"], "event": "zoo_inspect",
            "detail": f"Zoo Agent inspection complete; {len(s['kcl_files'])} KCL files written",
            "data": {"kcl_files": list(s["kcl_files"].keys()), "reply": reply_raw[:500]},
        })

        # Parse classification + BOM from agent reply — fall back to Qwen initial_eval
        verdict = _extract_json(reply_raw)
        if not verdict.get("bom"):
            # Fallback: use Qwen's initial evaluation BOM
            qwen_bom = s["initial_eval"].get("title_block", {}).get("bom") or []
            if not qwen_bom:
                qwen_bom = s["initial_eval"].get("detected_parameters", {}).get("bom") or []
            if qwen_bom:
                verdict["bom"] = qwen_bom
                s["trace"].append({"iteration": s["iteration"], "event": "zoo_inspect",
                                   "detail": f"Zoo Agent JSON incomplete; using Qwen BOM fallback ({len(qwen_bom)} items)"})
        s["classification"] = verdict
        if verdict.get("assembly_bbox_mm"):
            s["target_bbox"] = _parse_bbox(verdict["assembly_bbox_mm"])
        if not verdict.get("manufacturable", True):
            s["status"] = "done"
            s["final"] = True
            s["stage"] = "done"
            return {"done": True, "state": _json_safe(s), "verdict": verdict}

        # Build part plan from BOM for engine proving
        bom = verdict.get("bom") or []
        if bom:
            parts = self._bom_part_plan(s)
            if parts.get("parts"):
                s["proposal"] = parts
            else:
                s["proposal"] = {"parts": bom}
        else:
            # Try to build part plan from KCL files directly
            kcl_parts = []
            for fname, src in s["kcl_files"].items():
                if not isinstance(src, str) or not src.strip():
                    continue
                dims = _parse_kcl_dimensions(src)
                poz_id = f"POZ-{len(kcl_parts)+1:02d}"
                # Extract part name from filename
                part_name = fname.replace('.kcl', '').replace('poz01_', '').replace('poz02_', '').replace('_', ' ').title()
                kcl_parts.append({
                    "id": poz_id,
                    "name": part_name or f"Part {len(kcl_parts)+1}",
                    "shape": dims.get("shape", "plate"),
                    "L_mm": dims.get("L_mm", 100),
                    "W_mm": dims.get("W_mm", 100),
                    "T_mm": dims.get("T_mm", 10),
                    "radius_mm": dims.get("radius_mm"),
                    "qty": 1,
                })
            if kcl_parts:
                bbox = _union_bbox(kcl_parts)
                s["proposal"] = {
                    "parts": kcl_parts,
                    "assembly_bbox_mm": bbox,
                    "manufacturing_notes": "Auto-generated from KCL file dimensions.",
                }
                s["trace"].append({"iteration": s["iteration"], "event": "zoo_inspect",
                                   "detail": f"Built part plan from KCL dimensions: {len(kcl_parts)} parts, bbox {bbox}"})
            else:
                # Last resort: single-part plan from drawing envelope
                target = s["target_bbox"] or [400.0, 260.0, 100.0]
                part_name = tb.get("part_name", "Part")
                s["proposal"] = {
                    "parts": [{
                        "id": "POZ-01",
                        "name": part_name,
                        "shape": "plate",
                        "L_mm": float(target[0]),
                        "W_mm": float(target[1]),
                        "T_mm": float(target[2]) if len(target) > 2 else s["thickness"],
                        "qty": 1,
                    }],
                    "assembly_bbox_mm": [float(target[0]), float(target[1]), float(target[2]) if len(target) > 2 else s["thickness"]],
                    "manufacturing_notes": "Auto-generated single-part plan from drawing envelope.",
                }
                s["trace"].append({"iteration": s["iteration"], "event": "zoo_inspect",
                                   "detail": f"No BOM or KCL dims available; created single-part plan from envelope {target}"})

        s["stage"] = "engine"
        return {"done": False, "state": _json_safe(s)}

    # ---- Stage 2: Zoo Engine proves every part, debug loop, assembly ----
    def _stage_engine_prove(self, s: dict) -> dict:
        s["stage"] = "engine"
        s["stage_index"] = 2

        parts = (s.get("proposal") or {}).get("parts") or []
        kcl_files = s.get("kcl_files") or {}

        # If no KCL files from agent, try to generate from part plan
        if not kcl_files and parts:
            try:
                kcl = self._write_kcl(s)
                if kcl:
                    kcl_files["main.kcl"] = kcl
                    s["kcl_files"] = kcl_files
            except Exception as e:
                s["trace"].append({"iteration": s["iteration"], "event": "error",
                                   "detail": f"KCL synthesis error: {e}"})

        # Engine prove: measure every part
        measurements = []
        for p in parts:
            try:
                m = zoo_service.engine_prove_part(p, s["material"])
                m["qty"] = p.get("qty", 1)
                measurements.append(m)
            except Exception as e:
                s["trace"].append({"iteration": s["iteration"], "event": "error",
                                   "detail": f"Engine prove failed for {p.get('id')}: {e}"})
                measurements.append({
                    "part_id": p.get("id", "POZ-00"),
                    "name": p.get("name", ""),
                    "engine_real": False,
                    "volume_cm3": 0, "surface_area_cm2": 0, "mass_grams": 0,
                    "qty": p.get("qty", 1),
                })
        s["measurements"] = measurements

        measured_bbox = _union_bbox(parts)
        total_mass = sum(m.get("mass_grams", 0) * m.get("qty", 1) for m in measurements)
        s["total_mass_g"] = round(total_mass, 2)
        s["assembly_bbox_mm"] = measured_bbox

        # Run the critic for envelope matching
        s["critic"] = self._critic(s, measured_bbox, s.get("proposal") or {})

        # Debug loop: if KCL files exist but engine found issues, let agent fix
        if kcl_files and not s["critic"].get("pass") and s["iteration"] < s["max_iterations"]:
            kcl_list = "\n".join(f"// {name}:\n{src[:500]}" for name, src in kcl_files.items())
            fix_prompt = f"""The assembly envelope is off. Target: {s['target_bbox']} mm, Measured: {measured_bbox} mm.
Fix the KCL files so the union of all parts matches the target envelope.
Use edit_kcl_code to update the files.

Current KCL files:
{kcl_list}"""
            sess = zookeeper.open(s["zookeeper_conv"] or None)
            s["zookeeper_conv"] = sess.conversation_id
            fix_result = sess.prompt(fix_prompt, mode="thoughtful", forced_tools=["edit_kcl_code"])
            sess.close()
            if fix_result.get("kcl_files"):
                s["kcl_files"].update(fix_result["kcl_files"])
                s["trace"].append({"iteration": s["iteration"], "event": "engine_debug",
                                   "detail": f"Agent fixed {len(fix_result['kcl_files'])} KCL files"})

        s["trace"].append({
            "iteration": s["iteration"], "event": "engine_prove",
            "detail": f"Engine proved {len(measurements)} parts; total mass {s['total_mass_g']}g; "
                      f"envelope: {measured_bbox} mm (target {s['target_bbox']})",
            "data": {"critic": s["critic"], "total_mass_g": s["total_mass_g"]},
        })

        s["stage"] = "recipe"
        return {"done": False, "state": _json_safe(s)}

    # ---- Stage 3: Qwen Reçete Mühendisi — manufacturing recipe ----
    def _stage_qwen_recipe(self, s: dict) -> dict:
        s["stage"] = "recipe"
        s["stage_index"] = 3

        measurements = s.get("measurements") or []
        parts = (s.get("proposal") or {}).get("parts") or []
        verdict = s.get("classification") or {}
        tb = s["initial_eval"].get("title_block", {})

        # Build a rich context for Qwen to reason about manufacturing
        part_details = []
        for m in measurements:
            pid = m.get("part_id", "?")
            name = m.get("name", "")
            p = next((pp for pp in parts if pp.get("id") == pid), {})
            proc = ""
            for b in (verdict.get("bom") or []):
                if b.get("poz") == pid:
                    proc = b.get("process", "")
                    break
            part_details.append({
                "poz": pid,
                "name": name,
                "shape": p.get("shape", m.get("shape", "plate")),
                "qty": m.get("qty", p.get("qty", 1)),
                "volume_cm3": m.get("volume_cm3", 0),
                "surface_area_cm2": m.get("surface_area_cm2", 0),
                "mass_grams": m.get("mass_grams", 0),
                "process": proc,
            })

        recipe_prompt = f"""You are a senior manufacturing recipe engineer (Reçete Mühendisi).
Review the following engineered assembly and produce a detailed manufacturing plan.

PART: {tb.get('part_name', 'Assembly')}
DWG: {tb.get('drawing_number', 'N/A')}
MATERIAL: {s['material']}
ASSEMBLY ENVELOPE: {s.get('assembly_bbox_mm')} mm
TOTAL MASS: {s.get('total_mass_g')} g

ENGINE-MEASURED PARTS:
{json.dumps(part_details, indent=2)}

For each POZ, calculate and recommend:
1. SURFACE FINISHING: If the part needs painting/coating, calculate paint required
   (surface_area_cm2 × qty → total area → paint volume in liters)
2. CUTTING: If laser-cut, calculate total cut length (perimeter = 2×(L+W) for plates,
   circumference = 2πr for cylinders) and estimated cycle time
3. BENDING: If bent, count bends and estimate press brake time
4. WELDING: If welded assembly, estimate weld seam length and time
5. ASSEMBLY SEQUENCE: The order parts should be manufactured and assembled
6. COST ESTIMATE: Rough material + labor cost per part

Return ONLY this JSON:
{{
  "recipe": {{
    "total_paint_liters": <float>,
    "total_cut_length_mm": <float>,
    "total_cycle_time_min": <float>,
    "assembly_sequence": ["POZ-01: ...", "POZ-02: ..."],
    "cost_estimate": {{"material": "<currency>", "labor": "<currency>", "total": "<currency>"}}
  }},
  "parts": [
    {{
      "poz": "POZ-01",
      "paint_required_liters": <float or 0>,
      "cut_length_mm": <float or 0>,
      "bend_count": <int>,
      "process_time_min": <float>,
      "notes": "<one line manufacturing note>"
    }}
  ],
  "summary": "<one paragraph manufacturing summary in technical tone>"
}}"""

        try:
            headers = {
                "Authorization": f"Bearer {qwen_service.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": qwen_service.model,
                "messages": [{"role": "user", "content": recipe_prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }
            res = requests.post(
                f"{qwen_service.base_url}/chat/completions",
                headers=headers, json=payload, timeout=30,
            )
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                recipe = json.loads(content)
            else:
                recipe = {"error": f"Qwen API {res.status_code}", "summary": "Recipe generation failed."}
        except Exception as e:
            recipe = {"error": str(e), "summary": "Recipe generation failed."}

        s["recipe"] = recipe
        s["status"] = "done"
        s["final"] = True
        s["stage"] = "done"

        s["trace"].append({
            "iteration": s["iteration"], "event": "qwen_recipe",
            "detail": recipe.get("summary", "Manufacturing recipe generated"),
            "data": {"recipe": recipe},
        })

        return {"done": True, "state": _json_safe(s)}


engineering_loop = EngineeringLoop()