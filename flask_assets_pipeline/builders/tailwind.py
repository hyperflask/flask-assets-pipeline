from ..builder import BuilderBase
import subprocess
import os
import shutil


class TailwindBuilder(BuilderBase):
    prefix = "[tailwind]"
    matchline = "Done in"

    def start_dev_worker(self, exit_event, build_only=False, livereloader=None):
        self.check_tailwind_config()
        return super().start_dev_worker(exit_event, build_only, livereloader)

    def get_dev_worker_command(self, build_only):
        return self.get_command(watch=not build_only, dev=True)
    
    def dev_worker_callback(self, build_only, livereloader):
        if livereloader:
            livereloader.ping()

    def build(self, mapping, ignore_assets):
        self.check_tailwind_config()
        cmd, env = self.get_command()
        subprocess.run(cmd, env=dict(os.environ, **env))
        ignore_assets.append(self.assets.state.tailwind)

    def get_command(self, watch=False, dev=False):
        state = self.assets.state
        input = os.path.join(state.assets_folder, state.tailwind)
        output = os.path.join(state.output_folder, state.tailwind)
        args = ["-i", input, "-o", output]
        if not dev:
            args.append("--minify")
        if watch:
            args.append("--watch")
        args.extend(state.tailwind_args)
        cmd = (
            state.tailwind_bin + args
            if isinstance(state.tailwind_bin, list)
            else [state.tailwind_bin, *args]
        )

        content = [
            os.path.relpath(os.path.join(self.assets.app.root_path, self.assets.app.template_folder))
            + "/**/*.html",
            os.path.relpath(self.assets.app.static_folder) + "/**/*.js",
        ]
        content.extend(state.tailwind_suggested_content)
        env = {"TAILWIND_CONTENT": ";".join(content), "TAILWIND_INPUT": input, "TAILWIND_OUTPUT": output}

        return cmd, env

    def check_tailwind_config(self):
        state = self.assets.state
        if not os.path.exists("tailwind.config.js"):
            shutil.copyfile(
                os.path.join(os.path.dirname(__file__), "tailwind.config.js"), "tailwind.config.js"
            )
        if not os.path.exists(os.path.join(state.assets_folder, state.tailwind)):
            with open(os.path.join(state.assets_folder, state.tailwind), "w") as f:
                f.write("@tailwind base;\n@tailwind components;\n@tailwind utilities;")