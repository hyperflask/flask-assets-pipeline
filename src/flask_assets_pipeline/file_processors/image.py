from flask import current_app
import os
from io import BytesIO
import base64

try:
    from PIL import Image, ImageFilter
except ImportError:
    pass


DEFAULT_IMAGE_SIZES = [600, 1200, 2400, 4800]


class BaseImageProcessor:
    def __call__(self, destdir, filename, meta):
        with Image.open(os.path.join(destdir, filename)) as img:
            return self.process(img, filename, meta)

    def process(self, img, filename, meta):
        raise NotImplementedError()
    
    def save(self, img, filename, **kwargs):
        fullname = os.path.join(current_app.extensions['assets'].images_output_folder, filename)
        os.makedirs(os.path.dirname(fullname), exist_ok=True)
        img.save(fullname, **kwargs)
        return f"{current_app.extensions['assets'].images_output_url}/{filename}"


class ImageMeta(BaseImageProcessor):
    def process(self, img, filename, meta):
        meta["width"] = img.width
        meta["height"] = img.height


class ImageConverter(BaseImageProcessor):
    def __init__(self, target_ext, **save_kwargs):
        self.target_ext = f".{target_ext}" if target_ext else None
        self.save_kwargs = save_kwargs

    def process(self, img, filename, meta):
        filename = _rewrite_filename(filename, self.target_ext)
        return self.save(img, filename, **self.save_kwargs)
    

class ImageOptimizer(ImageConverter):
    def __init__(self, target_ext=None, **save_kwargs):
        save_kwargs['optimize'] = True
        super().__init__(target_ext, **save_kwargs)


class ImageResizer(BaseImageProcessor):
    def __init__(self, sizes=DEFAULT_IMAGE_SIZES, target_ext=None):
        self.sizes = sizes
        self.target_ext = f".{target_ext}" if target_ext else None

    def process(self, img, filename, meta):
        sizes = [w for w in self.sizes if w < img.width]
        for size in sizes:
            sizename = _rewrite_filename(filename, self.target_ext, f"-{size}")
            resized = img.copy()
            resized.thumbnail((size, img.height))
            meta.setdefault('sizes', {})[size] = self.save(resized, sizename, optimize=True)


class ImagePlaceholder(BaseImageProcessor):
    def process(self, img, filename, meta):
        img = img.copy()
        img.thumbnail((16, 16))
        img.filter(ImageFilter.BLUR)
        buffer = BytesIO()
        img.save(buffer, format="webp", optimize=True)
        b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        meta["placeholder"] = f"data:image/webp;base64,{b64}"


class ImageProcessorChain(BaseImageProcessor):
    def __init__(self, processors):
        self.processors = processors

    def process(self, img, filename, meta):
        url = filename
        for processor in self.processors:
            _url = processor.process(img, filename, meta)
            if _url:
                url = _url
        return url


def _rewrite_filename(filename, target_ext, suffix=''):
    base, ext = os.path.splitext(filename)
    return f"{base}{suffix}{target_ext or ext}"
