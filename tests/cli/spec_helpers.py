"""Shared by the spec and feature verb tests: a real, tiny PDF, and a file on disk.

A plain module rather than fixtures, because ``tiny_pdf`` takes arguments — the page
texts — and a fixture cannot.
"""


def tiny_pdf(*page_texts: str) -> bytes:
    """A minimal but real PDF, one page per string — built by hand so these tests need
    no Qt and no PDF writer, only the reader under test."""
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(len(page_texts))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, text in zip(page_ids, page_texts, strict=True):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def source(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return str(path)
