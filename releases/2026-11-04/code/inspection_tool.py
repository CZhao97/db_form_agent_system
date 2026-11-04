import json
from pathlib import Path
from typing import Type, List
from langchain.tools import BaseTool
from pydantic import BaseModel, Field

class InspectSearchResultsInput(BaseModel):
    run_dir: str = Field(..., description="The absolute path to the search run directory returned by fulltext_journal_search.")

class InspectSearchResultsTool(BaseTool):
    name: str = "inspect_search_results"
    description: str = (
        "Reads the top 10 papers from a search run directory and returns their Titles and Abstracts. "
        "Use this AFTER fulltext_journal_search to analyze the content of the found papers and discover new keywords."
    )
    args_schema: Type[BaseModel] = InspectSearchResultsInput

    def _run(self, run_dir: str) -> str:
        try:
            rpath = Path(run_dir)
            if not rpath.exists():
                return f"Error: Directory not found: {run_dir}"

            # Gather JSON files (excluding sidecars)
            json_files = sorted([
                f for f in rpath.glob("*.json") 
                if not f.name.endswith(".ner_cache.json") and not f.name.endswith(".metadata.json")
            ])
            
            if not json_files:
                return f"No paper JSON files found in {run_dir}"

            preview_lines = []
            preview_lines.append(f"Found {len(json_files)} papers in {run_dir}. Showing top 10:")
            
            for i, fpath in enumerate(json_files[:10]):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        p = json.load(f)
                        title = p.get("title", "No Title")
                        # Truncate abstract to ~500 chars to save tokens
                        abstract = p.get("abstract", "")
                        if abstract:
                            abstract = abstract[:500].replace("\n", " ") + "..."
                        else:
                            abstract = "(No Abstract)"
                            
                        source = p.get("source", "Unknown")
                        preview_lines.append(f"{i+1}. [{source}] {title}")
                        preview_lines.append(f"   Abstract: {abstract}")
                        preview_lines.append("") # Spacer
                except Exception as e:
                    preview_lines.append(f"{i+1}. Error reading {fpath.name}: {e}")

            return "\n".join(preview_lines)

        except Exception as e:
            return f"Error inspecting results: {str(e)}"
