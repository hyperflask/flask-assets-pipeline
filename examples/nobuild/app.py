from flask import Flask, render_template
from flask_assets_pipeline import AssetsPipeline


app = Flask(__name__)
assets = AssetsPipeline(app, include=["app.js", "main.css"])


@app.route("/")
def index():
    return render_template("index.html")
