from flask import Flask, render_template
from flask_assets_pipeline import AssetsPipeline


app = Flask(__name__)
assets = AssetsPipeline(
    app, bundles=["base.js", "page.js"], include=["base.js"], assets_folder="assets"
)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/page")
def page():
    assets.include("page.js")
    return render_template("page.html")
