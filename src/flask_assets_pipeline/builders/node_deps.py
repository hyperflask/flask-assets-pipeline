from .base import BuilderBase
from .esbuild import EsbuildBuilder
import subprocess
import os
import shutil


class NodeDependenciesBuilder(BuilderBase):
    def build(self, mapping, ignore_assets):
        for pkg in self.state.expose_node_packages:
            self.build_node_package(pkg)
        if self.state.copy_files_from_node_modules:
            self.copy_files_from_node_modules(self.state.copy_files_from_node_modules)

    def build_node_package(self, name):
        if ":" in name:
            name, input = name.split(":", 1)
        else:
            input = f"export * from '{name}'"
        outfile = os.path.join(self.state.bundle_output_folder, "vendor", f"{name}.js")
        if not os.path.exists(outfile):
            os.makedirs(os.path.dirname(outfile), exist_ok=True)
            subprocess.run(
                EsbuildBuilder(self.ext).make_esbuild_command(
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
        copy_files(
            files,
            self.state.node_modules_path,
            self.app.static_folder,
            self.app.logger,
        )


def copy_files(files, source_folder=None, output_folder=None, logger=None):
    for src, dest in files.items():
        if source_folder:
            src = os.path.join(source_folder, src)
            if not os.path.exists(src):
                if logger:
                    logger.warning(f"Cannot copy file: {src}")
                continue
        if output_folder:
            target = os.path.join(output_folder, dest)
        if os.path.isdir(src) and os.path.exists(target):
            if dest.endswith("/"):
                target = os.path.join(target, os.path.basename(src))
            else:
                if logger:
                    logger.debug(f"Removing target of file copy: {target}")
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.unlink(target)
        if logger:
            logger.debug(f"Copying files from '{src}' to '{target}'")
        if os.path.isdir(src):
            shutil.copytree(src, target)
        else:
            if not os.path.exists(os.path.dirname(target)):
                os.makedirs(os.path.dirname(target))
            shutil.copyfile(src, target)