from flask import current_app
from markupsafe import Markup
import os

try:
    from PIL import Image
except ImportError:
    pass


def image_attrs(filename, default_size=None, _external=False, _scheme=None):
    if current_app.debug or current_app.testing:
        process_image(filename)
    state = current_app.extensions["assets"]
    if default_size is None:
        default_size = state.images_default_size
    url, meta = state.instance.url(filename, with_meta=True, external=_external, scheme=_scheme)
    attrs = {"src": url}
    if "width" in meta:
        attrs["width"] = meta["width"]
    if "height" in meta:
        attrs["height"] = meta["height"]
    if "sizes" in meta:
        srcset = {int(s): state.instance.url(u, external=_external, scheme=_scheme) for s, u in meta["sizes"].items()}
        if "width" in meta:
            srcset[meta["width"]] = url
        attrs["srcset"] = ", ".join(f"{u} {s}w" for s, u in sorted(srcset.items()))
        if default_size and default_size in srcset:
            attrs["src"] = srcset[default_size]
    if "placeholder" in meta:
        attrs["style"] = f"background: url('{meta['placeholder']}') center center / cover no-repeat;"
    return attrs


def image_attrs_html(filename, _external=False, _scheme=None):
    attrs = image_attrs(filename, _external, _scheme)
    return Markup(" ".join(f"{k}=\"{v}\"" for k, v in attrs.items()))


def process_image(filename, force=False, write_mapping=True):
    state = current_app.extensions["assets"]
    if not force and filename in state.mapping:
        return
    
    meta = {}
    with Image.open(os.path.join(state.assets_folder, filename)) as img:
        url = state.instance.image_processor.process(img, filename, meta)

    state.mapping[filename] = [[url or filename, meta]]
    if write_mapping:
        state.instance.write_mapping_file(state.mapping)
