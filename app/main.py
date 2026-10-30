"""checkout-service -- a demo checkout API with a deliberately large memory footprint.

Stdlib only, so it runs on the public python image with no Dockerfile or pip
install. Kubernetes mounts this file from a ConfigMap and runs it directly.

On startup the service grows its resident memory to TARGET_MEMORY_MI (default
240 MiB, ~250 MB) to simulate a heavy in-memory cache. With a memory limit
below that (e.g. 128Mi) the kernel OOM-kills the container during warm-up.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))
TARGET_MEMORY_MI = int(os.environ.get("TARGET_MEMORY_MI", "240"))
CHUNK_MI = 8
MI = 1024 * 1024

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","service":"checkout-service","msg":"%(message)s"}',
)
log = logging.getLogger("checkout")

# Held for the life of the process so the memory stays resident.
_cache = []
_ready = threading.Event()
_stats = {"orders_total": 0, "orders_failed": 0}
_stats_lock = threading.Lock()


def rss_mi():
    """Current resident set size in MiB, read from /proc (Linux only)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def warm_cache():
    """Grow RSS to TARGET_MEMORY_MI in CHUNK_MI steps.

    Each chunk is filled with non-zero bytes so every page is actually touched
    and counted against the cgroup -- a zeroed bytearray could stay lazily mapped.
    """
    log.info(f"warming product cache, target={TARGET_MEMORY_MI}Mi")
    while rss_mi() < TARGET_MEMORY_MI:
        size = min(CHUNK_MI, TARGET_MEMORY_MI - int(rss_mi())) * MI
        if size <= 0:
            break
        _cache.append(b"\x01" * size)
        log.info(f"cache warm-up rss={rss_mi():.0f}Mi")
    log.info(f"product cache ready rss={rss_mi():.0f}Mi")
    _ready.set()


class Handler(BaseHTTPRequestHandler):
    server_version = "checkout-service/1.0"

    def _send(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
        elif self.path == "/readyz":
            if _ready.is_set():
                self._send(200, {"status": "ready"})
            else:
                self._send(503, {"status": "warming"})
        elif self.path == "/metrics":
            with _stats_lock:
                body = (
                    "# TYPE checkout_orders_total counter\n"
                    f"checkout_orders_total {_stats['orders_total']}\n"
                    "# TYPE checkout_orders_failed_total counter\n"
                    f"checkout_orders_failed_total {_stats['orders_failed']}\n"
                    "# TYPE checkout_process_resident_memory_mebibytes gauge\n"
                    f"checkout_process_resident_memory_mebibytes {rss_mi():.1f}\n"
                )
            self._send(200, body.encode(), "text/plain; version=0.0.4")
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/checkout":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            order = json.loads(self.rfile.read(length) or b"{}")
            items = order.get("items", [])
            if not items:
                raise ValueError("order has no items")
            total = sum(float(i.get("price", 0)) * int(i.get("qty", 1)) for i in items)
        except (ValueError, TypeError, AttributeError) as e:
            with _stats_lock:
                _stats["orders_failed"] += 1
            log.warning(f"checkout rejected: {e}")
            self._send(400, {"error": str(e)})
            return

        order_id = str(uuid.uuid4())
        with _stats_lock:
            _stats["orders_total"] += 1
        log.info(f"order placed id={order_id} items={len(items)} total={total:.2f}")
        self._send(201, {"order_id": order_id, "total": round(total, 2), "status": "confirmed"})

    def log_message(self, fmt, *args):
        # Skip probe and scrape noise; everything else goes through the JSON logger.
        if self.path not in ("/healthz", "/readyz", "/metrics"):
            log.info(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}")


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())

    threading.Thread(target=warm_cache, daemon=True).start()
    log.info(f"listening on :{PORT}")
    server.serve_forever()
    log.info("shut down cleanly")


if __name__ == "__main__":
    main()
