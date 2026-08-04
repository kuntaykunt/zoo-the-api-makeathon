import io
import json
import re
import threading
import uuid

import fitz
from PIL import Image

from app.services.zoo_service import zoo_service
from app.services.zookeeper_service import zookeeper, run_parallel_part_tasks
from app.services.qwen_service import qwen_service
from app.services.drawing_service import drawing_service

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
    """Agentic engineering loop: Zookeeper (design engineer) proposes the part
    breakdown of the drawing -> Zoo Engine measures every part for real ->
    a critic compares the measured assembly envelope to the vision-derived
    target and feeds the discrepancy back -> iterates until consistent ->
    renders 2D technical drawings."""

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
                    "QWEN OCR + VERDICT",
                    "ZOOKEEPER COUNCIL (briefing)",
                    "PARALLEL PART TASKS",
                    "COUNCIL REVIEW",
                    "ENGINE API KCL SYNTHESIS",
                    "KCL DEBUG / VERIFY LOOP",
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

        # ---- Stage machine: advance one stage per iterate call ----
        stage = s.get("stage", "init")
        try:
            if stage in ("init", "qwen"):
                return self._stage_qwen_verdict(s)
            if stage == "council":
                return self._stage_council(s)
            if stage == "parallel":
                return self._stage_parallel_parts(s)
            if stage == "review":
                return self._stage_council_review(s)
            if stage == "kcl":
                return self._stage_kcl_synthesis(s)
            if stage == "debug":
                return self._stage_kcl_debug(s)
        except Exception as e:
            s["status"] = "error"
            s["trace"].append({"iteration": s["iteration"], "event": "error", "detail": str(e)})
            return {"done": True, "error": str(e), "state": _json_safe(s)}
        # Fallback (legacy single-propose path)
        return self._legacy_iteration(s)

    # ---- Stage 0: Qwen OCR + verdict ----
    def _stage_qwen_verdict(self, s: dict) -> dict:
        s["stage"] = "qwen"
        s["stage_index"] = 1
        fb = s["file_bytes"] or b""
        if not fb and s.get("upload_path"):
            try:
                with open(s["upload_path"], "rb") as fh:
                    fb = fh.read()
            except Exception:
                fb = b""
        verdict = qwen_service.classify_drawing(fb, s["initial_eval"].get("file_name", ""))
        s["classification"] = verdict
        s["trace"].append({
            "iteration": s["iteration"], "event": "qwen_verdict",
            "detail": f"classification={verdict.get('classification')} manufacturable={verdict.get('manufacturable')} conf={verdict.get('confidence')}",
            "data": {"verdict": verdict},
        })
        if not verdict.get("manufacturable", False):
            s["status"] = "done"
            s["final"] = True
            s["stage"] = "done"
            return {"done": True, "state": _json_safe(s), "verdict": verdict}
        # Proceed to council
        s["stage"] = "council"
        return {"done": False, "state": _json_safe(s), "verdict": verdict}

    # ---- Stage 1: Zookeeper Council (briefing) ----
    def _stage_council(self, s: dict) -> dict:
        s["stage"] = "council"
        s["stage_index"] = 2
        verdict = s.get("classification") or {}
        bom = verdict.get("bom") or []
        tb = s["initial_eval"].get("title_block", {})
        target = s["target_bbox"] or [400.0, 260.0, 100.0]
        kind = "assembly" if verdict.get("classification") == "assembly" else "single part"
        prompt = f"""You are the Zoo Agent Council (lead design engineers). Review this {kind} drawing.

Title block: {tb}
Material: {s['material']} | Sheet thickness: {s['thickness']}mm
Drawing target envelope: {target} mm (L x W x H)
Qwen verdict: {verdict.get('classification')} (conf {verdict.get('confidence')})
BOM from Qwen OCR: {bom}

Define the engineering targets for the loop:
- expected part count (POZ count) and per-part role
- total target mass (g) and total target volume (cm3) budget
- the assembly envelope the UNION of parts must reproduce
- key manufacturing processes (laser-cut / bend / turn / weld / cast)

Return ONLY JSON:
{{"target_part_count":<n>, "total_mass_g_target":<g>, "total_volume_cm3_target":<cm3>,
  "assembly_bbox_mm":[L,W,H], "processes":[...], "council_notes":"<one line>"}}"""
        sess = zookeeper.open(s["zookeeper_conv"] or None)
        s["zookeeper_conv"] = sess.conversation_id
        result = sess.prompt(prompt, files=([{"name": "drawing.png", "mimetype": "image/png", "data": list(s["drawing_png"])}] if s.get("drawing_png") else []), mode="thoughtful")
        sess.close()
        council = _extract_json(result.get("reply", ""))
        s["council"] = council
        if council.get("assembly_bbox_mm"):
            s["target_bbox"] = _parse_bbox(council["assembly_bbox_mm"])
        if council.get("target_part_count"):
            s["target_part_count"] = int(council["target_part_count"])
        s["trace"].append({"iteration": s["iteration"], "event": "council", "detail": "Council briefing complete", "data": {"council": council}})
        s["stage"] = "parallel"
        return {"done": False, "state": _json_safe(s)}

    # ---- Stage 2: Parallel part tasks ----
    def _stage_parallel_parts(self, s: dict) -> dict:
        s["stage"] = "parallel"
        s["stage_index"] = 3
        # Build the part plan (use Qwen BOM if assembly, else propose)
        proposal = self._propose(s)
        if not proposal or not proposal.get("parts"):
            fb = self._bom_part_plan(s)
            if fb.get("parts"):
                proposal = fb
                s["trace"].append({"iteration": s["iteration"], "event": "fallback",
                                   "detail": f"Zookeeper returned no plan; using Qwen BOM fallback ({len(fb['parts'])} parts)",
                                   "data": {"proposal": fb}})
            else:
                s["status"] = "error"
                s["trace"].append({"iteration": s["iteration"], "event": "error", "detail": "No part plan from council/propose"})
                return {"done": True, "error": "No part plan generated", "state": _json_safe(s)}
        s["proposal"] = proposal
        parts = proposal["parts"]
        # Concurrent Zookeeper sessions, one task per part
        tasks = []
        for p in parts:
            tasks.append({
                "prompt": f"""You are a part design agent. Design POZ {p.get('id')} named '{p.get('name')}'.
Material: {s['material']}, thickness {s['thickness']}mm. This part must fit the assembly envelope.
Geometry: {p}. Produce a precise engineering spec + a minimal KittyCAD KCL sketch for THIS part only.
Return JSON: {{"id":"{p.get('id')}","name":"{p.get('name')}","shape":"{p.get('shape')}","L_mm":..,"W_mm":..,"T_mm":..,"radius_mm":..,"qty":{p.get('qty',1)},"kcl_code":"<kcl>","notes":"<one line>"}}""",
                "files": None,
                "mode": "thoughtful",
                "forced_tools": None,
            })
        s["trace"].append({"iteration": s["iteration"], "event": "parallel", "detail": f"Dispatching {len(tasks)} parallel part tasks to Zoo Agent"})
        results = run_parallel_part_tasks(tasks, max_workers=min(4, len(tasks)))
        designed = []
        for r, p in zip(results, parts):
            pj = _extract_json(r.get("reply", ""))
            if pj:
                pj["kcl_code"] = pj.get("kcl_code") or ""
                designed.append(pj)
            else:
                designed.append(p)
        s["designed_parts"] = designed
        s["trace"].append({"iteration": s["iteration"], "event": "parallel", "detail": f"{len(designed)} part designs received", "data": {"parts": designed}})
        s["stage"] = "review"
        return {"done": False, "state": _json_safe(s)}

    # ---- Stage 3: Council Review (cross-check Qwen BOM + measurements) ----
    def _stage_council_review(self, s: dict) -> dict:
        s["stage"] = "review"
        s["stage_index"] = 4
        designed = s.get("designed_parts") or []
        # Real engine measurement of every part
        measurements = []
        for p in designed:
            m = zoo_service.engine_prove_part(p, s["material"])
            m["qty"] = p.get("qty", 1)
            measurements.append(m)
        s["measurements"] = measurements
        measured_bbox = _union_bbox([{**p, "qty": 1} for p in designed])
        total_mass = sum(m["mass_grams"] * m["qty"] for m in measurements)
        s["total_mass_g"] = round(total_mass, 2)
        s["assembly_bbox_mm"] = measured_bbox
        # Council reviews against Qwen BOM + targets
        verdict = s.get("classification") or {}
        qwen_bom = {b.get("poz"): b for b in (verdict.get("bom") or [])}
        review_prompt = f"""Zoo Agent Council REVIEW.
Expected BOM (from Qwen OCR): {verdict.get('bom')}
Designed parts: {designed}
Engine measurements: {measurements}
Total measured mass: {s['total_mass_g']} g | target: {s.get('council', {}).get('total_mass_g_target')}
Measured assembly envelope: {measured_bbox} mm | target: {s['target_bbox']}

Verify:
- POZ ids/qty match the BOM
- total mass within 15% of target
- assembly envelope reproduces the drawing target
Return ONLY JSON: {{"pass":true/false,"discrepancies":["..."],"feedback":"<if fail, what to adjust>"}}"""
        sess = zookeeper.open(s["zookeeper_conv"] or None)
        s["zookeeper_conv"] = sess.conversation_id
        result = sess.prompt(review_prompt, mode="thoughtful")
        sess.close()
        review = _extract_json(result.get("reply", ""))
        s["critic"] = review
        s["trace"].append({"iteration": s["iteration"], "event": "council_review", "detail": f"PASS={review.get('pass')}", "data": {"review": review}})
        if review.get("pass") or s["iteration"] >= s["max_iterations"]:
            s["stage"] = "kcl"
        else:
            # feedback loop: re-run parallel design with critic feedback
            s["critic_feedback"] = review.get("feedback", "Adjust parts to match BOM and targets.")
            s["stage"] = "parallel"
        return {"done": False, "state": _json_safe(s)}

    # ---- Stage 4: Engine API KCL synthesis ----
    def _stage_kcl_synthesis(self, s: dict) -> dict:
        s["stage"] = "kcl"
        s["stage_index"] = 5
        try:
            kcl = self._write_kcl(s)
            s["kcl_code"] = kcl
            s["trace"].append({"iteration": s["iteration"], "event": "kcl_synthesis", "detail": "Assembly KCL written by Zoo KCL agent", "data": {"kcl_length": len(kcl)}})
        except Exception as e:
            s["trace"].append({"iteration": s["iteration"], "event": "error", "detail": f"KCL synthesis error: {e}"})
            s["kcl_code"] = s.get("kcl_code") or ""
        s["stage"] = "debug"
        return {"done": False, "state": _json_safe(s)}

    # ---- Stage 5: KCL Debug / Verify loop ----
    def _stage_kcl_debug(self, s: dict) -> dict:
        s["stage"] = "debug"
        s["stage_index"] = 6
        kcl = s.get("kcl_code") or ""
        if not kcl:
            s["status"] = "done"
            s["final"] = True
            s["stage"] = "done"
            return {"done": True, "state": _json_safe(s)}
        # Verify KCL compiles via engine
        verify = zoo_service.verify_geometry_readiness(kcl, {"material": s["material"]})
        s["kcl_verification"] = verify
        if verify.get("model_ready") or s["iteration"] >= s["max_iterations"] + 2:
            s["status"] = "done"
            s["final"] = True
            s["stage"] = "done"
            try:
                s["drawings"] = drawing_service.render_sheet(s, s.get("designed_parts") or [], s.get("measurements") or [])
            except Exception as e:
                print(f"[Loop] drawing render error: {e}")
                s["drawings"] = []
            s["trace"].append({"iteration": s["iteration"], "event": "kcl_verified", "detail": "KCL verified by engine"})
            return {"done": True, "state": _json_safe(s)}
        # Debug loop: ask agent to fix
        sess = zookeeper.open(s["zookeeper_conv"] or None)
        s["zookeeper_conv"] = sess.conversation_id
        fix = sess.prompt(f"The following KCL failed engine verification: {verify}. Fix it.\n```\n{kcl}\n```\nReturn ONLY corrected KCL.", mode="thoughtful", forced_tools=["edit_kcl_code"])
        sess.close()
        fixed = ""
        for name, src in (fix.get("kcl_files") or {}).items():
            if name.endswith(".kcl"):
                fixed = src
                break
        if fixed:
            s["kcl_code"] = fixed
            s["iteration"] += 1  # allow more debug iters
        return {"done": False, "state": _json_safe(s)}

    # ---- Legacy fallback (single propose) ----
    def _legacy_iteration(self, s: dict) -> dict:
        feedback = s["critic"]["feedback"] if s["critic"] and not s["critic"]["pass"] else None
        try:
            proposal = self._propose(s, feedback)
        except Exception as e:
            s["status"] = "error"
            s["trace"].append({"iteration": s["iteration"], "event": "error", "detail": str(e)})
            return {"done": True, "error": str(e), "state": _json_safe(s)}

        parts = proposal.get("parts") or []
        if not parts:
            s["status"] = "error"
            s["critic"] = {"pass": False, "feedback": "No parts proposed; retry with a plainer part breakdown.", "errors": {}}
            s["trace"].append({"iteration": s["iteration"], "event": "critic", "detail": "proposal empty"})
            s["status"] = "idle"
            return {"done": False, "state": _json_safe(s)}

        # Normalise numeric fields so the engine + union math never choke.
        cleaned = []
        for p in parts:
            p["L_mm"] = float(p.get("L_mm", 0) or 0)
            p["W_mm"] = float(p.get("W_mm", 0) or 0)
            p["T_mm"] = float(p.get("T_mm", s["thickness"]) or s["thickness"])
            p["radius_mm"] = float(p.get("radius_mm", 0) or 0)
            p.setdefault("qty", 1)
            cleaned.append(p)
        parts = cleaned
        s["proposal"] = proposal

        # Real engine measurement of every part.
        measurements = []
        for p in parts:
            m = zoo_service.engine_prove_part(p, s["material"])
            m["qty"] = p.get("qty", 1)
            measurements.append(m)
        s["measurements"] = measurements

        measured_bbox = _union_bbox(parts)
        s["critic"] = self._critic(s, measured_bbox, proposal)
        total_mass = sum(m["mass_grams"] * m["qty"] for m in measurements)
        s["total_mass_g"] = round(total_mass, 2)
        s["assembly_bbox_mm"] = measured_bbox
        self._trace(s, "critic", "Critic verdict: " + ("PASS" if s["critic"]["pass"] else "FAIL"),
                    {"critic": s["critic"], "total_mass_g": s["total_mass_g"]})

        if s["critic"]["pass"] or s["iteration"] >= s["max_iterations"]:
            s["status"] = "done"
            s["final"] = True
            try:
                kcl = self._write_kcl(s)
                proposal_parts = s.get("proposal", {}).get("parts") or []
                if proposal_parts:
                    proposal_parts[0]["kcl_code"] = kcl
            except Exception as e:
                print(f"[Loop] zookeeper KCL write error: {e}")
                s["kcl_code"] = s.get("kcl_code") or ""
            try:
                s["drawings"] = drawing_service.render_sheet(s, parts, measurements)
            except Exception as e:
                print(f"[Loop] drawing render error: {e}")
                s["drawings"] = []
        else:
            s["status"] = "needs_feedback"
        return {"done": s["final"], "state": _json_safe(s)}


engineering_loop = EngineeringLoop()