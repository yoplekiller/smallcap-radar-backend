import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.disclosures import router as disclosures_router

app = FastAPI(title="DART 공시 크롤러", version="0.1.0")

_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(disclosures_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
