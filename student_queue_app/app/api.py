from flask import Blueprint, jsonify, render_template
from flask_login import current_user, login_required

from .models import QueueSession
from .queue_service import serialize_session, passed_count


api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/sessions/<int:session_id>/snapshot")
@login_required
def session_snapshot(session_id: int):
    session = QueueSession.query.get_or_404(session_id)
    return jsonify(serialize_session(session))


@api_bp.route("/sessions/<int:session_id>/table")
@login_required
def session_table(session_id: int):
    session = QueueSession.query.get_or_404(session_id)
    return render_template("partials/_queue_table.html", session=session, current_user=current_user, passed_count=passed_count)
