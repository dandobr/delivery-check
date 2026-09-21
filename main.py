"""FastAPI backend. Run with: uvicorn main:app --reload"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pipeline.env import credentials_present, load_dotenv
from pipeline.llm import LLMError
from pipeline.verify import MAX_PHOTOS, verify_delivery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

load_dotenv()
if not credentials_present():
    logging.warning(
        "No ANTHROPIC_API_KEY found in the environment or in a .env file at the project root. "
        "The app will start, but every verification will fail with an authentication error."
    )

app = FastAPI(title="Delivery photo vs packing list")
STATIC = Path(__file__).parent / "static"

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/verify")
async def api_verify(packing_list: UploadFile = File(...), photos: list[UploadFile] = File(...)):
    if not photos or len(photos) > MAX_PHOTOS:
        raise HTTPException(400, f"Upload between 1 and {MAX_PHOTOS} photos.")
    pdf_bytes = await packing_list.read()
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(400, "packing_list must be a PDF file.")
    photo_inputs = []
    for i, p in enumerate(photos, start=1):
        data = await p.read()
        if not data:
            raise HTTPException(400, f"Photo {i} is empty.")
        photo_inputs.append((f"photo{i}", data))
    try:
        result = verify_delivery(pdf_bytes, photo_inputs)
    except (ValueError, LLMError) as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # surface API errors (bad key, rate limit) to the UI instead of a bare 500
        logging.exception("verification failed")
        raise HTTPException(502, f"{type(e).__name__}: {e}")
    # echo original filenames so the UI can map photo ids back to the user's files
    result["photo_files"] = [{"photo_id": f"photo{i}", "filename": p.filename} for i, p in enumerate(photos, start=1)]
    return JSONResponse(result)


app.mount("/static", StaticFiles(directory=STATIC), name="static")
