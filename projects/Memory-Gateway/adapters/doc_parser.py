"""文档解析 + 智能分块"""
from pathlib import Path
import traceback


def _open_pdf(path):
    """兼容 pymupdf 新 API 和 fitz 旧 API"""
    try:
        import pymupdf
        return pymupdf.open(str(path))
    except ImportError:
        import fitz
        return fitz.open(str(path))


def parse_document(file_path: str) -> str:
    """解析 PDF/Word/Markdown/TXT/CSV，返回纯文本"""
    p = Path(file_path)
    if not p.exists():
        return f"[文件不存在: {file_path}]"
    ext = p.suffix.lower()

    try:
        # PDF
        if ext == ".pdf":
            doc = _open_pdf(p)
            pages = []
            for i, page in enumerate(doc):
                text = page.get_text("text")
                if text.strip():
                    pages.append(f"<!-- 第 {i+1} 页 -->\n{text}")
            doc.close()
            return "\n\n".join(pages)

        # Word
        elif ext in (".docx", ".doc"):
            import docx
            d = docx.Document(str(p))
            parts = []
            for para in d.paragraphs:
                if para.text.strip():
                    parts.append(para.text)
            for i, table in enumerate(d.tables):
                rows = []
                for row in table.rows:
                    rows.append(" | ".join(c.text.strip() for c in row.cells))
                if rows:
                    parts.append(f"\n<!-- 表格 {i+1} -->\n" + "\n".join(rows))
            return "\n\n".join(parts)

        # Markdown / TXT / 其他文本
        elif ext in (".md", ".markdown", ".txt", ".log", ".json", ".yaml", ".yml"):
            return p.read_text(encoding="utf-8", errors="ignore")

        # CSV
        elif ext == ".csv":
            import csv
            lines = []
            with open(p, encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                for row in reader:
                    lines.append(" | ".join(row))
            return "\n".join(lines)

        # 其他：尝试文本读取
        else:
            try:
                return p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return f"[不支持的文件类型: {ext}]"

    except Exception as e:
        print(f"   [doc-parser] 解析失败 {file_path}: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return f"[解析失败: {type(e).__name__}: {e}]"


def smart_chunk(text: str, chunk_size: int = 384, overlap: int = 64) -> list:
    """按段落分块 + 重叠"""
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    cur = ""
    for p in paras:
        if len(p) > chunk_size:
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(p), chunk_size - overlap):
                seg = p[i:i + chunk_size]
                if seg.strip():
                    chunks.append(seg)
            continue

        if len(cur) + len(p) + 2 <= chunk_size:
            cur = (cur + "\n\n" + p) if cur else p
        else:
            if cur:
                chunks.append(cur)
                tail = cur[-overlap:] if overlap and len(cur) > overlap else ""
                cur = (tail + "\n\n" + p) if tail else p
            else:
                cur = p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c.strip()) > 20]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        text = parse_document(sys.argv[1])
        print(f"解析长度: {len(text)}")
        chunks = smart_chunk(text)
        print(f"分块数: {len(chunks)}")
        for i, c in enumerate(chunks[:3]):
            print(f"  块 {i}: {len(c)} 字 | {c[:60]}...")
