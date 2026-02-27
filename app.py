from __future__ import annotations

import io
import os
import re
import smtplib
import sqlite3
import textwrap
from datetime import date
from email.message import EmailMessage
from functools import wraps
from typing import Any

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_VERCEL = bool(os.environ.get("VERCEL"))
DB_PATH = os.environ.get(
    "DATABASE_PATH",
    "/tmp/portal.db" if IS_VERCEL else os.path.join(BASE_DIR, "portal.db"),
)

ATTENDANCE_THRESHOLD = 75
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

PDF_EXTENSIONS = {".pdf"}
TIMETABLE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

ROLE_RANK = {"student": 1, "professor": 2, "admin": 3}
STOP_WORDS = {
    "about",
    "after",
    "again",
    "between",
    "because",
    "could",
    "every",
    "first",
    "from",
    "have",
    "into",
    "their",
    "there",
    "these",
    "those",
    "where",
    "which",
    "while",
    "with",
    "would",
    "subject",
    "semester",
    "important",
    "student",
    "students",
    "question",
    "questions",
    "notes",
}

NAV_MAP = {
    "dashboard": "dashboard",
    "notes_page": "notes",
    "upload_note": "notes",
    "download_note": "notes",
    "rename_note": "notes",
    "delete_note": "notes",
    "question_papers": "question_papers",
    "previous_questions": "question_papers",
    "download_previous_question": "question_papers",
    "announcements": "announcements",
    "delete_announcement": "announcements",
    "attendance": "attendance",
    "send_attendance_alert": "attendance",
    "timetables": "timetables",
    "download_timetable": "timetables",
    "faculty_directory": "faculty",
    "user_profile": "faculty",
    "user_photo": "faculty",
    "profile": "profile",
    "notifications": "notifications",
    "exam_ready": "exam_ready",
    "delete_user": "dashboard",
}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error: Any) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def table_columns(db: sqlite3.Connection, table_name: str) -> set[str]:
    rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def ensure_column(db: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    if column_name not in table_columns(db, table_name):
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def generate_university_id(role: str, db: sqlite3.Connection) -> str:
    prefix = {"student": "STU", "professor": "PRO", "admin": "ADM"}[role]
    serial = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = ?",
        (role,),
    ).fetchone()["c"] + 1

    while True:
        candidate = f"{prefix}2026{serial:03d}"
        exists = db.execute(
            "SELECT 1 FROM users WHERE university_id = ?",
            (candidate,),
        ).fetchone()
        if not exists:
            return candidate
        serial += 1


def seed_demo_users(db: sqlite3.Connection) -> None:
    demo_users = [
        {
            "name": "Campus Admin",
            "email": "admin@campus.local",
            "password": "admin123",
            "role": "admin",
            "university_id": "ADM001",
            "designation": "System Administrator",
            "subject": "",
            "free_hours": "",
            "branch": "ALL",
            "study_program": "",
            "phone": "9876543212",
            "bio": "Default admin account. Please change password after first login.",
        },
        {
            "name": "Dr. Priya Sharma",
            "email": "priya.sharma@university.edu",
            "password": "prof123",
            "role": "professor",
            "university_id": "PRO001",
            "designation": "Associate Professor",
            "subject": "DSA, Machine Learning",
            "free_hours": "Mon-Fri 10 AM - 12 PM",
            "branch": "CSE",
            "study_program": "",
            "phone": "9876543210",
            "bio": "10+ years in AI/ML research. Published 20+ papers.",
        },
        {
            "name": "Dr. Arjun Mehta",
            "email": "arjun.mehta@university.edu",
            "password": "prof123",
            "role": "professor",
            "university_id": "PRO002",
            "designation": "Professor",
            "subject": "Mathematics",
            "free_hours": "Tue-Thu 2 PM - 4 PM",
            "branch": "CSE",
            "study_program": "",
            "phone": "9876543211",
            "bio": "Applied mathematics faculty with focus on exam strategy and fundamentals.",
        },
        {
            "name": "Dr. Nisha Verma",
            "email": "nisha.verma@university.edu",
            "password": "prof123",
            "role": "professor",
            "university_id": "PRO003",
            "designation": "Associate Professor",
            "subject": "Digital Electronics, Signals & Systems",
            "free_hours": "Mon-Wed 1 PM - 3 PM",
            "branch": "ECE",
            "study_program": "",
            "phone": "9876543221",
            "bio": "Embedded systems researcher and circuit design mentor.",
        },
        {
            "name": "Dr. Farhan Khan",
            "email": "farhan.khan@university.edu",
            "password": "prof123",
            "role": "professor",
            "university_id": "PRO004",
            "designation": "Professor",
            "subject": "Power Systems, Control Systems",
            "free_hours": "Tue-Thu 11 AM - 1 PM",
            "branch": "EEE",
            "study_program": "",
            "phone": "9876543222",
            "bio": "Power engineering faculty with industry consulting background.",
        },
        {
            "name": "Dr. Raghav Bansal",
            "email": "raghav.bansal@university.edu",
            "password": "prof123",
            "role": "professor",
            "university_id": "PRO005",
            "designation": "Associate Professor",
            "subject": "Thermodynamics, Manufacturing",
            "free_hours": "Mon-Fri 2 PM - 4 PM",
            "branch": "ME",
            "study_program": "",
            "phone": "9876543223",
            "bio": "Mechanical systems specialist focused on practical problem solving.",
        },
        {
            "name": "Dr. Ananya Iyer",
            "email": "ananya.iyer@university.edu",
            "password": "prof123",
            "role": "professor",
            "university_id": "PRO006",
            "designation": "Assistant Professor",
            "subject": "Structural Analysis, Surveying",
            "free_hours": "Wed-Fri 9 AM - 11 AM",
            "branch": "CE",
            "study_program": "",
            "phone": "9876543224",
            "bio": "Civil engineering faculty active in sustainable infrastructure studies.",
        },
        {
            "name": "Dr. Sneha Kulkarni",
            "email": "sneha.kulkarni@university.edu",
            "password": "prof123",
            "role": "professor",
            "university_id": "PRO007",
            "designation": "Assistant Professor",
            "subject": "Computer Networks, Cyber Security",
            "free_hours": "Mon-Thu 3 PM - 5 PM",
            "branch": "IT",
            "study_program": "",
            "phone": "9876543225",
            "bio": "Cybersecurity educator with hands-on SOC and network defense experience.",
        },
        {
            "name": "Student STU2024001",
            "email": "student@university.edu",
            "password": "student123",
            "role": "student",
            "university_id": "STU2024001",
            "designation": "Student",
            "subject": "",
            "free_hours": "",
            "branch": "CSE",
            "study_program": "B.Tech 2nd Year",
            "phone": "9876543213",
            "bio": "Focused on semester prep and collaboration with faculty.",
        },
        {
            "name": "Ayaan Gupta",
            "email": "ayaan.gupta@university.edu",
            "password": "student123",
            "role": "student",
            "university_id": "STU2024002",
            "designation": "Student",
            "subject": "",
            "free_hours": "",
            "branch": "CSE",
            "study_program": "B.Tech 3rd Year",
            "phone": "9876543231",
            "bio": "Interested in backend systems, open source, and teaching assistance.",
        },
        {
            "name": "Meera Nair",
            "email": "meera.nair@university.edu",
            "password": "student123",
            "role": "student",
            "university_id": "STU2024003",
            "designation": "Student",
            "subject": "",
            "free_hours": "",
            "branch": "ECE",
            "study_program": "B.Tech 2nd Year",
            "phone": "9876543232",
            "bio": "Focused on embedded systems and communication labs.",
        },
        {
            "name": "Kunal Singh",
            "email": "kunal.singh@university.edu",
            "password": "student123",
            "role": "student",
            "university_id": "STU2024004",
            "designation": "Student",
            "subject": "",
            "free_hours": "",
            "branch": "EEE",
            "study_program": "B.Tech 3rd Year",
            "phone": "9876543233",
            "bio": "Works on smart-grid projects and power-system simulations.",
        },
        {
            "name": "Rohan Patil",
            "email": "rohan.patil@university.edu",
            "password": "student123",
            "role": "student",
            "university_id": "STU2024005",
            "designation": "Student",
            "subject": "",
            "free_hours": "",
            "branch": "ME",
            "study_program": "B.Tech 4th Year",
            "phone": "9876543234",
            "bio": "Design and CAD enthusiast preparing for GATE.",
        },
        {
            "name": "Sana Ali",
            "email": "sana.ali@university.edu",
            "password": "student123",
            "role": "student",
            "university_id": "STU2024006",
            "designation": "Student",
            "subject": "",
            "free_hours": "",
            "branch": "CE",
            "study_program": "B.Tech 2nd Year",
            "phone": "9876543235",
            "bio": "Interested in transportation engineering and surveying.",
        },
        {
            "name": "Neha Kapoor",
            "email": "neha.kapoor@university.edu",
            "password": "student123",
            "role": "student",
            "university_id": "STU2024007",
            "designation": "Student",
            "subject": "",
            "free_hours": "",
            "branch": "IT",
            "study_program": "B.Tech 3rd Year",
            "phone": "9876543236",
            "bio": "Security and cloud learner, open to research collaboration.",
        },
        {
            "name": "Siddharth Jain",
            "email": "siddharth.jain@university.edu",
            "password": "student123",
            "role": "student",
            "university_id": "STU2024008",
            "designation": "Student",
            "subject": "",
            "free_hours": "",
            "branch": "BCA",
            "study_program": "BCA 2nd Year",
            "phone": "9876543237",
            "bio": "Practicing web dev and DSA for placements.",
        },
    ]

    for user in demo_users:
        existing = db.execute("SELECT id FROM users WHERE email = ?", (user["email"],)).fetchone()
        if existing:
            continue

        db.execute(
            """
            INSERT INTO users (
                name, email, password_hash, role, university_id, designation,
                subject, free_hours, branch, study_program, phone, bio, open_to_collab
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["name"],
                user["email"],
                generate_password_hash(user["password"]),
                user["role"],
                user["university_id"],
                user["designation"],
                user["subject"],
                user["free_hours"],
                user["branch"],
                user["study_program"],
                user["phone"],
                user["bio"],
                1 if user["role"] == "student" else 0,
            ),
        )


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_single_page_pdf(stream_commands: str, page_width: int, page_height: int) -> bytes:
    stream_bytes = stream_commands.encode("latin-1", "replace")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ).encode("latin-1"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream_bytes)} >>\n".encode("latin-1")
        + b"stream\n"
        + stream_bytes
        + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("latin-1"))
        pdf.extend(obj)
        if not obj.endswith(b"\n"):
            pdf.extend(b"\n")
        pdf.extend(b"endobj\n")

    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))

    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        ).encode("latin-1")
    )
    return bytes(pdf)


def _pdf_text(x: int, y: int, text: str, size: int = 10) -> str:
    return f"BT /F1 {size} Tf {x} {y} Td ({_pdf_escape(text)}) Tj ET\n"


def _pdf_line(x1: int, y1: int, x2: int, y2: int) -> str:
    return f"{x1} {y1} m {x2} {y2} l S\n"


def _pdf_rect(x: int, y: int, w: int, h: int, fill: bool = False) -> str:
    return f"{x} {y} {w} {h} re {'f' if fill else 'S'}\n"


def generate_document_pdf(title: str, subtitle: str, paragraphs: list[str], footer: str = "") -> bytes:
    # A4 portrait page
    width, height = 595, 842
    cmds: list[str] = []

    cmds.append("0.14 0.53 0.34 rg\n")
    cmds.append(_pdf_rect(30, 770, 535, 46, fill=True))
    cmds.append("1 1 1 rg\n")
    cmds.append(_pdf_text(45, 796, title[:68], 16))
    cmds.append(_pdf_text(45, 780, subtitle[:90], 10))

    cmds.append("0 0 0 rg\n")
    y = 746
    for para in paragraphs:
        wrapped = textwrap.wrap(para, width=90) or [""]
        for line in wrapped:
            if y < 84:
                break
            cmds.append(_pdf_text(44, y, line, 11))
            y -= 15
        if y < 84:
            break
        y -= 8

    if footer:
        cmds.append("0.33 0.33 0.33 rg\n")
        cmds.append(_pdf_text(44, 50, footer[:96], 9))

    return _build_single_page_pdf("".join(cmds), page_width=width, page_height=height)


def generate_timetable_pdf(
    branch: str,
    program: str,
    semester: str,
    rows: list[tuple[str, list[str]]],
    academic_year: str = "2025-26",
) -> bytes:
    # A4 landscape page for table readability
    width, height = 842, 595
    x0 = 42
    y_top = 458
    row_h = 44
    col_widths = [88, 100, 100, 100, 100, 100, 100, 100]
    col_labels = ["Day", "P1", "P2", "P3", "Recess", "P4", "P5", "P6"]
    table_w = sum(col_widths)
    table_h = row_h * (len(rows) + 1)
    y_bottom = y_top - table_h

    cmds: list[str] = []
    cmds.append("0.14 0.53 0.34 rg\n")
    cmds.append(_pdf_rect(34, 535, 774, 42, fill=True))
    cmds.append("1 1 1 rg\n")
    cmds.append(_pdf_text(50, 560, f"{program} - {branch} Timetable", 17))
    cmds.append(_pdf_text(50, 545, f"Semester: {semester} | Academic Year: {academic_year}", 10))

    cmds.append("0 0 0 rg\n")
    cmds.append(_pdf_text(44, 514, "Time Slots: P1 09:00-09:50 | P2 09:55-10:45 | P3 10:50-11:40", 9))
    cmds.append(_pdf_text(44, 501, "Recess 11:40-12:20 | P4 12:20-01:10 | P5 01:15-02:05 | P6 02:10-03:00", 9))

    # Header row tint
    cmds.append("0.90 0.96 0.92 rg\n")
    cmds.append(_pdf_rect(x0, y_top - row_h, table_w, row_h, fill=True))
    cmds.append("0 0 0 rg\n")
    cmds.append("0.9 w\n")

    # Outer border + horizontal lines
    cmds.append(_pdf_rect(x0, y_bottom, table_w, table_h, fill=False))
    for i in range(1, len(rows) + 1):
        y = y_top - i * row_h
        cmds.append(_pdf_line(x0, y, x0 + table_w, y))

    # Vertical lines
    x = x0
    for width_col in col_widths[:-1]:
        x += width_col
        cmds.append(_pdf_line(x, y_bottom, x, y_top))

    # Header text
    x = x0 + 8
    for idx, label in enumerate(col_labels):
        cmds.append(_pdf_text(x, y_top - 27, label, 10))
        x += col_widths[idx]

    # Rows text
    for row_idx, (day_name, subjects) in enumerate(rows):
        y_text = y_top - (row_idx + 2) * row_h + 18
        cell_items = [day_name] + subjects
        x = x0 + 7
        for col_idx, item in enumerate(cell_items[:8]):
            clipped = item[:17]
            cmds.append(_pdf_text(x, y_text, clipped, 9))
            x += col_widths[col_idx]

    cmds.append("0.3 0.3 0.3 rg\n")
    cmds.append(_pdf_text(44, 42, "Generated by University Unified Portal", 9))

    return _build_single_page_pdf("".join(cmds), page_width=width, page_height=height)


def seed_demo_content(db: sqlite3.Connection) -> None:
    user_rows = db.execute("SELECT id, email FROM users").fetchall()
    ids = {row["email"]: row["id"] for row in user_rows}

    if not ids:
        return

    # Follow graph so student feed feels alive.
    follow_pairs = [
        ("student@university.edu", "priya.sharma@university.edu"),
        ("ayaan.gupta@university.edu", "priya.sharma@university.edu"),
        ("ayaan.gupta@university.edu", "sneha.kulkarni@university.edu"),
        ("meera.nair@university.edu", "nisha.verma@university.edu"),
        ("kunal.singh@university.edu", "farhan.khan@university.edu"),
        ("rohan.patil@university.edu", "raghav.bansal@university.edu"),
        ("sana.ali@university.edu", "ananya.iyer@university.edu"),
        ("neha.kapoor@university.edu", "sneha.kulkarni@university.edu"),
        ("siddharth.jain@university.edu", "priya.sharma@university.edu"),
    ]
    for student_email, prof_email in follow_pairs:
        student_id = ids.get(student_email)
        prof_id = ids.get(prof_email)
        if student_id and prof_id:
            db.execute(
                "INSERT OR IGNORE INTO follows (student_id, professor_id) VALUES (?, ?)",
                (student_id, prof_id),
            )

    def ensure_note(
        prof_email: str,
        title: str,
        subject: str,
        content: str,
        important: int,
        bullets: list[str],
    ) -> None:
        prof_id = ids.get(prof_email)
        if not prof_id:
            return
        existing = db.execute(
            "SELECT id, file_blob FROM notes WHERE professor_id = ? AND title = ?",
            (prof_id, title),
        ).fetchone()
        pdf_blob = generate_document_pdf(
            title=title,
            subtitle=f"{subject} | Prepared by {prof_email.split('@')[0].replace('.', ' ').title()}",
            paragraphs=bullets,
            footer="University Unified Portal - Study Material",
        )
        if existing:
            if not existing["file_blob"]:
                db.execute(
                    """
                    UPDATE notes
                    SET file_name = ?, file_blob = ?, file_mime = ?, content = ?, subject = ?, is_important = ?
                    WHERE id = ?
                    """,
                    (
                        f"{clean_name(title)}.pdf",
                        pdf_blob,
                        "application/pdf",
                        content,
                        subject,
                        important,
                        existing["id"],
                    ),
                )
            return

        db.execute(
            """
            INSERT INTO notes (
                professor_id, title, subject, content, is_important, file_name, file_blob, file_mime
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prof_id,
                title,
                subject,
                content,
                important,
                f"{clean_name(title)}.pdf",
                pdf_blob,
                "application/pdf",
            ),
        )

    note_seeds = [
        (
            "priya.sharma@university.edu",
            "Data Structures - Unit 3",
            "DSA",
            "AVL trees, rotations, BFS/DFS traversal, complexity comparison, and exam-oriented tips.",
            1,
            [
                "Understand binary search tree imbalance and how AVL balancing fixes height growth.",
                "Cover LL, RR, LR, and RL rotations with one worked example each.",
                "Practice BFS and DFS pseudocode with adjacency list complexity analysis.",
                "Typical semester questions combine traversal, complexity, and balancing case analysis.",
            ],
        ),
        (
            "priya.sharma@university.edu",
            "Machine Learning Basics",
            "ML",
            "Supervised vs unsupervised learning, overfitting, cross-validation, confusion matrix, and feature scaling.",
            0,
            [
                "Differentiate regression and classification with real exam examples.",
                "Use confusion matrix to compute precision, recall, and F1 score.",
                "Apply cross-validation and feature scaling before model training.",
                "Know bias-variance tradeoff and ways to reduce overfitting.",
            ],
        ),
        (
            "arjun.mehta@university.edu",
            "Engineering Mathematics II",
            "Math",
            "Eigenvalues, eigenvectors, matrix decomposition, rank-nullity theorem, and solved examples.",
            1,
            [
                "Derive characteristic equation and compute eigenvalues step-by-step.",
                "Explain geometric interpretation of eigenvectors in linear transforms.",
                "Practice matrix diagonalization and decomposition-focused numerical problems.",
                "Prepare concise 5-mark answers around rank-nullity theorem statements.",
            ],
        ),
        (
            "nisha.verma@university.edu",
            "Digital Electronics Revision Pack",
            "ECE",
            "Combinational and sequential logic design, minimization techniques, and timing diagrams.",
            1,
            [
                "K-map simplification for SOP and POS forms with don't-care conditions.",
                "Design combinational circuits using decoders and multiplexers.",
                "Sequential circuits: SR, JK, D, and T flip-flop transitions and timing.",
                "Solve common latch race-around and setup/hold timing questions.",
            ],
        ),
        (
            "nisha.verma@university.edu",
            "Signals and Systems Quick Notes",
            "ECE",
            "Signal properties, Fourier transform intuition, convolution, and LTI system analysis.",
            0,
            [
                "Classify signals by energy/power and periodicity with examples.",
                "Master convolution steps for discrete and continuous signals.",
                "Use Fourier transform properties for common exam derivations.",
                "State and interpret key LTI system stability conditions.",
            ],
        ),
        (
            "farhan.khan@university.edu",
            "Power Systems Fundamentals",
            "EEE",
            "Per unit system, transmission line models, load flow basics, and power factor correction.",
            1,
            [
                "Convert line values into per-unit and compare across voltage levels.",
                "Discuss short, medium, and long transmission line model assumptions.",
                "Solve lagging power factor correction numerical questions.",
                "Prepare one-page revision sheet for load flow terminology.",
            ],
        ),
        (
            "farhan.khan@university.edu",
            "Control Systems - PID Tuning Notes",
            "EEE",
            "Transfer functions, Routh criterion, root locus, Bode plot basics, and PID tuning strategies.",
            0,
            [
                "Derive closed-loop transfer functions from block diagrams.",
                "Use Routh-Hurwitz criterion for quick stability checks.",
                "Interpret root locus movement under gain variation.",
                "Compare proportional, PI, and PID controller effects.",
            ],
        ),
        (
            "raghav.bansal@university.edu",
            "Thermodynamics Cycles",
            "ME",
            "Otto, Diesel, and Rankine cycle assumptions, efficiency formulas, and solved numericals.",
            1,
            [
                "Draw PV and TS diagrams for Otto and Diesel cycles.",
                "Analyze thermal efficiency trends under compression ratio changes.",
                "Work on combined cycle and Rankine reheating questions.",
                "Memorize exam formulas through concept-linked derivations.",
            ],
        ),
        (
            "raghav.bansal@university.edu",
            "Manufacturing Processes Handbook",
            "ME",
            "Casting, machining, welding, and metrology essentials with process selection logic.",
            0,
            [
                "Compare machining, casting, and forming by cost and accuracy.",
                "Explain welding defects and corrective methods.",
                "Use metrology tolerances and fit terminology correctly.",
                "Practice process selection questions based on component requirements.",
            ],
        ),
        (
            "ananya.iyer@university.edu",
            "Strength of Materials Unit 2",
            "CE",
            "Stress-strain fundamentals, bending moment, shear force, and Mohr's circle applications.",
            1,
            [
                "Plot bending moment and shear force diagrams from beam loading.",
                "Use principal stress equations and Mohr's circle interpretation.",
                "Differentiate brittle vs ductile material response in viva-style answers.",
                "Solve composite bar and thermal stress examples.",
            ],
        ),
        (
            "ananya.iyer@university.edu",
            "Surveying Field Methods",
            "CE",
            "Chain surveying, leveling, contour mapping, and total station basics for practical exams.",
            0,
            [
                "List field booking standards and common corrections in leveling.",
                "Interpret contour intervals and gradient estimation.",
                "Apply bearing and traverse adjustment principles.",
                "Prepare short notes for total station and EDM instrumentation.",
            ],
        ),
        (
            "sneha.kulkarni@university.edu",
            "Computer Networks Crash Sheet",
            "IT",
            "OSI model, IP addressing, routing basics, transport protocols, and network security checkpoints.",
            1,
            [
                "Differentiate OSI and TCP/IP stacks in tabular format.",
                "Practice subnetting and CIDR problems with quick checks.",
                "Explain TCP handshake and congestion control basics.",
                "Include firewall, IDS, and VPN concepts in 10-mark answers.",
            ],
        ),
        (
            "sneha.kulkarni@university.edu",
            "Cyber Security Essentials",
            "IT",
            "Cryptography basics, authentication models, OWASP risks, and secure coding habits.",
            0,
            [
                "Compare symmetric and asymmetric cryptography workflows.",
                "Describe hashing, salting, and password storage best practices.",
                "Summarize common web vulnerabilities and mitigations.",
                "Draft incident response flow for campus IT systems.",
            ],
        ),
    ]
    for seed in note_seeds:
        ensure_note(*seed)

    def ensure_question_paper(
        uploader_email: str,
        subject: str,
        exam_year: str,
        title: str,
        content: str,
        important_questions: str,
        paper_sections: list[str],
    ) -> None:
        uploader_id = ids.get(uploader_email)
        if not uploader_id:
            return
        existing = db.execute(
            "SELECT id, file_blob FROM previous_questions WHERE uploader_id = ? AND title = ? AND exam_year = ?",
            (uploader_id, title, exam_year),
        ).fetchone()

        pdf_blob = generate_document_pdf(
            title=title,
            subtitle=f"{subject} | {exam_year} | Previous Year Question Paper",
            paragraphs=paper_sections,
            footer="University Unified Portal - Question Paper Archive",
        )
        if existing:
            if not existing["file_blob"]:
                db.execute(
                    """
                    UPDATE previous_questions
                    SET file_name = ?, file_blob = ?, file_mime = ?, content = ?, important_questions = ?, subject = ?
                    WHERE id = ?
                    """,
                    (
                        f"{clean_name(title)}.pdf",
                        pdf_blob,
                        "application/pdf",
                        content,
                        important_questions,
                        subject,
                        existing["id"],
                    ),
                )
            return

        db.execute(
            """
            INSERT INTO previous_questions (
                subject, exam_year, title, content, important_questions, uploader_id,
                file_name, file_blob, file_mime
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject,
                exam_year,
                title,
                content,
                important_questions,
                uploader_id,
                f"{clean_name(title)}.pdf",
                pdf_blob,
                "application/pdf",
            ),
        )

    pyq_seeds = [
        (
            "priya.sharma@university.edu",
            "DSA",
            "2024",
            "DSA End-Sem 2024",
            "Section A: Short answers, Section B: Explain trees and graphs, Section C: one coding analysis question.",
            "Q2: Explain AVL Trees\nQ5: Write BFS/DFS algorithms",
            [
                "Section A (2 marks each): complexity, recursion, ADT definitions.",
                "Section B (5 marks each): tree balancing, graph traversal, hash collision handling.",
                "Section C (10 marks): design and analyze one optimized data structure workflow.",
            ],
        ),
        (
            "arjun.mehta@university.edu",
            "Math",
            "2024",
            "Math Mid-Term 2024",
            "Section A: definitions, Section B: matrix operations, Section C: numerical methods.",
            "Q1: Eigen values\nQ3: Matrix decomposition",
            [
                "Part A: vector spaces, linear dependence, determinant properties.",
                "Part B: matrix decomposition and rank-nullity theorem numericals.",
                "Part C: iterative method convergence and error bounds.",
            ],
        ),
        (
            "nisha.verma@university.edu",
            "ECE",
            "2023",
            "Digital Electronics End-Sem 2023",
            "Part A: logic gates, Part B: K-map and minimization, Part C: sequential circuit design.",
            "Q4: Minimize boolean expression using K-map\nQ7: Design synchronous counter",
            [
                "Part A: truth tables, canonical forms, and logic identities.",
                "Part B: K-map minimization for 3 and 4 variable expressions.",
                "Part C: flip-flop based design and timing analysis.",
            ],
        ),
        (
            "farhan.khan@university.edu",
            "EEE",
            "2023",
            "Power Systems End-Sem 2023",
            "Part A: per unit calculations, Part B: transmission line models, Part C: stability basics.",
            "Q3: Transmission line ABCD constants\nQ8: Power factor correction design",
            [
                "Part A: per-unit conversion and base value derivations.",
                "Part B: line parameters, Ferranti effect, and voltage regulation.",
                "Part C: reactive power planning and short conceptual notes.",
            ],
        ),
        (
            "raghav.bansal@university.edu",
            "ME",
            "2022",
            "Thermodynamics Semester Paper 2022",
            "Section A: properties and laws, Section B: cycle analysis, Section C: numericals.",
            "Q2: Derive Otto cycle efficiency\nQ6: Rankine cycle with reheating",
            [
                "Section A: Zeroth, first and second law conceptual questions.",
                "Section B: Otto, Diesel and Rankine cycle comparison.",
                "Section C: numerical set on entropy and thermal efficiency.",
            ],
        ),
        (
            "ananya.iyer@university.edu",
            "CE",
            "2022",
            "Strength of Materials End-Sem 2022",
            "Part A: stress strain, Part B: beam theory, Part C: principal stresses.",
            "Q1: Bending stress derivation\nQ5: Mohr circle construction",
            [
                "Part A: elasticity constants and Hooke law applications.",
                "Part B: SFD and BMD for simply supported and cantilever beams.",
                "Part C: principal stress and strain transformation numericals.",
            ],
        ),
        (
            "sneha.kulkarni@university.edu",
            "IT",
            "2024",
            "Computer Networks Mid-Sem 2024",
            "Part A: layered architecture, Part B: routing, Part C: transport and security.",
            "Q2: Subnetting and CIDR\nQ4: TCP congestion control phases",
            [
                "Part A: OSI vs TCP/IP and protocol mapping.",
                "Part B: shortest path routing and distance vector updates.",
                "Part C: TCP reliability, congestion control, and TLS basics.",
            ],
        ),
    ]
    for seed in pyq_seeds:
        ensure_question_paper(*seed)

    announcement_seeds = [
        (
            "priya.sharma@university.edu",
            "Extra Class on Saturday",
            "Extra class on Saturday 10 AM - Room 204.",
            "class",
            "CSE",
            0,
        ),
        (
            "priya.sharma@university.edu",
            "Assignment 3 Deadline",
            "Assignment 3 deadline extended to Jan 30. Please submit on portal.",
            "class",
            "CSE",
            0,
        ),
        (
            "admin@campus.local",
            "Annual Tech Fest InnoVate",
            "Annual Tech Fest InnoVate 2026 registrations are now open.",
            "university",
            "ALL",
            0,
        ),
        (
            "nisha.verma@university.edu",
            "ECE Lab Safety Briefing",
            "All ECE students must attend mandatory lab safety orientation on Monday.",
            "class",
            "ECE",
            0,
        ),
    ]
    for author_email, title, message, kind, target_branch, send_email_flag in announcement_seeds:
        author_id = ids.get(author_email)
        if not author_id:
            continue
        exists = db.execute(
            "SELECT id FROM announcements WHERE author_id = ? AND title = ?",
            (author_id, title),
        ).fetchone()
        if exists:
            continue
        db.execute(
            """
            INSERT INTO announcements (author_id, title, message, type, target_branch, send_email)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (author_id, title, message, kind, target_branch, send_email_flag),
        )

    attendance_plan = {
        "student@university.edu": [
            ("DSA", 24, 20, "priya.sharma@university.edu"),
            ("ML", 22, 16, "priya.sharma@university.edu"),
            ("Math", 21, 13, "arjun.mehta@university.edu"),
        ],
        "ayaan.gupta@university.edu": [
            ("DSA", 30, 25, "priya.sharma@university.edu"),
            ("OS", 28, 22, "sneha.kulkarni@university.edu"),
            ("Math", 26, 21, "arjun.mehta@university.edu"),
        ],
        "meera.nair@university.edu": [
            ("Digital Electronics", 28, 22, "nisha.verma@university.edu"),
            ("Signals", 27, 20, "nisha.verma@university.edu"),
            ("Math", 24, 18, "arjun.mehta@university.edu"),
        ],
        "kunal.singh@university.edu": [
            ("Power Systems", 26, 19, "farhan.khan@university.edu"),
            ("Control Systems", 24, 17, "farhan.khan@university.edu"),
            ("Math", 22, 16, "arjun.mehta@university.edu"),
        ],
        "rohan.patil@university.edu": [
            ("Thermodynamics", 27, 21, "raghav.bansal@university.edu"),
            ("Manufacturing", 24, 18, "raghav.bansal@university.edu"),
            ("Strength", 22, 16, "ananya.iyer@university.edu"),
        ],
        "sana.ali@university.edu": [
            ("SOM", 25, 19, "ananya.iyer@university.edu"),
            ("Surveying", 23, 17, "ananya.iyer@university.edu"),
            ("Math", 22, 16, "arjun.mehta@university.edu"),
        ],
        "neha.kapoor@university.edu": [
            ("Networks", 26, 21, "sneha.kulkarni@university.edu"),
            ("Cyber Security", 24, 19, "sneha.kulkarni@university.edu"),
            ("DSA", 22, 18, "priya.sharma@university.edu"),
        ],
        "siddharth.jain@university.edu": [
            ("Programming in C", 22, 17, "priya.sharma@university.edu"),
            ("Data Structures", 22, 16, "priya.sharma@university.edu"),
            ("Web Technologies", 20, 15, "sneha.kulkarni@university.edu"),
        ],
    }
    for student_email, subject_rows in attendance_plan.items():
        student_id = ids.get(student_email)
        if not student_id:
            continue
        existing_count = db.execute(
            "SELECT COUNT(*) AS c FROM attendance_entries WHERE student_id = ?",
            (student_id,),
        ).fetchone()["c"]
        if existing_count > 0:
            continue

        to_insert: list[tuple[Any, ...]] = []
        for subject, total, present, marker_email in subject_rows:
            marker_id = ids.get(marker_email) or ids.get("admin@campus.local")
            if not marker_id:
                continue
            for index in range(total):
                status = "present" if index < present else "absent"
                class_date = f"2026-01-{(index % 28) + 1:02d}"
                to_insert.append((student_id, subject, status, class_date, marker_id))

        if to_insert:
            db.executemany(
                """
                INSERT INTO attendance_entries (student_id, subject, status, class_date, marked_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                to_insert,
            )

    default_timetables = {
        "CSE": {
            "program": "B.Tech Computer Science",
            "semester": "Semester IV",
            "rows": [
                ("Monday", ["DSA", "DBMS", "Discrete Math", "RECESS", "OS", "DSA Lab", "Aptitude"]),
                ("Tuesday", ["OOP", "DBMS", "CN", "RECESS", "Math", "Project", "Library"]),
                ("Wednesday", ["DSA", "OS", "Math", "RECESS", "CN", "Soft Skills", "Sports"]),
                ("Thursday", ["DBMS", "OOP", "DSA", "RECESS", "CN Lab", "Seminar", "Mentor Hour"]),
                ("Friday", ["OS", "Math", "Aptitude", "RECESS", "DBMS Lab", "Project", "Club"]),
                ("Saturday", ["Revision", "Coding Test", "Tutorial", "RECESS", "Workshop", "Counselling", "Self Study"]),
            ],
        },
        "ECE": {
            "program": "B.Tech Electronics & Communication",
            "semester": "Semester IV",
            "rows": [
                ("Monday", ["Signals", "Digital", "Math", "RECESS", "Networks", "Digital Lab", "Aptitude"]),
                ("Tuesday", ["Analog", "Signals", "EMFT", "RECESS", "Math", "Project", "Library"]),
                ("Wednesday", ["Digital", "Networks", "Math", "RECESS", "Signals Lab", "Soft Skills", "Sports"]),
                ("Thursday", ["EMFT", "Analog", "Digital", "RECESS", "Microprocessors", "Seminar", "Mentor Hour"]),
                ("Friday", ["Networks", "Math", "Aptitude", "RECESS", "VLSI Basics", "Project", "Club"]),
                ("Saturday", ["Revision", "Quiz", "Tutorial", "RECESS", "Workshop", "Counselling", "Self Study"]),
            ],
        },
        "EEE": {
            "program": "B.Tech Electrical & Electronics",
            "semester": "Semester IV",
            "rows": [
                ("Monday", ["Power Sys", "Machines", "Math", "RECESS", "Control", "Power Lab", "Aptitude"]),
                ("Tuesday", ["Analog", "Control", "Math", "RECESS", "Machines", "Project", "Library"]),
                ("Wednesday", ["Power Sys", "Circuit Theory", "Math", "RECESS", "Control Lab", "Soft Skills", "Sports"]),
                ("Thursday", ["Machines", "Analog", "Power Sys", "RECESS", "PE", "Seminar", "Mentor Hour"]),
                ("Friday", ["Control", "Math", "Aptitude", "RECESS", "Power Electronics", "Project", "Club"]),
                ("Saturday", ["Revision", "Quiz", "Tutorial", "RECESS", "Workshop", "Counselling", "Self Study"]),
            ],
        },
        "ME": {
            "program": "B.Tech Mechanical Engineering",
            "semester": "Semester IV",
            "rows": [
                ("Monday", ["Thermo", "SOM", "Math", "RECESS", "Manufacturing", "CAD Lab", "Aptitude"]),
                ("Tuesday", ["Fluid", "Thermo", "Math", "RECESS", "Kinematics", "Project", "Library"]),
                ("Wednesday", ["Manufacturing", "SOM", "Math", "RECESS", "Thermo Lab", "Soft Skills", "Sports"]),
                ("Thursday", ["Kinematics", "Fluid", "Thermo", "RECESS", "PE", "Seminar", "Mentor Hour"]),
                ("Friday", ["SOM", "Math", "Aptitude", "RECESS", "Manufacturing Lab", "Project", "Club"]),
                ("Saturday", ["Revision", "Quiz", "Tutorial", "RECESS", "Workshop", "Counselling", "Self Study"]),
            ],
        },
        "CE": {
            "program": "B.Tech Civil Engineering",
            "semester": "Semester IV",
            "rows": [
                ("Monday", ["SOM", "Surveying", "Math", "RECESS", "Hydraulics", "Survey Lab", "Aptitude"]),
                ("Tuesday", ["Concrete", "SOM", "Math", "RECESS", "Geo Tech", "Project", "Library"]),
                ("Wednesday", ["Hydraulics", "Surveying", "Math", "RECESS", "Concrete Lab", "Soft Skills", "Sports"]),
                ("Thursday", ["Geo Tech", "Concrete", "SOM", "RECESS", "Transportation", "Seminar", "Mentor Hour"]),
                ("Friday", ["Surveying", "Math", "Aptitude", "RECESS", "Design Studio", "Project", "Club"]),
                ("Saturday", ["Revision", "Quiz", "Tutorial", "RECESS", "Workshop", "Counselling", "Self Study"]),
            ],
        },
        "IT": {
            "program": "B.Tech Information Technology",
            "semester": "Semester IV",
            "rows": [
                ("Monday", ["Networks", "Security", "Math", "RECESS", "DBMS", "Net Lab", "Aptitude"]),
                ("Tuesday", ["Cloud", "Networks", "Math", "RECESS", "Web Tech", "Project", "Library"]),
                ("Wednesday", ["Security", "DBMS", "Math", "RECESS", "Cloud Lab", "Soft Skills", "Sports"]),
                ("Thursday", ["Web Tech", "Cloud", "Networks", "RECESS", "AI Basics", "Seminar", "Mentor Hour"]),
                ("Friday", ["DBMS", "Math", "Aptitude", "RECESS", "Security Lab", "Project", "Club"]),
                ("Saturday", ["Revision", "Quiz", "Tutorial", "RECESS", "Workshop", "Counselling", "Self Study"]),
            ],
        },
        "BCA": {
            "program": "Bachelor of Computer Applications",
            "semester": "Semester IV",
            "rows": [
                ("Monday", ["DSA", "DBMS", "Math", "RECESS", "Web Dev", "DSA Lab", "Aptitude"]),
                ("Tuesday", ["Java", "DBMS", "Math", "RECESS", "OS", "Project", "Library"]),
                ("Wednesday", ["Web Dev", "OS", "Math", "RECESS", "DBMS Lab", "Soft Skills", "Sports"]),
                ("Thursday", ["Java", "DSA", "OS", "RECESS", "Python", "Seminar", "Mentor Hour"]),
                ("Friday", ["DBMS", "Math", "Aptitude", "RECESS", "Web Lab", "Project", "Club"]),
                ("Saturday", ["Revision", "Quiz", "Tutorial", "RECESS", "Workshop", "Counselling", "Self Study"]),
            ],
        },
        "BBA": {
            "program": "Bachelor of Business Administration",
            "semester": "Semester IV",
            "rows": [
                ("Monday", ["Marketing", "Finance", "Stats", "RECESS", "HR", "Case Study", "Aptitude"]),
                ("Tuesday", ["Economics", "Marketing", "Stats", "RECESS", "OB", "Project", "Library"]),
                ("Wednesday", ["Finance", "OB", "Stats", "RECESS", "Business Law", "Soft Skills", "Sports"]),
                ("Thursday", ["HR", "Economics", "Marketing", "RECESS", "MIS", "Seminar", "Mentor Hour"]),
                ("Friday", ["OB", "Stats", "Aptitude", "RECESS", "Entrepreneurship", "Project", "Club"]),
                ("Saturday", ["Revision", "Quiz", "Tutorial", "RECESS", "Workshop", "Counselling", "Self Study"]),
            ],
        },
    }

    uploader_id = ids.get("admin@campus.local") or ids.get("priya.sharma@university.edu")
    if uploader_id:
        for branch, payload in default_timetables.items():
            file_name = f"{branch.lower()}-timetable-sem4.pdf"
            exists = db.execute(
                "SELECT id FROM timetables WHERE branch = ? AND file_name = ?",
                (branch, file_name),
            ).fetchone()
            if exists:
                continue

            timetable_pdf = generate_timetable_pdf(
                branch=branch,
                program=payload["program"],
                semester=payload["semester"],
                rows=payload["rows"],
            )
            db.execute(
                """
                INSERT INTO timetables (branch, title, file_name, file_blob, file_mime, uploader_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    branch,
                    f"{branch} Timetable - Semester IV",
                    file_name,
                    timetable_pdf,
                    "application/pdf",
                    uploader_id,
                ),
            )


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student', 'professor', 'admin')),
            university_id TEXT UNIQUE,
            phone TEXT,
            photo_url TEXT,
            photo_blob BLOB,
            photo_mime TEXT,
            bio TEXT,
            branch TEXT,
            study_program TEXT,
            open_to_collab INTEGER DEFAULT 0,
            subject TEXT,
            free_hours TEXT,
            designation TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS follows (
            student_id INTEGER NOT NULL,
            professor_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, professor_id),
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (professor_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            subject TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            is_important INTEGER NOT NULL DEFAULT 0,
            file_name TEXT,
            file_blob BLOB,
            file_mime TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (professor_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS previous_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            exam_year TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            important_questions TEXT NOT NULL DEFAULT '',
            uploader_id INTEGER NOT NULL,
            file_name TEXT,
            file_blob BLOB,
            file_mime TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uploader_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS generated_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_ref_id INTEGER,
            source_text TEXT NOT NULL,
            questions TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('class', 'university', 'general')) DEFAULT 'class',
            target_branch TEXT NOT NULL DEFAULT 'ALL',
            send_email INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS attendance_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('present', 'absent')),
            class_date TEXT NOT NULL,
            marked_by INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (marked_by) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS timetables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch TEXT NOT NULL,
            title TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_blob BLOB NOT NULL,
            file_mime TEXT,
            uploader_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uploader_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_prev_questions ON previous_questions(subject, exam_year DESC);
        CREATE INDEX IF NOT EXISTS idx_announcement_created ON announcements(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance_entries(student_id, subject);
        CREATE INDEX IF NOT EXISTS idx_timetable_branch ON timetables(branch, created_at DESC);
        """
    )

    # Backward compatible migrations for older local DB versions.
    ensure_column(db, "users", "university_id", "TEXT")
    ensure_column(db, "users", "phone", "TEXT")
    ensure_column(db, "users", "photo_blob", "BLOB")
    ensure_column(db, "users", "photo_mime", "TEXT")

    ensure_column(db, "notes", "file_name", "TEXT")
    ensure_column(db, "notes", "file_blob", "BLOB")
    ensure_column(db, "notes", "file_mime", "TEXT")

    ensure_column(db, "previous_questions", "important_questions", "TEXT NOT NULL DEFAULT ''")
    ensure_column(db, "previous_questions", "file_name", "TEXT")
    ensure_column(db, "previous_questions", "file_blob", "BLOB")
    ensure_column(db, "previous_questions", "file_mime", "TEXT")

    seed_demo_users(db)

    # Fill university IDs for legacy accounts where value is missing.
    users_without_id = db.execute(
        "SELECT id, role FROM users WHERE university_id IS NULL OR university_id = ''"
    ).fetchall()
    for row in users_without_id:
        generated = generate_university_id(row["role"], db)
        db.execute("UPDATE users SET university_id = ? WHERE id = ?", (generated, row["id"]))

    # Keep fixed demo IDs stable even across legacy DB upgrades.
    fixed_demo_ids = {
        "admin@campus.local": "ADM001",
        "priya.sharma@university.edu": "PRO001",
        "arjun.mehta@university.edu": "PRO002",
        "nisha.verma@university.edu": "PRO003",
        "farhan.khan@university.edu": "PRO004",
        "raghav.bansal@university.edu": "PRO005",
        "ananya.iyer@university.edu": "PRO006",
        "sneha.kulkarni@university.edu": "PRO007",
        "student@university.edu": "STU2024001",
        "ayaan.gupta@university.edu": "STU2024002",
        "meera.nair@university.edu": "STU2024003",
        "kunal.singh@university.edu": "STU2024004",
        "rohan.patil@university.edu": "STU2024005",
        "sana.ali@university.edu": "STU2024006",
        "neha.kapoor@university.edu": "STU2024007",
        "siddharth.jain@university.edu": "STU2024008",
    }
    for email, university_id in fixed_demo_ids.items():
        db.execute(
            "UPDATE users SET university_id = ? WHERE email = ?",
            (university_id, email),
        )

    seed_demo_content(db)
    db.commit()


def current_user() -> sqlite3.Row | None:
    if "current_user" in g:
        return g.current_user

    user_id = session.get("user_id")
    if not user_id:
        g.current_user = None
        return None

    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    g.current_user = user
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please login first.", "warning")
                return redirect(url_for("login"))
            if user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def clean_name(name: str, fallback: str = "download") -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-")
    return safe_name or fallback


def send_text_download(file_name: str, body: str):
    file_base = clean_name(file_name)
    if not file_base.lower().endswith(".txt"):
        file_base = f"{file_base}.txt"

    return send_file(
        io.BytesIO(body.encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name=file_base,
    )


def send_blob_download(file_name: str, content: bytes, mime: str | None = None):
    return send_file(
        io.BytesIO(content),
        mimetype=mime or "application/octet-stream",
        as_attachment=True,
        download_name=clean_name(file_name),
    )


def read_uploaded_file(field_name: str, allowed_extensions: set[str]) -> tuple[str | None, bytes | None, str | None, str | None]:
    uploaded = request.files.get(field_name)
    if not uploaded or not uploaded.filename:
        return None, None, None, None

    filename = secure_filename(uploaded.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        return None, None, None, "Invalid file format. Please upload the supported format only."

    blob = uploaded.read()
    if not blob:
        return None, None, None, "Uploaded file is empty."

    if len(blob) > MAX_UPLOAD_BYTES:
        return None, None, None, f"File too large. Max size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."

    mime = uploaded.mimetype or "application/octet-stream"
    return filename, blob, mime, None


def build_exam_questions(raw_text: str) -> list[str]:
    text = re.sub(r"\s+", " ", raw_text).strip()
    if not text:
        return []

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", text)
        if len(s.strip()) >= 20
    ]

    word_counts: dict[str, int] = {}
    for word in re.findall(r"[A-Za-z]{5,}", text.lower()):
        if word in STOP_WORDS:
            continue
        word_counts[word] = word_counts.get(word, 0) + 1

    top_words = [
        item[0] for item in sorted(word_counts.items(), key=lambda p: p[1], reverse=True)[:8]
    ]

    questions: list[str] = []
    for word in top_words[:4]:
        questions.append(f"Define {word} and explain it with one practical example.")

    if len(top_words) >= 2:
        questions.append(
            f"Compare {top_words[0]} and {top_words[1]} with key differences and exam use-cases."
        )

    for sentence in sentences[:3]:
        short = sentence[:120].rstrip(".")
        questions.append(f"Write a short note on: {short}.")

    questions.extend(
        [
            "Create a 5-mark answer from this topic using concept, diagram, and one example.",
            "Draft one likely semester exam question and provide the ideal model answer.",
            "List common mistakes students make in this topic and how to avoid them.",
        ]
    )

    unique_questions: list[str] = []
    seen = set()
    for q in questions:
        if q not in seen:
            unique_questions.append(q)
            seen.add(q)

    return unique_questions[:10]


def create_notification(user_id: int, message: str, link: str | None = None) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)",
        (user_id, message, link),
    )


def get_recipients_for_announcement(
    author_id: int, target_branch: str, announce_type: str
) -> list[sqlite3.Row]:
    db = get_db()
    target = (target_branch or "ALL").strip().upper()
    kind = (announce_type or "class").strip().lower()

    if kind == "university":
        return db.execute(
            "SELECT id, email, name FROM users WHERE id != ?",
            (author_id,),
        ).fetchall()

    if kind == "class":
        if target in {"ALL", ""}:
            return db.execute(
                """
                SELECT id, email, name
                FROM users
                WHERE id != ?
                  AND (
                        role IN ('professor', 'admin')
                        OR (
                            role = 'student'
                            AND EXISTS (
                                SELECT 1
                                FROM follows f
                                WHERE f.student_id = users.id
                                  AND f.professor_id = ?
                            )
                        )
                      )
                """,
                (author_id, author_id),
            ).fetchall()

        return db.execute(
            """
            SELECT id, email, name
            FROM users
                WHERE id != ?
                  AND (
                        role IN ('professor', 'admin')
                        OR (
                            role = 'student'
                            AND EXISTS (
                                SELECT 1
                                FROM follows f
                                WHERE f.student_id = users.id
                                  AND f.professor_id = ?
                            )
                        )
                      )
            """,
            (author_id, author_id),
        ).fetchall()

    if target in {"ALL", ""}:
        return db.execute(
            "SELECT id, email, name FROM users WHERE id != ?",
            (author_id,),
        ).fetchall()

    return db.execute(
        """
        SELECT id, email, name
        FROM users
        WHERE id != ?
          AND (
                role IN ('professor', 'admin')
                OR (role = 'student' AND UPPER(COALESCE(branch, '')) = ?)
              )
        """,
        (author_id, target),
    ).fetchall()


def send_email(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user or "")

    if not smtp_host or not smtp_user or not smtp_password or not smtp_from:
        return False, "SMTP is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True, "Email sent successfully."
    except Exception as exc:  # pragma: no cover
        return False, f"Email send failed: {exc}"


def attendance_summary(student_id: int) -> list[dict[str, Any]]:
    rows = get_db().execute(
        """
        SELECT
            subject,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_count,
            COUNT(*) AS total_count
        FROM attendance_entries
        WHERE student_id = ?
        GROUP BY subject
        ORDER BY subject ASC
        """,
        (student_id,),
    ).fetchall()

    summary: list[dict[str, Any]] = []
    for row in rows:
        total = row["total_count"] or 0
        present = row["present_count"] or 0
        percent = int(round((present * 100.0 / total), 0)) if total else 0
        summary.append(
            {
                "subject": row["subject"],
                "present": present,
                "total": total,
                "percent": percent,
                "is_shortage": percent < ATTENDANCE_THRESHOLD,
            }
        )

    return summary


def overall_attendance(summary_rows: list[dict[str, Any]]) -> dict[str, int]:
    total = sum(row["total"] for row in summary_rows)
    present = sum(row["present"] for row in summary_rows)
    percent = int(round((present * 100.0 / total), 0)) if total else 0
    return {"present": present, "total": total, "percent": percent}


def send_shortage_email(student_row: sqlite3.Row, summary_rows: list[dict[str, Any]]) -> tuple[bool, str]:
    shortage_rows = [row for row in summary_rows if row["percent"] < ATTENDANCE_THRESHOLD]
    if not shortage_rows:
        return False, "No attendance shortage found for this student."

    lines = [
        f"Dear {student_row['name']},",
        "",
        f"Your attendance is below {ATTENDANCE_THRESHOLD}% in the following subjects:",
    ]
    for row in shortage_rows:
        lines.append(f"- {row['subject']}: {row['percent']}% ({row['present']}/{row['total']} classes)")

    lines.extend(
        [
            "",
            "Please attend classes regularly to avoid semester eligibility issues.",
            "",
            "Regards,",
            "University Unified Portal",
        ]
    )

    success, detail = send_email(
        student_row["email"],
        "Attendance Shortage Alert",
        "\n".join(lines),
    )
    return success, detail


def render_page(template_name: str, **context: Any):
    return render_template(template_name, **context)


@app.context_processor
def inject_globals() -> dict[str, Any]:
    user = current_user()
    unread_count = 0
    quick_notifications: list[sqlite3.Row] = []

    if user:
        db = get_db()
        unread_count = db.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
            (user["id"],),
        ).fetchone()["c"]
        quick_notifications = db.execute(
            """
            SELECT id, message, link, created_at
            FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (user["id"],),
        ).fetchall()

    return {
        "current_user": user,
        "role_rank": ROLE_RANK,
        "unread_count": unread_count,
        "quick_notifications": quick_notifications,
        "active_nav": NAV_MAP.get(request.endpoint or "", "dashboard"),
        "attendance_threshold": ATTENDANCE_THRESHOLD,
    }


@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_page("index.html", page_title="University Unified Portal")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))

    selected_role = request.form.get("role", "student") if request.method == "POST" else "student"

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip().lower()

        if not identifier or not password:
            flash("Please enter University ID/email and password.", "danger")
            return render_page("login.html", selected_role=selected_role, page_title="Sign In")

        db = get_db()
        user = db.execute(
            """
            SELECT * FROM users
            WHERE LOWER(email) = ? OR UPPER(COALESCE(university_id, '')) = ?
            """,
            (identifier.lower(), identifier.upper()),
        ).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid credentials.", "danger")
            return render_page("login.html", selected_role=selected_role, page_title="Sign In")

        if role in ROLE_RANK and user["role"] != role:
            flash("Selected role does not match this account.", "danger")
            return render_page("login.html", selected_role=selected_role, page_title="Sign In")

        session.clear()
        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['name']}.", "success")
        return redirect(url_for("dashboard"))

    return render_page("login.html", selected_role=selected_role, page_title="Sign In")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "student").strip().lower()
        branch = request.form.get("branch", "").strip()
        subject = request.form.get("subject", "").strip()

        if role not in {"student", "professor"}:
            flash("You can register only as student or professor.", "danger")
            return render_page("register.html", page_title="Create Account")

        if len(name) < 2 or len(password) < 6 or not email:
            flash("Use valid name, email, and password (min 6 chars).", "danger")
            return render_page("register.html", page_title="Create Account")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            flash("Email already exists. Please login.", "warning")
            return redirect(url_for("login"))

        university_id = generate_university_id(role, db)
        db.execute(
            """
            INSERT INTO users (
                name, email, password_hash, role, university_id, branch, subject,
                designation, open_to_collab
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                email,
                generate_password_hash(password),
                role,
                university_id,
                branch if role == "student" else (branch or "ALL"),
                subject,
                "Student" if role == "student" else "Professor",
                1 if role == "student" else 0,
            ),
        )
        db.commit()
        flash(f"Account created. Your University ID is {university_id}.", "success")
        return redirect(url_for("login"))

    return render_page("register.html", page_title="Create Account")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    db = get_db()

    if user["role"] == "student":
        attendance_rows = attendance_summary(user["id"])
        overall = overall_attendance(attendance_rows)
        followed_professors = db.execute(
            """
            SELECT u.id, u.name, u.designation, u.subject, u.branch
            FROM follows f
            JOIN users u ON u.id = f.professor_id
            WHERE f.student_id = ?
            ORDER BY u.name
            """,
            (user["id"],),
        ).fetchall()

        recent_announcements = db.execute(
            """
            SELECT a.*, u.name AS author_name
            FROM announcements a
            JOIN users u ON u.id = a.author_id
            WHERE (
                    a.type = 'university'
                    OR (
                        a.type = 'class'
                        AND EXISTS (
                            SELECT 1
                            FROM follows f
                            WHERE f.student_id = ?
                              AND f.professor_id = a.author_id
                        )
                    )
                    OR (
                        a.type = 'general'
                        AND (UPPER(a.target_branch) = 'ALL' OR UPPER(a.target_branch) = UPPER(COALESCE(?, '')))
                    )
                  )
            ORDER BY a.created_at DESC
            LIMIT 5
            """,
            (user["id"], user["branch"]),
        ).fetchall()

        note_count = db.execute("SELECT COUNT(*) AS c FROM notes").fetchone()["c"]
        ann_count = db.execute(
            """
            SELECT COUNT(*) AS c
            FROM announcements a
            WHERE (
                    a.type = 'university'
                    OR (
                        a.type = 'class'
                        AND EXISTS (
                            SELECT 1
                            FROM follows f
                            WHERE f.student_id = ?
                              AND f.professor_id = a.author_id
                        )
                    )
                    OR (
                        a.type = 'general'
                        AND (UPPER(a.target_branch) = 'ALL' OR UPPER(a.target_branch) = UPPER(COALESCE(?, '')))
                    )
                  )
            """,
            (user["id"], user["branch"]),
        ).fetchone()["c"]

        return render_page(
            "dashboard.html",
            page_title="Dashboard",
            attendance_rows=attendance_rows,
            overall_attendance=overall,
            recent_announcements=recent_announcements,
            note_count=note_count,
            announcement_count=ann_count,
            my_notes=None,
            stats=None,
            risk_rows=None,
            users=None,
            admin_notes=None,
            followed_professors=followed_professors,
        )

    if user["role"] == "professor":
        my_notes = db.execute(
            """
            SELECT * FROM notes
            WHERE professor_id = ?
            ORDER BY created_at DESC
            LIMIT 8
            """,
            (user["id"],),
        ).fetchall()

        follower_count = db.execute(
            "SELECT COUNT(*) AS c FROM follows WHERE professor_id = ?",
            (user["id"],),
        ).fetchone()["c"]

        my_announcements = db.execute(
            "SELECT COUNT(*) AS c FROM announcements WHERE author_id = ?",
            (user["id"],),
        ).fetchone()["c"]

        students = db.execute(
            "SELECT id, name FROM users WHERE role = 'student' ORDER BY name"
        ).fetchall()
        risk_rows: list[dict[str, Any]] = []
        for student in students:
            rows = attendance_summary(student["id"])
            if not rows:
                continue
            overall = overall_attendance(rows)
            if overall["percent"] < ATTENDANCE_THRESHOLD:
                risk_rows.append(
                    {
                        "id": student["id"],
                        "name": student["name"],
                        "percent": overall["percent"],
                    }
                )

        return render_page(
            "dashboard.html",
            page_title="Professor Dashboard",
            stats={
                "followers": follower_count,
                "notes": len(my_notes),
                "announcements": my_announcements,
            },
            my_notes=my_notes,
            risk_rows=risk_rows[:8],
            attendance_rows=None,
            overall_attendance=None,
            recent_announcements=None,
            note_count=None,
            announcement_count=None,
            users=None,
            admin_notes=None,
            followed_professors=None,
        )

    stats = {
        "users": db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"],
        "students": db.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'student'").fetchone()["c"],
        "professors": db.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'professor'").fetchone()["c"],
        "notes": db.execute("SELECT COUNT(*) AS c FROM notes").fetchone()["c"],
        "announcements": db.execute("SELECT COUNT(*) AS c FROM announcements").fetchone()["c"],
        "timetables": db.execute("SELECT COUNT(*) AS c FROM timetables").fetchone()["c"],
    }

    users = db.execute(
        "SELECT id, name, email, role, university_id, created_at FROM users ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    admin_notes = db.execute(
        """
        SELECT n.id, n.title, n.subject, n.created_at, u.name AS professor_name
        FROM notes n
        JOIN users u ON u.id = n.professor_id
        ORDER BY n.created_at DESC
        LIMIT 20
        """
    ).fetchall()

    return render_page(
        "dashboard.html",
        page_title="Admin Dashboard",
        stats=stats,
        users=users,
        admin_notes=admin_notes,
        attendance_rows=None,
        overall_attendance=None,
        recent_announcements=None,
        note_count=None,
        announcement_count=None,
        my_notes=None,
        risk_rows=None,
        followed_professors=None,
    )


@app.route("/notes", methods=["GET", "POST"])
@app.route("/notes-materials", methods=["GET", "POST"])
@login_required
def notes_page():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        if user["role"] not in {"professor", "admin"}:
            abort(403)

        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        content = request.form.get("content", "").strip()
        is_important = 1 if request.form.get("is_important") == "on" else 0

        file_name, file_blob, file_mime, file_error = read_uploaded_file("pdf_file", PDF_EXTENSIONS)
        if file_error:
            flash(file_error, "danger")
            return redirect(url_for("notes_page"))

        if not title or not subject:
            flash("Please add note title and subject.", "danger")
            return redirect(url_for("notes_page"))

        if len(content) < 20 and not file_blob:
            flash("Add note text (min 20 chars) or upload a PDF.", "danger")
            return redirect(url_for("notes_page"))

        cursor = db.execute(
            """
            INSERT INTO notes (professor_id, title, subject, content, is_important, file_name, file_blob, file_mime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user["id"], title, subject, content, is_important, file_name, file_blob, file_mime),
        )
        note_id = cursor.lastrowid

        if user["role"] == "professor":
            followers = db.execute(
                "SELECT student_id FROM follows WHERE professor_id = ?",
                (user["id"],),
            ).fetchall()
            message = (
                f"{user['name']} uploaded an IMPORTANT note: {title}"
                if is_important
                else f"{user['name']} uploaded a new note: {title}"
            )
            for row in followers:
                create_notification(
                    row["student_id"],
                    message,
                    url_for("notes_page") + f"#note-{note_id}",
                )

        db.commit()
        flash("Note uploaded successfully.", "success")
        return redirect(url_for("notes_page"))

    subject_filter = request.args.get("subject", "").strip()

    if user["role"] == "student":
        if subject_filter:
            notes = db.execute(
                """
                SELECT n.*, u.name AS professor_name, u.id AS professor_id
                FROM notes n
                JOIN users u ON u.id = n.professor_id
                WHERE UPPER(n.subject) = UPPER(?)
                ORDER BY n.created_at DESC
                """,
                (subject_filter,),
            ).fetchall()
        else:
            notes = db.execute(
                """
                SELECT n.*, u.name AS professor_name, u.id AS professor_id
                FROM notes n
                JOIN users u ON u.id = n.professor_id
                ORDER BY n.created_at DESC
                """
            ).fetchall()

        subjects = db.execute("SELECT DISTINCT subject FROM notes ORDER BY subject").fetchall()
        return render_page(
            "notes.html",
            page_title="Notes & Study Materials",
            mode="student",
            notes=notes,
            subject_filter=subject_filter,
            subjects=subjects,
            my_notes=None,
        )

    if user["role"] == "admin":
        my_notes = db.execute(
            """
            SELECT n.*, u.name AS professor_name
            FROM notes n
            JOIN users u ON u.id = n.professor_id
            ORDER BY n.created_at DESC
            """
        ).fetchall()
    else:
        my_notes = db.execute(
            """
            SELECT n.*, u.name AS professor_name
            FROM notes n
            JOIN users u ON u.id = n.professor_id
            WHERE n.professor_id = ?
            ORDER BY n.created_at DESC
            """,
            (user["id"],),
        ).fetchall()

    subjects = db.execute("SELECT DISTINCT subject FROM notes ORDER BY subject").fetchall()
    return render_page(
        "notes.html",
        page_title="Upload & Manage Notes",
        mode="manage",
        my_notes=my_notes,
        notes=None,
        subjects=subjects,
        subject_filter=subject_filter,
    )


@app.route("/notes/new", methods=["GET", "POST"])
@login_required
def upload_note():
    return redirect(url_for("notes_page"))


@app.route("/notes/<int:note_id>/rename", methods=["POST"])
@role_required("professor", "admin")
def rename_note(note_id: int):
    user = current_user()
    db = get_db()

    note = db.execute("SELECT id, professor_id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not note:
        abort(404)

    if user["role"] != "admin" and note["professor_id"] != user["id"]:
        abort(403)

    new_title = request.form.get("new_title", "").strip()
    if len(new_title) < 3:
        flash("Title must be at least 3 characters.", "danger")
        return redirect(url_for("notes_page"))

    db.execute("UPDATE notes SET title = ? WHERE id = ?", (new_title, note_id))
    db.commit()
    flash("Note title updated.", "success")
    return redirect(url_for("notes_page"))


@app.route("/notes/<int:note_id>/delete", methods=["POST"])
@role_required("professor", "admin")
def delete_note(note_id: int):
    user = current_user()
    db = get_db()

    note = db.execute("SELECT id, professor_id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not note:
        abort(404)

    if user["role"] != "admin" and note["professor_id"] != user["id"]:
        abort(403)

    db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    db.commit()
    flash("Note deleted.", "info")
    return redirect(url_for("notes_page"))


@app.route("/notes/<int:note_id>/download")
@login_required
def download_note(note_id: int):
    note = get_db().execute(
        """
        SELECT n.*, u.name AS professor_name
        FROM notes n
        JOIN users u ON u.id = n.professor_id
        WHERE n.id = ?
        """,
        (note_id,),
    ).fetchone()

    if not note:
        abort(404)

    if note["file_blob"]:
        return send_blob_download(note["file_name"] or f"note-{note_id}.pdf", note["file_blob"], note["file_mime"])

    body = (
        f"Title: {note['title']}\n"
        f"Subject: {note['subject']}\n"
        f"Professor: {note['professor_name']}\n"
        f"Created: {note['created_at']}\n"
        f"Important: {'Yes' if note['is_important'] else 'No'}\n\n"
        f"{note['content']}\n"
    )
    return send_text_download(note["title"], body)


@app.route("/follow/<int:professor_id>", methods=["POST"])
@role_required("student")
def follow_professor(professor_id: int):
    user = current_user()
    db = get_db()

    faculty = db.execute(
        "SELECT id, name, role FROM users WHERE id = ?", (professor_id,)
    ).fetchone()
    if not faculty or faculty["role"] != "professor":
        abort(404)

    cursor = db.execute(
        "INSERT OR IGNORE INTO follows (student_id, professor_id) VALUES (?, ?)",
        (user["id"], professor_id),
    )

    if cursor.rowcount:
        create_notification(
            professor_id,
            f"{user['name']} started following you.",
            url_for("user_profile", user_id=user["id"]),
        )
        flash(f"You are now following {faculty['name']}.", "success")
    else:
        flash(f"You already follow {faculty['name']}.", "info")

    db.commit()
    return redirect(request.referrer or url_for("faculty_directory"))


@app.route("/unfollow/<int:professor_id>", methods=["POST"])
@role_required("student")
def unfollow_professor(professor_id: int):
    user = current_user()
    db = get_db()

    db.execute(
        "DELETE FROM follows WHERE student_id = ? AND professor_id = ?",
        (user["id"], professor_id),
    )
    db.commit()
    flash("Unfollowed successfully.", "info")
    return redirect(request.referrer or url_for("faculty_directory"))


@app.route("/announcements", methods=["GET", "POST"])
@login_required
def announcements():
    user = current_user()
    db = get_db()

    can_manage = user["role"] in {"professor", "admin"}

    if request.method == "POST":
        if not can_manage:
            abort(403)

        title = request.form.get("title", "").strip()
        message = request.form.get("message", "").strip()
        announce_type = request.form.get("announce_type", "class").strip().lower()
        target_branch = request.form.get("target_branch", "ALL").strip().upper() or "ALL"
        send_email_flag = 1 if request.form.get("send_email") == "on" else 0

        if announce_type not in {"class", "university", "general"}:
            flash("Invalid announcement type.", "danger")
            return redirect(url_for("announcements"))

        if len(title) < 4 or len(message) < 10:
            flash("Title and message are required (min length 4 and 10).", "danger")
            return redirect(url_for("announcements"))

        cursor = db.execute(
            """
            INSERT INTO announcements (author_id, title, message, type, target_branch, send_email)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user["id"], title, message, announce_type, target_branch, send_email_flag),
        )
        announcement_id = cursor.lastrowid

        recipients = get_recipients_for_announcement(user["id"], target_branch, announce_type)
        for rec in recipients:
            create_notification(
                rec["id"],
                f"Announcement: {title}",
                url_for("announcements") + f"#ann-{announcement_id}",
            )

        sent_count = 0
        email_error = None
        if send_email_flag:
            for rec in recipients[:120]:
                ok, detail = send_email(
                    rec["email"],
                    f"University Announcement: {title}",
                    f"Hello {rec['name']},\n\n{message}\n\n- University Unified Portal",
                )
                if ok:
                    sent_count += 1
                else:
                    email_error = detail
                    break

        db.commit()

        if send_email_flag and email_error:
            flash(
                f"Announcement posted, but email dispatch stopped: {email_error}",
                "warning",
            )
        elif send_email_flag:
            flash(f"Announcement posted and emailed to {sent_count} users.", "success")
        else:
            flash("Announcement posted successfully.", "success")

        return redirect(url_for("announcements"))

    kind = request.args.get("kind", "all").strip().lower()
    params: list[Any] = []

    base_query = (
        "SELECT a.*, u.name AS author_name, u.role AS author_role "
        "FROM announcements a JOIN users u ON u.id = a.author_id"
    )

    where_parts = []
    if user["role"] == "student":
        where_parts.append(
            """
            (
                a.type = 'university'
                OR (
                    a.type = 'class'
                    AND EXISTS (
                        SELECT 1
                        FROM follows f
                        WHERE f.student_id = ?
                          AND f.professor_id = a.author_id
                    )
                )
                OR (
                    a.type = 'general'
                    AND (
                        UPPER(a.target_branch) = 'ALL'
                        OR UPPER(a.target_branch) = UPPER(COALESCE(?, ''))
                    )
                )
            )
            """
        )
        params.append(user["id"])
        params.append(user["branch"])

    if kind in {"class", "university", "general"}:
        where_parts.append("a.type = ?")
        params.append(kind)

    if where_parts:
        base_query += " WHERE " + " AND ".join(where_parts)

    base_query += " ORDER BY a.created_at DESC"
    announcements_rows = db.execute(base_query, params).fetchall()

    my_announcements = []
    if can_manage:
        my_announcements = db.execute(
            """
            SELECT * FROM announcements
            WHERE author_id = ?
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (user["id"],),
        ).fetchall()

    return render_page(
        "announcements.html",
        page_title="Announcements",
        announcements=announcements_rows,
        my_announcements=my_announcements,
        can_manage=can_manage,
        selected_kind=kind,
    )


@app.route("/announcements/<int:announcement_id>/delete", methods=["POST"])
@role_required("professor", "admin")
def delete_announcement(announcement_id: int):
    user = current_user()
    db = get_db()

    row = db.execute(
        "SELECT id, author_id FROM announcements WHERE id = ?",
        (announcement_id,),
    ).fetchone()
    if not row:
        abort(404)

    if user["role"] != "admin" and row["author_id"] != user["id"]:
        abort(403)

    db.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
    db.commit()
    flash("Announcement deleted.", "info")
    return redirect(url_for("announcements"))


@app.route("/question-papers", methods=["GET", "POST"])
@app.route("/previous-questions", methods=["GET", "POST"])
@login_required
def question_papers():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        if user["role"] not in {"professor", "admin"}:
            abort(403)

        subject = request.form.get("subject", "").strip()
        exam_year = request.form.get("exam_year", "").strip()
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        important_questions = request.form.get("important_questions", "").strip()

        file_name, file_blob, file_mime, file_error = read_uploaded_file("pdf_file", PDF_EXTENSIONS)
        if file_error:
            flash(file_error, "danger")
            return redirect(url_for("question_papers"))

        if not subject or not exam_year or not title:
            flash("Please fill subject, exam year, and title.", "danger")
            return redirect(url_for("question_papers"))

        if len(content) < 20 and not file_blob:
            flash("Add question content (min 20 chars) or upload a PDF.", "danger")
            return redirect(url_for("question_papers"))

        db.execute(
            """
            INSERT INTO previous_questions (
                subject, exam_year, title, content, important_questions, uploader_id,
                file_name, file_blob, file_mime
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject,
                exam_year,
                title,
                content,
                important_questions,
                user["id"],
                file_name,
                file_blob,
                file_mime,
            ),
        )

        student_rows = db.execute("SELECT id FROM users WHERE role = 'student'").fetchall()
        for s in student_rows:
            create_notification(
                s["id"],
                f"New question paper uploaded: {title}",
                url_for("question_papers"),
            )

        db.commit()
        flash("Question paper uploaded.", "success")
        return redirect(url_for("question_papers"))

    subject_filter = request.args.get("subject", "").strip()

    if subject_filter:
        rows = db.execute(
            """
            SELECT p.*, u.name AS uploader_name
            FROM previous_questions p
            JOIN users u ON u.id = p.uploader_id
            WHERE UPPER(p.subject) = UPPER(?)
            ORDER BY p.exam_year DESC, p.created_at DESC
            """,
            (subject_filter,),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT p.*, u.name AS uploader_name
            FROM previous_questions p
            JOIN users u ON u.id = p.uploader_id
            ORDER BY p.exam_year DESC, p.created_at DESC
            """
        ).fetchall()

    subjects = db.execute(
        "SELECT DISTINCT subject FROM previous_questions ORDER BY subject"
    ).fetchall()

    return render_page(
        "previous_questions.html",
        page_title="Question Papers",
        questions=rows,
        subject_filter=subject_filter,
        subjects=subjects,
    )


@app.route("/question-papers/<int:question_id>/download")
@app.route("/previous-questions/<int:question_id>/download")
@login_required
def download_previous_question(question_id: int):
    row = get_db().execute(
        """
        SELECT p.*, u.name AS uploader_name
        FROM previous_questions p
        JOIN users u ON u.id = p.uploader_id
        WHERE p.id = ?
        """,
        (question_id,),
    ).fetchone()

    if not row:
        abort(404)

    if row["file_blob"]:
        return send_blob_download(
            row["file_name"] or f"question-paper-{question_id}.pdf",
            row["file_blob"],
            row["file_mime"],
        )

    body = (
        f"Title: {row['title']}\n"
        f"Subject: {row['subject']}\n"
        f"Year: {row['exam_year']}\n"
        f"Uploaded by: {row['uploader_name']}\n"
        f"Created: {row['created_at']}\n\n"
        f"Important Questions:\n{row['important_questions'] or '-'}\n\n"
        f"{row['content']}\n"
    )
    return send_text_download(row["title"], body)


@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        status = request.form.get("status", "").strip().lower()
        class_date = request.form.get("class_date", "").strip() or str(date.today())
        send_email_flag = request.form.get("send_email") == "on"

        if status not in {"present", "absent"}:
            flash("Invalid attendance status.", "danger")
            return redirect(url_for("attendance"))

        if len(subject) < 2:
            flash("Please provide a valid subject.", "danger")
            return redirect(url_for("attendance"))

        if user["role"] in {"professor", "admin"}:
            student_id = request.form.get("student_id", type=int)
            if not student_id:
                flash("Please select a student.", "danger")
                return redirect(url_for("attendance"))
        else:
            student_id = user["id"]

        student = db.execute(
            "SELECT id, name, email FROM users WHERE id = ? AND role = 'student'",
            (student_id,),
        ).fetchone()
        if not student:
            flash("Student not found.", "danger")
            return redirect(url_for("attendance"))

        db.execute(
            """
            INSERT INTO attendance_entries (student_id, subject, status, class_date, marked_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (student_id, subject, status, class_date, user["id"]),
        )
        db.commit()

        summary_rows = attendance_summary(student_id)
        overall = overall_attendance(summary_rows)
        flashed_msg = f"Attendance marked for {student['name']}."

        if overall["percent"] < ATTENDANCE_THRESHOLD:
            create_notification(
                student_id,
                f"Attendance warning: {overall['percent']}% overall attendance.",
                url_for("attendance"),
            )
            db.commit()

            if send_email_flag:
                ok, detail = send_shortage_email(student, summary_rows)
                if ok:
                    flashed_msg += " Shortage email sent."
                else:
                    flashed_msg += f" Email not sent: {detail}"

        flash(flashed_msg, "success")
        if user["role"] in {"professor", "admin"}:
            return redirect(url_for("attendance", student_id=student_id))
        return redirect(url_for("attendance"))

    if user["role"] == "student":
        rows = attendance_summary(user["id"])
        overall = overall_attendance(rows)
        return render_page(
            "attendance.html",
            page_title="Attendance Tracker",
            mode="student",
            rows=rows,
            overall=overall,
            students=None,
            selected_student=None,
        )

    students = db.execute(
        "SELECT id, name, university_id, email, branch FROM users WHERE role = 'student' ORDER BY name"
    ).fetchall()

    selected_student_id = request.args.get("student_id", type=int)
    if not selected_student_id and students:
        selected_student_id = students[0]["id"]

    selected_student = None
    rows: list[dict[str, Any]] = []
    overall = {"present": 0, "total": 0, "percent": 0}

    if selected_student_id:
        selected_student = db.execute(
            "SELECT id, name, email, university_id, branch FROM users WHERE id = ?",
            (selected_student_id,),
        ).fetchone()
        if selected_student:
            rows = attendance_summary(selected_student_id)
            overall = overall_attendance(rows)

    return render_page(
        "attendance.html",
        page_title="Attendance Tracker",
        mode="manage",
        rows=rows,
        overall=overall,
        students=students,
        selected_student=selected_student,
    )


@app.route("/attendance/email-alert/<int:student_id>", methods=["POST"])
@role_required("professor", "admin")
def send_attendance_alert(student_id: int):
    db = get_db()
    student = db.execute(
        "SELECT id, name, email FROM users WHERE id = ? AND role = 'student'",
        (student_id,),
    ).fetchone()

    if not student:
        abort(404)

    summary_rows = attendance_summary(student_id)
    ok, detail = send_shortage_email(student, summary_rows)
    if ok:
        create_notification(
            student_id,
            "Attendance shortage email has been sent to your registered email.",
            url_for("attendance"),
        )
        db.commit()
        flash("Attendance shortage email sent.", "success")
    else:
        flash(detail, "warning")

    return redirect(url_for("attendance", student_id=student_id))


@app.route("/timetables", methods=["GET", "POST"])
@login_required
def timetables():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        if user["role"] != "admin":
            abort(403)

        branch = request.form.get("branch", "").strip().upper()
        title = request.form.get("title", "").strip()

        file_name, file_blob, file_mime, file_error = read_uploaded_file(
            "timetable_file",
            TIMETABLE_EXTENSIONS,
        )
        if file_error:
            flash(file_error, "danger")
            return redirect(url_for("timetables"))

        if not branch or not title or not file_blob:
            flash("Branch, title, and file are required.", "danger")
            return redirect(url_for("timetables"))

        db.execute(
            """
            INSERT INTO timetables (branch, title, file_name, file_blob, file_mime, uploader_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (branch, title, file_name, file_blob, file_mime, user["id"]),
        )

        recipients = db.execute(
            "SELECT id FROM users WHERE role IN ('student', 'professor') AND (UPPER(COALESCE(branch, '')) = ? OR role = 'professor')",
            (branch,),
        ).fetchall()
        for rec in recipients:
            create_notification(rec["id"], f"New timetable uploaded for {branch}.", url_for("timetables"))

        db.commit()
        flash("Timetable uploaded.", "success")
        return redirect(url_for("timetables", branch=branch))

    branch_filter = request.args.get("branch", "").strip().upper()
    if not branch_filter and user["role"] == "student" and user["branch"]:
        branch_filter = user["branch"].upper()

    if branch_filter:
        rows = db.execute(
            """
            SELECT t.*, u.name AS uploader_name
            FROM timetables t
            JOIN users u ON u.id = t.uploader_id
            WHERE UPPER(t.branch) = ? OR UPPER(t.branch) = 'ALL'
            ORDER BY t.created_at DESC
            """,
            (branch_filter,),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT t.*, u.name AS uploader_name
            FROM timetables t
            JOIN users u ON u.id = t.uploader_id
            ORDER BY t.created_at DESC
            """
        ).fetchall()

    branches = db.execute("SELECT DISTINCT branch FROM timetables ORDER BY branch").fetchall()

    return render_page(
        "timetables.html",
        page_title="Timetables",
        timetables=rows,
        branches=branches,
        branch_filter=branch_filter,
    )


@app.route("/timetables/<int:timetable_id>/download")
@login_required
def download_timetable(timetable_id: int):
    row = get_db().execute(
        "SELECT * FROM timetables WHERE id = ?",
        (timetable_id,),
    ).fetchone()

    if not row:
        abort(404)

    return send_blob_download(row["file_name"], row["file_blob"], row["file_mime"])


@app.route("/faculty")
@login_required
def faculty_directory():
    user = current_user()
    db = get_db()

    query = request.args.get("q", "").strip()

    if user["role"] == "student":
        sql = """
            SELECT u.*,
                   CASE WHEN f.student_id IS NULL THEN 0 ELSE 1 END AS is_following,
                   (SELECT COUNT(*) FROM notes n WHERE n.professor_id = u.id) AS note_count,
                   (SELECT COUNT(*) FROM previous_questions p WHERE p.uploader_id = u.id) AS paper_count
            FROM users u
            LEFT JOIN follows f ON f.professor_id = u.id AND f.student_id = ?
            WHERE u.role IN ('professor', 'admin')
        """
        params: list[Any] = [user["id"]]
    else:
        sql = """
            SELECT u.*,
                   0 AS is_following,
                   (SELECT COUNT(*) FROM notes n WHERE n.professor_id = u.id) AS note_count,
                   (SELECT COUNT(*) FROM previous_questions p WHERE p.uploader_id = u.id) AS paper_count
            FROM users u
            WHERE u.role IN ('professor', 'admin')
        """
        params = []

    if query:
        sql += " AND (LOWER(u.name) LIKE ? OR LOWER(COALESCE(u.subject, '')) LIKE ? OR LOWER(COALESCE(u.email, '')) LIKE ?)"
        like = f"%{query.lower()}%"
        params.extend([like, like, like])

    sql += " ORDER BY CASE WHEN u.role = 'professor' THEN 1 ELSE 2 END, u.name"

    faculty_rows = db.execute(sql, params).fetchall()
    return render_page(
        "faculty.html",
        page_title="Faculty Directory",
        faculty_rows=faculty_rows,
        query=query,
    )


@app.route("/search/professor-suggestions")
@login_required
def professor_suggestions():
    query = request.args.get("q", "").strip().lower()
    if len(query) < 1:
        return jsonify({"items": []})

    db = get_db()
    rows = db.execute(
        """
        SELECT id, name, role, designation, subject, email, photo_url, photo_blob
        FROM users
        WHERE role IN ('professor', 'admin')
          AND (
                LOWER(name) LIKE ?
                OR LOWER(COALESCE(subject, '')) LIKE ?
                OR LOWER(email) LIKE ?
              )
        ORDER BY CASE WHEN role = 'professor' THEN 1 ELSE 2 END, name
        LIMIT 8
        """,
        (f"%{query}%", f"%{query}%", f"%{query}%"),
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "name": row["name"],
                "role": row["role"],
                "designation": row["designation"] or ("Professor" if row["role"] == "professor" else "Admin"),
                "subject": row["subject"] or "",
                "avatar": (
                    url_for("user_photo", user_id=row["id"])
                    if row["photo_blob"]
                    else (row["photo_url"] or "")
                ),
            }
        )

    return jsonify({"items": items})


@app.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        db.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ?",
            (user["id"],),
        )
        db.commit()
        flash("All notifications marked as read.", "success")
        return redirect(url_for("notifications"))

    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    return render_page("notifications.html", page_title="Notifications", notifications=rows)


@app.route("/exam-ready", methods=["GET", "POST"])
@login_required
def exam_ready():
    user = current_user()
    db = get_db()

    source_notes = db.execute(
        """
        SELECT n.id, n.title, n.subject, n.content, u.name AS professor_name
        FROM notes n
        JOIN users u ON u.id = n.professor_id
        ORDER BY n.created_at DESC
        LIMIT 100
        """
    ).fetchall()

    generated_questions: list[str] = []

    if request.method == "POST":
        source_type = request.form.get("source_type", "syllabus")
        source_ref_id = None
        source_text = ""

        if source_type == "note":
            note_id = request.form.get("note_id", type=int)
            note = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if not note:
                flash("Selected note not found.", "danger")
                return render_page(
                    "exam_ready.html",
                    page_title="Exam Ready Questions",
                    notes=source_notes,
                    generated_questions=generated_questions,
                )

            source_ref_id = note["id"]
            source_text = note["content"] or f"{note['title']} {note['subject']} core concepts and exam answers"
        else:
            source_text = request.form.get("syllabus_text", "").strip()

        generated_questions = build_exam_questions(source_text)
        if not generated_questions:
            flash("Please provide enough content to generate questions.", "danger")
            return render_page(
                "exam_ready.html",
                page_title="Exam Ready Questions",
                notes=source_notes,
                generated_questions=[],
            )

        if user["role"] == "student":
            db.execute(
                """
                INSERT INTO generated_questions (student_id, source_type, source_ref_id, source_text, questions)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    source_type,
                    source_ref_id,
                    source_text[:1200],
                    "\n".join(f"{i + 1}. {q}" for i, q in enumerate(generated_questions)),
                ),
            )
            db.commit()

    return render_page(
        "exam_ready.html",
        page_title="Exam Ready Questions",
        notes=source_notes,
        generated_questions=generated_questions,
    )


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", user["name"]).strip()
        phone = request.form.get("phone", "").strip()
        photo_url = request.form.get("photo_url", "").strip()
        bio = request.form.get("bio", "").strip()
        branch = request.form.get("branch", "").strip().upper()
        study_program = request.form.get("study_program", "").strip()
        open_to_collab = 1 if request.form.get("open_to_collab") == "on" else 0
        subject = request.form.get("subject", "").strip()
        free_hours = request.form.get("free_hours", "").strip()
        designation = request.form.get("designation", "").strip()
        _photo_name, photo_blob, photo_mime, photo_error = read_uploaded_file(
            "photo_file",
            IMAGE_EXTENSIONS,
        )

        if photo_error:
            flash(photo_error, "danger")
            return redirect(url_for("profile"))

        if len(name) < 2:
            flash("Name should be at least 2 characters.", "danger")
            return redirect(url_for("profile"))

        next_photo_blob = user["photo_blob"]
        next_photo_mime = user["photo_mime"]
        if photo_blob:
            next_photo_blob = photo_blob
            next_photo_mime = photo_mime

        db.execute(
            """
            UPDATE users
            SET name = ?, phone = ?, photo_url = ?, bio = ?, branch = ?, study_program = ?,
                open_to_collab = ?, subject = ?, free_hours = ?, designation = ?,
                photo_blob = ?, photo_mime = ?
            WHERE id = ?
            """,
            (
                name,
                phone,
                photo_url,
                bio,
                branch,
                study_program,
                open_to_collab,
                subject,
                free_hours,
                designation,
                next_photo_blob,
                next_photo_mime,
                user["id"],
            ),
        )
        db.commit()
        g.pop("current_user", None)
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    return render_page(
        "profile.html",
        page_title="My Profile",
        profile_user=user,
        own_profile=True,
        notes=[],
        papers=[],
        is_following=False,
        timetable=None,
    )


@app.route("/user/<int:user_id>")
@login_required
def user_profile(user_id: int):
    db = get_db()
    viewer = current_user()

    profile_user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not profile_user:
        abort(404)

    notes = []
    papers = []
    timetable = None
    is_following = False

    if profile_user["role"] in {"professor", "admin"}:
        notes = db.execute(
            """
            SELECT * FROM notes
            WHERE professor_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (profile_user["id"],),
        ).fetchall()

        papers = db.execute(
            """
            SELECT * FROM previous_questions
            WHERE uploader_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (profile_user["id"],),
        ).fetchall()

        if profile_user["branch"]:
            timetable = db.execute(
                """
                SELECT * FROM timetables
                WHERE UPPER(branch) = UPPER(?) OR UPPER(branch) = 'ALL'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (profile_user["branch"],),
            ).fetchone()

        if viewer["role"] == "student" and profile_user["role"] == "professor":
            row = db.execute(
                "SELECT 1 FROM follows WHERE student_id = ? AND professor_id = ?",
                (viewer["id"], profile_user["id"]),
            ).fetchone()
            is_following = bool(row)

    return render_page(
        "profile.html",
        page_title="Faculty Profile",
        profile_user=profile_user,
        own_profile=(viewer["id"] == profile_user["id"]),
        notes=notes,
        papers=papers,
        is_following=is_following,
        timetable=timetable,
    )


@app.route("/user/<int:user_id>/photo")
@login_required
def user_photo(user_id: int):
    row = get_db().execute(
        "SELECT photo_blob, photo_mime FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row or not row["photo_blob"]:
        abort(404)

    return send_file(
        io.BytesIO(row["photo_blob"]),
        mimetype=row["photo_mime"] or "image/jpeg",
        as_attachment=False,
        download_name=f"user-{user_id}-photo",
    )


@app.route("/admin/user/<int:user_id>/role", methods=["POST"])
@role_required("admin")
def change_role(user_id: int):
    db = get_db()
    viewer = current_user()
    new_role = request.form.get("new_role", "").strip().lower()

    if new_role not in ROLE_RANK:
        flash("Invalid role selected.", "danger")
        return redirect(url_for("dashboard"))

    if user_id == viewer["id"] and new_role != "admin":
        flash("Admin cannot demote own account.", "danger")
        return redirect(url_for("dashboard"))

    university_id = generate_university_id(new_role, db)
    db.execute(
        "UPDATE users SET role = ?, university_id = ? WHERE id = ?",
        (new_role, university_id, user_id),
    )
    db.commit()
    flash("User role updated.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_user(user_id: int):
    viewer = current_user()
    db = get_db()

    target = db.execute(
        "SELECT id, name, role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not target:
        abort(404)

    if target["id"] == viewer["id"]:
        flash("You cannot delete your own admin account.", "danger")
        return redirect(url_for("dashboard"))

    if target["role"] not in {"professor", "student"}:
        flash("Only professor and student accounts can be deleted from this panel.", "warning")
        return redirect(url_for("dashboard"))

    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    flash(f"Deleted account: {target['name']}", "info")
    return redirect(url_for("dashboard"))


@app.route("/admin/note/<int:note_id>/delete", methods=["POST"])
@role_required("admin")
def delete_note_admin(note_id: int):
    return delete_note(note_id)


@app.errorhandler(403)
def forbidden(_error):
    return render_page("error.html", code=403, message="You do not have permission for this page."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_page("error.html", code=404, message="The page you requested was not found."), 404


@app.errorhandler(413)
def too_large(_error):
    return render_page(
        "error.html",
        code=413,
        message=f"Request too large. Max upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
    ), 413


with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=True)
