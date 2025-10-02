import os
import time
import logging
import pickle
import json
from pathlib import Path
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc import ImageRefMode, PictureItem, TableItem
from docling.datamodel.pipeline_options import PdfPipelineOptions

from docling.chunking import HybridChunker
from transformers import AutoTokenizer


import re
import hashlib

os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Constants ---
PDF_FILES = [
    "data/Clinical Chemistry LC-MS Method Development.pdf",
    "data/scisignal.adw1245_sm.pdf",
    "data/Tandem MS-Book.pdf",
]
OUTPUT_DIR = Path("docling_all_output")
COMBINED_OUTPUT_FILE = OUTPUT_DIR / "combined_parsed_data.json"
IMAGE_RESOLUTION_SCALE = 2.0
CHUNK_SIZE = 512


FIGURE_CAPTION_PATTERNS = [
    r"^Fig\.\s*S?\d+\.?",
    r"^Figure\s*\d+\.?",
    r"^Fig\.",
    r"^Scheme\s+\d+",
]

TABLE_CAPTION_PATTERNS = [
    r"^Table\s*S?\d+\.?",
    r"^Table\s*\d+",
    r"^Table\s*\d+\.\d+",
]


def generate_unique_id(prefix, doc_hash, counter):
    """Generate unique ID using document hash."""
    return f"{prefix}_{doc_hash}_{counter}"


def get_document_hash(filepath):
    """Generate a short hash for the document."""
    return hashlib.md5(str(filepath).encode()).hexdigest()[:8]


def find_caption_on_page(element, conv_res, page_no, patterns):
    """
    Find caption for an element on the same page using specific patterns.
    NOTE: This function can be inefficient on large documents as it iterates all items.
    """
    if not page_no:
        return "", ""

    page_texts = []
    element_found = False
    for item, level in conv_res.document.iterate_items():
        item_page = get_page_number(item, conv_res)
        if item_page == page_no:
            is_target_element = item == element
            if is_target_element:
                element_found = True
                page_texts.append(("[ELEMENT]", False))  # Mark element position
            elif hasattr(item, "text") and item.text:
                page_texts.append((item.text.strip(), True))

    if not element_found:
        return "", ""

    element_idx = -1
    for i, (text, is_text) in enumerate(page_texts):
        if text == "[ELEMENT]":
            element_idx = i
            break

    # Look for caption patterns on the same page
    caption = ""
    # Check texts after element first (more common)
    for i in range(element_idx + 1, min(element_idx + 10, len(page_texts))):
        text, is_text = page_texts[i]
        if is_text:
            for pattern in patterns:
                if re.match(pattern, text, re.IGNORECASE):
                    caption = text
                    # Collect continuation lines
                    for j in range(i + 1, min(i + 5, len(page_texts))):
                        next_text, next_is_text = page_texts[j]
                        if next_is_text:
                            if not next_text or (
                                next_text[0].isupper() and caption.endswith(".")
                            ):
                                break
                            caption += " " + next_text
                        else:
                            break
                    break
            if caption:
                break

    # If no caption found after, check before
    if not caption:
        for i in range(max(0, element_idx - 5), element_idx):
            text, is_text = page_texts[i]
            if is_text:
                for pattern in patterns:
                    if re.match(pattern, text, re.IGNORECASE):
                        caption = text
                        break
            if caption:
                break

    context_texts = [
        text for text, is_text in page_texts if is_text and text != caption
    ]
    context = " ".join(context_texts)[:500]

    return caption, context


def get_page_number(element, conv_res):
    """Extract page number from element."""
    if hasattr(element, "prov") and element.prov:
        for prov_item in element.prov:
            if hasattr(prov_item, "page_no"):
                return prov_item.page_no
    return None


def run_parsing():
    """Parse PDFs and create unified output."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "images").mkdir(exist_ok=True)

    pipeline_options = PdfPipelineOptions(
        images_scale=IMAGE_RESOLUTION_SCALE,
        generate_picture_images=True,
        generate_table_images=True,
    )
    doc_converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    combined_data = {
        "documents": [],
        "total_chunks": 0,
        "total_images": 0,
        "total_tables": 0,
        "processing_time": 0,
    }

    for pdf_path in PDF_FILES:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            logging.warning(f"File not found, skipping: {pdf_path}")
            continue

        logging.info(f"Parsing: {pdf_path}")
        start_time = time.time()

        conv_res = doc_converter.convert(pdf_path)
        doc_filename = pdf_path.stem
        doc_hash = get_document_hash(pdf_path)

        images_data = []
        tables_data = []
        picture_counter = 0
        table_counter = 0

        # =================================================================
        # Main processing loop
        # =================================================================
        for element, level in conv_res.document.iterate_items():
            if isinstance(element, PictureItem):
                picture_counter += 1
                image_filename = (
                    OUTPUT_DIR
                    / "images"
                    / f"{doc_filename}-{doc_hash}-picture-{picture_counter}.png"
                )

                try:
                    page_no = get_page_number(element, conv_res)

                    caption, context = find_caption_on_page(
                        element, conv_res, page_no, patterns=FIGURE_CAPTION_PATTERNS
                    )

                    image_obj = element.get_image(conv_res.document)
                    if image_obj:
                        with image_filename.open("wb") as fp:
                            image_obj.save(fp, "PNG")

                    image_info = {
                        "image_id": generate_unique_id(
                            "img", doc_hash, picture_counter
                        ),
                        "image_path": str(image_filename),
                        "caption": caption,
                        "page_no": page_no,
                        "surrounding_text": context,
                        "document": doc_filename,
                    }
                    images_data.append(image_info)
                    logging.info(
                        f"Image {picture_counter}: caption={'Yes' if caption else 'No'}, page={page_no}"
                    )
                except Exception as e:
                    logging.warning(f"Could not process image {picture_counter}: {e}")

            elif isinstance(element, TableItem):
                table_counter += 1
                table_filename = (
                    OUTPUT_DIR
                    / "images"
                    / f"{doc_filename}-{doc_hash}-table-{table_counter}.png"
                )

                try:
                    page_no = get_page_number(element, conv_res)

                    caption, context = find_caption_on_page(
                        element, conv_res, page_no, patterns=TABLE_CAPTION_PATTERNS
                    )

                    image_obj = element.get_image(conv_res.document)
                    if image_obj:
                        with table_filename.open("wb") as fp:
                            image_obj.save(fp, "PNG")

                    markdown_text = element.export_to_markdown(doc=conv_res.document)
                    table_info = {
                        "table_id": generate_unique_id("tbl", doc_hash, table_counter),
                        "image_path": str(table_filename),
                        "markdown_text": markdown_text,
                        "caption": caption,
                        "page_no": page_no,
                        "surrounding_text": context,
                        "document": doc_filename,
                    }
                    tables_data.append(table_info)
                    logging.info(
                        f"Table {table_counter}: caption={'Yes' if caption else 'No'}, page={page_no}"
                    )
                except Exception as e:
                    logging.warning(f"Could not process table {table_counter}: {e}")

        # --- Chunking ---
        logging.info("Loading tokenizer object from local files...")
        local_tokenizer_path = "./models/all-MiniLM-L6-v2"
        try:
            # tokenizer_object = AutoTokenizer.from_pretrained(local_tokenizer_path)
            # logging.info("Tokenizer object loaded successfully.")

            logging.info("Initializing HybridChunker with the pre-loaded tokenizer...")
            chunker = HybridChunker(
                tokenizer=local_tokenizer_path,  # Use the local tokenizer path
                # chunk_size=CHUNK_SIZE,
                # chunk_overlap=50,
                # split_by="sentences",
                max_tokens=CHUNK_SIZE,
            )
            logging.info("HybridChunker initialized successfully.")

            chunks = list(chunker.chunk(conv_res.document))
            chunks_data = [
                {
                    "chunk_id": generate_unique_id("chunk", doc_hash, idx),
                    "document": doc_filename,
                    "text": chunk.text,
                    "contextualized_text": chunker.contextualize(chunk),
                    "metadata": {
                        "headings": (
                            chunk.meta.headings
                            if hasattr(chunk.meta, "headings")
                            else []
                        ),
                        "page_nos": (
                            list(
                                set(
                                    [
                                        p.page_no
                                        for item in chunk.meta.doc_items
                                        if hasattr(item, "prov")
                                        for p in item.prov
                                        if hasattr(p, "page_no")
                                    ]
                                )
                            )
                            if hasattr(chunk.meta, "doc_items")
                            else []
                        ),
                    },
                }
                for idx, chunk in enumerate(chunks)
            ]

        except FileNotFoundError:
            logging.error(
                f"Tokenizer files not found at {local_tokenizer_path}. Please run `download_model.py` first."
            )
            chunks_data = []

        # --- Linking & Post-processing ---
        for image in images_data:
            if image["page_no"]:
                image["nearby_chunk_ids"] = [
                    c["chunk_id"]
                    for c in chunks_data
                    if image["page_no"] in c["metadata"].get("page_nos", [])
                ][:3]

        # Post-processing to remove images that are duplicates of tables
        table_captions = {t["caption"] for t in tables_data if t["caption"]}
        original_image_count = len(images_data)
        images_data = [
            img for img in images_data if img["caption"] not in table_captions
        ]
        removed_count = original_image_count - len(images_data)
        if removed_count > 0:
            logging.info(
                f"Removed {removed_count} image(s) that were duplicates of tables based on caption matching."
            )

        # --- Aggregating Data ---
        processing_time = time.time() - start_time
        doc_data = {
            "document_name": doc_filename,
            "document_hash": doc_hash,
            "chunks": chunks_data,
            "images": images_data,
            "tables": tables_data,
            "statistics": {
                "chunk_count": len(chunks_data),
                "image_count": len(images_data),
                "table_count": len(tables_data),
                "processing_time": processing_time,
            },
        }

        combined_data["documents"].append(doc_data)
        combined_data["total_chunks"] += len(chunks_data)
        combined_data["total_images"] += len(images_data)
        combined_data["total_tables"] += len(tables_data)
        combined_data["processing_time"] += processing_time
        logging.info(f"Processed {doc_filename} in {processing_time:.2f}s")

    # --- Saving Final Output ---
    with COMBINED_OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(combined_data, f, indent=2, ensure_ascii=False)

    logging.info("\n=== Final Summary ===")
    logging.info(f"Total documents: {len(combined_data['documents'])}")
    logging.info(f"Total chunks: {combined_data['total_chunks']}")
    logging.info(f"Total images: {combined_data['total_images']}")
    logging.info(f"Total tables: {combined_data['total_tables']}")
    logging.info(f"Total time: {combined_data['processing_time']:.2f}s")
    logging.info(f"Output saved to: {COMBINED_OUTPUT_FILE}")


if __name__ == "__main__":
    run_parsing()
