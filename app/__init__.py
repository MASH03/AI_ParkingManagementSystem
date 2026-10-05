from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import click
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import text

from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config


from app.extensions import csrf, db, limiter, login_manager, migrate
from app.models import (
    Facility,
    IncidentReport,
    MaintenanceRequest,
    ParkZone,
    Reservation,
    Staff,
    TicketPrice,
    User,
    Visitor,
    VisitorFeedback,
    utcnow,
)
from app.routes import register_blueprints


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    os.makedirs(app.instance_path, exist_ok=True)

    if app.config.get("SESSION_COOKIE_SECURE") or os.getenv("FLASK_ENV") == "production":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    register_blueprints(app)
    register_cli(app)
    register_handlers(app)

    @app.get("/health")
    def health_check():
        """Readiness endpoint for container orchestrators and load balancers."""
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            db.session.rollback()
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ok"})

    @app.context_processor
    def inject_globals():
        return {"current_year": datetime.now().year}

    if app.config.get("TESTING") or app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        with app.app_context():
            db.create_all()

    return app


@login_manager.user_loader
def load_user(user_id: str):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Authentication required."}), 401
    return redirect(url_for("auth.login", next=request.full_path))


def register_handlers(app: Flask) -> None:
    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://cdn.tailwindcss.com "
            "https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'",
        )
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.errorhandler(400)
    def bad_request(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Invalid request."}), 400
        return render_template("error.html", code=400, message="The request could not be processed."), 400

    @app.errorhandler(403)
    def forbidden(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "You do not have permission for this action."}), 403
        return render_template("error.html", code=403, message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Record not found."}), 404
        return render_template("error.html", code=404, message="That page could not be found."), 404

    @app.errorhandler(429)
    def rate_limited(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Too many requests. Please try again later."}), 429
        return render_template("error.html", code=429, message="Please wait before trying again."), 429

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        if request.path.startswith("/api/"):
            return jsonify({"error": "An internal error occurred."}), 500
        return render_template("error.html", code=500, message="An internal error occurred."), 500


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        click.echo("Database tables are ready.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(username: str, password: str):
        username = username.strip().lower()
        if len(username) < 3 or len(password) < 12:
            raise click.ClickException("Username must be 3+ characters and password 12+ characters.")
        if User.query.filter_by(username=username).first():
            raise click.ClickException("That username already exists.")
        user = User(username=username, role="Administrator")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Administrator '{username}' created.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Add clearly labeled, non-production fixtures for classroom demonstration."""
        if ParkZone.query.first():
            raise click.ClickException("Seed data was not added because operational data already exists.")
        admin = User.query.filter_by(role="Administrator").first()
        if not admin:
            raise click.ClickException("Create an administrator before loading demo fixtures.")

        zones = [
            ParkZone(name="Main Entrance", description="Primary visitor entry", max_capacity=300, current_visitors=120),
            ParkZone(name="Playground", description="Children's recreation area", max_capacity=100, current_visitors=86),
            ParkZone(name="Picnic Area", description="Reservable picnic spaces", max_capacity=240, current_visitors=105),
            ParkZone(name="Nature Trail", description="Managed nature walk", max_capacity=180, current_visitors=47),
        ]
        db.session.add_all(zones)
        db.session.flush()
        facilities = [
            Facility(name="Comfort Room 2", facility_type="Comfort Room", zone=zones[1], capacity=12, status="Under Maintenance"),
            Facility(name="Lakeside Gazebo", facility_type="Gazebo", zone=zones[2], capacity=25, status="Available"),
            Facility(name="Sports Court A", facility_type="Sports Court", zone=zones[2], capacity=40, status="Available"),
        ]
        db.session.add_all(facilities)
        db.session.flush()
        staff = Staff(employee_id="DEMO-001", name="Demo Park Staff", position="Operations Assistant", assigned_zone=zones[0], shift="Day")
        db.session.add(staff)
        db.session.add_all(
            [
                TicketPrice(category="Adult", amount=50),
                TicketPrice(category="Child", amount=25),
                TicketPrice(category="Senior Citizen", amount=30),
                TicketPrice(category="PWD", amount=30),
                TicketPrice(category="Student", amount=35),
                TicketPrice(category="Group", amount=40),
            ]
        )
        now = utcnow()
        for index, (hour, guests) in enumerate([(9, 30), (11, 45), (15, 80), (16, 95)]):
            db.session.add(
                Visitor(
                    display_name=f"Demo visitor group {index + 1}",
                    category="Group",
                    guest_count=guests,
                    entry_time=now.replace(hour=hour, minute=0, second=0, microsecond=0),
                    created_by=admin,
                )
            )
        for index in range(3):
            db.session.add(
                MaintenanceRequest(
                    facility=facilities[0],
                    zone=zones[1],
                    issue_title="Recurring plumbing concern (demo)",
                    description="Demonstration fixture for AI Factory analysis.",
                    priority="High",
                    reported_by=admin,
                    report_date=now - timedelta(hours=index),
                )
            )
        db.session.add(
            IncidentReport(
                incident_number="DEMO-INC-001",
                incident_type="Overcrowding",
                zone=zones[1],
                incident_date=date.today(),
                incident_time=time(15, 30),
                description="Demonstration crowding report.",
                reported_by=admin,
                severity="Medium",
            )
        )
        for index in range(4):
            db.session.add(
                VisitorFeedback(
                    rating=3,
                    category="Cleanliness",
                    comment="Demo comment: more waste bins requested near picnic tables.",
                    zone=zones[2],
                    is_anonymous=True,
                )
            )
        db.session.add(
            Reservation(
                reservation_number="DEMO-RES-001",
                customer_name="Demo Customer",
                facility=facilities[1],
                reservation_date=date.today(),
                start_time=time(13, 0),
                end_time=time(15, 0),
                guest_count=20,
                status="Confirmed",
            )
        )
        db.session.commit()
        click.echo("Demo fixtures loaded. They are labeled and must not be used as production data.")
