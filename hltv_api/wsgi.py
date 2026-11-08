"""Production WSGI entry point; database path is shared with the collector."""
import os
from .api import create_app
from .store import Store

application = create_app(Store(os.environ.get("HLTV_DB", "/data/hltv.sqlite3")))
