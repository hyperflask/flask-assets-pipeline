from ..builder import BuilderBase
import tempfile
import subprocess
import os
import json


class EsbuildBuilder(BuilderBase):
    matchline = "\[watch\] build finished"
    merge_metafile = False

    def init(self, assets):
        super().init(assets)
        self.metafile = tempfile.NamedTemporaryFile(prefix="assets", delete=False)

    @property
    def prefix(self):
        return f"[{self.assets.state.esbuild_script}]" if self.assets.state.esbuild_script else "[esbuild]"

    def start_dev_worker(self, exit_event, build_only=False, livereloader=None):
        process = super().start_dev_worker(exit_event, build_only, livereloader)
        if process and build_only:
            self.write_mapping_from_metafile(self.metafile.name, merge=self.merge_metafile)
        return process

    def get_dev_worker_command(self, build_only):
        if not self.assets.state.bundles:
            return None, None
        return self.get_command(
                    watch=not build_only, dev=True, metafile=self.metafile.name
                )

    def dev_worker_callback(self, build_only, livereloader):
        with self.assets.app.app_context():
            if self.write_mapping_from_metafile(self.metafile.name) and livereloader:
                livereloader.ping()

    def cleanup_after_dev_worker(self):
        os.unlink(self.metafile.name)

    def build(self, mapping, ignore_assets):
        if not self.assets.state.bundles:
            return
        cmd, env = self.get_command(metafile=self.metafile.name)
        subprocess.run(cmd, env=dict(os.environ, **env))
        inputs, _mapping = self.convert_metafile(self.metafile.name)
        mapping.update(_mapping)
        ignore_assets.extend(inputs)
        os.unlink(self.metafile.name)

    def get_command(self, watch=False, dev=False, metafile=None):
        state = self.assets.state
        inputs = []
        entrypoints = []
        for entrypoint in self.assets.bundle_files(entrypoints_only=True):
            path = entrypoint.resolve_path(state.assets_folder)
            inputs.append(path)
            if entrypoint.outfile:
                path = f"{entrypoint.outfile}={path}"
            entrypoints.append(path)

        if state.esbuild_script:
            cmd = self.make_script_command()
            cmd.extend(state.esbuild_args)
        else:
            args = list(entrypoints)
            args.extend(
                [
                    "--bundle",
                    "--format=esm",
                    "--asset-names=[dir]/[name]-[hash]",
                    "--chunk-names=[dir]/[name]-[hash]",
                    "--entry-names=[dir]/[name]-[hash]",
                    f"--outbase={state.assets_folder}",
                    f"--outdir={state.output_folder}",
                ]
            )
            args.extend([f"--alias:{o}={n}" for o, n in state.esbuild_aliases.items()])
            args.extend([f"--external:{e}" for e in state.esbuild_external])
            if state.esbuild_splitting:
                args.append("--splitting")
            if state.esbuild_target:
                args.append(f"--target={','.join(state.esbuild_target)}")
            if metafile:
                args.append(f"--metafile={metafile}")
            if dev:
                args.append("--sourcemap")
            else:
                args.append("--minify")
            if watch:
                args.append("--watch")
            args.extend(state.esbuild_args)
            cmd = self.make_esbuild_command(args)

        env = {
            "NODE_PATH": state.node_modules_path,
            "ESBUILD_DEV": "1" if dev else "0",
            "ESBUILD_WATCH": "1" if watch else "0",
            "ESBUILD_INPUTS": ";".join(inputs),
            "ESBUILD_ENTRYPOINTS": ";".join(entrypoints),
            "ESBUILD_OUTBASE": state.assets_folder,
            "ESBUILD_OUTDIR": state.output_folder,
            "ESBUILD_METAFILE": metafile or "",
            "ESBUILD_SPLITTING": "1" if state.esbuild_splitting else "0",
            "ESBUILD_TARGET": ",".join(state.esbuild_target or []),
            "ESBUILD_ALIASES": ";".join(
                [f"{k}={v}" for k, v in state.esbuild_aliases.items()]
            ),
            "ESBUILD_EXTERNAL": ";".join(state.esbuild_external),
        }

        return cmd, env

    def make_script_command(self, script_filename=None):
        if not script_filename:
            script_filename = self.assets.state.esbuild_script
        if not script_filename:
            raise Exception("No esbuild script provided")
        if not isinstance(script_filename, list):
            return ["node", script_filename]
        return script_filename

    def make_esbuild_command(self, args):
        return (
            self.assets.state.esbuild_bin + args
            if isinstance(self.assets.state.esbuild_bin, list)
            else [self.assets.state.esbuild_bin, *args]
        )

    def convert_metafile(self, filename=None):
        state = self.assets.state
        if not filename:
            filename = state.esbuild_metafile
        outputrel = os.path.relpath(state.output_folder)

        entrypoints = {}
        for entrypoint in self.assets.bundle_files(entrypoints_only=True):
            path = entrypoint.resolve_path(state.assets_folder)
            entrypoints[path] = entrypoint

        with open(filename) as f:
            meta = json.load(f)

        inputs = []
        mapping = {}
        for output, info in meta["outputs"].items():
            if "entryPoint" not in info:
                continue
            path = os.path.abspath(info["entryPoint"])
            if path not in entrypoints:
                continue
            if not entrypoints[path].is_abs:
                inputs.append(entrypoints[path].filename)
            path = entrypoints[path].path
            o = mapping.setdefault(path, [])
            url = state.output_url + output[len(outputrel) :]
            if url.endswith(".js"):
                url = [url, {"modifier": "import"}]
            o.append(url)
            if "cssBundle" in info:
                o.append(state.output_url + info["cssBundle"][len(outputrel) :])
            for import_info in info["imports"]:
                if import_info["kind"] == "import-statement":
                    o.append(
                        [
                            state.output_url + import_info["path"][len(outputrel) :],
                            {"modifier": "modulepreload"},
                        ]
                    )

        return inputs, mapping

    def write_mapping_from_metafile(self, filename, out=None, merge=False):
        try:
            inputs, mapping = self.convert_metafile(
                filename
            )
        except json.JSONDecodeError:
            return False
        self.assets.write_mapping_file(mapping, out, merge)
        return True
