from flask import render_template, g, has_request_context, url_for, send_from_directory, current_app
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
from .builders.cache_worker import CacheServiceWorkerBuilder, CACHE_WORKER_SCRIPT


@dataclass
class AssetsPipelineState:
    bundles: t.Mapping[str, t.Sequence[t.Union[str, "Entrypoint"]]]
    include: t.Sequence[t.Tuple[int, str]]
    route_template: str
    inline: bool
    include_inline_on_demand: bool
    inline_template_exts: t.Sequence[str]
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
    cache_worker: bool
    cache_worker_name: t.Optional[str]
    cache_worker_urls: t.Sequence[str]
    cache_worker_filename: str
    cache_worker_register: bool
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
        inline_template_exts=[".html", ".jinja"],
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
        cache_worker=False,
        cache_worker_name=None,
        cache_worker_urls=None,
        cache_worker_filename="cache-worker.js",
        cache_worker_register=None,
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
            inline_template_exts=app.config.get("ASSETS_INLINE_TEMPLATE_EXTS", inline_template_exts) or [],
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
            esbuild_aliases=app.config.get("ASSETS_ESBUILD_ALIASES", esbuild_aliases) or {},
            esbuild_external=app.config.get("ASSETS_ESBUILD_EXTERNAL", esbuild_external) or [],
            livereload_port=app.config.get("ASSETS_LIVERELOAD_PORT", livereload_port),
            tailwind=app.config.get("ASSETS_TAILWIND", tailwind),
            tailwind_args=app.config.get("ASSETS_TAILWIND_ARGS", tailwind_args) or [],
            tailwind_bin=app.config.get("ASSETS_TAILWIND_BIN", tailwind_bin),
            tailwind_suggested_content=app.config.get("ASSETS_TAILWIND_SUGGESTED_CONTENT", tailwind_suggested_content) or [],
            node_modules_path=app.config.get("ASSETS_NODE_MODULES_PATH", node_modules_path) or os.environ.get("NODE_PATH", "node_modules"),
            copy_files_from_node_modules=app.config.get("ASSETS_COPY_FILES_FROM_NODE_MODULES", copy_files_from_node_modules) or {},
            cdn_host=app.config.get("ASSETS_CDN_HOST", cdn_host),
            cdn_enabled=not app.debug if cdn_enabled is None else cdn_enabled,
            cache_worker=app.config.get("ASSETS_CACHE_WORKER", cache_worker),
            cache_worker_name=app.config.get("ASSETS_CACHE_WORKER_NAME", cache_worker_name),
            cache_worker_urls=app.config.get("ASSETS_CACHE_WORKER_URLS", cache_worker_urls) or [],
            cache_worker_filename=app.config.get("ASSETS_CACHE_WORKER_FILENAME", cache_worker_filename),
            cache_worker_register=app.config.get("ASSETS_CACHE_WORKER_REGISTER", cache_worker_register),
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
        if state.tailwind:
            self.include(f"{state.output_url}/{state.tailwind}")

        if not state.cdn_host:
            state.cdn_enabled = False
        if state.cache_worker_register is None:
            state.cache_worker_register = state.cache_worker
        if state.cache_worker_register:
            self.register_cache_worker_route()

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

    def bundle(self, assets, name=None, include=False, priority=1, from_package=None, assets_folder=None, output_folder=None):
        bundles = {}
        if isinstance(assets, dict):
            bundles = assets
        elif name:
            bundles[name] = assets
        else:
            bundles = {str(f): [f] for f in assets}
        for name, files in bundles.items():
            self.state.bundles[name] = [
                f if isinstance(f, Entrypoint) or is_abs_url(f) else
                Entrypoint.create(f, from_package=from_package, assets_folder=assets_folder, output_folder=output_folder)
                for f in files
            ]
        if include:
            self.include(list(bundles.keys()), priority)

    def blueprint_bundle(self, blueprint, assets, include=False):
        return self.bundle(
            assets,
            name=f"@{blueprint.name}",
            include=include,
            assets_folder=blueprint.static_folder,
            output_folder=blueprint.name,
        )

    def bundle_files(self, name=None, entrypoints_only=False):
        if name:
            files = self.state.bundles[name]
        else:
            files = [f for files in self.state.bundles.values() for f in files]
        if entrypoints_only:
            return [f if isinstance(f, Entrypoint) else Entrypoint.create(f) for f in files if not is_abs_url(f)]
        return files

    def include(self, path, priority=1):
        if not isinstance(path, (tuple, list)):
            path = [path]
        assets = g.include_assets if has_request_context() else self.state.include
        for p in path:
            if not isinstance(p, (tuple, list)) and p in self.state.bundles:
                assets.extend([(priority, str(e)) for e in self.bundle_files(p)])
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

    def url(self, filename, with_meta=False, single=True, external=False, with_pre=False, resolve=True):
        r = re.compile("(defer )?(static|import|prefetch|modulepreload|preload( as [a-z]+)?) ")
        meta = {}
        if isinstance(filename, (tuple, list)):
            filename, meta = filename
            if not isinstance(meta, dict):
                meta = {"modifier": meta}
        else:
            m = r.match(filename)
            if m:
                if m.group(1):
                    meta["defer"] = True
                meta["modifier"] = m.group(2)
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
        resolved_urls = self.resolve_asset_filename_to_url(filename) if resolve else [filename]
        for url in resolved_urls:
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
            if not with_pre and url_meta.get("modifier") in ("prefetch", "preload", "modulepreload"):
                continue
            urls[url] = url_meta
            
        urls = list(urls.keys() if not with_meta else urls.items())
        return urls[0] if single else urls

    def urls(self, paths=None, with_meta=False, external=False, with_pre=False, resolve=True):
        if paths is None:
            includes = g.include_assets if has_request_context() and 'include_assets' in g else self.state.include
            paths = [i[1] for i in sorted(includes, key=lambda i: i[0], reverse=True)]
        elif isinstance(paths, str):
            paths = [paths]
        urls = {}
        for f in paths:
            urls.update(dict(self.url(f, with_meta=True, single=False, external=external, with_pre=with_pre, resolve=resolve)))
        return urls.items() if with_meta else list(urls.keys())

    def split_urls(self, paths=None, with_meta=False, external=False, resolve=True):
        urls = self.urls(paths, with_meta=True, external=external, with_pre=True, resolve=resolve)
        pre = []
        scripts = []
        styles = []
        for url, meta in urls:
            if meta.get("modifier") in ("prefetch", "preload", "modulepreload"):
                pre.append((url, meta) if with_meta else url)
            elif url.endswith(".css") or meta.get("content_type") == "style":
                styles.append((url, meta) if with_meta else url)
            else:
                scripts.append((url, meta) if with_meta else url)
        return pre, scripts, styles

    def tags(self, paths=None, external=False, with_pre=True, resolve=True):
        tags = []
        pre = []
        for url, meta in self.urls(paths, with_meta=True, external=external, with_pre=with_pre, resolve=resolve):
            attrs = "".join(
                f' {k}' if v is True else f' {k}="{v}"'
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
        return Markup("\n".join(pre + tags))

    def head(self):
        tags = []
        if self.state.import_map:
            tags.append(
                '<script type="importmap">%s</script>'
                % json.dumps({"imports": self.state.import_map})
            )
        tags.append(self.tags())
        if self.state.cache_worker_register:
            tags.append(CACHE_WORKER_SCRIPT % {"worker_url": url_for("cache_service_worker")})
        if self.app.debug:
            tags.append(LIVERELOAD_SCRIPT % {"livereload_port": self.state.livereload_port})
        return Markup("\n".join(tags))

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

    def add_catch_all_route(self, include_root=True, endpoint="frontend_catch_all", **kwargs):
        paths = ["/<path:path>"]
        if include_root:
            paths.append("/")
        self.add_route(endpoint, paths, **kwargs)

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
        ]
        if self.state.tailwind:
            builtins.append(TailwindBuilder())
        if self.state.cache_worker:
            builtins.append(CacheServiceWorkerBuilder())
        for builder in builtins + self.state.builders:
            self.load_builder(builder)
        return self.builders

    def load_builder(self, builder, prepend=False):
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
        if prepend:
            self.builders.insert(0, builder)
        else:
            self.builders.append(builder)
        return builder
    
    def get_builder(self, builder_class):
        for builder in self.load_builders():
            if isinstance(builder, builder_class):
                return builder
        builder = builder_class()
        builder.init(self)
        return builder
    
    def register_cache_worker_route(self, url=None):
        def view_func():
            resp = send_from_directory(self.state.output_folder, self.state.cache_worker_filename, mimetype="text/javascript")
            resp.headers.add("Expires", 0)
            return resp
        self.app.add_url_rule(url or f"/{self.state.cache_worker_filename}", endpoint="cache_service_worker", view_func=view_func)


@dataclass
class Entrypoint:
    filename: str
    outfile: t.Optional[str] = None
    from_package: t.Optional[str] = None

    @classmethod
    def create(cls, filename, outfile=None, from_package=None, assets_folder=None, output_folder=None):
        if "=" in filename:
            filename, outfile = filename.split("=", 1)
        if ":" in filename:
            from_package, filename = filename.split(":", 1)
        if from_package and not outfile:
            outfile = filename
        path = filename
        if assets_folder and not os.path.isabs(filename):
            path = os.path.join(assets_folder, filename)
            if not outfile:
                outfile = filename
        if output_folder:
            outfile = os.path.join(output_folder, outfile or filename)
        return cls(path, outfile, from_package)
    
    @property
    def path(self):
        return f"{self.from_package}:{self.filename}" if self.from_package else self.filename
    
    @property
    def is_abs(self):
        return self.from_package or os.path.isabs(self.filename)
    
    def resolve_path(self, assets_folder=None):
        filename = self.filename
        if self.from_package == "jinja":
            filename = current_app.jinja_env.loader.get_source(current_app.jinja_env, filename)[1] # resolve filename without compiling templates
        elif self.from_package:
            filename = resolve_package_file(self.from_package, filename)
        elif not os.path.isabs(filename) and assets_folder:
            filename = os.path.join(assets_folder, filename)
        return filename
    
    def __str__(self):
        return self.path
    
    def __repr__(self):
        return f"{self.path}={self.outfile}" if self.outfile else self.path


def resolve_package_file(package, filename):
    m = importlib.import_module(package)
    return os.path.join(os.path.dirname(m.__file__), filename)