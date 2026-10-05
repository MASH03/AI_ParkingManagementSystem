# Deployment

## Local development

Use Python 3.11 or newer, create a virtual environment, install `requirements.txt`, copy `.env.example` to `.env`, generate a strong `SECRET_KEY`, initialize an administrator, and run Flask. SQLite data is written below `instance/` and is intentionally ignored.

## Production checklist

1. Use PostgreSQL and set `DATABASE_URL` to a TLS-enabled connection string.
2. Set `FLASK_ENV=production`, a random `SECRET_KEY`, `OPENAI_API_KEY`, and the approved `OPENAI_MODEL` through the platform secret manager.
3. Run database migrations before switching traffic.
4. Serve with Gunicorn behind an HTTPS reverse proxy, for example `gunicorn 'app:create_app()'`.
5. Set `RATELIMIT_STORAGE_URI` to a private Redis endpoint when running multiple workers; do not use the in-memory backend across replicas.
6. Restrict outbound traffic, centralize application logs, back up the database, and monitor factory failures and repeated authentication failures.
7. Run `pytest`, dependency auditing, and a manual role/CSRF review for every release.

The in-process background thread is suitable for this medium student project. A production-scale deployment should move factory jobs to a durable queue while retaining the same database run state and two-agent contracts.

## Container and AWS reference deployment

`Dockerfile` runs the web process as an unprivileged user on port `8000`; `GET /health` is the load-balancer readiness check. For a local container smoke test, copy `.env.example` to `.env`, set a development `SECRET_KEY`, and run:

```powershell
docker compose up --build
```

The checked-in AWS foundation is in [`terraform/aws`](terraform/aws). It provisions a multi-AZ VPC, HTTPS application load balancer, private ECS Fargate web service, CloudWatch logging, and private PostgreSQL database. It deliberately accepts **secret ARNs**, never secret values. Create the database URL, Flask secret, and OpenAI key in AWS Secrets Manager before planning. See [`terraform/aws/README.md`](terraform/aws/README.md) for the deployment sequence.

## Render Deployment

This repository includes a [`render.yaml`](render.yaml) blueprint for fast, automated deployment on [Render](https://render.com).

### Option A: Automatic Blueprint Deployment (Recommended)

1. **Push code to GitHub/GitLab**.
2. Log into the [Render Dashboard](https://dashboard.render.com).
3. Click **New +** > **Blueprint**.
4. Connect your repository. Render will automatically detect [`render.yaml`](render.yaml) and provision:
   - A **PostgreSQL Database** (`parksmart-db`)
   - A **Python Web Service** (`parksmart-app`) running Gunicorn with `flask init-db` run automatically on pre-deploy.
5. In the Render Dashboard under `parksmart-app` > **Environment**, set `OPENAI_API_KEY` to your valid key.
6. Click **Apply**.

### Option B: Manual Setup via Render Dashboard

If configuring manually without the Blueprint:

1. **Create PostgreSQL Database**:
   - Name: `parksmart-db`
   - Database Name: `parksmart`
   - Copy the **Internal Database URL** once created.

2. **Create Web Service**:
   - Environment: `Python`
   - Build Command: `pip install -r requirements.txt`
   - Pre-Deploy Command: `flask init-db`
   - Start Command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 90 run:app`
   - Health Check Path: `/health`

3. **Set Environment Variables**:
   - `DATABASE_URL`: *(paste Internal Database URL)*
   - `SECRET_KEY`: *(generate a long secret string)*
   - `FLASK_ENV`: `production`
   - `OPENAI_API_KEY`: *(your key)*
   - `OPENAI_MODEL`: `gpt-4o-mini`
   - `PYTHON_VERSION`: `3.11.9`

### Creating the First Administrator User on Render

Once deployed, access the service's **Shell** tab in the Render Dashboard or run via the Render CLI:

```bash
flask create-admin --username admin --password "YourStrongPassword123!"
```

To load demonstration fixtures if needed for testing:

```bash
flask seed-demo
```

