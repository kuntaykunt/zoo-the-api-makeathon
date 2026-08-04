import os
import base64
import uuid
import re
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any

from app.config import config
from app.services.qwen_service import qwen_service
from app.services.zoo_service import zoo_service
from app.services.dfma_service import dfma_service
from app.services.engineering_loop import engineering_loop
from app.services import library_service

app = FastAPI(
    title="Zoo Auto-CAD & DFMA Pipeline",
    description="Star Wars Terminal Agent Harness & Loop Engineering for Zoo The API Makeathon",
    version="2.4.0"
)

# Ensure static directories exist
os.makedirs("app/static/css", exist_ok=True)
os.makedirs("app/static/js", exist_ok=True)
os.makedirs("app/static/uploads", exist_ok=True)
os.makedirs(os.path.join("library", "samples"), exist_ok=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/library/samples", StaticFiles(directory=os.path.join("library", "samples")), name="samples")
templates = Jinja2Templates(directory="templates")

class UserAnswerRequest(BaseModel):
    initial_eval: dict
    user_answers: dict

class ExplodeAssemblyRequest(BaseModel):
    kcl_code: str
    part_name: str = "Assembly"

class VerifyZooModelRequest(BaseModel):
    kcl_code: str

class EngineeringStartRequest(BaseModel):
    initial_eval: Any = {}
    user_answers: Any = {}
    upload_name: str = ""
    file_url: str = ""

class EngineeringIterateRequest(BaseModel):
    session_id: str


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Renders the main Studio UI."""
    return templates.TemplateResponse(request=request, name="index.html", context={"zoo_status": zoo_service.check_health()})


@app.post("/api/upload-drawing")
async def upload_drawing(file: UploadFile = File(...)):
    """
    Loop Step 1: Upload technical drawing & execute Qwen-VL Vision Agent inspection.
    Normalizes image format to prevent Qwen 400 InvalidParameter errors.
    """
    try:
        contents = await file.read()

        # Sanitize the client-supplied filename to prevent path traversal
        # (e.g. "../../etc/passwd"). Keep the original stem for display only.
        safe_name = os.path.basename(file.filename or "drawing")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", safe_name)
        if not safe_name:
            safe_name = "drawing"
        stored_name = f"{uuid.uuid4().hex}_{safe_name}"
        file_path = os.path.join("app/static/uploads", stored_name)
        with open(file_path, "wb") as f:
            f.write(contents)

        # Evaluate drawing via Qwen Vision Service (keep original name for vision context)
        eval_result = qwen_service.evaluate_drawing(contents, file.filename or stored_name)
        eval_result["file_name"] = file.filename or stored_name
        eval_result["file_url"] = f"/static/uploads/{stored_name}"

        # Persist to the Library so the drawing can be recalled later.
        try:
            tb = eval_result.get("title_block", {}) or {}
            library_service.save_record({
                "title": tb.get("part_name") or (file.filename or stored_name).split(".")[0],
                "file_name": file.filename or stored_name,
                "file_url": eval_result["file_url"],
                "source": "upload",
                "title_block": tb,
                "detected_parameters": eval_result.get("detected_parameters"),
            })
        except Exception as lib_err:
            print(f"[Library] save note: {lib_err}")

        return JSONResponse(eval_result)

    except Exception as e:
        print(f"[UploadError] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/answer-questions")
async def answer_questions(payload: UserAnswerRequest):
    """
    Loop Step 2 & 3: Submit answers, synthesize KCL, query Zoo Engine API readiness.
    """
    kcl_res = qwen_service.generate_kcl_from_answers(payload.initial_eval, payload.user_answers)
    zoo_verify = zoo_service.verify_geometry_readiness(kcl_res["kcl_code"], kcl_res)
    dfma_res = dfma_service.analyze_manufacturing(kcl_res["kcl_code"], kcl_res, zoo_verify)

    # Update the matching Library record with KCL + DFMA + Zoo verification.
    try:
        tb = payload.initial_eval.get("title_block", {}) or {}
        fname = payload.initial_eval.get("file_name")
        existing = library_service.list_records(limit=10000)
        match = next((r for r in existing if r.get("file_name") == fname), None)
        rec = {
            "title": tb.get("part_name") or (fname or "Unnamed").split(".")[0],
            "file_name": fname,
            "file_url": payload.initial_eval.get("file_url"),
            "source": "upload",
            "title_block": tb,
            "detected_parameters": payload.initial_eval.get("detected_parameters"),
            "kcl_code": kcl_res["kcl_code"],
            "dfma_analysis": dfma_res,
            "zoo_verification": zoo_verify,
        }
        if match:
            rec["id"] = match["id"]
        library_service.save_record(rec)
    except Exception as lib_err:
        print(f"[Library] update note: {lib_err}")

    return JSONResponse({
        "status": "success",
        "kcl_code": kcl_res["kcl_code"],
        "material": kcl_res["material"],
        "thickness_mm": kcl_res["thickness_mm"],
        "zoo_verification": zoo_verify,
        "model_ready": zoo_verify.get("model_ready", False),
        "dfma_analysis": dfma_res
    })


@app.post("/api/verify-zoo-model")
async def verify_zoo_model(payload: VerifyZooModelRequest):
    res = zoo_service.verify_geometry_readiness(payload.kcl_code, {"material": "St37-2"})
    return JSONResponse(res)


@app.post("/api/explode-assembly")
async def explode_assembly(payload: ExplodeAssemblyRequest):
    sub_parts = qwen_service.explode_assembly(payload.kcl_code, payload.part_name)
    return JSONResponse({
        "assembly_name": payload.part_name,
        "sub_part_count": len(sub_parts),
        "parts": sub_parts
    })


def _resolve_upload_path(name: str, file_url: str) -> str:
    """Resolve the on-disk path of an uploaded or sample drawing.

    Tries, in order:
      1. file_url mapping (/static/uploads/X -> app/static/uploads/X,
         /library/samples/X -> library/samples/X)
      2. original name inside app/static/uploads/
      3. original name inside library/samples/   (for repo sample drawings)
    """
    candidates = []
    if file_url:
        cleaned = file_url.split("?")[0].lstrip("/")
        if cleaned.startswith("static/"):
            candidates.append(cleaned)
        elif cleaned.startswith("library/samples/"):
            candidates.append(cleaned)
        elif cleaned.startswith("uploads/"):
            candidates.append(os.path.join("app", cleaned))
        else:
            candidates.append(os.path.join("app/static", cleaned))
    if name:
        bn = os.path.basename(name)
        candidates.append(os.path.join("app/static/uploads", bn))
        candidates.append(os.path.join("library/samples", bn))
        candidates.append(os.path.join("app/static/uploads", name))
        candidates.append(os.path.join("library/samples", name))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    # Fallback: most recent file in uploads (best effort)
    updir = "app/static/uploads"
    if os.path.isdir(updir):
        files = [f for f in os.listdir(updir) if not f.startswith(".")]
        if files:
            return os.path.join(updir, sorted(files)[-1])
    raise FileNotFoundError("; ".join(candidates))


@app.post("/api/engineering-loop/start")
async def engineering_start(payload: EngineeringStartRequest):
    """
    Agentic Loop Step 1: open an engineering session. Zookeeper (Agent API) acts
    as the design engineer, Zoo Engine as the measuring instrument, and a critic
    enforces the drawing envelope.
    """
    name = payload.upload_name or payload.initial_eval.get("file_name", "drawing.pdf")
    try:
        path = _resolve_upload_path(name, payload.file_url)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"upload file not found: {name} (searched: {e})")
    file_bytes = b""
    try:
        with open(path, "rb") as fh:
            file_bytes = fh.read()
    except Exception:
        file_bytes = b""
    session_id = engineering_loop.create_session(payload.initial_eval, payload.user_answers, path, file_bytes)
    return JSONResponse({"session_id": session_id, "state": engineering_loop.get_state(session_id)})


@app.post("/api/engineering-loop/iterate")
async def engineering_iterate(payload: EngineeringIterateRequest):
    """Agentic Loop Step 2: run one engineer->measure->critic iteration."""
    res = engineering_loop.run_iteration(payload.session_id)
    return JSONResponse(res)


@app.get("/api/engineering-loop/state/{session_id}")
async def engineering_state(session_id: str):
    state = engineering_loop.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session not found")
    return JSONResponse(state)


@app.get("/api/health")
async def health_check():
    return {
        "status": "online",
        "zoo_api": zoo_service.check_health(),
        "qwen_configured": bool(config.QWEN_API_KEY and not config.QWEN_API_KEY.startswith("your_"))
    }


# --------------------------------------------------------------------------- #
#  API Keys (encrypted persistence)                                          #
# --------------------------------------------------------------------------- #
class KeysRequest(BaseModel):
    qwen_api_key: str = ""
    zoo_api_key: str = ""
    qwen_base_url: str = ""
    zoo_base_url: str = ""


@app.get("/api/keys")
async def get_keys():
    """Return key status + masked previews (never the raw secret)."""
    return {
        "qwen_configured": config.has_qwen(),
        "zoo_configured": config.has_zoo(),
        "qwen_preview": config.masked(config.QWEN_API_KEY),
        "zoo_preview": config.masked(config.ZOO_API_KEY),
        "qwen_base_url": config.QWEN_BASE_URL,
        "zoo_base_url": config.ZOO_BASE_URL,
    }


@app.post("/api/keys")
async def save_keys(payload: KeysRequest):
    """Encrypt and persist the supplied API keys."""
    # Only overwrite when a non-empty value is provided (don't blank existing).
    qwen = payload.qwen_api_key.strip() if payload.qwen_api_key else config.QWEN_API_KEY
    zoo = payload.zoo_api_key.strip() if payload.zoo_api_key else config.ZOO_API_KEY
    config.save_keys(qwen, zoo, payload.qwen_base_url.strip(), payload.zoo_base_url.strip())
    return {
        "status": "saved",
        "qwen_configured": config.has_qwen(),
        "zoo_configured": config.has_zoo(),
        "qwen_preview": config.masked(config.QWEN_API_KEY),
        "zoo_preview": config.masked(config.ZOO_API_KEY),
    }


# --------------------------------------------------------------------------- #
#  Library (persisted drawing records)                                        #
# --------------------------------------------------------------------------- #
class LibrarySaveRequest(BaseModel):
    record_id: int = None
    title: str = ""
    file_name: str = ""
    file_url: str = ""
    source: str = "upload"
    title_block: dict = None
    detected_parameters: dict = None
    kcl_code: str = ""
    dfma_analysis: dict = None
    zoo_verification: dict = None


@app.get("/api/library")
async def library_list():
    records = library_service.list_records()
    imported = library_service.import_samples()
    if imported:
        records = library_service.list_records()
    return {"records": records, "imported_samples": imported}


@app.get("/api/library/{record_id}")
async def library_get(record_id: int):
    rec = library_service.get_record(record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="record not found")
    return rec


@app.post("/api/library/save")
async def library_save(payload: LibrarySaveRequest):
    rid = library_service.save_record(payload.model_dump())
    return {"id": rid, "status": "saved"}


