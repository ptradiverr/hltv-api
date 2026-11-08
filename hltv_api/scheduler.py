"""One collector loop per pod; API requests only read the shared database."""
import logging
import os
import signal
from threading import Event

from .collector import Collector, CollectionError
from .parser import ParseError
from .store import Store
from .transport import TransportError

LOG = logging.getLogger("hltv-scheduler")


def collect_cycle(store):
    collector = Collector(backend="curl")
    try:
        for kind in ("results", "upcoming"):
            records = collector.collect(kind)
            store.save(records)
            LOG.info("Stored %d %s matches", len(records), kind)
    finally:
        collector.close()


def run(store, interval, stopped):
    if interval < 900:
        raise ValueError("Collection interval must be at least 900 seconds")
    while not stopped.is_set():
        try:
            collect_cycle(store)
        except (CollectionError, ParseError, TransportError, OSError, ValueError):
            # Free-form errors may contain upstream diagnostics: log a fixed
            # message. A blocked results request skips the rest of this cycle.
            LOG.error("Collection failed; retaining existing data until the next cycle")
        stopped.wait(interval)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopped = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    store = Store(os.environ.get("HLTV_DB", "/data/hltv.sqlite3"))
    run(store, int(os.environ.get("HLTV_INTERVAL_SECONDS", "1800")), stopped)


if __name__ == "__main__":
    main()
