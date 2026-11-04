import hashlib
import json
import os
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import psycopg
from docx import Document
from openpyxl import load_workbook
from psycopg.rows import dict_row
from pypdf import PdfReader
from pptx import Presentation
import xlrd


ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml"}


def load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()


def connect():
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"), port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "postgres"), password=os.environ.get("PGPASSWORD", ""),
        dbname=os.environ.get("PGDATABASE", "energy_ia"), row_factory=dict_row,
    )


def _ollama(path, payload):
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}{path}", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=int(os.environ.get("OLLAMA_TIMEOUT", "600"))) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"No fue posible conectar con Ollama en {base_url}: {error}") from error


def _chunks(text, size=1200, overlap=200):
    clean = " ".join(text.split())
    return [clean[start:start + size] for start in range(0, len(clean), size - overlap) if clean[start:start + size].strip()]


def _vector(values):
    return "[" + ",".join(f"{float(value):.9g}" for value in values) + "]"


def ingest_pages(document_name, pages, raw=None):
    records = [(page, index, chunk) for page, text in pages for index, chunk in enumerate(_chunks(text))]
    if not records:
        raise ValueError("El documento no contiene texto indexable.")
    source = raw if raw is not None else "\n".join(text for _, text in pages).encode("utf-8")
    digest = hashlib.sha256(source).hexdigest()
    embeddings = _ollama("/api/embed", {
        "model": os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        "input": [record[2] for record in records],
    })["embeddings"]
    if len(embeddings) != len(records):
        raise RuntimeError("Ollama no devolvió una representación vectorial para cada fragmento.")
    with connect() as db:
        db.execute("DELETE FROM public.sop_chunks WHERE document_name=%s", (document_name,))
        for (page, index, content), embedding in zip(records, embeddings):
            db.execute(
                """INSERT INTO public.sop_chunks(document_hash,document_name,page,chunk_index,content,embedding)
                VALUES(%s,%s,%s,%s,%s,%s::vector)""",
                (digest, document_name, page, index, content, _vector(embedding)),
            )
    return len(records)


def ingest_text(document_name, text):
    return ingest_pages(document_name, [(1, text)], text.encode("utf-8"))


def extract_document(filename, raw):
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError(f"Tipo de archivo no compatible: {extension or 'sin extensión'}")
    stream = BytesIO(raw)
    if extension == ".pdf":
        return [(index + 1, page.extract_text() or "") for index, page in enumerate(PdfReader(stream).pages)]
    if extension == ".docx":
        return [(1, "\n".join(paragraph.text for paragraph in Document(stream).paragraphs))]
    if extension == ".xlsx":
        workbook = load_workbook(stream, read_only=True, data_only=True)
        return [(index + 1, f"Hoja: {sheet.title}\n" + "\n".join(" | ".join(str(value) for value in row if value is not None) for row in sheet.iter_rows(values_only=True))) for index, sheet in enumerate(workbook.worksheets)]
    if extension == ".xls":
        workbook = xlrd.open_workbook(file_contents=raw)
        return [(index + 1, f"Hoja: {sheet.name}\n" + "\n".join(" | ".join(str(sheet.cell_value(row, column)) for column in range(sheet.ncols)) for row in range(sheet.nrows))) for index, sheet in enumerate(workbook.sheets())]
    if extension == ".pptx":
        presentation = Presentation(stream)
        return [(index + 1, "\n".join(shape.text for shape in slide.shapes if hasattr(shape, "text"))) for index, slide in enumerate(presentation.slides)]
    return [(1, raw.decode("utf-8", errors="replace"))]


def ingest_document(filename, raw):
    return ingest_pages(filename, extract_document(filename, raw), raw)


def list_documents():
    with connect() as db:
        return db.execute(
            """SELECT document_name,COUNT(*) chunks,MIN(created_at) indexed_at
            FROM public.sop_chunks GROUP BY document_name ORDER BY document_name"""
        ).fetchall()


def delete_document(document_name):
    with connect() as db:
        rows = db.execute(
            "DELETE FROM public.sop_chunks WHERE document_name=%s RETURNING id", (document_name,)
        ).fetchall()
    return len(rows)


def retrieve(question, limit=5):
    embedding = _ollama("/api/embed", {
        "model": os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"), "input": [question],
    })["embeddings"][0]
    vector = _vector(embedding)
    with connect() as db:
        return db.execute(
            """SELECT document_name,page,content,embedding <=> %s::vector distance
            FROM public.sop_chunks ORDER BY embedding <=> %s::vector LIMIT %s""",
            (vector, vector, limit),
        ).fetchall()


def answer_rag(question):
    chunks = retrieve(question)
    if not chunks:
        raise ValueError("No hay documentación Energy indexada.")
    evidence, sources = [], []
    for chunk in chunks:
        label = f"{chunk['document_name']} · página {chunk['page']}"
        evidence.append(f"[{label}]\n{chunk['content']}")
        if label not in sources:
            sources.append(label)
    prompt = f"""Responde en español usando exclusivamente la evidencia recuperada. Distingue hechos documentales de recomendaciones y no inventes valores. Relaciona la respuesta con el activo, el rango de riesgo y las variables dominantes cuando estén presentes. Prioriza parada segura, reducción controlada de carga, LOTO y validación con instrumentos calibrados. Si falta evidencia, indícalo. Cita las fuentes entre corchetes. Máximo 260 palabras.

EVIDENCIA:
{chr(10).join(evidence)}

PREGUNTA: {question}"""
    response = _ollama("/api/chat", {
        "model": os.environ.get("OLLAMA_CHAT_MODEL", "llama3.1:8b"),
        "messages": [
            {"role": "system", "content": "Eres un copiloto documental de operación, mantenimiento y confiabilidad para generación térmica."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 4096, "num_predict": 420},
    })
    return response["message"]["content"], sources
