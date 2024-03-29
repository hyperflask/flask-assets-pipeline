# Flask-Assets-Pipeline

Modern assets pipeline for Flask.

 - Asset bundling using [esbuild](https://esbuild.github.io/).
 - Live reloading
 - Support for [tailwind](https://tailwindcss.com/)
 - Compatible with #nobuild leveraging [import maps](https://developer.mozilla.org/en-US/docs/Web/HTML/Element/script/type/importmap)
 - Extract inline scripts and styles from templates and bundle them properly
 - CDN support

## Installation

Using pip:

    pip install flask-assets-pipeline

You will need to install esbuild:

    npm install esbuild

## Usage

### Introduction

Initialize the AssetsPipeline extension and list your JS and CSS that need bundling, located in the app's static directory:

```python
from flask import Flask
from flask_assets_pipeline import AssetsPipeline

app = Flask(__name__)
assets = AssetsPipeline(app, bundles=[
    'app.js',
    'app.css'
])
```

> [!TIP]
> You can also import css in your js files directly. Related stylesheets will be automatically included when their corresponding js is included.

In your template, use the `asset_tags` directive to render the needed tags to include your assets.

```jinja
<head>
    {% asset_tags %}
</head>
```

### Development mode

While in development, use the `flask assets dev` command to launch esbuild (and optionnaly tailwind). This will watch your files and expose a live reloading endpoint.
Source maps are automatically enabled in development mode.

### Bundles

Bundles are the files that will be used as inputs in the esbuild command.  
Filenames are relative to the assets folder unless it's an absolute path. Bundles can also contain URLs that will be ignored during the build process but that will be used in includes.

Bundles can either be a list of files or a dict of named bundles:

```python
assets = AssetsPipeline(app, bundles={
    "@default": ['base.js'],
    "@home": ['home.js', 'home.css']
}, include=["@default"])

@app.route("/")
def home():
    assets.include("@home")
    return render_template("home.html")
```

When using named bundles, its files are not concatanated together. It is simply a way to reference multiple files at once.
Files from all named bundles will be provided as input in the esbuild command.

> [!NOTE]
> Named bundles do not need to start their name with @ but it's a good convention to follow.

[Code splitting](https://esbuild.github.io/api/#splitting) is enabled by default.

The `bundle()` and `blueprint_bundle()` methods allow you to register bundle with more options.

### Manage included assets

By default, all bundled assets are included in your pages. You can change this behavior and manually select what asset to include on a given page.

```python
assets = AssetsPipeline(app, bundles=[
    'base.js',
    'home.js'
], include=["base.js"])

@app.route("/")
def home():
    assets.include("home.js")
    return render_template("home.html")
```

The `include_asset()` function is also available in templates. It does not return anything, only includes assets for `{% asset_tags %}` to take into account.

In the include list, you can also add paths for any files in the static folder and urls.

```python
assets = AssetsPipeline(app, bundles={
    'base.js',
    'home.js'
}, include=[
    "base.js",
    "https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,100;0,300;0,400;0,500;0,700;0,900;1,100;1,300;1,400;1,500;1,700;1,900&display=swap"
])
```

> [!WARNING]
> By default, included assets that are not bundles won't be included as modules (`<script type="module">`). Change that by prefixing them with "import ".
>
> ```python
> assets = AssetsPipeline(app, bundles={
>     "base.js"
> }, include=[
>     "base.js",
>     "import other.js"
> ])
> ```

### Including media assets

For assets other than scripts and stylesheets, use `asset_url(filename)` in your templates to get the url.

```jinja
<img src="{{ asset_url('cat.jpg') }}">
```

## Building for production

Use the following command to build assets for production:

    $ flask assets build

This will:

 - build your bundles using esbuild
 - build your css with tailwind if enabled
 - minify files and not produce source maps
 - generate a mapping file (default: assets.json)

Files built using esbuild and tailwind will be generated in a dist folder in the static directory.

> [!IMPORTANT]
> Make sure to ship all generated files and the mapping file to production

> [!TIP]
> It is not recommended to build in production. You should build in a separate environment (eg: CI),
> then generate a tarball (or any other deliverable, eg: docker image) that you ship to production.

## Tailwind support

Flask-Assets-Pipeline can launch tailwind in the background at the same time as esbuild and build your css file.
The output css file will be automatically included.

```python
assets = AssetsPipeline(app, bundles=[
    'base.js'
], tailwind='main.css')
```

If the tailwind config or the input file is missing, they will be automatically generated.
Make sure your tailwind config includes all the needed content paths to watch for.

Example config:

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js"
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

## Using a separate assets folder

You can use a separate assets folder than your app static folder. This folder won't be exposed in production so raw assets are safe.

When using a separate assets folder:

 - Always use `asset_url()` for your assets' urls
 - In development, the assets folder will be exposed and assets served directly from it
 - For production, you must call the build command
 - During the build, assets will be copied to the static folder with a hash in their filename (for cache busting)

```python
assets = AssetsPipeline(app, bundles=['app.js'], assets_folder='assets')
```

## Inline assets

Flask-Assets-Pipeline allows to define scripts and styles directly in your templates. Their content will be extracted and bundled using the previously mentionned process.

To enable inline assets, set the inline option to true.

```python
assets = AssetsPipeline(app, ..., inline=True)
```

Add the `bundle` attribute to your script and style tags to extract and bundle them.

Example *datatable.html* template:

```jinja
<table class="datatable">
    <!-- ... -->
</table>

<script bundle>
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".datatable").forEach(table => {
        // ...
    });
});
</script>

<style bundle>
.datatable {
    /* ... */
}
</style>
```

When this template is used as part of your request, its associated assets will be automatically included.

> [!IMPORTANT]
> No jinja directives can be used inside the bundled script and style tags

> [!NOTE]
> Extracted assets will be stored in your assets folder.  
> You can customize the name of the extracted files using a value for the bundle attribute: `<script bundle="filename.js">`

## Frontend routes

If your are building a Single Page App (SPA), you will use a frontend router. To make sure these routes exist on the backend,
you can register them:

```python
assets.add_route("login", "/login")
assets.add_route("account", "/account", decorators=[login_required]) # apply decorators
```

These routes simply return a rendered template defined using `ASSETS_ROUTE_TEMPLATE` (default is *frontend_route.html*)

## No build

If you're not planning to use any feature that require preprocessing (eg. typescript) or are using an externel build system, you can skip defining bundles.

```python
assets = AssetsPipeline(app, include=['app.js', 'app.css'])
```

> [!WARNING]
> Script mentionned in include are not included as module by default. If you wish to do so, prefix them with "import ":
>
> ```
> assets = AssetsPipeline(app, include=['import app.js', 'app.css'])
> ```

> [!WARNING]
> If you are using a separate assets folder, you will still need to build for production as assets need to
> be copied to the static folder

When using no build, it may be needed to edit the [import map](https://developer.mozilla.org/en-US/docs/Web/HTML/Element/script/type/importmap):

```python
assets = AssetsPipeline(app, ..., import_map={"mypkg": "https://..."})
assets.map_import("myotherpkg", "https://...")
```

The import map will be rendered as part of `{% asset_tags %}`.

You may want to expose some package from your node_modules directory to import them in your scripts.
Exposed packages will be bundled using esbuild and added to the import map.

```python
assets = AssetsPipeline(app, ..., expose_node_packages=["mypkg"])
assets.expose_node_package("myotherpkg")
```

You can then import them as usual in your scripts.

## Preloading and prefetching

You can include assets and urls for [preloading](https://developer.mozilla.org/en-US/docs/Web/HTML/Attributes/rel/preload) and/or [prefetching](https://developer.mozilla.org/en-US/docs/Web/HTML/Attributes/rel/prefetch).

Similarly to how "import" can be specified, use "preload" in front of your included asset. The preload content type will be determined based on the file extension. You can specify it manually using `preload as TYPE URL`.

For prefetching, use "prefetch" as the prefix.

```python
assets = AssetsPipeline(app, include=["preload dependency.js", "preload as image cat.jpg", "prefetch page.js"])
```

## Including external assets

Any URLs can be used in the include list.

It is possible to provide additionnal metadata like crossorigin and integrity hash.

```python
assets = AssetsPipeline(app, include=["http://example.com/external.js#integrity=sha384-XXXX"])
```

Any parameter in the fragment part will be transformed to attributes of the html element used to include the asset.

By default, `crossorigin="anonymous"` is automatically applied to any url used.

## Using a CDN

Set the cdn host in your configuration to use a CDN when debug mode is not enabled.

```python
assets = AssetsPipeline(app, ..., cdn_host="https://xxx.cloudfront.net")
```

You can control when the cdn is used or not using the ASSETS_CDN_ENABLED config option (it will override the default behavior).

## Configuration

| Config key | Extension argument | Description | Default |
| --- | --- | --- | --- |
| ASSETS_BUNDLES | bundles | List of assets to build | |
| ASSETS_INCLUDE | include | List of assets to include in your page | All assets in bundles |
| ASSETS_ROUTE_TEMPLATE | route_template | The template to use for frontend routes | frontend_route.html |
| ASSETS_INLINE | inline | Whether to extract assets from templates | False |
| ASSETS_IMPORT_MAP | import_map | ES Modules import map | {} |
| ASSETS_EXPOSE_NODE_PACKAGES | expose_node_packages | Node packages to expose to the frontend via the import map | [] |
| ASSETS_FOLDER | assets_folder | Search path for asset files | The app static_folder |
| ASSETS_URL_PATH | assets_url_path | Base URL for the assets endpoint when in debug mode | /static/assets |
| ASSETS_STAMP_ASSETS | stamp_assets | Whether to stamp filenames with the file's hash when copying files from the assets folder to the static folder | True |
| ASSETS_OUTPUT_FOLDER | output_folder | The output folder for bundled files relative to the static folder | dist |
| ASSETS_OUTPUT_URL | output_url | Base url for outputted file | /static/dist |
| ASSETS_MAPPING_FILE | mapping_file | Location of the mapping file to resolve assets filename to their built equivalent | assets.json |
| ASSETS_ESBUILD_ARGS | esbuild_args | Additional esbuild arguments | [] |
| ASSETS_ESBUILD_BIN | esbuild_bin | esbuild binary location | npx esbuild |
| ASSETS_ESBUILD_SPLITTING | esbuild_splitting | Use the --splitting option | True |
| ASSETS_ESBUILD_TARGET | esbuild_target | Set the target option for esbuild (use a list) | [] |
| ASSETS_LIVERELOAD_PORT | livereload_port | Port onto which to start the livereloading server | 8000 |
| ASSETS_TAILWIND | tailwind | Tailwind input css file | |
| ASSETS_TAILWIND_ARGS | tailwind_args | Additional tailwind arguments | [] |
| ASSETS_TAILWIND_BIN | tailwind_bin | tailwindcss binary location | npx tailwindcss |
| ASSETS_NODE_MODULES_PATH | node_modules_path | Path to the node_modules directory | node_modules |
| ASSETS_COPY_FILES_FROM_NODE_MODULES | copy_files_from_node_modules | Mapping of src/dest files to copy from node modules | {} |

## Commands

| Command | Description |
| --- | --- |
| assets dev | Start the build process in development |
| assets build | Build your assets for production |
| assets extract | Extract assets from templates |
| assets init-tailwind | Create the tailwind config |