from ..builder import BuilderBase
import subprocess
import os
import tempfile


class TailwindBuilder(BuilderBase):
    prefix = "[tailwind]"
    matchline = "Done in"

    def start_dev_worker(self, exit_event, build_only=False, livereloader=None):
        self.check_tailwind_setup()
        return super().start_dev_worker(exit_event, build_only, livereloader)

    def get_dev_worker_command(self, build_only):
        return self.get_command(watch=not build_only, dev=True), {}
    
    def dev_worker_callback(self, build_only, livereloader):
        if livereloader:
            livereloader.ping()

    def build(self, mapping, ignore_assets):
        self.check_tailwind_setup()
        cmd = self.get_command()
        subprocess.run(cmd)
        ignore_assets.append(self.assets.state.tailwind)

    def get_command(self, watch=False, dev=False):
        state = self.assets.state
        input = os.path.join(state.assets_folder, state.tailwind)
        output = os.path.join(state.output_folder, state.tailwind)

        if state.tailwind_expand_env_vars:
            tmpfile = tempfile.NamedTemporaryFile(delete=False)
            with open(input) as fi, tmpfile as fo:
                fo.write(os.path.expandvars(fi.read()))
            input = tmpfile.name

        args = ["-i", input, "-o", output]
        if not dev:
            args.append("--minify")
        if watch:
            args.append("--watch")
        if state.tailwind_expand_env_vars:
            args.extend(["--cwd", os.getcwd()])
        args.extend(state.tailwind_args)
        cmd = (
            state.tailwind_bin + args
            if isinstance(state.tailwind_bin, list)
            else [state.tailwind_bin, *args]
        )
        return cmd

    def check_tailwind_setup(self):
        state = self.assets.state
        filename = os.path.join(state.assets_folder, state.tailwind)
        if not os.path.exists(filename):
            with open(filename, "w") as f:
                f.write(f"@import \"tailwindcss\";\n")