"""Database-layer tests on a throwaway SQLite file."""
import json

from backend.database import (delete_extractions, get_db,
                              index_extraction_for_search, sha256_bytes,
                              sha256_file)

DOC_ID = "sha256:" + "a" * 64


def _insert_document(conn, doc_id=DOC_ID, filename="test.pdf"):
    conn.execute(
        "INSERT INTO documents (document_id, filename, source, file_path) VALUES (?, ?, 'upload', '/tmp/x.pdf')",
        (doc_id, filename))


def _insert_extraction(conn, doc_id=DOC_ID, status="success"):
    conn.execute(
        """INSERT INTO extractions (document_id, status, extracted_at, table_count, result_json)
           VALUES (?, ?, '2026-01-01T00:00:00Z', 1, ?)""",
        (doc_id, status, json.dumps({"document_id": doc_id, "tables": []})))


def test_insert_and_fetch(db_path):
    conn = get_db(db_path)
    _insert_document(conn)
    _insert_extraction(conn)
    conn.commit()
    row = conn.execute("SELECT * FROM extractions WHERE document_id = ?", (DOC_ID,)).fetchone()
    assert row["status"] == "success"
    conn.close()


def test_delete_document_cascades_extraction(db_path):
    conn = get_db(db_path)
    _insert_document(conn)
    _insert_extraction(conn)
    conn.commit()
    conn.execute("DELETE FROM documents WHERE document_id = ?", (DOC_ID,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0] == 0
    conn.close()


def test_fts_search_and_delete(db_path):
    conn = get_db(db_path)
    _insert_document(conn)
    tables = [{"headers": ["Item", "Revenue"], "rows": [["Aramco", "12,345"]]}]
    index_extraction_for_search(conn, DOC_ID, "aramco_q1.pdf", tables)
    conn.commit()

    hit = conn.execute(
        "SELECT document_id FROM table_search WHERE table_search MATCH ?",
        ('"aramco"',)).fetchall()
    assert [r["document_id"] for r in hit] == [DOC_ID]

    hit = conn.execute(
        "SELECT document_id FROM table_search WHERE table_search MATCH ?",
        ('"revenue"',)).fetchall()
    assert len(hit) == 1

    miss = conn.execute(
        "SELECT document_id FROM table_search WHERE table_search MATCH ?",
        ('"nonexistent"',)).fetchall()
    assert miss == []

    _insert_extraction(conn)
    conn.commit()
    deleted = delete_extractions(conn, [DOC_ID])
    conn.commit()
    assert deleted == 1
    assert conn.execute("SELECT COUNT(*) FROM table_search").fetchone()[0] == 0
    conn.close()


def test_reindex_replaces_fts_rows(db_path):
    conn = get_db(db_path)
    _insert_document(conn)
    index_extraction_for_search(conn, DOC_ID, "f.pdf",
                                [{"headers": ["Old"], "rows": []}])
    index_extraction_for_search(conn, DOC_ID, "f.pdf",
                                [{"headers": ["New"], "rows": []}])
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM table_search").fetchone()[0] == 1
    hit = conn.execute("SELECT * FROM table_search WHERE table_search MATCH '\"new\"'").fetchall()
    assert len(hit) == 1
    conn.close()


def test_sha256_identity(tmp_path):
    data = b"%PDF-1.4 fake"
    f1 = tmp_path / "name_one.pdf"
    f2 = tmp_path / "totally_different_name.pdf"
    f1.write_bytes(data)
    f2.write_bytes(data)
    assert sha256_file(f1) == sha256_file(f2) == sha256_bytes(data)
    assert sha256_file(f1).startswith("sha256:")


def test_extraction_upsert_is_latest_only(db_path):
    conn = get_db(db_path)
    _insert_document(conn)
    _insert_extraction(conn, status="failed")
    conn.execute(
        """INSERT INTO extractions (document_id, status, extracted_at, table_count, result_json)
           VALUES (?, 'success', '2026-01-02T00:00:00Z', 3, '{}')
           ON CONFLICT(document_id) DO UPDATE SET
               status=excluded.status, extracted_at=excluded.extracted_at,
               table_count=excluded.table_count, result_json=excluded.result_json""",
        (DOC_ID,))
    conn.commit()
    rows = conn.execute("SELECT * FROM extractions").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["table_count"] == 3
    conn.close()
