import os
from flask import Flask

from dotenv import load_dotenv

from app.extensions import csrf, llm, get_db, close_db
from app.blueprints.triage import triage_bp
from app.blueprints.analytics import analytics_bp


def create_app():
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        DATABASE=os.path.join(app.root_path, "..", "data", "app.db"),
        MAX_CONTENT_LENGTH=5000,
    )

    data_dir = os.path.dirname(app.config["DATABASE"])
    os.makedirs(data_dir, exist_ok=True)

    csrf.init_app(app)
    llm.init_app(app)
    app.teardown_appcontext(close_db)

    app.register_blueprint(triage_bp)
    app.register_blueprint(analytics_bp)

    return app
