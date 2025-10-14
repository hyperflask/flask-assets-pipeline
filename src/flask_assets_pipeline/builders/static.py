from .base import BuilderBase
import os
import shutil
import hashlib
import os


class StaticAssetsBuilder(BuilderBase):
    def __init__(self, src, dest=None, baseurl=None, stamp=None, processor=None):
        self.src = src
        self.dest = dest or src
        self.baseurl = baseurl
        self.stamp = stamp
        self.processor = processor

    def init(self, ext):
        super().init(ext)
        if self.stamp is None:
            self.stamp = ext.state.stamp_assets
        if self.processor is None:
            self.processor = ext.static_assets_file_processor

    def start_dev_worker(self, exit_event, build_only=False, livereloader=None):
        pass

    def build(self, mapping, ignore_assets):
        mapping.update(self.copy_all(ignore_files=ignore_assets))

    def copy_all(self, ignore_files=None):
        ignore_files = ignore_files or []
        for files in self.state.bundles.values():
            ignore_files.extend(files)
        if self.state.tailwind:
            ignore_files.append(self.state.tailwind)

        mapping = {}
        for root, _, filenames in os.walk(self.src):
            for filename in filenames:
                srcfile = os.path.join(root, filename)
                relname = os.path.relpath(srcfile, self.src)
                if ignore_files and relname in ignore_files:
                    continue
                mapping[relname] = [self.copy_file(relname)]

        return mapping
    
    def copy_file(self, relname):
        srcfile = os.path.join(self.src, relname)
        destrel = stamp_filename(srcfile, relname) if self.stamp else relname
        destfile = os.path.join(self.dest, destrel)
        if destfile != srcfile:
            if destrel != relname:
                self.app.logger.info(f"Copying asset {relname} as {destrel}")
            else:
                self.app.logger.info(f"Copying asset {relname}")
            os.makedirs(os.path.dirname(destfile), exist_ok=True)
            shutil.copyfile(srcfile, destfile)

        meta = {}
        if destfile.endswith(".js"):
            meta["map_as"] = relname

        if self.processor:
            _url = self.processor(self.dest, destrel, meta)

        url = f"{self.baseurl}/{destrel}" if self.baseurl else destrel
        if _url:
            meta["original"] = url
            url = _url
        return [url, meta]


def stamp_filename(filename, alias=None):
    hash = hash_file(filename)[:10]
    base, ext = os.path.splitext(alias or filename)
    return f"{base}-{hash}{ext}"


def hash_file(filename):
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with open(filename, "rb", buffering=0) as f:
        while n := f.readinto(mv):
            h.update(mv[:n])
    return h.hexdigest()
