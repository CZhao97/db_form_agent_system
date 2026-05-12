# Public Release Manifest

Included:

- Core source code in `code/`.
- Agent prompts in `prompts/`.
- Curated runner scripts in `scripts/run/`.
- Evaluation and citation-audit scripts in `scripts/evaluation/`.
- Offline index utilities in `scripts/offline_index/`.
- Manuscript LaTeX source, compiled PDFs, generated figures, and supplementary information in `manuscript/`.
- Documentation, dependency list, citation metadata, license, and environment template.

Excluded:

- `.env` and any key files.
- Virtual environments.
- Notebook scratch work.
- Local result directories and symlinks.
- Downloaded full-text papers and cache folders.
- Large CSV/JSON/Parquet/FAISS/SQLite intermediate artifacts.
- Machine-specific absolute paths.

Recommended GitHub release process:

```bash
cd public_release/db-curator
git init
git add .
git commit -m "Prepare DB-Curator public release"
git branch -M main
git remote add origin <your-public-repo-url>
git push -u origin main
```
