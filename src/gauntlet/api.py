"""api.py — FastAPI REST API."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException

from gauntlet.client      import GauntletClient
from gauntlet.config      import GauntletConfig
from gauntlet.models      import EvaluateRequest, EvaluationJob, GauntletResult, InputErrorResponse, JobStatus
from gauntlet.orchestrator import prepare_evaluation_input, run_pipeline
from gauntlet.parsing     import InputError
from gauntlet.validation  import ValidationError, validate_request

_config: GauntletConfig | None = None
_client: GauntletClient | None = None
_jobs:   dict[str, EvaluationJob] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _client
    _config = GauntletConfig.from_env()
    _client = GauntletClient(_config)
    yield


app = FastAPI(
    title="Gauntlet",
    description="Better decisions through rigorous argument.",
    version="0.3.0",
    lifespan=lifespan,
)


def _deps() -> tuple[GauntletConfig, GauntletClient]:
    if _config is None or _client is None:
        raise HTTPException(503, "Service not initialised")
    return _config, _client


@app.get("/v1/health")
async def health() -> dict[str, Any]:
    return {
        "status":        "ok",
        "version":       "0.3.0",
        "mode":          _config.mode if _config else "unknown",
        "primary_model": _config.primary.model if _config else "unknown",
        "preflight_model": _config.preflight.model if _config else "unknown",
        "tavily":        "configured" if (_config and _config.tavily_api_key) else "missing",
    }


@app.post("/v1/evaluate", response_model=GauntletResult)
async def evaluate_sync(request: EvaluateRequest) -> GauntletResult:
    """Synchronous bipolar evaluation. Blocks until complete."""
    try:
        validate_request(request)
    except ValidationError as e:
        raise HTTPException(422, {"errors": e.errors})

    config, client = _deps()
    try:
        return await run_pipeline(request, config, client)
    except InputError as e:
        raise HTTPException(422, InputErrorResponse(
            code=e.code, message=e.message, claims=e.claims
        ).model_dump())
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/evaluate/async", status_code=202)
async def evaluate_async(request: EvaluateRequest) -> dict[str, str]:
    """Async bipolar evaluation. Returns job_id immediately."""
    try:
        validate_request(request)
    except ValidationError as e:
        raise HTTPException(422, {"errors": e.errors})

    config, client = _deps()
    try:
        prepared = await prepare_evaluation_input(request.input, config, client)
    except InputError as e:
        raise HTTPException(422, InputErrorResponse(
            code=e.code, message=e.message, claims=e.claims
        ).model_dump())

    job_id = str(uuid.uuid4())
    _jobs[job_id] = EvaluationJob(job_id=job_id, status=JobStatus.pending)

    async def _run() -> None:
        _jobs[job_id] = EvaluationJob(job_id=job_id, status=JobStatus.running)
        try:
            result = await run_pipeline(request, config, client, prepared=prepared)
            _jobs[job_id] = EvaluationJob(job_id=job_id, status=JobStatus.complete, result=result)
        except InputError as e:
            _jobs[job_id] = EvaluationJob(job_id=job_id, status=JobStatus.failed,
                                          error=f"{e.code}: {e.message}")
        except Exception as e:
            _jobs[job_id] = EvaluationJob(job_id=job_id, status=JobStatus.failed, error=str(e))

    asyncio.create_task(_run())
    return {"job_id": job_id}


@app.get("/v1/jobs/{job_id}", response_model=EvaluationJob)
async def get_job(job_id: str) -> EvaluationJob:
    """Poll async job status and result."""
    if job_id not in _jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return _jobs[job_id]


@app.delete("/v1/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str) -> None:
    if job_id not in _jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")
    del _jobs[job_id]
