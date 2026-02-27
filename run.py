from app import create_app
from app.config import SERVER_HOST, SERVER_PORT
from app.logger import init_logging

app = create_app()
log = init_logging(app)   # attache handlers à app.logger

if __name__ == "__main__":
    log.info(f"Start webhook-cleaner on {SERVER_HOST}:{SERVER_PORT}")
    app.run(host=SERVER_HOST, port=SERVER_PORT)
