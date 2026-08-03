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
    description="Zoo The API Makeathon submission for PDF-to-KCL 3D CAD & Manufacturing Agent",
    version="1.0.0"
)

# Ensure static directories exist
os.makedirs("app/static/css", exist_ok=True)
os.makedirs("app/static/js", exist_ok=True)
os.makedirs("app/static/uploads", exist_ok=True)
os.makedirs("app/static/renders", exist_ok=True)

# Generate a sample SVG/PNG render placeholder for 3D viewport if needed
sample_render_path = "app/static/renders/sample_3d_render.png"
if not os.path.exists(sample_render_path):
    # Create simple placeholder SVG/image file
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (600, 450), color='#0f172a')
    d = ImageDraw.Draw(img)
    d.rectangle([150, 100, 450, 350], outline='#38bdf8', width=3)
    d.polygon([(150, 100), (200, 60), (500, 60), (450, 100)], outline='#38bdf8', width=2)
    d.polygon([(450, 100), (500, 60), (500, 310), (450, 350)], outline='#38bdf8', width=2)
    d.text((210, 210), "ZOO KCL 3D MODEL", fill="#f8fafc")
    d.text((180, 240), "Compiled via Zoo Engine API", fill="#94a3b8")
    img.save(sample_render_path)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="templates")

class UserAnswerRequest(BaseModel):
    initial_eval: dict
    user_answers: dict

class CompileKCLRequest(BaseModel):
    kcl_code: str
    part_name: str = "Part"

class ExplodeAssemblyRequest(BaseModel):
    kcl_code: str
    part_name: str = "Assembly"

class DFMARequest(BaseModel):
    kcl_code: str
    part_name: str = "Part"
    thickness_mm: float = 2.0
    material: str = "Aluminum 6061-T6"


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Renders the main Studio UI."""
    return templates.TemplateResponse(request=request, name="index.html", context={"zoo_status": zoo_service.check_health()})


@app.post("/api/upload-drawing")
async def upload_drawing(file: UploadFile = File(...)):
    """
    Step 1: Upload technical drawing (PDF / JPEG / PNG) and evaluate drawing info with Qwen-VL.
    Returns YES/NO evaluation and missing parameters Q&A.
    """
    try:
        contents = await file.read()
        file_path = f"app/static/uploads/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Base64 encode for Qwen Vision API
        image_b64 = base64.b64encode(contents).decode("utf-8")
        mime_type = file.content_type or "image/jpeg"
        
        if mime_type == "application/pdf":
            # For PDF, use default mime or fallback
            mime_type = "image/png"

        # Evaluate drawing completeness via Qwen-VL
        eval_result = qwen_service.evaluate_drawing(image_b64, mime_type)
        eval_result["file_name"] = file.filename
        eval_result["file_url"] = f"/static/uploads/{file.filename}"

        return JSONResponse(eval_result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/answer-questions")
async def answer_questions(payload: UserAnswerRequest):
    """
    Step 2: Submit answers to missing drawing questions.
    Synthesizes final KCL code and compiles via Zoo API.
    """
    # 1. Synthesize KCL
    kcl_res = qwen_service.generate_kcl_from_answers(payload.initial_eval, payload.user_answers)
    
    # 2. Compile with Zoo API
    zoo_res = zoo_service.compile_kcl(kcl_res["kcl_code"])
    
    # 3. Analyze DFMA
    dfma_res = dfma_service.analyze_manufacturing(kcl_res["kcl_code"], kcl_res)

    return JSONResponse({
        "status": "success",
        "kcl_code": kcl_res["kcl_code"],
        "material": kcl_res["material"],
        "thickness_mm": kcl_res["thickness_mm"],
        "zoo_compile": zoo_res,
        "dfma_analysis": dfma_res
    })


@app.post("/api/compile-kcl")
async def compile_kcl(payload: CompileKCLRequest):
    """
    Directly compiles KCL code using Zoo Engine API.
    """
    zoo_res = zoo_service.compile_kcl(payload.kcl_code)
    return JSONResponse(zoo_res)


@app.post("/api/explode-assembly")
async def explode_assembly(payload: ExplodeAssemblyRequest):
    """
    Step 3: Explodes an assembly into individual manufacturable sub-parts.
    """
    sub_parts = qwen_service.explode_assembly(payload.kcl_code, payload.part_name)
    
    # Enrich each sub-part with individual DFMA
    for part in sub_parts:
        part["dfma"] = dfma_service.analyze_manufacturing(part["kcl_code"], {
            "material": "Aluminum 6061-T6",
            "thickness_mm": 2.0,
            "part_name": part["part_name"]
        })

    return JSONResponse({
        "assembly_name": payload.part_name,
        "sub_part_count": len(sub_parts),
        "parts": sub_parts
    })


@app.post("/api/analyze-dfma")
async def analyze_dfma(payload: DFMARequest):
    """
    Step 4: DFMA & Manufacturing Operations Agent analysis.
    """
    res = dfma_service.analyze_manufacturing(payload.kcl_code, {
        "material": payload.material,
        "thickness_mm": payload.thickness_mm,
        "part_name": payload.part_name
    })
    return JSONResponse(res)


@app.get("/api/health")
async def health_check():
    """System API status check."""
    return {
        "status": "online",
        "zoo_api": zoo_service.check_health(),
        "qwen_configured": bool(config.QWEN_API_KEY and not config.QWEN_API_KEY.startswith("your_"))
    }
