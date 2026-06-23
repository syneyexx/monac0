from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

from monaco_ai.config import load_settings, ensure_dirs
from monaco_ai.db import MonacoDB
from monaco_ai.utils import chunk_text, sha256_bytes

ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".py", ".json", ".csv", ".html", ".css", ".js"}:
        return path.read_text(errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception as e:
            return f"[PDF parse error: {e}]"
    if suffix == ".docx":
        try:
            import docx
            d = docx.Document(str(path))
            return "\n".join(p.text for p in d.paragraphs)
        except Exception as e:
            return f"[DOCX parse error: {e}]"
    return ""


def import_file(db: MonacoDB, path: Path, topic: str | None = None) -> int:
    data = path.read_bytes()
    file_hash = sha256_bytes(data)
    text = read_text(path)
    if not text or text.startswith("["):
        return 0
    topic = topic or path.parent.name or "documents"
    source_id = db.add_source("document", path.name, str(path), topic, {"sha256": file_hash, "size": len(data), "suffix": path.suffix}, reliability=0.65)
    count = 0
    for idx, chunk in enumerate(chunk_text(text, max_chars=3000, overlap=300)):
        if db.add_chunk(source_id, topic, path.name, str(path), idx, chunk, quality_score=0.65):
            count += 1
    return count


def extract_zip(zip_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                continue
            if info.is_dir():
                continue
            target = out_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
            files.append(target)
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--topic", default=None)
    args = ap.parse_args()
    settings = load_settings(ROOT)
    ensure_dirs(settings)
    db = MonacoDB(settings.db_path)
    path = Path(args.path)
    if path.suffix.lower() == ".zip":
        files = extract_zip(path, settings.root / "data" / "downloads" / path.stem)
    elif path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
    else:
        files = [path]
    total = 0
    for f in files:
        c = import_file(db, f, args.topic)
        if c:
            print(f"imported {f}: {c} chunks")
            total += c
    print(f"DONE. chunks={total}")


if __name__ == "__main__":
    main()
