"""FastAPI app: /health, /recommend, and the static single-page UI."""

import mimetypes
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import DATA_DIR, ROOT_DIR, get_params
from app.decisions import COLUMNS, DecisionLog, decision_row
from app.explain import explain_day
from app.recommend import build_response
from app.scenario import build_day_bank
from app.schemas import DecisionRequest, HealthResponse, RecommendRequest, RecommendResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.params = get_params()
    app.state.bank = build_day_bank(app.state.params)
    app.state.decision_log = DecisionLog(
        Path(os.environ.get("SCA_DECISION_LOG") or DATA_DIR / "decision_log.csv")
    )
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


@app.post("/decisions")
def post_decision(req: DecisionRequest, request: Request):
    body = req.model_dump(exclude={"action"})
    resp = build_response(request.app.state.bank, body, request.app.state.params)
    row = decision_row(req.action, body, resp, datetime.now())
    return {"row": request.app.state.decision_log.append(row)}


@app.get("/decisions")
def get_decisions(request: Request):
    return {"rows": request.app.state.decision_log.rows(), "label": "SIMULATED"}


@app.get("/decisions.csv")
def get_decisions_csv(request: Request):
    path = request.app.state.decision_log.path
    if path.exists():
        return FileResponse(path, media_type="text/csv", filename="decision_log.csv")
    return Response(
        ",".join(COLUMNS) + "\r\n",
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="decision_log.csv"'},
    )


@app.get("/explain")
def explain(request: Request, source_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$")):
    try:
        datetime.strptime(source_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="source_date is not a valid calendar date")
    bank = request.app.state.bank
    try:
        return explain_day(bank, source_date)
    except KeyError:
        eligible = bank.forecasts.eligible
        lo, hi = eligible.min().strftime("%Y-%m-%d"), eligible.max().strftime("%Y-%m-%d")
        raise HTTPException(
            status_code=404, detail=f"no forecast for that day (eligible: {lo} to {hi})"
        )


# Windows registries can map .js to text/plain, which browsers refuse for module scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
app.mount("/", StaticFiles(directory=ROOT_DIR / "static", html=True), name="static")
