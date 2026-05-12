# Architecture Overview

DB-Curator is a stateful multi-agent workflow for scientific database construction.

## Stages

1. **Intent refinement** converts an open-ended user request into a topic definition, inclusion criteria, exclusion criteria, and a verification rubric.
2. **Dynamic literature construction** searches online APIs and optional local corpora. The literature set is not fixed: broad topic searches, inspected results, candidate identities, and unresolved rubric predicates can all trigger additional retrieval.
3. **Candidate discovery and filtering** extracts chemical candidates from retrieved literature, normalizes identifiers, ranks candidates by topic relevance, and filters a smaller queue for verification.
4. **Predicate-state verification** verifies each candidate through a Researcher--Critique loop. Required rubric items must be supported by cited paper context, exclusion criteria must not be triggered, and unresolved evidence gaps drive follow-up retrieval or an evidence-limited label.

## Core Objects

- `user_request`: the original open-ended scientific curation request.
- `refined_definition`: the clarified topic scope.
- `rubric`: mandatory and exclusionary predicates used for verification.
- `candidate`: a normalized entity proposed for database inclusion.
- `evidence`: cited spans or local context from retrieved papers.
- `claim_label`: the final verification state, such as Confirmed or Insufficient Direct Evidence.

## Tooling

The public code includes tools for literature search, document parsing, offline indexing, chemical NER, PubChem/RDKit/OPSIN grounding, candidate ranking, and provenance-aware verification.


## Demo Schema

The static web demo in `demo/` uses a lightweight JSON representation of a run. It is not a required internal format; it is an export format for visualization. The important fields are `summary`, `stages`, `literature`, and `candidates`. Each candidate can expose `rubric`, `evidence`, and `iterations` for interactive inspection.
