"""
paddleocr-service — self-hosted OCR via PaddleOCR + PP-Structure.

Endpoints:
  GET  /health
  POST /ocr   multipart file (PDF or image) → JSON

OCR model files download to PADDLE_HOME on first use and are persisted
via a Docker volume (paddleocr-models → /app/models).
"""
import io
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
import structlog
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()

# Models download here; mount as a volume so they survive restarts.
os.environ.setdefault("PADDLE_HOME", "/app/models")

_ocr_engine = None
_struct_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ocr_engine, _struct_engine
    log.info("paddleocr.init.start")
    from paddleocr import PaddleOCR, PPStructure

    _ocr_engine = PaddleOCR(
        use_angle_cls=True,
        lang="en",
        use_gpu=False,
        show_log=False,
    )
    _struct_engine = PPStructure(
        table=True,
        ocr=True,
        show_log=False,
        use_gpu=False,
        recovery=False,
    )
    log.info("paddleocr.init.done")
    yield


app = FastAPI(title="paddleocr-service", lifespan=lifespan)


# ── helpers ──────────────────────────────────────────────────────────────────

def _to_images(data: bytes, filename: str) -> list[np.ndarray]:
    """Convert raw bytes (PDF or image) to a list of RGB numpy arrays."""
    is_pdf = data[:4] == b"%PDF" or filename.lower().endswith(".pdf")
    if is_pdf:
        from pdf2image import convert_from_bytes
        pil_pages = convert_from_bytes(data, dpi=150)
        return [np.array(p.convert("RGB")) for p in pil_pages]
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return [np.array(img)]


def _parse_ocr_page(page_result) -> tuple[list[dict], list[str]]:
    """Extract blocks and text lines from one page of PaddleOCR output."""
    blocks: list[dict] = []
    texts: list[str] = []
    if not page_result:
        return blocks, texts
    for line in page_result:
        if not line:
            continue
        bbox_pts, (text, conf) = line
        # bbox_pts: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] — flatten to 8 floats
        flat_bbox = [float(v) for pt in bbox_pts for v in pt]
        blocks.append({"text": text, "bbox": flat_bbox, "confidence": round(float(conf), 4)})
        texts.append(text)
    return blocks, texts


def _parse_struct_page(struct_result: list[dict]) -> tuple[list[Any], list[Any]]:
    """Split PP-Structure output into tables and layout blocks."""
    tables: list[Any] = []
    layout: list[Any] = []
    for item in struct_result or []:
        block_type = item.get("type", "")
        bbox = item.get("bbox", [])
        res = item.get("res", {})
        if block_type == "table":
            tables.append({
                "bbox": bbox,
                "html": res.get("html", "") if isinstance(res, dict) else "",
            })
        layout.append({"type": block_type, "bbox": bbox})
    return tables, layout


# ── routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "service": "paddleocr-service", "engines_ready": _ocr_engine is not None}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    if _ocr_engine is None:
        raise HTTPException(503, "OCR engines not initialised")

    t0 = time.time()
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")

    try:
        images = _to_images(data, file.filename or "upload.bin")
    except Exception as e:
        log.error("ocr.convert_failed", error=str(e))
        raise HTTPException(422, f"Could not decode file: {e}")

    all_blocks: list[dict] = []
    all_tables: list[Any] = []
    all_layout: list[Any] = []
    page_texts: list[str] = []

    for page_idx, img_arr in enumerate(images):
        try:
            ocr_result = _ocr_engine.ocr(img_arr, cls=True)
            # PaddleOCR wraps single-image result in an extra list
            page_data = ocr_result[0] if ocr_result else []
            blocks, texts = _parse_ocr_page(page_data)
            all_blocks.extend(blocks)
            page_texts.append(" ".join(texts))
        except Exception as e:
            log.warning("ocr.page_failed", page=page_idx, error=str(e))
            page_texts.append("")

        try:
            struct_result = _struct_engine(img_arr)
            tables, layout = _parse_struct_page(struct_result)
            all_tables.extend(tables)
            all_layout.extend(layout)
        except Exception as e:
            log.warning("structure.page_failed", page=page_idx, error=str(e))

    confidences = [b["confidence"] for b in all_blocks]
    mean_confidence = round(float(np.mean(confidences)), 4) if confidences else 0.0
    duration_ms = int((time.time() - t0) * 1000)

    log.info(
        "ocr.done",
        pages=len(images),
        blocks=len(all_blocks),
        tables=len(all_tables),
        mean_confidence=mean_confidence,
        duration_ms=duration_ms,
    )

    return {
        "text": "\n".join(page_texts),
        "blocks": all_blocks,
        "tables": all_tables,
        "layout": all_layout,
        "mean_confidence": mean_confidence,
        "page_count": len(images),
        "duration_ms": duration_ms,
    }
