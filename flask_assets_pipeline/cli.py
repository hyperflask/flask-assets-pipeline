from flask import current_app
from flask.cli import AppGroup
from jinja2 import TemplateNotFound
import subprocess
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import click
import json
import tempfile
import re
import shutil
from .livereload import start_reloader_app, Broker, ReloadHandler


assets_cli = AppGroup("assets")


class TemplateCompilerHandler(FileSystemEventHandler):
    def __init__(self, path, app, broker=None):
        self.path = os.path.abspath(path)
        self.app = app
        self.broker = broker

    def on_modified(self, event):
        if not event.is_directory and os.path.abspath(event.src_path).startswith(self.path):
            tpl = os.path.relpath(event.src_path, self.path)
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

    @staticmethod
    def observe(observer, path, app, broker):
        observer.schedule(TemplateCompilerHandler(path, app, broker), path, recursive=True)


@assets_cli.command()
@click.option(
    "--watch-template-folder",
    type=click.Path(),
    multiple=True,
    help="Additional template folders to watch (the app and blueprints one are auto included)",
)
@click.option("--watch-path", type=click.Path(), multiple=True, help="Additional paths to watch")
@click.option("--watch-app", is_flag=True, help="Whether to watch python files in the app root")
@click.option(
    "--livereload/--no-livereload",
    is_flag=True,
    default=True,
    help="Whether to start a livereload server",
)
@click.option(
    "--livereload-templates/--no-livereload-templates",
    is_flag=True,
    default=True,
    help="Whether to reload when templates change",
)
@click.option("--build-only", is_flag=True, help="Build and exit")
def dev(watch_template_folder, watch_path, watch_app, livereload, livereload_templates, build_only):
    """Watch and build assets in development mode and launch a livereload server"""
    state = current_app.extensions["assets"]
    observer = Observer()
    broker = Broker()
    if build_only:
        livereload = False
    if not livereload:
        livereload_templates = False

    if livereload:
        click.echo(f"Starting with livereload enabled on port {state.livereload_port}")
        for path in watch_path:
            observer.schedule(ReloadHandler(broker), path, recursive=True)
        if watch_app:
            observer.schedule(
                ReloadHandler(broker, lambda e: e.src_path.endswith(".py")),
                current_app.root_path,
                recursive=True,
            )

    state.instance.build_node_dependencies()

    if state.inline:
        click.echo("Extracting bundled assets from templates")
        state.instance.extract_from_templates()
        current_app.jinja_env.auto_reload = True
        
    if not build_only and (state.inline or livereload_templates):
        # recompile templates when they are modified to immediately extract assets and trigger a rebuild
        watch_template_folder = list(watch_template_folder) + [
            os.path.join(current_app.root_path, current_app.template_folder)
        ]
        for bp in current_app.iter_blueprints():
            if bp.template_folder:
                watch_template_folder.append(os.path.join(bp.root_path, bp.template_folder))
        watch_template_folder.extend(state.watch_template_folders)
        for path in watch_template_folder:
            if os.path.exists(path):
                TemplateCompilerHandler.observe(
                    observer, path, state.instance.app, broker if livereload_templates else None
                )

    exit_event = threading.Event()
    processes = []
    esbuild_metafile = None

    if state.bundles:
        esbuild_metafile = tempfile.NamedTemporaryFile(delete=False)

        def on_esbuild_finished():
            with state.instance.app.app_context():
                if _convert_esbuild_metafile(esbuild_metafile.name) and livereload:
                    broker.ping()

        processes.append(
            start_build_worker(
                state.instance.get_esbuild_command(
                    watch=not build_only, dev=True, metafile=esbuild_metafile.name
                ),
                prefix=f"[{state.esbuild_script}]" if state.esbuild_script else "[esbuild]",
                callback=on_esbuild_finished if not build_only else None,
                matchline="\[watch\] build finished",
                exit_event=exit_event,
            )
        )

        if build_only:
            _convert_esbuild_metafile(esbuild_metafile.name)

    if state.tailwind:
        state.instance.check_tailwind_config()
        processes.append(
            start_build_worker(
                state.instance.get_tailwind_command(watch=not build_only, dev=True),
                prefix="[tailwind]",
                callback=broker.ping if livereload else None,
                matchline="Done in",
                exit_event=exit_event,
            )
        )

    if build_only:
        return

    if livereload or state.inline:
        observer.start()

    if not livereload:
        try:
            for process in processes:
                process.wait()
        except KeyboardInterrupt:
            for process in processes:
                process.terminate()
                process.wait()
    else:
        start_reloader_app(broker, state.livereload_port)
        exit_event.set()
        for process in processes:
            process.terminate()
            process.wait()

    if livereload or state.inline:
        observer.stop()
        observer.join()

    if esbuild_metafile:
        os.unlink(esbuild_metafile.name)


def start_build_worker(cmd_env_tuple, prefix="", callback=None, matchline=None, exit_event=None):
    args, env = cmd_env_tuple
    kwargs = (
        {"text": True, "bufsize": 1, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
        if callback
        else {}
    )
    process = subprocess.Popen(args, env=dict(os.environ, **env), **kwargs)
    if not callback:
        process.wait()
        return process

    def task():
        while not exit_event or not exit_event.is_set():
            line = process.stdout.readline().strip()
            click.echo(prefix + line)
            if not matchline or re.match(matchline, line):
                callback()

    thread = threading.Thread(target=task)
    thread.start()
    return process


@assets_cli.command()
def build():
    """Build assets for production"""
    state = current_app.extensions["assets"]

    state.instance.build_node_dependencies()
    if state.inline:
        state.instance.extract_from_templates()

    mapping = {}
    ignore_assets = []

    if state.bundles:
        metafile = tempfile.NamedTemporaryFile(prefix="assets", delete=False)
        cmd, env = state.instance.get_esbuild_command(metafile=metafile.name)
        subprocess.run(cmd, env=dict(os.environ, **env))
        inputs, _mapping = state.instance.convert_esbuild_metafile(metafile.name)
        mapping.update(_mapping)
        ignore_assets.extend(inputs)
        os.unlink(metafile.name)

    if state.tailwind:
        state.instance.check_tailwind_config()
        cmd, env = state.instance.get_tailwind_command()
        subprocess.run(cmd, env=dict(os.environ, **env))
        ignore_assets.append(state.tailwind)

    if state.assets_folder != current_app.static_folder:
        assets = state.instance.copy_assets_to_static(ignore_files=ignore_assets)
        for src, dest in assets.items():
            if dest.endswith(".js"):
                dest = [dest, {"map_as": src}]
            mapping[src] = [dest]

    _dump_mapping_file(mapping)


@assets_cli.command()
@click.argument("filename", type=click.Path(exists=True))
@click.option(
    "--out", type=click.Path(), help="Output file (default: outputs to configured mapping file)"
)
@click.option("--merge", is_flag=True, help="Merge the output with the existing mapping file")
def convert_esbuild_metafile(filename, out, merge):
    _convert_esbuild_metafile(filename, out, merge)


def _convert_esbuild_metafile(filename, out=None, merge=False):
    try:
        inputs, mapping = current_app.extensions["assets"].instance.convert_esbuild_metafile(
            filename
        )
    except json.JSONDecodeError:
        return False
    _dump_mapping_file(mapping, out, merge)
    return True


def _dump_mapping_file(mapping, out=None, merge=False):
    if not out:
        out = current_app.extensions["assets"].mapping_file
    with open(out, "rw" if merge else "w") as f:
        if merge:
            mapping = dict(json.load(f), **mapping)
        json.dump(mapping, f, indent=2)


@assets_cli.command()
def extract():
    """Extract inline assets from templates"""
    current_app.extensions["assets"].instance.extract_from_templates()


@assets_cli.command()
def init_tailwind():
    """Initialize tailwind configuration and input file (if they are missing)"""
    current_app.extensions["assets"].instance.check_tailwind_config()


@assets_cli.command()
@click.option("--port", type=click.INT)
@click.argument("paths", nargs=-1)
def livereload(paths, port):
    """Start a livereload server for the specified paths indepentently from the dev command"""
    if not port:
        port = int(current_app.extensions["assets"].livereload_port)
    click.echo(f"Starting with livereload enabled on port {port}")
    click.echo(f"Watching paths: {', '.join(paths)}")
    broker = Broker()
    obs = Observer()
    handler = ReloadHandler(broker)
    for path in paths:
        obs.schedule(handler, path, recursive=True)
    obs.start()
    start_reloader_app(broker, port)
    obs.stop()
    obs.join()


@assets_cli.command()
@click.option("--filename", type=click.Path(), default="esbuild.mjs", help="Output filename")
def generate_esbuild_script(filename):
    """Generate a script to build assets with esbuild. Allows you to customize your build with plugins."""
    click.echo(f"Generating esbuild script in {filename}")
    shutil.copyfile(os.path.join(os.path.dirname(__file__), "esbuild.mjs"), filename)
    click.echo(
        f"Configure your app to use this script: app.config['ASSETS_ESBUILD_SCRIPT'] = '{filename}'"
    )


@assets_cli.command(
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    )
)
@click.argument("args", nargs=-1)
def esbuild_script(args):
    """Run your esbuild script"""
    state = current_app.extensions["assets"]
    _, env = state.instance.get_esbuild_command()
    cmd = state.instance.make_esbuild_script_command()
    cmd.extend(args)
    subprocess.run(cmd, env=dict(os.environ, **env))


@assets_cli.command()
@click.argument("name")
def download_google_font(name):
    pass
