from flask import Flask
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from werkzeug.serving import run_simple
import queue
import os
import logging


LIVERELOAD_SCRIPT = """
<script nonce="%(nonce)s">
let livereloadTimeout;
new EventSource('http://localhost:%(livereload_port)s').addEventListener('change', () => {
    if (livereloadTimeout) {
        clearTimeout(livereloadTimeout);
    }
    livereloadTimeout = setTimeout(() => {
        window.location.reload();
    }, 200);
});
</script>
"""


class ReloadHandler(FileSystemEventHandler):
    def __init__(self, broker, filter=None, callback=None):
        self.broker = broker
        self.filter = filter
        self.callback = callback

    def on_modified(self, event):
        if not self.filter or self.filter(event):
            if self.callback:
                self.callback(event, self.broker)
            else:
                self.broker.ping()


class Reloader:
    def __init__(self, observer=None):
        if not observer:
            observer = Observer()
        self.observer = observer
        self.subscribers = []

    def observe(self, path, filter=None, callback=None, recursive=True):
        self.observer.schedule(ReloadHandler(self, filter, callback), path, recursive=recursive)

    def subscribe(self):
        q = queue.Queue(maxsize=5)
        self.subscribers.append(q)
        return q

    def ping(self):
        print("Reloading")
        subscribers = self.subscribers
        msg = "event: change\ndata: ok\n\n"
        for i in reversed(range(len(subscribers))):
            try:
                subscribers[i].put_nowait(msg)
            except queue.Full:
                del subscribers[i]


def create_reloader_app(reloader):
    app = Flask(__name__)

    @app.after_request
    def after_request(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.route("/")
    def index():
        def stream():
            sub = reloader.subscribe()
            while True:
                yield sub.get()

        return stream(), {"Content-Type": "text/event-stream", "Access-Control-Allow-Origin": "*"}

    return app


def start_reloader_app(reloader, port):
    os.environ["FLASK_RUN_FROM_CLI"] = "false"
    logger = logging.getLogger("werkzeug")
    for handler in logger.handlers:
        logger.removeHandler(handler)
    logger.addHandler(logging.NullHandler())
    app = create_reloader_app(reloader)
    run_simple("127.0.0.1", int(port), app, threaded=True)
