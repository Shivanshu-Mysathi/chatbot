import logging
from app.core.config import get_settings

def configure_logging() -> None:
    # Avoid request headers and bodies so credentials and conversation content are not logged.
    logging.basicConfig(level=get_settings().log_level.upper(), format='%(asctime)s %(levelname)s %(name)s %(message)s')
