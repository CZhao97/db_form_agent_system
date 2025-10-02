import os
import time
import logging
import json
from pathlib import Path
import google.generativeai as genai
from PIL import Image
import copy

# export GOOGLE_API_KEY=AIzaSyAxesKJ3CcJ03VIO7hMqjZiM5xJyNF9BQk

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# PIPELINE 1 OUTPUT
INPUT_JSON_FILE = Path("docling_all_output/combined_parsed_data.json")
# INPUT_JSON_FILE = Path("docling_all_output/enriched_data.json")

# PIPELINE 2 OUTPUT
OUTPUT_JSON_FILE = Path("docling_all_output/enriched_data.json")

API_CALL_DELAY_SECONDS = 3


IMAGE_PROMPT_TEMPLATE = """
You are an expert in analytical chemistry and mass spectrometry, specializing in analyzing figures from academic papers. Your task is to provide a rich, context-aware description of the following scientific figure, synthesizing all available information.

--- FIGURE ---
[IMAGE DATA HERE]

--- ORIGINAL CAPTION ---
{image_caption}

--- SURROUNDING TEXT FROM THE DOCUMENT ---
{surrounding_text}

--- ADDITIONAL CONTEXT FROM NEARBY PARAGRAPHS ---
{nearby_chunks_text}

--- INSTRUCTIONS ---
Based on all the provided information, generate a single, comprehensive paragraph that explains the figure's significance. Follow these steps in your reasoning process:

1.  **Multi-Scale Visual Analysis:** First, analyze the figure's visual information at two different scales.
    * **Macro View (Overall Structure):** Start with a wide view. Describe the overall composition and purpose of the figure. What is the logical flow? How do the main parts (e.g., schematics, plots) relate to each other to tell a story?
    * **Micro View (Zoom-in on Details):** Now, zoom in on specific features. Describe at least three key details with high precision.
        * **Detail 1:**        
        * **Detail 2 :**         
        * **Detail 3 :** 
2.  **Contextual Integration:** Second, weave the macro and micro visual details you observed into the context provided by the caption and text. Explain how the zoomed-in details serve as specific evidence for the high-level process being described.

3.  **Conclusive Summary:** Finally, synthesize the multi-scale analysis into your final output. Deliver a conclusion that is supported by both the figure's overall message and the specific, fine-grained visual data you examined. The goal is to demonstrate a comprehensive understanding from the forest to the trees.

The final output MUST be a single, well-written paragraph in analytical prose. Do not use lists or bullet points.

"""

TABLE_PROMPT_TEMPLATE = """
You are an expert data analyst specializing in interpreting tables from analytical chemistry publications. Your task is to provide an in-depth, data-driven interpretation of the following scientific table by synthesizing all available information.

--- TABLE IMAGE ---
[IMAGE DATA HERE]

--- TABLE DATA (MARKDOWN FORMAT) ---
{table_markdown_text}

--- ORIGINAL CAPTION ---
{table_caption}

--- SURROUNDING TEXT FROM THE DOCUMENT ---
{surrounding_text}

--- ADDITIONAL CONTEXT FROM NEARBY PARAGRAPHS ---
{nearby_chunks_text}

--- INSTRUCTIONS ---
Based on all the provided information, generate a single, comprehensive paragraph that interprets the table's data and explains its conclusions. Follow these steps in your reasoning process:

1.  **Purpose and Scope:** First, using the caption and surrounding text, state the main purpose of the table. What is being measured? What was the experimental setup?

2.  **Data Analysis & Trend Identification:** Second, meticulously analyze the structured data provided in the Markdown format. Identify key trends, significant data points, or important comparisons. Are there high/low values? Does the data show a correlation or support a specific hypothesis mentioned in the text?

3.  **Conclusive Interpretation:** Finally, synthesize all this information into your final output. Explain what the data in the table demonstrates and what conclusions it supports, as described in the context. Your summary should be data-driven and conclusive.

The final output MUST be a single, well-written paragraph in analytical prose. Do not use lists or bullet points.
"""


def get_nearby_chunks_text(item_info, chunks_map):

    if "nearby_chunk_ids" not in item_info:
        return ""

    texts = []
    for chunk_id in item_info["nearby_chunk_ids"]:
        if chunk_id in chunks_map:
            texts.append(chunks_map[chunk_id].get("contextualized_text", ""))

    return "\n\n".join(texts)


def enrich_item_description(item_info, chunks_map, model, item_type):

    try:
        image_path = Path(item_info["image_path"])
        if not image_path.exists():
            logging.warning(
                f"Image file not found for {item_info.get('image_id') or item_info.get('table_id')}: {image_path}"
            )
            return None

        img = Image.open(image_path)

        if item_type == "image":
            prompt = IMAGE_PROMPT_TEMPLATE.format(
                image_caption=item_info.get("caption", ""),
                surrounding_text=item_info.get("surrounding_text", ""),
                nearby_chunks_text=get_nearby_chunks_text(item_info, chunks_map),
            )
            content_for_api = [prompt, img]
        elif item_type == "table":
            prompt = TABLE_PROMPT_TEMPLATE.format(
                table_markdown_text=item_info.get("markdown_text", ""),
                table_caption=item_info.get("caption", ""),
                surrounding_text=item_info.get("surrounding_text", ""),
                nearby_chunks_text=get_nearby_chunks_text(item_info, chunks_map),
            )
            content_for_api = [prompt, img]
        else:
            return None

        logging.info("Sending request to Gemini API...")
        response = model.generate_content(content_for_api)
        logging.info("Received response from Gemini API.")

        return response.text

    except Exception as e:
        logging.error(
            f"Failed to process item {item_info.get('image_id') or item_info.get('table_id')} with Gemini API: {e}"
        )
        return None


def run_enrichment_pipeline():

    logging.info("--- Pipeline 2: Enrichment Started ---")

    # 1. API
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logging.error(
            "GOOGLE_API_KEY environment variable not set. Please set it before running."
        )
        return
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash-lite")

    # 2. JSON load
    if not INPUT_JSON_FILE.exists():
        logging.error(f"Input file not found: {INPUT_JSON_FILE}")
        return

    logging.info(f"Loading data from {INPUT_JSON_FILE}...")
    with INPUT_JSON_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    enriched_data = copy.deepcopy(data)

    for doc in enriched_data["documents"]:
        doc_name = doc["document_name"]
        logging.info(f"--- Processing document: {doc_name} ---")

        chunks_map = {chunk["chunk_id"]: chunk for chunk in doc.get("chunks", [])}

        logging.info(f"Found {len(doc.get('images', []))} images to process.")
        for image_info in doc.get("images", []):
            item_id = image_info["image_id"]
            logging.info(f"Processing image: {item_id}")

            if image_info.get("caption"):
                logging.info(f"Processing image: {item_id} (Caption found)")

                description = enrich_item_description(
                    image_info, chunks_map, model, "image"
                )
                if description:
                    image_info["vlm"] = description
                    logging.info(f"Successfully enriched image: {item_id}")

                logging.info(
                    f"Waiting for {API_CALL_DELAY_SECONDS} seconds to respect API rate limit..."
                )
                time.sleep(API_CALL_DELAY_SECONDS)
            else:

                logging.info(f"Skipping image: {item_id} (No caption)")

        logging.info(f"Found {len(doc.get('tables', []))} tables to process.")
        for table_info in doc.get("tables", []):
            item_id = table_info["table_id"]
            logging.info(f"Processing table: {item_id}")

            if table_info.get("caption"):
                logging.info(f"Processing table: {item_id} (Caption found)")

                description = enrich_item_description(
                    table_info, chunks_map, model, "table"
                )
                if description:
                    table_info["vlm"] = description
                    logging.info(f"Successfully enriched table: {item_id}")

                logging.info(
                    f"Waiting for {API_CALL_DELAY_SECONDS} seconds to respect API rate limit..."
                )
                time.sleep(API_CALL_DELAY_SECONDS)
            else:

                logging.info(f"Skipping table: {item_id} (No caption)")

    logging.info(f"Saving enriched data to {OUTPUT_JSON_FILE}...")
    with OUTPUT_JSON_FILE.open("w", encoding="utf-8") as f:
        json.dump(enriched_data, f, indent=2, ensure_ascii=False)

    logging.info("--- Pipeline 2: Enrichment Finished ---")


if __name__ == "__main__":
    run_enrichment_pipeline()
