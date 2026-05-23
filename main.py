# -*- coding: utf-8 -*-
"""
Sky Group Tasks — Replit entry point
"""
import os
from datetime import datetime
from flask import Flask, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "skygroup-tasks-secret-2026")

from task_tracker import tasks_bp, start_overdue_checker, DEPARTMENTS

app.register_blueprint(tasks_bp)
start_overdue_checker()
app.jinja_env.globals["now"] = datetime.now


@app.route("/")
def index():
    return redirect(url_for("tasks.dashboard"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
