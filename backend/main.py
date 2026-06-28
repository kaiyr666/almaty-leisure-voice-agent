import os
from dotenv import load_dotenv

# Must load env vars before any module imports that read them
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .logger import get_logger
from .mcp_client import mcp_client

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=== Voice AI Assistant starting up ===")
    try:
        await mcp_client.connect()
    except Exception as e:
        log.warning(
            "MCP Playwright failed to connect on startup — scraping will use fallback data. Error: %s", e
        )
    yield
    log.info("=== Voice AI Assistant shutting down ===")
    await mcp_client.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
    log.info("Frontend static files mounted from %s", frontend_dir)
else:
    log.error("Frontend directory not found: %s", frontend_dir)


@app.get("/")
async def get():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    log.error("index.html not found at %s", index_path)
    return HTMLResponse(content="<h1>Frontend not found</h1>", status_code=404)


from .agent import handle_gemini_session


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_host = websocket.client.host if websocket.client else "unknown"
    log.info("New WebSocket connection from %s", client_host)
    await websocket.accept()
    try:
        await handle_gemini_session(websocket)
    except WebSocketDisconnect:
        log.info("WebSocket client %s disconnected normally", client_host)
    except Exception as e:
        log.error("Unhandled WebSocket error for %s: %s", client_host, e, exc_info=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
