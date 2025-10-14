import subprocess


class ExternalToolProcessor:
    def __init__(self, cmdline, silent_errors=False):
        self.cmdline = cmdline
        self.silent_errors = silent_errors

    def __call__(self, destdir, filename, meta):
        cmd = (
            self.cmdline
            if isinstance(self.cmdline, list)
            else [self.cmdline]
        )
        subprocess.run(cmd + [filename], check=not self.silent_errors)