import sys

# Some libraries (e.g. F5-TTS) print non-ASCII text (reference transcripts in Hindi/
# Urdu/etc.) straight to stdout — Windows' default console codepage (cp1252) crashes
# on that. Reconfiguring here, once, at process start, so no library's internal print()
# can ever take the server down.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from auth import get_current_user
from templating import templates
from routers import auth_routes, companions, chat, settings_routes, admin, conversations, voice_messages, voice_library

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Companion Platform")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_routes.router)
app.include_router(companions.router)
app.include_router(chat.router)
app.include_router(settings_routes.router)
app.include_router(admin.router)
app.include_router(conversations.router)
app.include_router(voice_messages.router)
app.include_router(voice_library.router)


@app.get("/")
def landing(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/companions", status_code=303)
    return templates.TemplateResponse(request, "landing.html", {})
