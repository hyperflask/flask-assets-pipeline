from .base import BuilderBase
import subprocess
import os
import re


class TailwindBuilder(BuilderBase):
    prefix = "[tailwind]"
    matchline = "Done in"

    def start_dev_worker(self, exit_event, build_only=False, livereloader=None):
        self.check_tailwind_setup()

        if livereloader and (self.state.tailwind_expand_env_vars or self.state.tailwind_sources):
            livereloader.observe(
                os.path.join(self.state.assets_folder, self.state.tailwind),
                callback=lambda e, b: self.expand_tailwind_file(),
            )

        return super().start_dev_worker(exit_event, build_only, livereloader)

    def get_dev_worker_command(self, build_only):
        return self.get_command(watch=not build_only, dev=True), {}

    def dev_worker_callback(self, build_only, livereloader):
        if livereloader:
            livereloader.ping()

    def cleanup_after_dev_worker(self):
        if self.state.tailwind_expand_env_vars:
            filename = os.path.join(self.state.assets_folder, f"{self.state.tailwind}.expanded.css")
            if os.path.exists(filename):
                os.remove(filename)

    def build(self, mapping, ignore_assets):
        self.check_tailwind_setup()
        cmd = self.get_command()
        subprocess.run(cmd)
        ignore_assets.extend([self.state.tailwind, f"{self.state.tailwind}.expanded.css"])

    def get_command(self, watch=False, dev=False):
        input = self.expand_tailwind_file()
        output = os.path.join(self.state.bundle_output_folder, self.state.tailwind)

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
        return cmd

    def expand_tailwind_file(self):
        input = os.path.join(self.state.assets_folder, self.state.tailwind)
        if not self.state.tailwind_expand_env_vars and not self.state.tailwind_sources:
            return input
        expanded = input + ".expanded.css"
        with open(input) as fi, open(expanded, "w") as fo:
            source = fi.read()
            if self.state.tailwind_expand_env_vars:
                source = os.path.expandvars(source)
            if self.state.tailwind_sources:
                source = self.expand_tailwind_sources(source)
            fo.write(source)
        return expanded

    def expand_tailwind_sources(self, source):
        lines = source.split("\n")
        insert_at = -1
        # insert after the tailwind import
        for i, line in enumerate(lines):
            if re.match(r"^@import\s+\"tailwindcss\"", line):
                insert_at = i + 1
                break
        for src in self.state.tailwind_sources:
            lines.insert(insert_at, f'@source "{src}";')
            insert_at += 1
        return "\n".join(lines)

    def check_tailwind_setup(self):
        filename = os.path.join(self.state.assets_folder, self.state.tailwind)
        if not os.path.exists(filename):
            with open(filename, "w") as f:
                f.write('@import "tailwindcss";\n')
