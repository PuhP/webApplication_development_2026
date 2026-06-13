import os
import time

from sqlalchemy.exc import OperationalError

from app import create_app
from app.seed import init_database

app = create_app()


def _init_with_retry() -> None:
    if os.getenv("AUTO_INIT_DB", "true").lower() not in {"1", "true", "yes", "on"}:
        return

    recreate = os.getenv("RECREATE_DB", "false").lower() in {"1", "true", "yes", "on"}
    seed_demo = os.getenv("SEED_DEMO_DATA", "true").lower() in {"1", "true", "yes", "on"}

    attempts = 20
    for attempt in range(1, attempts + 1):
        try:
            with app.app_context():
                init_database(seed_demo=seed_demo, recreate=recreate)
            return
        except OperationalError as exc:
            if attempt == attempts:
                raise
            print(f"БД ещё не готова ({attempt}/{attempts}): {exc}")
            time.sleep(2)


if __name__ == "__main__":
    _init_with_retry()
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
        threaded=True,
    )
