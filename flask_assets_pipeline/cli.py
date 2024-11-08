from flask import current_app
from flask.cli import AppGroup
import subprocess
import threading
import os
import click
import shutil
from .livereload import start_reloader_app, Reloader
from .builders.esbuild import EsbuildBuilder
from .builders.templates import TemplateBuilder
from .builders.tailwind import TailwindBuilder


assets_cli = AppGroup("assets")


@assets_cli.command()
@click.option("--watch-path", type=click.Path(), multiple=True, help="Additional paths to watch")
@click.option("--watch-app", is_flag=True, help="Whether to watch python files in the app root")
@click.option(
    "--livereload/--no-livereload",
    is_flag=True,
    default=True,
    help="Whether to start a livereload server",
)
@click.option("--build-only", is_flag=True, help="Build and exit")
def dev(watch_path, watch_app, livereload, build_only):
    """Watch and build assets in development mode and launch a livereload server"""
    state = current_app.extensions["assets"]
    if build_only:
        livereload = False

    reloader = None
    if livereload:
        reloader = Reloader()
        click.echo(f"Starting with livereload enabled on port {state.livereload_port}")
        for path in watch_path:
            reloader.observe(path)
        if watch_app:
            reloader.observe(current_app.root_path, lambda e: e.src_path.endswith(".py"))

    exit_event = threading.Event()
    processes = []

    for builder in state.instance.load_builders():
        process = builder.start_dev_worker(exit_event, build_only, reloader)
        if process:
            processes.append((builder, process))

    if reloader:
        reloader.observer.start()
        start_reloader_app(reloader, state.livereload_port)
        exit_event.set()
        for builder, dev_worker_process in processes:
            dev_worker_process.terminate()
            dev_worker_process.wait()
        reloader.observer.stop()
        reloader.observer.join()
    else:
        try:
            for builder, dev_worker_process in processes:
                dev_worker_process.wait()
        except KeyboardInterrupt:
            exit_event.set()
            for builder, dev_worker_process in processes:
                dev_worker_process.terminate()
                dev_worker_process.wait()

    for builder, dev_worker_process in processes:
        builder.cleanup_after_dev_worker()


@assets_cli.command()
def build():
    """Build assets for production"""
    state = current_app.extensions["assets"]

    mapping = {}
    ignore_assets = []

    for builder in state.instance.load_builders():
        builder.build(mapping, ignore_assets)

    if state.assets_folder != current_app.static_folder:
        assets = state.instance.copy_assets_to_static(ignore_files=ignore_assets)
        for src, dest in assets.items():
            if dest.endswith(".js"):
                dest = [dest, {"map_as": src}]
            mapping[src] = [dest]

    state.instance.write_mapping_file(mapping)


@assets_cli.command()
def extract():
    """Extract inline assets from templates"""
    builder = current_app.extensions["assets"].instance.get_builder(TemplateBuilder)
    builder.extract_from_templates()


@assets_cli.command()
def init_tailwind():
    """Initialize tailwind configuration and input file (if they are missing)"""
    builder = current_app.extensions["assets"].instance.get_builder(TailwindBuilder)
    builder.check_tailwind_config()


@assets_cli.command()
@click.option("--port", type=click.INT)
@click.argument("paths", nargs=-1)
def livereload(paths, port):
    """Start a livereload server for the specified paths indepentently from the dev command"""
    if not port:
        port = int(current_app.extensions["assets"].livereload_port)
    click.echo(f"Starting with livereload enabled on port {port}")
    click.echo(f"Watching paths: {', '.join(paths)}")
    reloader = Reloader()
    for path in paths:
        reloader.observe(path)
    reloader.observer.start()
    start_reloader_app(reloader, port)
    reloader.observer.stop()
    reloader.observer.join()


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
@click.option("--watch", is_flag=True)
@click.option("--dev", is_flag=True)
@click.argument("args", nargs=-1)
def esbuild_script(watch, dev, args):
    """Run your esbuild script"""
    builder = current_app.extensions["assets"].instance.get_builder(EsbuildBuilder)
    _, env = builder.get_command(watch=watch, dev=dev)
    cmd = builder.make_script_command()
    cmd.extend(args)
    subprocess.run(cmd, env=dict(os.environ, **env))


@assets_cli.command()
@click.argument("name")
def download_google_font(name):
    pass
