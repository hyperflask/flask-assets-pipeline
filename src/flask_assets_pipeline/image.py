from flask import current_app
from markupsafe import Markup
import os

try:
    from PIL import Image
except ImportError:
    pass


def image_attrs(filename, _external=False, _scheme=None):
    if current_app.debug or current_app.testing:
        ensure_image_meta(filename)
    state = current_app.extensions["assets"]
    url, meta = state.instance.url(filename, with_meta=True, external=_external, scheme=_scheme)
    attrs = {"src": url}
    if "width" in meta:
        attrs["width"] = meta["width"]
    if "height" in meta:
        attrs["height"] = meta["height"]
    if "sizes" in meta: 
        attrs["srcset"] = ", ".join(f"{state.instance.url(u, external=_external, scheme=_scheme)} {s}w"
                                    for s, u in sorted(meta["sizes"].items()))
    if "placeholder" in meta:
        attrs["style"] = f"background: url('{meta['placeholder']}') center center / cover no-repeat;"
    return attrs


def image_attrs_html(filename, _external=False, _scheme=None):
    attrs = image_attrs(filename, _external, _scheme)
    return Markup(" ".join(f"{k}=\"{v}\"" for k, v in attrs.items()))


def ensure_image_meta(filename, force=False, write_mapping=True):
    state = current_app.extensions["assets"]
    if not force and filename in state.mapping:
        return
    
    meta = {}
    with Image.open(os.path.join(state.assets_folder, filename)) as img:
        url = state.instance.image_processor.process(img, filename, meta)

    state.mapping[filename] = [[url or filename, meta]]
    if write_mapping:
        state.instance.write_mapping_file(state.mapping)
