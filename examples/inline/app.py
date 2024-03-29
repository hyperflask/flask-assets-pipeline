from flask import Flask, render_template
from flask_assets_pipeline import AssetsPipeline


app = Flask(__name__)
assets = AssetsPipeline(app, inline=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/page")
def page():
    return render_template("page.html")
