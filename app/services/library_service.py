"""Library service: persists every inspected drawing so it can be recalled later.

Each record stores the original file reference, the vision evaluation
(title block + detected parameters), the synthesized KCL, the DFMA analysis
and the Zoo Engine verification result. Records live in a local SQLite file
(library.db) which is gitignored.
"""

import os
import json
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES_DIR = os.path.join(BASE_DIR, "library", "samples")
DB_PATH = os.path.join(BASE_DIR, "library.db")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS drawings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            file_name TEXT,
            file_url TEXT,
            source TEXT DEFAULT 'upload',
            title_block TEXT,
            detected_parameters TEXT,
            kcl_code TEXT,
            dfma_analysis TEXT,
            zoo_verification TEXT,
            created_at TEXT
        )"""
    )
    return conn


def save_record(data: dict) -> int:
    """Insert or update a drawing record. `data['id']` (if present) triggers update."""
    title_block = data.get("title_block")
    detected = data.get("detected_parameters")
    conn = _connect()
    try:
        if data.get("id"):
            conn.execute(
                """UPDATE drawings SET title=?, file_name=?, file_url=?, source=?,
                   title_block=?, detected_parameters=?, kcl_code=?, dfma_analysis=?,
                   zoo_verification=?, created_at=? WHERE id=?""",
                (
                    data.get("title", "Unnamed"),
                    data.get("file_name"),
                    data.get("file_url"),
                    data.get("source", "upload"),
                    json.dumps(title_block) if title_block is not None else None,
                    json.dumps(detected) if detected is not None else None,
                    data.get("kcl_code"),
                    json.dumps(data.get("dfma_analysis")) if data.get("dfma_analysis") is not None else None,
                    json.dumps(data.get("zoo_verification")) if data.get("zoo_verification") is not None else None,
                    _now(),
                    data["id"],
                ),
            )
            rid = data["id"]
        else:
            cur = conn.execute(
                """INSERT INTO drawings
                   (title, file_name, file_url, source, title_block, detected_parameters,
                    kcl_code, dfma_analysis, zoo_verification, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("title", "Unnamed"),
                    data.get("file_name"),
                    data.get("file_url"),
                    data.get("source", "upload"),
                    json.dumps(title_block) if title_block is not None else None,
                    json.dumps(detected) if detected is not None else None,
                    data.get("kcl_code"),
                    json.dumps(data.get("dfma_analysis")) if data.get("dfma_analysis") is not None else None,
                    json.dumps(data.get("zoo_verification")) if data.get("zoo_verification") is not None else None,
                    _now(),
                ),
            )
            rid = cur.lastrowid
        conn.commit()
        return rid
    finally:
        conn.close()


def list_records(limit: int = 100) -> list:
    """Return a lightweight list (no big blobs) of saved drawings, newest first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, title, file_name, file_url, source, created_at "
            "FROM drawings ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_record(record_id: int) -> dict | None:
    """Return a full record (with all JSON blobs parsed) or None."""
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM drawings WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("title_block", "detected_parameters", "dfma_analysis", "zoo_verification"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        return d
    finally:
        conn.close()


def import_samples() -> int:
    """Scan library/samples for image/PDF files not yet imported and add them.

    Returns the number of newly imported sample records.
    """
    if not os.path.isdir(SAMPLES_DIR):
        return 0
    existing = {r.get("file_name") for r in list_records(limit=10000)}
    imported = 0
    for name in sorted(os.listdir(SAMPLES_DIR)):
        if name.startswith(".") or name in existing:
            continue
        lower = name.lower()
        if not (lower.endswith((".png", ".jpg", ".jpeg", ".pdf", ".webp", ".bmp"))):
            continue
        rec = {
            "title": os.path.splitext(name)[0],
            "file_name": name,
            "file_url": f"/library/samples/{name}",
            "source": "sample",
        }
        save_record(rec)
        imported += 1
    return imported
