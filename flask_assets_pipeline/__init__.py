from flask import render_template, g, has_request_context, url_for, send_from_directory
from markupsafe import Markup
from dataclasses import dataclass
import typing as t
import os
import json
import re
import urllib.parse
import importlib
from .cli import assets_cli
from .jinja import configure_environment
from .livereload import LIVERELOAD_SCRIPT
from .utils import copy_assets, is_abs_url
from .builder import BuilderBase
from .builders.node_deps import NodeDependenciesBuilder
from .builders.templates import TemplateBuilder
from .builders.esbuild import EsbuildBuilder
from .builders.tailwind import TailwindBuilder


@dataclass
class AssetsPipelineState:
    bundles: t.Sequence[str] | t.Mapping[str, t.Sequence[str]]
    include: t.Sequence[t.Tuple[int, str]]
    route_template: str
    inline: bool
    include_inline_on_demand: bool
    import_map: t.Mapping[str, str]
    expose_node_packages: t.Sequence[str]
    assets_folder: str
    assets_endpoint: str
    assets_url_path: str
    stamp_assets: bool
    output_folder: str
    output_url: str
    mapping_file: str
    esbuild_script: str
    esbuild_cache_metafile: bool
    esbuild_args: t.Sequence[str]
    esbuild_bin: str
    esbuild_splitting: bool
    esbuild_target: t.Optional[t.Sequence[str]]
    esbuild_aliases: t.Mapping[str, str]
    esbuild_external: t.Sequence[str]
    livereload_port: str
    tailwind: str
    tailwind_args: t.Sequence[str]
    tailwind_bin: str
    tailwind_suggested_content: t.Sequence[str]
    node_modules_path: str
    copy_files_from_node_modules: t.Mapping[str, str]
    cdn_host: str
    cdn_enabled: bool
    mapping: t.Mapping[str, t.Sequence[str]]
    watch_template_folders: t.Sequence[str]
    builders: t.Sequence[t.Type[BuilderBase]]
    instance: "AssetsPipeline"


PRELOAD_AS_EXT_MAPPING = {
    "css": "style",
    "js": "script",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "webp": "image",
    "svg": "image",
    "woff": "font",
    "woff2": "font",
    "ttf": "font",
    "otf": "font",
    "mp4": "video",
    "webm": "video",
    "ogg": "video",
    "mp3": "audio",
    "wav": "audio",
    "flac": "audio",
    "aac": "audio",
    "json": "fetch",
    "html": "fetch",
}


class AssetsPipeline:
    def __init__(self, app=None, **kwargs):
        if app:
            self.init_app(app, **kwargs)

    def init_app(
        self,
        app,
        bundles=None,
        include=None,
        route_template="frontend_route.html",
        inline=False,
        include_inline_on_demand=False,
        import_map=None,
        expose_node_packages=None,
        assets_folder=None,
        assets_url_path="/static/assets",
        stamp_assets=True,
        output_folder=None,
        output_url=None,
        mapping_file="assets.json",
        esbuild_script=None,
        esbuild_cache_metafile=None,
        esbuild_args=None,
        esbuild_bin=["npx", "esbuild"],
        esbuild_splitting=True,
        esbuild_target=None,
        esbuild_aliases=None,
        esbuild_external=None,
        livereload_port="7878",
        tailwind=None,
        tailwind_args=None,
        tailwind_bin=["npx", "tailwindcss"],
        tailwind_suggested_content=None,
        node_modules_path=None,
        copy_files_from_node_modules=None,
        cdn_host=None,
        cdn_enabled=None,
        with_jinja_ext=True
    ):
        bundles = app.config.get("ASSETS_BUNDLES", bundles)
        include = app.config.get("ASSETS_INCLUDE", include)
        assets_folder = app.config.get("ASSETS_FOLDER", assets_folder)
        output_folder = app.config.get("ASSETS_OUTPUT_FOLDER", output_folder)
        output_url = app.config.get("ASSETS_OUTPUT_URL", output_url)
        mapping_file = app.config.get("ASSETS_MAPPING_FILE", mapping_file)
        esbuild_cache_metafile = app.config.get("ASSETS_ESBUILD_CACHE_METAFILE", esbuild_cache_metafile)  # fmt: skip
        cdn_enabled = app.config.get("ASSETS_CDN_ENABLED", cdn_enabled)

        if assets_folder is None:
            assets_folder = app.static_folder
        else:
            assets_folder = os.path.join(app.root_path, assets_folder)
        if not output_folder:
            output_folder = os.path.join(app.static_folder, "dist")
        else:
            output_folder = os.path.join(app.root_path, output_folder)
        if not output_url:
            output_url = f"{app.static_url_path}/dist"

        self.app = app
        state = self.state = AssetsPipelineState(
            bundles={},
            include=[],
            route_template=app.config.get("ASSETS_ROUTE_TEMPLATE", route_template),
            inline=app.config.get("ASSETS_INLINE", inline),
            include_inline_on_demand=app.config.get("ASSETS_INCLUDE_INLINE_ON_DEMAND", include_inline_on_demand),
            import_map=app.config.get("ASSETS_IMPORT_MAP", import_map) or {},
            expose_node_packages=app.config.get("ASSETS_EXPOSE_NODE_PACKAGES", expose_node_packages) or [],
            assets_folder=assets_folder,
            assets_endpoint="static",
            assets_url_path=app.config.get("ASSETS_URL_PATH", assets_url_path),
            stamp_assets=app.config.get("ASSETS_STAMP", stamp_assets),
            output_folder=output_folder,
            output_url=output_url,
            mapping_file=os.path.join(app.root_path, mapping_file),
            esbuild_script=app.config.get("ASSETS_ESBUILD_SCRIPT", esbuild_script),
            esbuild_cache_metafile=not app.debug if esbuild_cache_metafile is None else esbuild_cache_metafile,
            esbuild_args=app.config.get("ASSETS_ESBUILD_ARGS", esbuild_args) or [],
            esbuild_bin=app.config.get("ASSETS_ESBUILD_BIN", esbuild_bin),
            esbuild_splitting=app.config.get("ASSETS_ESBUILD_SPLITTING", esbuild_splitting),
            esbuild_target=app.config.get("ASSETS_ESBUILD_TARGET", esbuild_target),
            esbuild_aliases=app.config.get("ASSETS_PACKAGE_ALIASES", esbuild_aliases) or {},
            esbuild_external=app.config.get("ASSETS_EXTERNAL_PACKAGES", esbuild_external) or [],
            livereload_port=app.config.get("ASSETS_LIVERELOAD_PORT", livereload_port),
            tailwind=app.config.get("ASSETS_TAILWIND", tailwind),
            tailwind_args=app.config.get("ASSETS_TAILWIND_ARGS", tailwind_args) or [],
            tailwind_bin=app.config.get("ASSETS_TAILWIND_BIN", tailwind_bin),
            tailwind_suggested_content=app.config.get("ASSETS_TAILWIND_SUGGESTED_CONTENT", tailwind_suggested_content) or [],
            node_modules_path=app.config.get("ASSETS_NODE_MODULES_PATH", node_modules_path) or os.environ.get("NODE_PATH", "node_modules"),
            copy_files_from_node_modules=app.config.get("ASSETS_COPY_FILES_FROM_NODE_MODULES", copy_files_from_node_modules) or {},
            cdn_host=app.config.get("ASSETS_CDN_HOST", cdn_host),
            cdn_enabled=not app.debug if cdn_enabled is None else cdn_enabled,
            mapping={},
            watch_template_folders=[],
            builders=[],
            instance=self,
        )  # fmt: skip
        app.extensions["assets"] = state

        separate_assets_folder = app.static_folder != state.assets_folder
        state.mapping = self.read_mapping()
        self.map_mapped_files()
        if (
            not app.debug
            and (state.bundles or state.tailwind or separate_assets_folder)
            and not state.mapping
        ):
            app.logger.warning(
                "No assets mapping found, please run 'flask assets build' to generate it"
            )

        if bundles:
            self.bundle(bundles, include=include is None)
        if include:
            self.include(include)

        if not state.cdn_host:
            state.cdn_enabled = False

        if separate_assets_folder and app.debug:
            # in debug mode, no need to copy assets to static, we serve them directly
            app.add_url_rule(
                f"{state.assets_url_path}/<path:filename>",
                endpoint="assets",
                view_func=lambda filename: send_from_directory(
                    state.assets_folder, filename, max_age=app.get_send_file_max_age(filename)
                ),
            )
            state.assets_endpoint = "assets"

        self.map_exposed_node_packages()

        configure_environment(app, asset_tags=with_jinja_ext, inline_assets=state.inline)

        @app.before_request
        def before_request():
            g.include_assets = list(state.include)
            if state.tailwind:
                self.include(f"{state.output_url}/{state.tailwind}")

        def include_asset(*args, **kwargs):
            self.include(*args, **kwargs)
            return ""

        app.jinja_env.globals.update(
            include_asset=include_asset,
            asset_url=self.url,
            static_url=lambda f, **kw: url_for("static", filename=f, **kw),
        )

        app.cli.add_command(assets_cli)
        self.builders = []

    def bundle(self, assets, name=None, include=False, priority=1, assets_folder=None, output_folder=None):
        bundles = {}
        if isinstance(assets, dict):
            bundles = assets
        elif name:
            bundles[name] = assets
        else:
            bundles = {f: [f] for f in assets}
        for name, files in bundles.items():
            self.state.bundles[name] = [self.format_bundle_file(f, assets_folder=assets_folder, output_folder=output_folder) for f in files]
        if include:
            self.include(list(bundles.keys()), priority)

    def format_bundle_file(self, filename, outfile=None, assets_folder=None, output_folder=None):
        if is_abs_url(filename):
            return filename
        if "=" in filename:
            filename, _outfile = filename.split("=", 1)
            if not outfile:
                outfile = _outfile
        path = filename
        if assets_folder and not os.path.isabs(filename):
            path = os.path.abspath(os.path.join(assets_folder, filename))
            if not outfile:
                outfile = filename
        if output_folder:
            outfile = os.path.join(output_folder, outfile or filename)
        if outfile:
            return path, outfile
        return path

    def blueprint_bundle(self, blueprint, assets, include=False):
        return self.bundle(
            assets,
            name=f"@{blueprint.name}",
            include=include,
            assets_folder=blueprint.static_folder,
            output_folder=blueprint.name,
        )

    def bundle_files(self, name=None, entrypoint_only=False):
        _files = []
        if name:
            files = self.state.bundles[name]
        else:
            files = [f for files in self.state.bundles.values() for f in files]
        for file in files:
            entrypoint = file
            outfile = None
            if isinstance(file, (tuple, list)):
                entrypoint, outfile = file
            elif not is_abs_url(file) and "=" in file:
                entrypoint, outfile = file.split("=", 1)
            _files.append((entrypoint, outfile))
        return [f[0] for f in _files] if entrypoint_only else _files

    def package_from_path(self, path, alias=None):
        if not alias:
            alias = os.path.basename(path)
        self.state.esbuild_aliases[alias] = os.path.abspath(path)

    def package_from_blueprint(self, blueprint, alias=None):
        if not alias:
            alias = blueprint.name
        self.state.esbuild_aliases[alias] = os.path.abspath(blueprint.static_folder)

    def include(self, path, priority=1):
        if not isinstance(path, (tuple, list)):
            path = [path]
        assets = g.include_assets if has_request_context() else self.state.include
        for p in path:
            if p in self.state.bundles:
                assets.extend([(priority, f) for f in self.bundle_files(p, True)])
            else:
                assets.append([priority, p])

    def resolve_asset_filename_to_url(self, filename):
        if has_request_context() and "assets_map" in g:
            mapping = g.assets_map
        else:
            mapping = self.state.mapping
            if self.app.debug:
                mapping = self.read_mapping()
            if has_request_context():
                g.assets_map = mapping
        return mapping.get(filename, [filename])

    def url(self, filename, with_meta=False, single=True, external=False):
        r = re.compile("(static|import|prefetch|modulepreload|preload( as [a-z]+)?) ")
        meta = {}
        if isinstance(filename, (tuple, list)):
            filename, meta = filename
            if not isinstance(meta, dict):
                meta = {"modifier": meta}
        else:
            m = r.match(filename)
            if m:
                meta["modifier"] = m.group(1)
                filename = filename[m.end() :]
                if meta["modifier"].startswith("preload as "):
                    meta["modifier"], meta["content_type"] = meta["modifier"].split(" as ", 1)
                elif meta["modifier"] == "preload":
                    meta["content_type"] = PRELOAD_AS_EXT_MAPPING.get(
                        filename.split(".")[-1], "fetch"
                    )
        if "#" in filename:
            filename, fragment = filename.split("#", 1)
            meta.update(urllib.parse.parse_qs(fragment))

        urls = {}
        for url in self.resolve_asset_filename_to_url(filename):
            url_meta = dict(meta)
            if isinstance(url, (tuple, list)):
                url, _meta = url
                url_meta.update(_meta)
            if is_abs_url(url):
                url_meta.setdefault("crossorigin", "anonymous")
            else:
                if not url.startswith("/"):
                    url = url_for(
                        'static' if url_meta.get("modifier") == "static" else self.state.assets_endpoint,
                        filename=url,
                        _external=external if not self.state.cdn_enabled else False,
                    )
                if self.state.cdn_enabled:
                    url = self.state.cdn_host + url
            urls[url] = url_meta
            
        urls = list(urls.keys()) if not with_meta else urls.items()
        return urls[0] if single else urls

    def urls(self, paths=None, with_meta=False):
        if paths is None:
            includes = g.include_assets if has_request_context() and 'include_assets' in g else self.state.include
            paths = [i[1] for i in sorted(includes, key=lambda i: i[0], reverse=True)]
        elif isinstance(paths, str):
            paths = [paths]
        urls = {}
        for f in paths:
            urls.update(dict(self.url(f, with_meta=True, single=False)))
        return urls.items() if with_meta else list(urls.keys())

    def tags(self, paths=None):
        tags = []
        pre = []
        if self.state.import_map:
            tags.append(
                '<script type="importmap">%s</script>'
                % json.dumps({"imports": self.state.import_map})
            )
        for url, meta in self.urls(paths, with_meta=True):
            attrs = "".join(
                f' {k}="{v}"'
                for k, v in meta.items()
                if v and k not in ("modifier", "content_type")
            )
            if meta.get("modifier") == "prefetch":
                pre.append('<link rel="prefetch" href="%s"%s>' % (url, attrs))
            elif meta.get("modifier") == "preload":
                pre.append(
                    '<link rel="preload" href="%s" as="%s"%s>' % (url, meta["content_type"], attrs)
                )
            elif meta.get("modifier") == "modulepreload":
                pre.append('<link rel="modulepreload" href="%s"%s>' % (url, attrs))
            elif meta.get("modifier") == "import":
                tags.append('<script src="%s" type="module"%s></script>' % (url, attrs))
            elif url.endswith(".css") or meta.get("content_type") == "style":
                tags.append('<link rel="stylesheet" href="%s"%s>' % (url, attrs))
            else:
                tags.append('<script src="%s"%s></script>' % (url, attrs))
        if self.app.debug:
            tags.append(LIVERELOAD_SCRIPT % {"livereload_port": self.state.livereload_port})
        return Markup("\n".join(pre + tags))

    def add_route(self, endpoint, url, decorators=None, template=None, app=None, **options):
        app = app or self.app
        def view_func(*args, **kwargs):
            return render_template(template or self.state.route_template)
        if decorators:
            for decorator in decorators:
                view_func = decorator(view_func)
        urls = url if isinstance(url, (list, tuple)) else [url]
        for url in urls:
            app.add_url_rule(url, endpoint, view_func, **options)

    def map_import(self, name, url):
        self.state.import_map[name] = url

    def map_mapped_files(self):
        for src, out in self.state.mapping.items():
            for file in out:
                if isinstance(file, (tuple, list)) and file[1].get("map_as"):
                    self.map_import(file[1]["map_as"], file[0])

    def map_exposed_node_packages(self):
        for name in self.state.expose_node_packages:
            if ":" in name:
                name, _ = name.split(":", 1)
            self.map_import(name, f"{self.state.output_url}/vendor/{name}.js")

    def read_mapping(self):
        try:
            with open(self.state.mapping_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def write_mapping_file(self, mapping, out=None, merge=False):
        if not out:
            out = self.state.mapping_file
        with open(out, "rw" if merge else "w") as f:
            if merge:
                mapping = dict(json.load(f), **mapping)
            json.dump(mapping, f, indent=2)

    def copy_assets_to_static(self, src=None, dest=None, stamp=None, ignore_files=None):
        if src is None:
            src = self.state.assets_folder
        if dest is None:
            dest = self.app.static_folder
        if stamp is None:
            stamp = self.state.stamp_assets

        ignore_files = ignore_files or []
        for files in self.state.bundles.values():
            ignore_files.extend(files)
        if self.state.tailwind:
            ignore_files.append(self.state.tailwind)

        return copy_assets(src, dest, stamp, ignore_files, self.app.logger)
    
    def load_builders(self):
        if self.builders:
            return self.builders
        builtins = [
            NodeDependenciesBuilder(),
            TemplateBuilder(),
            EsbuildBuilder(),
            TailwindBuilder(),
        ]
        for builder in builtins + self.state.builders:
            if isinstance(builder, str):
                if ":" in builder:
                    module, class_name = builder.rsplit(":", 1)
                else:
                    module = builder
                    class_name = None
                m = importlib.import_module(module)
                if class_name:
                    builder = getattr(m, class_name)
                else:
                    for cls in m.__dict__.values():
                        if isinstance(cls, type) and issubclass(cls, BuilderBase):
                            builder = cls
                            break
                if isinstance(builder, str):
                    raise Exception(f"Builder class '{builder}' not found in module")
            elif isinstance(builder, type):
                builder = builder()
            builder.init(self)
            self.builders.append(builder)
        return self.builders
    
    def get_builder(self, builder_class):
        for builder in self.load_builders():
            if isinstance(builder, builder_class):
                return builder
        builder = builder_class()
        builder.init(self)
        return builder