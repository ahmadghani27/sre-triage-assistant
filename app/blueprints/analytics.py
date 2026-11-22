"""HTTP layer dasbor analitik."""

from flask import Blueprint, jsonify, render_template

from app.services.analytics_service import AnalyticsService

analytics_bp = Blueprint("analytics", __name__)

_service: AnalyticsService | None = None


def _get_service() -> AnalyticsService:
    global _service
    if _service is None:
        _service = AnalyticsService()
    return _service


@analytics_bp.get("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@analytics_bp.get("/api/analytics/charts")
def charts():
    service = _get_service()
    return jsonify(
        {
            "category_distribution": service.category_distribution(),
            "severity_distribution": service.severity_distribution(),
            "incident_trend": service.incident_trend(),
            "summary": service.summary(),
        }
    )