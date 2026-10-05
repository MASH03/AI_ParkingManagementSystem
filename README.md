# ParkSmart AI

ParkSmart AI is a medium-level student Park Management System built with Flask. It combines a complete operational **AI Platform** with a controlled **AI Factory** that uses exactly two primary agents to analyze real park data and propose evidence-based actions.

This is not a chatbot. The agents receive privacy-minimized operational aggregates, exchange validated structured data, preserve execution logs, and stop at recommendations that an administrator must review.

## Features

- Administrator and park staff authentication with server-side role enforcement
- Responsive dashboard with visitors, tickets, reservations, facilities, maintenance, incidents, feedback, recommendations, priority issues, activity, and five charts
- Visitor registration and exit tracking with minimal personal data
- Category-based ticket prices, ticket generation, payment status, and entrance status
- Park zones with capacity, current occupancy, facilities, and operating status
- Facility inventory, condition, capacity, and inspection scheduling
- Reservation lifecycle with facility-capacity and double-booking validation
- Maintenance history, assignment, priority, status, and completion tracking
- Incident reporting by type, zone, severity, status, and action taken
- Anonymous public visitor feedback plus staff review workflow
- Staff assignments, shifts, account status, and administrator-created login accounts
- Date-filtered reports with JSON, CSV, and printable HTML exports
- AI Factory status polling, agent logs, run history, partial-failure recovery, and Agent 2 retry
- Administrator-only recommendation approval, rejection, implementation, and notes

## AI Platform

The AI Platform is the full park management application. Its operational records are the source of truth. The dashboard and reports query this data directly, while the AI Factory receives a deliberately smaller aggregate snapshot containing counts, usage summaries, categories, conditions, and statuses—not visitor names, contacts, staff contacts, or payment details.

## AI Factory

```text
Operational data
      |
      v
Park Operations Analyst (Agent 1)
      |
      v
Validated OperationsAnalysis
      |
      v
Park Recommendation Agent (Agent 2)
      |
      +---- insufficient evidence? ----> one focused Agent 1 pass maximum
      |
      v
Validated recommendations
      |
      v
Administrator review
```

### Agent 1 — Park Operations Analyst

Agent 1 receives aggregate traffic, occupancy, facility, reservation, maintenance, incident, feedback, and ticket data. Its independent prompt forbids recommendations and unsupported claims. Pydantic validates traffic status, peak periods, evidence-backed findings, priority issues, data gaps, and the summary before anything reaches Agent 2.

### Agent 2 — Park Recommendation Agent

Agent 2 receives the original aggregate snapshot plus Agent 1's validated analysis. Its separate prompt produces bounded, actionable recommendations with priority reasons, evidence, related areas, and concrete actions. It can request one focused re-analysis when evidence is insufficient. The factory prevents any further loop.

The implementation uses the OpenAI Responses API with Pydantic Structured Outputs, following the [official OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs). Provider code is isolated in `app/services/ai/provider.py`; business services do not import the SDK.

## Technology

- Python 3.11+
- Flask, Jinja2, Flask-Login, Flask-WTF, Flask-Limiter
- SQLAlchemy with SQLite locally and PostgreSQL-compatible configuration
- Tailwind CSS and Chart.js in the browser
- Vanilla JavaScript and Fetch API
- OpenAI Python SDK and Pydantic
- pytest and pytest-cov

## Installation

```powershell
git clone https://github.com/Arjunren/parksmart-ai.git
cd parksmart-ai
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Generate a long random `SECRET_KEY` and put it in `.env`. Add `OPENAI_API_KEY` for AI Factory runs. The default `OPENAI_MODEL` is cost-conscious and can be changed through configuration without changing agent code.

Initialize the database and create the first administrator:

```powershell
$env:FLASK_APP = "run.py"
flask init-db
flask create-admin
flask run
```

Open `http://127.0.0.1:5000`. The public anonymous feedback form is available at `/feedback/submit`.

### Optional demonstration fixtures

After creating an administrator, `flask seed-demo` adds clearly labeled classroom demonstration records. It refuses to run when operational data already exists. These fixtures must not be treated as production data.

## Configuration

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session and CSRF signing key |
| `OPENAI_API_KEY` | Server-side OpenAI credential; never exposed to JavaScript |
| `OPENAI_MODEL` | Structured-output capable model name |
| `DATABASE_URL` | SQLite or PostgreSQL SQLAlchemy URL |
| `RATELIMIT_STORAGE_URI` | Redis URL for shared rate limits in production; `memory://` locally |
| `FLASK_ENV` | `development` or `production` cookie/security behavior |

Never commit `.env`, local SQLite databases, real visitor records, API keys, or other secrets.

## Running tests

```powershell
pytest
pytest --cov=app --cov-report=term-missing
```

Tests use an in-memory SQLite database and mocked AI providers. They do not call the OpenAI API.

## Security

ParkSmart AI includes password hashing, CSRF protection, secure session settings, role checks, ORM parameter binding, Jinja output escaping, allow-list validation, defensive response headers, rate limits, request-size limits, API timeouts, safe errors, and activity/agent logging. AI recommendations never directly change operational records. See [SECURITY.md](SECURITY.md) for the OWASP-oriented review.

## Documentation

- [Implementation plan](IMPLEMENTATION_PLAN.md)
- [Architecture and agent contracts](ARCHITECTURE.md)
- [Complete final-project blueprint](FINAL_PROJECT_BLUEPRINT.md)
- [Security](SECURITY.md)
- [Deployment Guide (Render & Production)](DEPLOYMENT.md)
- [Render Deployment Blueprint](render.yaml)
- [AWS Terraform foundation](terraform/aws/README.md)

## Screenshots

The dashboard, resource tables, AI Factory monitor, and recommendation review pages are ready for screenshots after loading either local operational records or the explicitly labeled demo fixtures. Keeping screenshots out of the initial source avoids presenting synthetic fixture values as real park operations.

## License

MIT — see [LICENSE](LICENSE).
