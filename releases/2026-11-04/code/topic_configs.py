from __future__ import annotations

from pathlib import Path


ROOT = Path("/home/chen/GNPS_SIM/agent/db_form_agent_system")
MANUSCRIPT_UPPER_STREAM_RESULTS_DIR = ROOT / "manuscript" / "upper_stream_results"
TMP_RERUNS_UPPER_TOPICS_DIR = MANUSCRIPT_UPPER_STREAM_RESULTS_DIR / "_tmp_reruns"


TOPIC_CONFIGS = {
    "dbp": {
        "domain": "dbp",
        "run_dir": TMP_RERUNS_UPPER_TOPICS_DIR / "20260409_002116_form_a_database_of_disinfection_byproducts_dbps",
        "default_query": "Form a database of disinfection byproducts (DBPs).",
        "user_definition": (
            "A disinfection byproduct is a specific chemical compound formed during a "
            "water disinfection or oxidation process when disinfectants or oxidants "
            "react with naturally occurring or anthropogenic precursors in real or "
            "simulated water matrices, with evidence attributing the compound’s "
            "formation to that treatment process."
        ),
    },
    "blood_exposome": {
        "domain": "blood",
        "run_dir": TMP_RERUNS_UPPER_TOPICS_DIR / "20260409_035049_form_a_database_of_human_blood_exposome_chemicals",
        "default_query": "Form a database of human blood exposome chemicals.",
        "user_definition": (
            "A human blood exposome chemical is a specific chemical entity reported in "
            "human blood or systemic circulation that is introduced by, structurally "
            "modified by, or significantly changes in amount in response to the "
            "external environment, and is supported by evidence from primary "
            "literature, biomonitoring surveys, or public metabolomics datasets "
            "associated with human blood specimens."
        ),
    },
    "drug_compounds": {
        "domain": "drug",
        "run_dir": MANUSCRIPT_UPPER_STREAM_RESULTS_DIR / "drug_compounds_20260331_040723",
        "default_query": "Form a database of drug compounds.",
        "user_definition": (
            "A drug compound is a core active drug substance or drug entity represented "
            "in a drug database, including small-molecule and biologic drugs, that "
            "elicits or is intended to elicit pharmacologically relevant effects, "
            "while excluding specific finished dosage forms, secondary brand names, "
            "and other non-active product-level entries."
        ),
    },
    "microbial_natural_products": {
        "domain": "microbial_natural_product",
        "run_dir": TMP_RERUNS_UPPER_TOPICS_DIR / "20260409_004104_form_a_database_of_microbial_natural_products",
        "default_query": "Form a database of microbial natural products.",
        "user_definition": (
            "A microbial natural product is a specific chemical metabolite produced by "
            "microorganisms, such as bacteria, fungi, or cyanobacteria, curated from "
            "peer-reviewed primary scientific literature and supported by sufficient "
            "analytical evidence for unambiguous structural assignment, while excluding "
            "primary metabolites and non-secondary-metabolite biomolecules."
        ),
    },
    "human_endogenous_metabolites": {
        "domain": "endogenous_metabolite",
        "run_dir": TMP_RERUNS_UPPER_TOPICS_DIR / "20260415_224447_form_a_database_of_human_endogenous_metabolites",
        "default_query": "Form a database of human endogenous metabolites.",
        "user_definition": (
            "A human endogenous metabolite is a specific small-molecule metabolite "
            "produced within the human body and functioning in biochemical and "
            "physiological processes, while excluding exogenous chemicals and "
            "microbiota-only metabolites unless they are also produced by host "
            "metabolism."
        ),
    },
}


DOMAIN_TO_TOPIC_KEY = {
    "dbp": "dbp",
    "blood": "blood_exposome",
    "drug": "drug_compounds",
    "microbial_natural_product": "microbial_natural_products",
    "endogenous_metabolite": "human_endogenous_metabolites",
}


def topic_config_for_domain(domain: str) -> dict:
    try:
        return TOPIC_CONFIGS[DOMAIN_TO_TOPIC_KEY[domain]]
    except KeyError as exc:
        raise ValueError(f"Unsupported domain for TOPIC_CONFIGS lookup: {domain}") from exc
