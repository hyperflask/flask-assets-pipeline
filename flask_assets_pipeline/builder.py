import subprocess
import click
import threading
import re
import os


class BuilderBase:
    prefix = ""
    matchline = None
    dev_worker_callback = None

    def init(self, assets):
        self.assets = assets

    def start_dev_worker(self, exit_event, build_only=False, livereloader=None):
        args, env = self.get_dev_worker_command(build_only)

        if not args:
            self.build({}, [])
            return
        
        kwargs = (
            {"text": True, "bufsize": 1, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
            if self.dev_worker_callback
            else {}
        )
        process = subprocess.Popen(args, env=dict(os.environ, **env), **kwargs)
        if not self.dev_worker_callback:
            process.wait()
            return process

        def task():
            while not exit_event or not exit_event.is_set():
                line = process.stdout.readline().strip()
                click.echo(self.prefix + line)
                if not self.matchline or re.match(self.matchline, line):
                    self.dev_worker_callback(build_only, livereloader)

        thread = threading.Thread(target=task)
        thread.start()
        return process
    
    def get_dev_worker_command(self, build_only):
        return None, None
    
    def cleanup_after_dev_worker(self):
        pass
    
    def build(self, mapping, ignore_assets):
        raise NotImplementedError()


class Builder(BuilderBase):
    def __init__(self, callback):
        self.callback = callback

    def build(self, mapping, ignore_assets):
        self.callback()