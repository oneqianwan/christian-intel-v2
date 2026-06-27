from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import init_db
from routers import agent, bookmarks, chat, configs, conversations, diagnostics, export, health, missions, search, url_analysis

app = FastAPI(title="Christian Intel v2", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_root():
    return {"status": "ok"}

@app.on_event("startup")
async def startup():
    init_db()

app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(conversations.router, prefix="/api", tags=["conversations"])
app.include_router(missions.router, prefix="/api", tags=["missions"])
app.include_router(diagnostics.router, prefix="/api", tags=["diagnostics"])
app.include_router(url_analysis.router, prefix="/api", tags=["url_analysis"])
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(export.router, prefix="/api", tags=["export"])
app.include_router(bookmarks.router, prefix="/api", tags=["bookmarks"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(configs.router, prefix="/api", tags=["configs"])
app.include_router(agent.router)
