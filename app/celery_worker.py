# celery_worker.py (à la racine du projet, importable)
from app import create_app
from app.extensions import make_celery, celery

# 1) create flask app
flask_app = create_app()

# 2) configure global celery with the flask app
make_celery(flask_app)

# now 'celery' is configured and tasks imported
# export celery for CLI: celery -A celery_worker.celery worker --loglevel=info