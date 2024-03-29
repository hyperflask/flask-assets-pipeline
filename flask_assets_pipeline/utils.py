import os
import shutil
import hashlib


def copy_assets(src, dest, stamp=True, ignore_files=None, logger=None):
    files = {}
    for root, _, filenames in os.walk(src):
        for filename in filenames:
            srcfile = os.path.join(root, filename)
            relpath = os.path.relpath(srcfile, src)
            if ignore_files and relpath in ignore_files:
                continue
            destfile = relpath
            if stamp:
                hash = hash_file(srcfile)[:10]
                base, ext = os.path.splitext(destfile)
                destfile = f"{base}-{hash}{ext}"
            files[relpath] = destfile

    copy_files(files, source_folder=src, output_folder=dest, logger=logger)
    return files


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


def hash_file(filename):
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with open(filename, "rb", buffering=0) as f:
        while n := f.readinto(mv):
            h.update(mv[:n])
    return h.hexdigest()
