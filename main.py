import uvicorn
from app.config import config

if __name__ == "__main__":
    print(f"🚀 Starting Zoo Auto-CAD & DFMA Pipeline on http://{config.HOST}:{config.PORT}")
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=True)
