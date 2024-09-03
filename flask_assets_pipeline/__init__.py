from flask import render_template, g, has_request_context, url_for, send_from_directory
from markupsafe import Markup
from dataclasses import dataclass
import typing as t
import os
import json
import subprocess
import re
import urllib.parse
import shutil
from .cli import assets_cli
from .jinja import configure_environment
from .livereload import LIVERELOAD_SCRIPT
from .utils import copy_files, copy_assets


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

    def read_mapping(self):
        try:
            with open(self.state.mapping_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

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
            includes = g.include_assets if has_request_context() else self.state.include
            paths = [i[1] for i in sorted(includes, key=lambda i: i[0], reverse=True)]
        elif isinstance(paths, str):
            paths = [paths]
        urls = {}
        for f in paths:
            urls.update(dict(self.url(f, with_meta=True, single=False)))
        return urls.items() if with_meta else list(urls.keys())

    def tags(self):
        tags = []
        pre = []
        if self.state.import_map:
            tags.append(
                '<script type="importmap">%s</script>'
                % json.dumps({"imports": self.state.import_map})
            )
        for url, meta in self.urls(with_meta=True):
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

    def add_route(self, endpoint, url, decorators=None, **options):
        def view_func():
            return render_template(self.state.route_template)

        if decorators:
            for decorator in decorators:
                view_func = decorator(view_func)
        self.app.add_url_rule(url, endpoint=endpoint, view_func=view_func, **options)

    def map_import(self, name, url):
        self.state.import_map[name] = url

    def map_mapped_files(self):
        for src, out in self.state.mapping.items():
            for file in out:
                if isinstance(file, (tuple, list)) and file[1].get("map_as"):
                    self.map_import(file[1]["map_as"], file[0])

    def extract_from_templates(self, env=None, loader=None, write=True):
        if not env:
            env = self.app.jinja_env
        if not loader:
            loader = env.loader
        with self.app.app_context():
            env.write_inline_assets = write
            for template in loader.list_templates():
                source = loader.get_source(env, template)[0]
                env.compile(source, template) # force the compilation so the extension parse() method is executed

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

    def get_esbuild_command(self, watch=False, dev=False, metafile=None):
        inputs = []
        entrypoints = []
        for entrypoint, outfile in self.bundle_files():
            if is_abs_url(entrypoint):
                continue
            if not os.path.isabs(entrypoint):
                entrypoint = os.path.join(self.state.assets_folder, entrypoint)
            inputs.append(entrypoint)
            if outfile:
                entrypoint = f"{outfile}={entrypoint}"
            entrypoints.append(entrypoint)

        if self.state.esbuild_script:
            cmd = self.make_esbuild_script_command()
            cmd.extend(self.state.esbuild_args)
        else:
            args = list(entrypoints)
            args.extend(
                [
                    "--bundle",
                    "--format=esm",
                    "--asset-names=[dir]/[name]-[hash]",
                    "--chunk-names=[dir]/[name]-[hash]",
                    "--entry-names=[dir]/[name]-[hash]",
                    f"--outbase={self.state.assets_folder}",
                    f"--outdir={self.state.output_folder}",
                ]
            )
            args.extend([f"--alias:{o}={n}" for o, n in self.state.esbuild_aliases.items()])
            args.extend([f"--external:{e}" for e in self.state.esbuild_external])
            if self.state.esbuild_splitting:
                args.append("--splitting")
            if self.state.esbuild_target:
                args.append(f"--target={','.join(self.state.esbuild_target)}")
            if metafile:
                args.append(f"--metafile={metafile}")
            if dev:
                args.append("--sourcemap")
            else:
                args.append("--minify")
            if watch:
                args.append("--watch")
            args.extend(self.state.esbuild_args)
            cmd = self.make_esbuild_command(args)

        env = {
            "NODE_PATH": self.state.node_modules_path,
            "ESBUILD_DEV": "1" if dev else "0",
            "ESBUILD_WATCH": "1" if watch else "0",
            "ESBUILD_INPUTS": ";".join(inputs),
            "ESBUILD_ENTRYPOINTS": ";".join(entrypoints),
            "ESBUILD_OUTBASE": self.state.assets_folder,
            "ESBUILD_OUTDIR": self.state.output_folder,
            "ESBUILD_METAFILE": metafile or "",
            "ESBUILD_SPLITTING": "1" if self.state.esbuild_splitting else "0",
            "ESBUILD_TARGET": ",".join(self.state.esbuild_target or []),
            "ESBUILD_ALIASES": ";".join(
                [f"{k}={v}" for k, v in self.state.esbuild_aliases.items()]
            ),
            "ESBUILD_EXTERNAL": ";".join(self.state.esbuild_external),
        }

        return cmd, env

    def make_esbuild_script_command(self, script_filename=None):
        if not script_filename:
            script_filename = self.state.esbuild_script
        if not isinstance(script_filename, list):
            return ["node", script_filename]
        return script_filename

    def make_esbuild_command(self, args):
        return (
            self.state.esbuild_bin + args
            if isinstance(self.state.esbuild_bin, list)
            else [self.state.esbuild_bin, *args]
        )

    def convert_esbuild_metafile(self, filename=None):
        if not filename:
            filename = self.state.esbuild_metafile
        inputrel = os.path.relpath(self.state.assets_folder) + "/"
        outputrel = os.path.relpath(self.state.output_folder)

        with open(filename) as f:
            meta = json.load(f)

        inputs = []
        for input, info in meta["inputs"].items():
            inputs.append(
                input[len(inputrel) :] if input.startswith(inputrel) else os.path.abspath(input)
            )

        mapping = {}
        for output, info in meta["outputs"].items():
            if "entryPoint" not in info:
                continue
            o = mapping.setdefault(
                info["entryPoint"][len(inputrel) :]
                if info["entryPoint"].startswith(inputrel)
                else os.path.abspath(info["entryPoint"]),
                [],
            )
            url = self.state.output_url + output[len(outputrel) :]
            if url.endswith(".js"):
                url = [url, {"modifier": "import"}]
            o.append(url)
            if "cssBundle" in info:
                o.append(self.state.output_url + info["cssBundle"][len(outputrel) :])
            for import_info in info["imports"]:
                if import_info["kind"] == "import-statement":
                    o.append(
                        [
                            self.state.output_url + import_info["path"][len(outputrel) :],
                            {"modifier": "modulepreload"},
                        ]
                    )

        return inputs, mapping

    def get_tailwind_command(self, watch=False, dev=False):
        input = os.path.join(self.state.assets_folder, self.state.tailwind)
        output = os.path.join(self.state.output_folder, self.state.tailwind)
        args = ["-i", input, "-o", output]
        if not dev:
            args.append("--minify")
        if watch:
            args.append("--watch")
        args.extend(self.state.tailwind_args)
        cmd = (
            self.state.tailwind_bin + args
            if isinstance(self.state.tailwind_bin, list)
            else [self.state.tailwind_bin, *args]
        )

        content = [
            os.path.relpath(os.path.join(self.app.root_path, self.app.template_folder))
            + "/**/*.html",
            os.path.relpath(self.app.static_folder) + "/**/*.js",
        ]
        content.extend(self.state.tailwind_suggested_content)
        env = {"TAILWIND_CONTENT": ";".join(content), "TAILWIND_INPUT": input, "TAILWIND_OUTPUT": output}

        return cmd, env

    def check_tailwind_config(self):
        if not os.path.exists("tailwind.config.js"):
            shutil.copyfile(
                os.path.join(os.path.dirname(__file__), "tailwind.config.js"), "tailwind.config.js"
            )
        if not os.path.exists(os.path.join(self.state.assets_folder, self.state.tailwind)):
            with open(os.path.join(self.state.assets_folder, self.state.tailwind), "w") as f:
                f.write("@tailwind base;\n@tailwind components;\n@tailwind utilities;")

    def build_node_dependencies(self):
        for pkg in self.state.expose_node_packages:
            self.build_node_package(pkg)
        if self.state.copy_files_from_node_modules:
            self.copy_files_from_node_modules(self.state.copy_files_from_node_modules)

    def map_exposed_node_packages(self):
        for name in self.state.expose_node_packages:
            if ":" in name:
                name, _ = name.split(":", 1)
            self.map_import(name, f"{self.state.output_url}/vendor/{name}.js")

    def build_node_package(self, name):
        if ":" in name:
            name, input = name.split(":", 1)
        else:
            input = f"export * from '{name}'"
        outfile = os.path.join(self.state.output_folder, "vendor", f"{name}.js")
        if not os.path.exists(outfile):
            os.makedirs(os.path.dirname(outfile), exist_ok=True)
            subprocess.run(
                self.make_esbuild_command(
                    [
                        "--bundle",
                        "--minify",
                        "--format=esm",
                        f"--sourcefile={name}.js",
                        f"--outfile={outfile}",
                    ]
                ),
                input=input.encode("utf-8"),
            )

    def copy_files_from_node_modules(self, files):
        copy_files(files, self.state.node_modules_path, self.app.static_folder, self.app.logger)


def is_abs_url(path):
    return re.match("([a-z]+:)?//", path)
