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
    zoo_verify = zoo_service.verify_geometry_readiness(kcl_res["kcl_code"])
    dfma_res = dfma_service.analyze_manufacturing(kcl_res["kcl_code"], kcl_res)

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
    res = zoo_service.verify_geometry_readiness(payload.kcl_code)
    return JSONResponse(res)


@app.post("/api/explode-assembly")
async def explode_assembly(payload: ExplodeAssemblyRequest):
    sub_parts = qwen_service.explode_assembly(payload.kcl_code, payload.part_name)
    return JSONResponse({
        "assembly_name": payload.part_name,
        "sub_part_count": len(sub_parts),
        "parts": sub_parts
    })


@app.get("/api/health")
async def health_check():
    return {
        "status": "online",
        "zoo_api": zoo_service.check_health(),
        "qwen_configured": bool(config.QWEN_API_KEY and not config.QWEN_API_KEY.startswith("your_"))
    }
