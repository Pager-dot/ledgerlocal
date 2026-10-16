"""Turn whatever the user dropped in a folder into something a model can read."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ledgerlocal.errors import RenderError

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".heic"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".eml", ".html", ".htm"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED = IMAGE_SUFFIXES | TEXT_SUFFIXES | PDF_SUFFIXES

MAX_TEXT_CHARS = 24_000


@dataclass
class Rendered:
    """A document prepared for the model: either page images or plain text."""

    path: Path
    digest: str
    images: list[bytes]
    text: str
    page_count: int

    @property
    def is_visual(self) -> bool:
        return bool(self.images)


def digest_file(path: Path) -> str:
    """Content hash, used to make re-ingesting the same folder a no-op."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED


def render(path: Path, *, max_pages: int = 4, dpi: int = 180) -> Rendered:
    suffix = path.suffix.lower()
    if not path.is_file():
        raise RenderError(f"{path} is not a file")
    if suffix not in SUPPORTED:
        raise RenderError(f"unsupported file type {suffix!r} ({path.name})")

    digest = digest_file(path)

    if suffix in TEXT_SUFFIXES:
        text = path.read_text("utf-8", errors="replace")[:MAX_TEXT_CHARS]
        if not text.strip():
            raise RenderError(f"{path.name} is empty")
        return Rendered(path=path, digest=digest, images=[], text=text, page_count=1)

    if suffix in IMAGE_SUFFIXES:
        return Rendered(
            path=path,
            digest=digest,
            images=[_normalise_image(path.read_bytes())],
            text="",
            page_count=1,
        )

    return _render_pdf(path, digest, max_pages=max_pages, dpi=dpi)


def _render_pdf(path: Path, digest: str, *, max_pages: int, dpi: int) -> Rendered:
    try:
        import pymupdf  # type: ignore
    except ImportError:
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError as exc:
            raise RenderError(
                "reading PDFs needs PyMuPDF. Install it with `pip install 'ledgerlocal[pdf]'`, "
                "or convert the PDF to a PNG first."
            ) from exc

    try:
        document = pymupdf.open(path)
    except Exception as exc:  # pragma: no cover - depends on the file
        raise RenderError(f"could not open {path.name}: {exc}") from exc

    with document:
        total = document.page_count
        if total == 0:
            raise RenderError(f"{path.name} has no pages")

        # If the PDF already carries a text layer (most emailed invoices do),
        # use it: it is exact, and it lets the smaller text-only model do the
        # job in a fraction of the time a vision pass would take.
        embedded = "\n".join(
            document[index].get_text("text") for index in range(min(total, max_pages))
        ).strip()
        if len(embedded) >= 200:
            return Rendered(
                path=path, digest=digest, images=[], text=embedded[:MAX_TEXT_CHARS], page_count=total
            )

        zoom = dpi / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)
        images = [
            document[index].get_pixmap(matrix=matrix).tobytes("png")
            for index in range(min(total, max_pages))
        ]

    return Rendered(path=path, digest=digest, images=images, text="", page_count=total)


def _normalise_image(data: bytes, max_edge: int = 1800) -> bytes:
    """Downscale huge phone photos, if Pillow is around. Harmless if not."""
    try:
        import io

        from PIL import Image  # type: ignore
    except ImportError:
        return data

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if max(image.size) <= max_edge and image.format == "PNG":
                return data
            image = image.convert("RGB")
            image.thumbnail((max_edge, max_edge))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
    except Exception:  # pragma: no cover - a corrupt image is the model's problem
        return data


def discover(root: Path, *, recursive: bool = True) -> list[Path]:
    """Every supported document under ``root``, in a stable order."""
    if root.is_file():
        return [root] if is_supported(root) else []
    pattern = "**/*" if recursive else "*"
    found = [
        candidate
        for candidate in root.glob(pattern)
        if candidate.is_file() and is_supported(candidate) and not candidate.name.startswith(".")
    ]
    return sorted(found)
