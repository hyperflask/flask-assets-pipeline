from ..builder import BuilderBase
import click
import os
from flask import current_app
from watchdog.events import FileSystemEventHandler
from jinja2 import TemplateNotFound


class TemplateBuilder(BuilderBase):
    def start_dev_worker(self, exit_event, build_only=False, livereloader=None):
        if self.assets.state.inline:
            click.echo("Extracting bundled assets from templates")
            self.extract_from_templates()
            current_app.jinja_env.auto_reload = True
            
        if livereloader:
            # recompile templates when they are modified to immediately extract assets and trigger a rebuild
            watch_template_folder = [os.path.join(current_app.root_path, current_app.template_folder)]
            for bp in current_app.iter_blueprints():
                if bp.template_folder:
                    watch_template_folder.append(os.path.join(bp.root_path, bp.template_folder))
            watch_template_folder.extend(self.assets.state.watch_template_folders)
            for path in watch_template_folder:
                if os.path.exists(path):
                    livereloader.observer.schedule(
                        TemplateCompilerHandler(path, self.assets.app, livereloader), path, recursive=True
                    )

    def build(self, mapping, ignore_assets):
        if self.assets.state.inline:
            self.extract_from_templates()

    def extract_from_templates(self, env=None, loader=None, write=True):
        if not env:
            env = self.assets.app.jinja_env
        if not loader:
            loader = env.loader
        with self.assets.app.app_context():
            env.write_inline_assets = write
            for template in loader.list_templates():
                if template.rsplit(".", 1)[1].lower() in self.assets.state.inline_template_exts:
                    source = loader.get_source(env, template)[0]
                    env.compile(source, template) # force the compilation so the extension parse() method is executed


class TemplateCompilerHandler(FileSystemEventHandler):
    def __init__(self, path, app, broker=None):
        self.path = os.path.abspath(path)
        self.app = app
        self.broker = broker

    def on_modified(self, event):
        if not event.is_directory and os.path.abspath(event.src_path).startswith(self.path):
            tpl = os.path.relpath(event.src_path, self.path)
            if template.rsplit(".", 1)[1].lower() not in self.app.extensions["assets"].inline_template_exts:
                return
            try:
                with self.app.app_context():
                    try:
                        source = self.app.jinja_env.loader.get_source(self.app.jinja_env, tpl)[0]
                        self.app.jinja_env.compile(source, tpl) # force the compilation so the extension parse() method is executed
                    except TemplateNotFound:
                        # handle loaders that do weird stuff :)
                        for template in self.app.jinja_loader.list_templates():
                            if template.endswith(tpl):
                                self.app.jinja_env.get_template(template)
                if self.broker:
                    self.broker.ping()
            except:
                raise

