Offline checks (run from manuscript/):
python3 reproduction/check_consolidated_results.py
python3 reproduction/check_researcher_endpoint.py
python3 reproduction/check_recall_tables.py
python3 -m unittest discover -s reproduction -p test_construction_recall.py
python3 figure_generation/nature_final.py
bash COMPILE.sh

Figure generation requires matplotlib, numpy, scipy, pandas, PyMuPDF and Pillow.
Manuscript compilation requires XeLaTeX. Figure 1 is supplied as final artwork.
Local provenance paths in source tables identify original archived runs. These
paths are not required to recompute the bundled endpoint tables or figures.
