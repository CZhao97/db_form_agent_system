# Release Checklist

Before pushing this snapshot to a public GitHub repository:

- [x] Remove `.env`, key files, virtual environments, caches, logs, downloaded PDFs, FAISS indexes, and local result folders.
- [x] Replace machine-specific absolute paths with environment variables or public documentation.
- [x] Include `.env.example` instead of real secrets.
- [x] Include core code, prompts, manuscript source, final figures, and public documentation.
- [x] Keep external benchmark/results data out of git; reference them through `docs/data_availability.md`.
- [x] Verify Python files parse successfully.
- [x] Verify manuscript LaTeX source compiles from the public snapshot.

Suggested first public commit:

```bash
cd public_release/db-curator
git init
git add .
git commit -m "Prepare DB-Curator public release"
git branch -M main
git remote add origin <your-public-repo-url>
git push -u origin main
```

Recommended GitHub repository settings:

- Enable secret scanning and push protection.
- Add the external data DOI/URL to the repository About section after Zenodo release.
- Create a GitHub release matching the manuscript submission snapshot.
