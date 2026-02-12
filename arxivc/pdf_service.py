
import fitz  # PyMuPDF
import io
import base64
import os
from typing import List, Dict
from functools import lru_cache

@lru_cache(maxsize=8)
def _extract_images_cached(abs_pdf_path: str, max_images: int, mtime: float):
    """
    Internal cached extractor.
    Returns tuples to keep cached values immutable.
    """
    records = []
    doc = fitz.open(abs_pdf_path)
    img_count = 0

    try:
        for page_index, page in enumerate(doc):
            if img_count >= max_images:
                break

            image_list = page.get_images()

            for img_index, img in enumerate(image_list):
                if img_count >= max_images:
                    break

                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]

                width = base_image.get("width", 0)
                height = base_image.get("height", 0)
                if width < 150 or height < 150:
                    continue

                b64_str = base64.b64encode(image_bytes).decode("utf-8")
                mime_type = base_image["ext"]

                records.append((
                    page_index + 1,
                    img_index,
                    mime_type,
                    width,
                    height,
                    f"data:image/{mime_type};base64,{b64_str}",
                ))
                img_count += 1
    finally:
        doc.close()

    return tuple(records)

def extract_images_from_pdf(pdf_path: str, max_images: int = 10) -> List[Dict[str, str]]:
    """
    Extracts images from a PDF file.
    Returns a list of dicts: { "page": int, "index": int, "base64": str, "width": int, "height": int }
    """
    if not os.path.exists(pdf_path):
        return []

    try:
        abs_path = os.path.abspath(pdf_path)
        mtime = os.path.getmtime(abs_path)
        cached = _extract_images_cached(abs_path, max_images, mtime)
        return [{
            "page": rec[0],
            "index": rec[1],
            "mime": rec[2],
            "width": rec[3],
            "height": rec[4],
            "src": rec[5],
        } for rec in cached]
    except Exception as e:
        print(f"Error extracting images from {pdf_path}: {e}")
        return []
