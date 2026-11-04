# DB-Curator — publication snapshot, 2026-11-04

DB-Curator connects a user-approved scientific scope, rubric-guided literature
research and compound-level verification across five chemical domains.

## Contents

- `code/`, `notebooks/`, `prompts/`: current implementation snapshot and prompts.
- `manuscript/`: main paper, Supplementary Information, source data, figures and offline checks.
- `MANIFEST.json`: SHA-256 and size of each bundled file.
- `LICENSE`: MIT licence for original software.
- `DATA_LICENSE.md`: data licensing and third-party source conditions.

## Current results

The benchmark experiment includes 1,887 candidate evaluations with complete token
and runtime measurements. Final Researcher reports classify 975 as Confirmed.
The literature-reference inventory contains 7,647 instances, with 7,624 real
literature references, 23 incorrect references and 7,246 source-located attributed
texts. These counts have different definitions and are retained in separate fields.
The construction experiment contains 1,000 retained entries across five domains.

## Reproduce the tables and figures

```bash
cd manuscript
python3 reproduction/check_consolidated_results.py
python3 reproduction/check_researcher_endpoint.py
python3 reproduction/check_recall_tables.py
python3 figure_generation/nature_final.py
bash COMPILE.sh
```

The endpoint checks use only the Python standard library. Plotting requires the
scientific packages in `requirements.txt`. XeLaTeX is needed for the manuscript.
No model calls or external retrieval are needed to reproduce these frozen results.

## Live workflow

The live workflow is implemented in `notebooks/e2e_agent_v2.py` and `code/`.
Install `requirements.txt`, configure credentials through environment variables
using `.env.example`, and provide permitted literature sources and offline shards.
Live research requires configured services and model access. This archive does
not distribute the locally indexed corpus or claim that new live runs reproduce
hosted-model decisions deterministically.

## Data and code locations

Versioned public archive: https://doi.org/10.5281/zenodo.21285739
Development repository: https://github.com/CZhao97/db_form_agent_system
The repository may require access while the Zenodo snapshot is publicly readable.

Licensed full texts, downloaded benchmark releases, model caches, credentials,
runtime indexes and unrelated historical experiments are not redistributed.
Some provenance fields retain original local file paths for audit purposes.
