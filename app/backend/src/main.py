from contextlib import asynccontextmanager
from time import perf_counter
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from src.config import get_cors_origins, get_database_url
from src.db import check_db, get_db, init_db_schema
from src.metrics import REQUEST_COUNT, REQUEST_LATENCY, prometheus_app
from src.models import Task
from src.schemas import TaskCreate, TaskRead, TaskUpdate

SERVICE_NAME = "TinyTasks API"
SERVICE_VERSION = "0.1.0"


# Initialize database schema on app startup.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # For SQLite (local dev/tests) we still auto-create tables.
    # For Postgres (Docker / production) schema is managed by Alembic.
    if get_database_url().startswith("sqlite"):
        init_db_schema()
    yield


app = FastAPI(title="TinyTasks API (MVP)", lifespan=lifespan)

cors_origins = get_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],  # allow all HTTP methods
    allow_headers=["*"],  # allow all headers
)


# Record request count and latency for Prometheus.
@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = perf_counter()
    method = request.method
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration = perf_counter() - start

        route = request.scope.get("route")
        path = route.path if route and hasattr(route, "path") else request.url.path

        REQUEST_COUNT.labels(
            method=method,
            path=path,
            status=str(status_code),
        ).inc()

        REQUEST_LATENCY.labels(
            method=method,
            path=path,
        ).observe(duration)


# Health check endpoint
# Verify that the service is alive and responding.
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# Database health check endpoint.
# Executes a simple query to verify database connectivity.
@app.get("/db/healthz")
def db_healthz():
    check_db()
    return {"db": "ok"}


# Prometheus metrics endpoint
# Exposes collected application metrics in plain text format
@app.get("/metrics")
def metrics():
    return PlainTextResponse(prometheus_app(), media_type="text/plain")


# Root endpoint
# Basic service info.
@app.get("/")
def root():
    return JSONResponse({"service": SERVICE_NAME, "version": SERVICE_VERSION})


# Create a new task in DB.
@app.post("/api/tasks", response_model=TaskRead, status_code=201)
def create_task(
    payload: TaskCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    task = Task(title=payload.title)
    db.add(task)
    db.commit()
    db.refresh(task)

    # Set Location header to the newly created resource
    response.headers["Location"] = f"/api/tasks/{task.id}"

    return task


# Return all tasks from DB.
@app.get("/api/tasks", response_model=list[TaskRead])
def list_tasks(
    db: Session = Depends(get_db),
    done: Optional[bool] = Query(default=None, description="Filter by completion status"),
    limit: int = Query(default=50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
):
    # Return tasks with optional filtering and pagination.
    q = db.query(Task).order_by(Task.created_at.desc(), Task.id.desc())
    if done is not None:
        q = q.filter(Task.done == done)
    return q.offset(offset).limit(limit).all()


# Return a single task by ID
@app.get("/api/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# Update a task by ID (title and/or done).
@app.patch("/api/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: str, payload: TaskUpdate, db: Session = Depends(get_db)):

    # Find task by ID
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Reject empty payloads like {}
    if payload.title is None and payload.done is None:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    # Apply updates
    if payload.title is not None:
        task.title = payload.title
    if payload.done is not None:
        task.done = payload.done

    db.commit()
    db.refresh(task)
    return task


# Delete a task by ID. Returns 204 if deleted, 404 if not found
@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return None
