import os
import re
import secrets
import sqlite3
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import filetype
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


# ==========================================
# 1. PROJECT PATHS
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent

UPLOAD_FOLDER = BASE_DIR / "backend" / "uploads"
DATABASE_FOLDER = BASE_DIR / "database"
INSTANCE_FOLDER = BASE_DIR / "backend" / "instance"

DATABASE_PATH = DATABASE_FOLDER / "syncbridge.db"
SECRET_KEY_PATH = INSTANCE_FOLDER / "secret_key"

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
DATABASE_FOLDER.mkdir(parents=True, exist_ok=True)
INSTANCE_FOLDER.mkdir(parents=True, exist_ok=True)


# ==========================================
# 2. SECRET KEY
# ==========================================

SECRET_KEY = ""

if SECRET_KEY_PATH.exists():
    SECRET_KEY = SECRET_KEY_PATH.read_text(encoding="utf-8").strip()

if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    SECRET_KEY_PATH.write_text(SECRET_KEY, encoding="utf-8")


# ==========================================
# 3. FLASK CONFIGURATION
# ==========================================

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "frontend"),
    static_folder=str(BASE_DIR / "frontend"),
    static_url_path="",
)

app.config["SECRET_KEY"] = SECRET_KEY
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Keep False for local HTTP on your Wi-Fi.
# Change to True when the application uses HTTPS.
app.config["SESSION_COOKIE_SECURE"] = False

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["WTF_CSRF_TIME_LIMIT"] = 3600

csrf = CSRFProtect(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


# ==========================================
# 4. UPLOAD RESTRICTIONS AND VALIDATION
# ==========================================

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "pdf", "txt", "csv",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "zip",
    "mp3", "wav", "mp4", "mov",
}


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def validate_file_content(file_path, extension):
    """
    Check that uploaded file contents are consistent with the extension.
    This is basic file-type validation, not malware scanning.
    """

    # Text and CSV files do not have a reliable magic-byte signature.
    if extension in {"txt", "csv"}:
        try:
            content = file_path.read_bytes()

            if b"\x00" in content:
                return False

            content.decode("utf-8-sig")
            return True
        except (UnicodeDecodeError, OSError):
            return False

    # ZIP archives and modern Microsoft Office documents.
    if extension in {"zip", "docx", "xlsx", "pptx"}:
        try:
            if not zipfile.is_zipfile(file_path):
                return False

            with zipfile.ZipFile(file_path, "r") as archive:
                # Check that the archive can be read without corruption.
                if archive.testzip() is not None:
                    return False

                if extension == "zip":
                    return True

                required_entries = {
                    "docx": "word/document.xml",
                    "xlsx": "xl/workbook.xml",
                    "pptx": "ppt/presentation.xml",
                }

                return required_entries[extension] in set(archive.namelist())

        except (OSError, zipfile.BadZipFile, RuntimeError):
            return False

    # Older Microsoft Office documents use an OLE container signature.
    if extension in {"doc", "xls", "ppt"}:
        try:
            with open(file_path, "rb") as uploaded:
                signature = uploaded.read(8)

            return signature == bytes.fromhex("D0 CF 11 E0 A1 B1 1A E1")
        except OSError:
            return False

    # Detect supported image, PDF, audio and video formats by file signature.
    try:
        with open(file_path, "rb") as uploaded:
            header = uploaded.read(261)
    except OSError:
        return False

    detected = filetype.guess(header)

    if detected is None:
        return False

    expected_extensions = {
        "png": {"png"},
        "jpg": {"jpg", "jpeg"},
        "jpeg": {"jpg", "jpeg"},
        "gif": {"gif"},
        "webp": {"webp"},
        "pdf": {"pdf"},
        "mp3": {"mp3"},
        "wav": {"wav"},
        "mp4": {"mp4"},
        # Some MOV files are identified by filetype as MP4/ISO base media.
        "mov": {"mov", "mp4"},
    }

    return detected.extension.lower() in expected_extensions.get(extension, set())


# ==========================================
# 5. DATABASE CONNECTION
# ==========================================

def get_db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# ==========================================
# 6. DATABASE INITIALIZATION AND MIGRATION
# ==========================================

def init_database():
    with closing(get_db()) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                stored_name TEXT NOT NULL UNIQUE,
                file_size INTEGER NOT NULL,
                transfer_type TEXT NOT NULL,
                transferred_at TEXT NOT NULL,
                user_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Add user_id to an existing transfers table if it is an older version.
        columns = connection.execute(
            "PRAGMA table_info(transfers)"
        ).fetchall()

        column_names = [column["name"] for column in columns]

        if "user_id" not in column_names:
            connection.execute("""
                ALTER TABLE transfers
                ADD COLUMN user_id INTEGER REFERENCES users(id)
            """)

        connection.commit()


# ==========================================
# 7. LOGIN PROTECTION
# ==========================================

def login_required(route_function):
    @wraps(route_function)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "message": "Please log in to continue.",
                }), 401

            return redirect(url_for("login"))

        return route_function(*args, **kwargs)

    return decorated_function


# ==========================================
# 8. HOME PAGE
# ==========================================

@app.route("/")
@login_required
def home():
    return render_template("index.html")


# ==========================================
# 9. REGISTRATION
# ==========================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash(
                "Username must be 3–30 characters and contain only letters, numbers or underscores.",
                "error",
            )
            return render_template("register.html")

        if len(password) < 10:
            flash("Password must contain at least 10 characters.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        password_hash = generate_password_hash(password)

        try:
            with closing(get_db()) as connection:
                connection.execute("""
                    INSERT INTO users (username, password_hash, created_at)
                    VALUES (?, ?, ?)
                """, (
                    username,
                    password_hash,
                    datetime.now().isoformat(timespec="seconds"),
                ))

                user = connection.execute(
                    "SELECT id FROM users WHERE username = ?",
                    (username,),
                ).fetchone()

                # Assign legacy files with no owner to the first new account.
                # Existing files already assigned to another user are untouched.
                connection.execute("""
                    UPDATE transfers
                    SET user_id = ?
                    WHERE user_id IS NULL
                """, (user["id"],))

                connection.commit()

        except sqlite3.IntegrityError:
            flash("That username is already taken.", "error")
            return render_template("register.html")

        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# ==========================================
# 10. LOGIN
# ==========================================

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with closing(get_db()) as connection:
            user = connection.execute("""
                SELECT * FROM users
                WHERE username = ?
            """, (username,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session.permanent = True

            return redirect(url_for("home"))

        flash("Incorrect username or password.", "error")

    return render_template("login.html")


# ==========================================
# 11. LOGOUT
# ==========================================

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have logged out successfully.", "success")
    return redirect(url_for("login"))


# ==========================================
# 12. SERVER STATUS
# ==========================================

@app.route("/api/status")
def status():
    return jsonify({
        "success": True,
        "message": "SyncBridge server is running!",
        "server": "Python Flask",
        "timestamp": datetime.now().isoformat(),
    })


# ==========================================
# 13. UPLOAD FILE
# ==========================================

@app.route("/api/upload", methods=["POST"])
@login_required
def upload_file():
    if "file" not in request.files:
        return jsonify({
            "success": False,
            "message": "No file was selected.",
        }), 400

    uploaded_file = request.files["file"]

    if not uploaded_file.filename:
        return jsonify({
            "success": False,
            "message": "Please select a file.",
        }), 400

    original_name = secure_filename(uploaded_file.filename)

    if not original_name:
        return jsonify({
            "success": False,
            "message": "Invalid filename.",
        }), 400

    if not allowed_file(original_name):
        return jsonify({
            "success": False,
            "message": "This file type is not allowed.",
        }), 400

    extension = original_name.rsplit(".", 1)[1].lower()

    # Use a random storage name so uploaded filenames cannot overwrite files.
    stored_name = f"{uuid.uuid4().hex}.{extension}"
    file_path = UPLOAD_FOLDER / stored_name

    try:
        uploaded_file.save(file_path)

        # Check that the actual contents match the selected extension.
        if not validate_file_content(file_path, extension):
            file_path.unlink(missing_ok=True)
            return jsonify({
                "success": False,
                "message": "File contents do not match the selected file type.",
            }), 400

        file_size = file_path.stat().st_size

        with closing(get_db()) as connection:
            connection.execute("""
                INSERT INTO transfers
                (filename, stored_name, file_size, transfer_type,
                 transferred_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                original_name,
                stored_name,
                file_size,
                "Incoming",
                datetime.now().isoformat(timespec="seconds"),
                session["user_id"],
            ))

            connection.commit()

    except Exception:
        if file_path.exists():
            file_path.unlink(missing_ok=True)

        app.logger.exception("File upload failed.")

        return jsonify({
            "success": False,
            "message": "The file could not be saved.",
        }), 500

    return jsonify({
        "success": True,
        "message": "File received successfully!",
        "filename": original_name,
    })




# ==========================================
# 15. DELETE ONE OF THE LOGGED-IN USER'S FILES
# ==========================================

@app.route("/api/files/<int:file_id>", methods=["DELETE"])
@login_required
def delete_file(file_id):
    with closing(get_db()) as connection:
        record = connection.execute("""
            SELECT id, stored_name
            FROM transfers
            WHERE id = ? AND user_id = ?
        """, (file_id, session["user_id"])).fetchone()

        if record is None:
            return jsonify({
                "success": False,
                "message": "File not found.",
            }), 404

        file_path = UPLOAD_FOLDER / record["stored_name"]

        # Remove the physical file first. If removal fails, keep its database row.
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            app.logger.exception("Could not delete uploaded file.")
            return jsonify({
                "success": False,
                "message": "The file could not be deleted. Please try again.",
            }), 500

        connection.execute(
            "DELETE FROM transfers WHERE id = ? AND user_id = ?",
            (file_id, session["user_id"]),
        )
        connection.commit()

    return jsonify({
        "success": True,
        "message": "File deleted successfully.",
        "deleted_id": file_id,
    })


# ==========================================
# 16. CLEAR ALL FILES FOR THE LOGGED-IN USER
# ==========================================

@app.route("/api/files/clear", methods=["DELETE"])
@login_required
def clear_user_files():
    deleted_count = 0
    failed_files = []

    with closing(get_db()) as connection:
        records = connection.execute("""
            SELECT id, stored_name
            FROM transfers
            WHERE user_id = ?
        """, (session["user_id"],)).fetchall()

        for record in records:
            file_path = UPLOAD_FOLDER / record["stored_name"]

            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                app.logger.exception(
                    "Could not delete uploaded file with record ID %s.",
                    record["id"],
                )
                failed_files.append(record["id"])
                continue

            connection.execute(
                "DELETE FROM transfers WHERE id = ? AND user_id = ?",
                (record["id"], session["user_id"]),
            )
            deleted_count += 1

        connection.commit()

    if failed_files:
        return jsonify({
            "success": False,
            "message": (
                f"{deleted_count} file(s) deleted. "
                f"{len(failed_files)} file(s) could not be deleted."
            ),
            "deleted_count": deleted_count,
            "failed_count": len(failed_files),
        }), 500

    return jsonify({
        "success": True,
        "message": "Your file list has been cleared.",
        "deleted_count": deleted_count,
    })


# ==========================================
# 14. LIST ONLY THE LOGGED-IN USER'S FILES
# ==========================================

@app.route("/api/files")
@login_required
def list_files():
    with closing(get_db()) as connection:
        records = connection.execute("""
            SELECT id, filename, file_size, transfer_type, transferred_at
            FROM transfers
            WHERE user_id = ?
            ORDER BY id DESC
        """, (session["user_id"],)).fetchall()

    return jsonify([
        {
            "id": record["id"],
            "filename": record["filename"],
            "file_size": record["file_size"],
            "transfer_type": record["transfer_type"],
            "transferred_at": record["transferred_at"],
        }
        for record in records
    ])


# ==========================================
# 17. SECURE DOWNLOAD
# ==========================================

@app.route("/api/download/<int:file_id>")
@login_required
def download_file(file_id):
    with closing(get_db()) as connection:
        record = connection.execute("""
            SELECT *
            FROM transfers
            WHERE id = ? AND user_id = ?
        """, (
            file_id,
            session["user_id"],
        )).fetchone()

    # A file belonging to another user is treated as not found.
    if record is None:
        return jsonify({
            "success": False,
            "message": "File not found.",
        }), 404

    file_path = UPLOAD_FOLDER / record["stored_name"]

    if not file_path.is_file():
        return jsonify({
            "success": False,
            "message": "The stored file is missing.",
        }), 404

    return send_from_directory(
        str(UPLOAD_FOLDER),
        record["stored_name"],
        as_attachment=True,
        download_name=record["filename"],
    )


# ==========================================
# 18. ERROR HANDLERS
# ==========================================

@app.errorhandler(413)
def file_too_large(error):
    return jsonify({
        "success": False,
        "message": "File exceeds the 50 MB limit.",
    }), 413


# ==========================================
# 19. START SERVER
# ==========================================

init_database()

if __name__ == "__main__":
    print("\n====================================")
    print("       SYNCBRIDGE SERVER")
    print("====================================")
    print("Authentication enabled.")
    print("Private file access enabled.")
    print("Access locally at http://127.0.0.1:5000")
    print("Press CTRL+C to stop the server.")
    print("====================================\n")

    app.run(host="0.0.0.0", port=5000, debug=False)
