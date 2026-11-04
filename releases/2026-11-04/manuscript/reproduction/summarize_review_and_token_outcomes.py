"""Reproduce token/loop summaries and index the located non-Confirmed review."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import median


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def review_history(row):
    path = Path(row["final_record_path"])
    if sha(path) != row["final_record_sha256"]:
        raise ValueError(f"Final record hash changed: {path}")
    history = json.loads(path.read_text()).get("stop_history")
    if not history:
        resource = Path(row["resource_source"])
        if resource.suffix == ".json":
            states = sorted(resource.parent.glob("state_[0-9]*.json"))
            if states:
                path = states[-1]
                history = json.loads(path.read_text())["state"].get("stop_history")
    if not isinstance(history, list) or not history:
        raise ValueError(f"Missing review history for {row['case_id']}")
    # Each stop-history entry records a Critique assessment, not a model/tool call.
    return history, path


def main():
    manuscript = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=manuscript.parents[2])
    parser.add_argument("--output", type=Path,
                        default=manuscript / "source_data/review_token_analysis_20261103")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    token_source = manuscript / "figure_generation/source_data/benchmark_operational_current.csv"
    review_source = args.repo_root / "manuscript/all_labeled/db_curator_not_confirmed_blood_db.csv"
    old_summary = args.repo_root / "manuscript/all_labeled/processed_pool_precision_recall_corrected.csv"
    old_script = args.repo_root / "manuscript/evaluation_plan/agentic_workflow_ablation/fix_recall_definition.py"
    rows = read_csv(token_source)
    assert len({row["case_id"] for row in rows}) == len(rows)
    linked = []
    for row in rows:
        if row["token_status"] != "complete_recorded_usage":
            continue
        history, path = review_history(row)
        linked.append({
            "case_id": row["case_id"], "topic": row["topic"],
            "candidate": row["candidate"], "final_label": row["final_label"],
            "tokens": int(row["tokens"]), "review_points": len(history),
            "repeated_review": len(history) > 1,
            "history_source_path": str(path), "history_source_sha256": sha(path),
        })
    total_tokens = sum(row["tokens"] for row in linked)
    groups = []
    for topic in ["all"] + sorted({row["topic"] for row in linked}):
        for confirmed in [True, False]:
            subset = [row for row in linked
                      if (topic == "all" or row["topic"] == topic)
                      and (row["final_label"] == "Confirmed") == confirmed]
            tokens = sum(row["tokens"] for row in subset)
            repeated = sum(row["repeated_review"] for row in subset)
            groups.append({
                "topic": topic, "outcome": "Confirmed" if confirmed else "non_Confirmed",
                "n": len(subset), "median_tokens": median(row["tokens"] for row in subset),
                "mean_tokens": tokens / len(subset), "total_tokens": tokens,
                "fraction_of_all_tokens": tokens / total_tokens,
                "repeated_review_n": repeated, "repeated_review_fraction": repeated / len(subset),
            })
    review_rows = read_csv(review_source)
    assert all(row["config_tag"] == "section1" for row in review_rows)
    review_index = []
    for index, row in enumerate(review_rows, 2):
        comment = row["Mannual inspection"].strip()
        review_index.append({
            "source_csv_row": index, "topic": row["topic"],
            "candidate_name": row["candidate_name"], "config_tag": row["config_tag"],
            "system_claim": row["claim"], "original_reviewer_comment": comment,
            "review_interpretation": "comment_requires_explicit_validity_coding" if comment
            else "no_objection_under_author_confirmed_review_convention",
            "human_valid_label": "", "results_dir": row["results_dir"],
        })
    write_csv(args.output / "token_review_case_links.csv", linked)
    write_csv(args.output / "token_review_summary.csv", groups)
    write_csv(args.output / "located_construction_nonconfirmed_review.csv", review_index)
    report = {
        "inputs": {str(path): sha(path) for path in
                   [token_source, review_source, old_summary, old_script]},
        "script_sha256": sha(Path(__file__)),
        "benchmark_records": len(rows), "complete_token_records": len(linked),
        "overall_groups": groups[:2],
        "review_endpoint": "More than one recorded Critique assessment in the same evaluation run",
        "review_endpoint_is_not_search_call_count": True,
        "construction_review_records_located": len(review_index),
        "construction_review_nonblank_comments": sum(bool(r["original_reviewer_comment"]) for r in review_index),
        "old_recall_audit": {
            "blood_FN_rule": "Counts any nonblank manual comment as a false negative",
            "other_topic_FN_rule": "Zero values hardcoded in TOPIC_COUNTS",
            "current_recall_recomputed": False,
            "reason": "The two comments do not explicitly identify human-valid false negatives",
        },
        "original_annotations_modified": False, "new_model_calls": 0,
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
