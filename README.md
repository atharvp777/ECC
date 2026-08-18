# Orbit

Atharv's personal AI-powered productivity system for eBAJA, AgroVault, college, and personal projects.

---

## Project Structure

```
engineering-command-center/
├── backend/                  # Python FastAPI backend
│   ├── app/
│   │   ├── core/
│   │   │   ├── config.py     # Settings & env vars
│   │   │   └── database.py   # SQLAlchemy engine & session
│   │   ├── models/           # SQLAlchemy ORM models
│   │   │   ├── project.py
│   │   │   ├── task.py
│   │   │   ├── note.py
│   │   │   ├── document.py
│   │   │   └── meeting.py
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── routers/          # FastAPI route handlers
│   │   │   ├── dashboard.py
│   │   │   ├── projects.py
│   │   │   ├── tasks.py
│   │   │   ├── notes.py
│   │   │   ├── documents.py
│   │   │   └── meetings.py
│   │   └── main.py           # App entry point
│   ├── requirements.txt
│   └── start.bat             # Windows one-click start
├── frontend/                 # React + Tauri (next phase)
└── README.md
```

---

## Phase 1: Backend Setup (Done ✅)

### Database Tables
| Table | Description |
|---|---|
| `projects` | Baja, AgroVault, College, Personal, Internship |
| `tasks` | Priority, status, deadlines, recurring tasks |
| `notes` | Markdown notes linked to projects |
| `documents` | Uploaded PDFs, datasheets, rulebooks |
| `meetings` | Meeting logs with action items |
| `meeting_action_items` | Per-meeting to-dos with assignees |

### API Endpoints
| Method | Endpoint | Description |
|---|---|---|
| GET | `/dashboard/stats` | Project & task overview counts |
| GET/POST | `/projects/` | List / create projects |
| GET/PATCH/DELETE | `/projects/{id}` | Get / update / delete project |
| GET/POST | `/tasks/` | List / create tasks (filter by project, status, priority) |
| GET | `/tasks/today` | Tasks due today or overdue |
| GET | `/tasks/upcoming` | Tasks due in next N days |
| GET/POST | `/notes/` | Notes with tag & project filtering |
| POST | `/documents/upload` | Upload PDF, DOCX, TXT, images |
| GET/POST | `/meetings/` | Meeting logs |
| POST | `/meetings/{id}/action-items` | Add action items |

---

## Getting Started (Windows)

```bash
# 1. Clone / open the backend folder
cd backend

# 2. Double-click start.bat, OR run manually:
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 3. Open Swagger UI
http://localhost:8000/docs
```

### Environment Variables (optional)
Create `backend/.env`:
```
OPENAI_API_KEY=sk-...       # For AI chat (Phase 2)
DEBUG=True
```

---

## Roadmap

- [x] **Phase 1** — Database schema + FastAPI backend (this file)
- [ ] **Phase 2** — React + Tauri desktop UI shell (Dashboard + Sidebar)
- [ ] **Phase 3** — AI Chat module (OpenAI API integration)
- [ ] **Phase 4** — Knowledge Base + document search (FAISS)
- [ ] **Phase 5** — Meeting transcription + auto-summary
- [ ] **Phase 6** — Calendar, GitHub, Google integrations
