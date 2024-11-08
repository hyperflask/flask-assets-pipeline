from ..builder import BuilderBase
from ..utils import copy_files
from .esbuild import EsbuildBuilder
import subprocess
import os


class NodeDependenciesBuilder(BuilderBase):
    def build(self, mapping, ignore_assets):
        for pkg in self.assets.state.expose_node_packages:
            self.build_node_package(pkg)
        if self.assets.state.copy_files_from_node_modules:
            self.copy_files_from_node_modules(self.assets.state.copy_files_from_node_modules)

    def build_node_package(self, name):
        if ":" in name:
            name, input = name.split(":", 1)
        else:
            input = f"export * from '{name}'"
        outfile = os.path.join(self.state.output_folder, "vendor", f"{name}.js")
        if not os.path.exists(outfile):
            os.makedirs(os.path.dirname(outfile), exist_ok=True)
            subprocess.run(
                EsbuildBuilder(self.assets).make_esbuild_command(
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
        copy_files(files, self.assets.state.node_modules_path,
                   self.assets.app.static_folder, self.assets.app.logger)