"""FastAPI app: /health, /recommend, and the static single-page UI."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR, get_params
from app.recommend import build_response
from app.scenario import build_day_bank
from app.schemas import HealthResponse, RecommendRequest, RecommendResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.params = get_params()
    app.state.bank = build_day_bank(app.state.params)
    yield


app = FastAPI(title="Smart Cooling Advisor (SIMULATED)", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
def health(request: Request):
    return {
        "status": "ok",
        "model_trained": request.app.state.bank is not None,
        "label": "SIMULATED",
    }


@app.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest, request: Request):
    return build_response(request.app.state.bank, req.model_dump(), request.app.state.params)


app.mount("/", StaticFiles(directory=ROOT_DIR / "static", html=True), name="static")
