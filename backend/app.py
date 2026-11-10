
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    request,
    send_from_directory,
    render_template
)
from werkzeug.utils import secure_filename

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_FOLDER = BASE_DIR / "backend" / "uploads"
DATABASE_FOLDER = BASE_DIR / "database"
DATABASE_PATH = DATABASE_FOLDER / "syncbridge.db"

# Create required folders
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
DATABASE_FOLDER.mkdir(parents=True, exist_ok=True)

# Flask configuration
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "frontend"),
    static_folder=str(BASE_DIR / "frontend"),
    static_url_path=""
)

app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

# Initialize database
def init_database():
    connection = sqlite3.connect(DATABASE_PATH)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            stored_name TEXT NOT NULL UNIQUE,
            file_size INTEGER NOT NULL,
            transfer_type TEXT NOT NULL,
            transferred_at TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()


# Save transfer information
def save_transfer(filename, stored_name, file_size, transfer_type):
    connection = sqlite3.connect(DATABASE_PATH)

    connection.execute("""
        INSERT INTO transfers
        (filename, stored_name, file_size, transfer_type, transferred_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        filename,
        stored_name,
        file_size,
        transfer_type,
        datetime.now().isoformat(timespec="seconds")
    ))

    connection.commit()
    connection.close()


# Main dashboard
@app.route("/")
def home():
    return render_template("index.html")


# Server health check
@app.route("/api/status")
def status():
    return jsonify({
        "success": True,
        "message": "SyncBridge server is running!",
        "server": "Python Flask",
        "timestamp": datetime.now().isoformat()
    })


# Upload a file from a connected device
@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({
            "success": False,
            "message": "No file was selected."
        }), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({
            "success": False,
            "message": "Please select a file."
        }), 400

    original_name = secure_filename(file.filename)

    if not original_name:
        return jsonify({
            "success": False,
            "message": "Invalid filename."
        }), 400

    stored_name = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{original_name}"
    file_path = UPLOAD_FOLDER / stored_name

    file.save(file_path)

    save_transfer(
        original_name,
        stored_name,
        file_path.stat().st_size,
        "Incoming"
    )

    return jsonify({
        "success": True,
        "message": "File received successfully!",
        "filename": original_name
    })


# List uploaded files
@app.route("/api/files")
def list_files():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    records = connection.execute("""
        SELECT * FROM transfers
        ORDER BY id DESC
    """).fetchall()

    connection.close()

    return jsonify([
        {
            "id": record["id"],
            "filename": record["filename"],
            "file_size": record["file_size"],
            "transfer_type": record["transfer_type"],
            "transferred_at": record["transferred_at"]
        }
        for record in records
    ])


# Download a file
@app.route("/api/download/<int:file_id>")
def download_file(file_id):
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    record = connection.execute(
        "SELECT * FROM transfers WHERE id = ?",
        (file_id,)
    ).fetchone()

    connection.close()

    if record is None:
        return jsonify({
            "success": False,
            "message": "File not found."
        }), 404

    return send_from_directory(
        str(UPLOAD_FOLDER),
        record["stored_name"],
        as_attachment=True,
        download_name=record["filename"]
    )


# Handle oversized uploads
@app.errorhandler(413)
def file_too_large(error):
    return jsonify({
        "success": False,
        "message": "File exceeds the 50 MB limit."
    }), 413


if __name__ == "__main__":
    init_database()

    print("\n====================================")
    print("       SYNCBRIDGE SERVER")
    print("====================================")
    print("Server starting...")
    print("Access locally at http://127.0.0.1:5000")
    print("Press CTRL+C to stop the server.")
    print("====================================\n")

    app.run(host="0.0.0.0", port=5000, debug=False)
