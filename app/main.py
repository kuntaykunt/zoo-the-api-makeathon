import os
import base64
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.config import config
from app.services.qwen_service import qwen_service
from app.services.zoo_service import zoo_service
from app.services.dfma_service import dfma_service
from app.services.engineering_loop import engineering_loop

app = FastAPI(
    title="Zoo Auto-CAD & DFMA Pipeline",
    description="Star Wars Terminal Agent Harness & Loop Engineering for Zoo The API Makeathon",
    version="2.4.0"
)

# Ensure static directories exist
os.makedirs("app/static/css", exist_ok=True)
os.makedirs("app/static/js", exist_ok=True)
os.makedirs("app/static/uploads", exist_ok=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
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
    initial_eval: dict
    user_answers: dict
    upload_name: str = ""

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
        file_path = f"app/static/uploads/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(contents)

        # Evaluate drawing via Qwen Vision Service
        eval_result = qwen_service.evaluate_drawing(contents, file.filename)
        eval_result["file_name"] = file.filename
        eval_result["file_url"] = f"/static/uploads/{file.filename}"

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


@app.post("/api/engineering-loop/start")
async def engineering_start(payload: EngineeringStartRequest):
    """
    Agentic Loop Step 1: open an engineering session. Zookeeper (Agent API) acts
    as the design engineer, Zoo Engine as the measuring instrument, and a critic
    enforces the drawing envelope.
    """
    name = payload.upload_name or payload.initial_eval.get("file_name", "drawing.pdf")
    path = f"app/static/uploads/{os.path.basename(name)}"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"upload file not found: {name}")
    session_id = engineering_loop.create_session(payload.initial_eval, payload.user_answers, path)
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
