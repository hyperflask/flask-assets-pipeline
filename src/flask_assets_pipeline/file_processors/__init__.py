import glob
import re
import mimetypes
import importlib


class ProcessorDispatcher:
    def __init__(self, processors=None, logger=None):
        self.logger = logger
        self.processors = []
        if processors:
            self.add_many(processors)

    def add(self, pattern, processor):
        if isinstance(processor, str):
            mod, cls = processor.split(":", 1)
            processor = getattr(importlib.import_module(mod), cls)
        if isinstance(processor, type):
            processor = processor()
        self.processors.append((compile_processor_pattern(pattern), processor))

    def add_many(self, processors, pattern=None):
        if pattern:
            for processor in processors:
                self.add(pattern, processor)
        else:
            for pattern, processor in (processors.items() if isinstance(processors, dict) else processors):
                self.add(pattern, processor)

    def match(self, name):
        for matcher, processor in self.processors:
            if matcher(name):
                yield processor

    def __call__(self, destdir, filename, meta):
        url = filename
        for processor in self.match(filename):
            try:
                _url = processor(destdir, filename, meta)
                if _url:
                    url = _url
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error processing asset {filename} with {processor}: {e}")
        return url


def compile_processor_pattern(pattern):
    if isinstance(pattern, (list, tuple)):
        patterns = [compile_processor_pattern(p) for p in pattern]
        def matcher(filename):
            return any(p.match(filename) for p in patterns)
        return matcher

    if pattern.startswith("mime:"):
        mime = pattern[5:]
        def matcher(filename):
            mimetype, _ = mimetypes.guess_type(filename)
            return mimetype == mime if "/" in mime else (mimetype and mimetype.startswith(f"{mime}/"))
        return matcher
    
    if pattern.startswith("re:"):
        r = re.compile(pattern[3:])
        def matcher(filename):
            return r.match(filename)
        return matcher
    
    r = re.compile(glob.translate(pattern, recursive=True))
    def matcher(filename):
        return r.match(filename)
    return matcher