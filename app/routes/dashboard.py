from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from flask import Blueprint, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.models import (
    AIRecommendation,
    ActivityLog,
    Facility,
    IncidentReport,
    MaintenanceRequest,
    ParkZone,
    Reservation,
    Ticket,
    TicketPrice,
    Visitor,
    VisitorFeedback,
)


bp = Blueprint("dashboard", __name__)


def _bounds(target: date):
    start = datetime.combine(target, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


@bp.get("/landing")
@bp.get("/home")
def landing():
    zones = ParkZone.query.order_by(ParkZone.name).all()
    ticket_prices = TicketPrice.query.order_by(TicketPrice.amount).all()
    facilities = Facility.query.filter_by(status="Available").limit(8).all()
    total_capacity = sum(z.capacity for z in zones) or 500
    current_inside = sum(
        visitor.guest_count for visitor in Visitor.query.filter(Visitor.exit_time.is_(None)).all()
    )
    occupancy_pct = min(100, int((current_inside / total_capacity) * 100)) if total_capacity else 0
    return render_template(
        "landing.html",
        zones=zones,
        ticket_prices=ticket_prices,
        facilities=facilities,
        total_capacity=total_capacity,
        current_inside=current_inside,
        occupancy_pct=occupancy_pct,
    )


@bp.get("/")
def index():
    if not current_user.is_authenticated:
        return redirect(url_for("dashboard.landing"))
    return render_template("dashboard.html")


@bp.get("/dashboard")
@login_required
def dashboard_view():
    return render_template("dashboard.html")


@bp.get("/api/dashboard")
@login_required
def api_dashboard():
    today = date.today()
    start, end = _bounds(today)
    week_start = start - timedelta(days=6)
    visitors = Visitor.query.filter(Visitor.entry_time >= start, Visitor.entry_time < end).all()
    visitor_total = sum(visitor.guest_count for visitor in visitors)
    current_inside = sum(
        visitor.guest_count for visitor in Visitor.query.filter(Visitor.exit_time.is_(None)).all()
    )
    tickets_today = Ticket.query.filter(Ticket.entry_timestamp >= start, Ticket.entry_timestamp < end).count()
    reservations_today = Reservation.query.filter_by(reservation_date=today).count()
    active_facilities = Facility.query.filter_by(status="Available").count()
    maintenance_facilities = Facility.query.filter_by(status="Under Maintenance").count()
    open_maintenance = MaintenanceRequest.query.filter(
        MaintenanceRequest.status.in_(["Open", "Assigned", "In Progress"])
    ).count()
    incidents_today = IncidentReport.query.filter_by(incident_date=today).count()
    feedback_count = VisitorFeedback.query.filter(
        VisitorFeedback.feedback_date >= start, VisitorFeedback.feedback_date < end
    ).count()
    pending_recommendations = AIRecommendation.query.filter_by(status="Pending").count()
    priority_issues = AIRecommendation.query.filter(
        AIRecommendation.status == "Pending",
        AIRecommendation.priority.in_(["High", "Critical"]),
    ).count()

    traffic = []
    for offset in range(7):
        day_start = week_start + timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        records = Visitor.query.filter(
            Visitor.entry_time >= day_start, Visitor.entry_time < day_end
        ).all()
        traffic.append(
            {
                "label": day_start.strftime("%a"),
                "count": sum(record.guest_count for record in records),
            }
        )

    peak_counter = Counter(f"{visitor.entry_time.hour:02d}:00" for visitor in visitors)
    reservation_trend = []
    for offset in range(7):
        day = today - timedelta(days=6 - offset)
        reservation_trend.append(
            {"label": day.strftime("%a"), "count": Reservation.query.filter_by(reservation_date=day).count()}
        )
    maintenance_by_status = Counter(
        item.status for item in MaintenanceRequest.query.order_by(MaintenanceRequest.id).all()
    )
    feedback_by_category = Counter(
        item.category for item in VisitorFeedback.query.order_by(VisitorFeedback.id).all()
    )
    activities = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(8).all()

    return jsonify(
        {
            "metrics": {
                "visitors_today": visitor_total,
                "currently_inside": current_inside,
                "tickets_today": tickets_today,
                "reservations_today": reservations_today,
                "active_facilities": active_facilities,
                "maintenance_facilities": maintenance_facilities,
                "open_maintenance": open_maintenance,
                "incidents_today": incidents_today,
                "feedback_today": feedback_count,
                "ai_recommendations": pending_recommendations,
                "priority_issues": priority_issues,
            },
            "charts": {
                "visitor_traffic": traffic,
                "peak_hours": [
                    {"label": label, "count": count}
                    for label, count in sorted(peak_counter.items())
                ],
                "reservation_trends": reservation_trend,
                "maintenance": [
                    {"label": label, "count": count}
                    for label, count in maintenance_by_status.items()
                ],
                "feedback": [
                    {"label": label, "count": count}
                    for label, count in feedback_by_category.items()
                ],
            },
            "activities": [
                {
                    "action": item.action,
                    "details": item.details,
                    "user": item.user.username if item.user else "System",
                    "created_at": item.created_at.isoformat(),
                }
                for item in activities
            ],
        }
    )

