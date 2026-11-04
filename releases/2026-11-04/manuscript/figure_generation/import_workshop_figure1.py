"""Import the complete workshop overview without redrawing its artwork."""
import argparse
import hashlib
import json
from pathlib import Path

import pymupdf
from PIL import Image


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root.parents[2] /
                        'manuscript/agenticls_2026_full/DB_Curator_AgenticLS_camera_ready.pdf')
    parser.add_argument('--output', type=Path, default=root / 'figures/workshop_style')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    with pymupdf.open(source) as original:
        pages = [p.number for p in original if 'Figure 1:' in p.get_text()]
        if len(pages) != 1:
            raise ValueError('Expected one Figure 1 caption in the workshop PDF')
        page_index = pages[0]
        page = original[page_index]
        assert page.search_for('Shared control: approved Topic Definition + Acceptance Rubric')
        # The frozen workshop page has artwork above its caption at y=244.59 pt.
        clip = pymupdf.Rect(107, 71, 505, 235)
        assert all(rect.y0 > clip.y1 for rect in page.search_for('Figure 1:'))
        target_width = 180 / 25.4 * 72
        with pymupdf.open() as figure:
            target = figure.new_page(width=target_width, height=target_width * clip.height / clip.width)
            target.show_pdf_page(target.rect, original, page_index, clip=clip)
            figure.set_metadata({'title': 'DB-Curator workshop workflow overview',
                                 'subject': 'Original workshop artwork and shared rubric control'})
            figure.save(args.output / 'Figure1.pdf', garbage=4, deflate=True)
    with pymupdf.open(args.output / 'Figure1.pdf') as figure:
        page = figure[0]
        text = page.get_text()
        assert 'Shared control:' in text and 'Figure 1:' not in text
        for ext, dpi in [('png', 300), ('tiff', 600)]:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            if ext == 'png':
                pix.save(args.output / 'Figure1.png')
            else:
                Image.frombytes('RGB', [pix.width, pix.height], pix.samples).save(
                    args.output / 'Figure1.tiff', compression='tiff_lzw', dpi=(dpi, dpi))
    metadata = {'source': str(source), 'source_sha256': sha(source),
                'source_page_1_based': page_index + 1, 'clip_points': list(clip),
                'width_mm': 180, 'artwork_redrawn': False,
                'shared_control_bar_preserved': True,
                'outputs': {f'Figure1.{ext}': sha(args.output / f'Figure1.{ext}')
                            for ext in ['pdf', 'png', 'tiff']}}
    (args.output / 'Figure1_provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
