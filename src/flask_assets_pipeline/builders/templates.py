from .base import BuilderBase
import click
import os
from flask import current_app
from watchdog.events import FileSystemEventHandler
from jinja2 import TemplateNotFound


class TemplateBuilder(BuilderBase):
    def start_dev_worker(self, exit_event, build_only=False, livereloader=None):
        if self.state.inline:
            click.echo("Extracting bundled assets from templates")
            self.extract_from_templates()
            current_app.jinja_env.auto_reload = True

        if livereloader:
            # recompile templates when they are modified to immediately extract assets and trigger a rebuild
            watch_template_folder = [
                os.path.join(current_app.root_path, current_app.template_folder)
            ]
            for bp in current_app.iter_blueprints():
                if bp.template_folder:
                    watch_template_folder.append(os.path.join(bp.root_path, bp.template_folder))
            watch_template_folder.extend(self.state.watch_template_folders)
            for path in watch_template_folder:
                if os.path.exists(path):
                    livereloader.observer.schedule(
                        TemplateCompilerHandler(path, self.app, livereloader),
                        path,
                        recursive=True,
                    )

    def build(self, mapping, ignore_assets):
        if self.state.inline:
            self.extract_from_templates()

    def extract_from_templates(self, env=None, loader=None, write=True):
        if not env:
            env = self.app.jinja_env
        if not loader:
            loader = env.loader
        with self.app.app_context():
            env.write_inline_assets = write
            for template in loader.list_templates():
                if os.path.splitext(template)[1].lower() in self.state.inline_template_exts:
                    source = loader.get_source(env, template)[0]
                    env.compile(
                        source, template
                    )  # force the compilation so the extension parse() method is executed


class TemplateCompilerHandler(FileSystemEventHandler):
    def __init__(self, path, app, broker=None):
        self.path = os.path.abspath(path)
        self.app = app
        self.broker = broker

    def on_modified(self, event):
        if not event.is_directory:
            self.compile(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self.compile(event.src_path)

    def on_moved(self, event):
        # editors doing atomic saves write a temp file then rename it
        if not event.is_directory:
            self.compile(event.dest_path)

    def compile(self, path):
        path = os.path.abspath(path)
        if not path.startswith(self.path + os.sep):
            return
        tpl = os.path.relpath(path, self.path)
        if (
            os.path.splitext(tpl)[1].lower()
            not in self.app.extensions["assets"].inline_template_exts
        ):
            return
        env = self.app.jinja_env
        with self.app.app_context():
            try:
                source = env.loader.get_source(env, tpl)[0]
                env.compile(source, tpl)  # force the compilation so the extension parse() method is executed
            except TemplateNotFound:
                # the template may be registered under a prefixed name (eg: app/components/Foo.html)
                tpl = tpl.replace(os.sep, "/")
                for template in env.loader.list_templates():
                    if template != tpl and not template.endswith("/" + tpl):
                        continue
                    source, filename, _ = env.loader.get_source(env, template)
                    if filename and os.path.abspath(filename) != path:
                        continue
                    env.compile(source, template)
        if self.broker:
            self.broker.ping()
