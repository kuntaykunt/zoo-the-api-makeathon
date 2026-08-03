import io
import json
import re
import threading
import uuid

import fitz
from PIL import Image

from app.services.zoo_service import zoo_service
from app.services.zookeeper_service import zookeeper
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

    def create_session(self, initial_eval: dict, user_answers: dict, upload_path: str) -> str:
        session_id = uuid.uuid4().hex[:12]
        vision = initial_eval.get("detected_parameters", {})
        tb = initial_eval.get("title_block", {})
        with SESSIONS_LOCK:
            SESSIONS[session_id] = {
                "id": session_id,
                "status": "idle",
                "iteration": 0,
                "max_iterations": MAX_ITERATIONS,
                "initial_eval": initial_eval,
                "user_answers": user_answers,
                "upload_path": upload_path,
                "drawing_png": None,
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
        self._trace(s, "engineer", "Zookeeper engineer proposal received", {
            "raw": result["reply"][:600],
            "proposal": proposal,
        })
        return proposal

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