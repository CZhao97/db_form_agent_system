#!/bin/bash

echo "Generating main figures..."
python manuscript/scripts/generate_nmi_figures.py

echo "Generating supplementary figures..."
python manuscript/scripts/generate_supplementary_figures.py

echo "Generating summary table..."
python manuscript/scripts/generate_summary_table.py

echo "Generating advanced NMI figure..."
python manuscript/scripts/manuscript_nmi_advanced.py

echo "Generating alignment figure..."
python manuscript/scripts/analyze_alignment.py

echo "Generating rubric analysis figures..."
python manuscript/scripts/generate_rubric_figures.py

echo "All figures and tables generated successfully in manuscript/figures/"
