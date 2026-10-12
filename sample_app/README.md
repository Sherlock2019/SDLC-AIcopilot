# Customer Portal API (sample application)

The small FastAPI service the AI-SDLC Champion Lab operates against.
It is deliberately simple and deliberately under-tested so the lab has real work to do.

| Endpoint       | Purpose                                  |
|----------------|------------------------------------------|
| `GET /health`  | Liveness and version                     |
| `POST /login`  | Exchange email + password for a session  |
| `GET /profile` | Return the authenticated customer        |

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8100
pytest --cov=app
```

`frontend/index.html` is a dependency-free page that exercises the three endpoints.

The lab copies this directory into a throw-away git repository (the "local mock git" sandbox),
so nothing an agent does ever modifies these files.
