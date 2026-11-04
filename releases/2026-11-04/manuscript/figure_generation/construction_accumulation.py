"""Final cohort membership in the recorded candidate-processing order."""
import json

from nature_figures import Canvas, DATA, GREY, GRID, NAMES, QA, ROOT, TOPICS, read, save


def figure():
    rows = read(DATA/'construction_accumulation.csv')
    c = Canvas(102)
    ax = c.ax(19, 7, 154, 76)
    colors = ['#588FB8', '#C78D6B', '#6D9E95', '#B6A056', '#AB8FA8']
    for topic, name, color in zip(TOPICS, NAMES, colors):
        subset = [r for r in rows if r['topic'] == topic]
        x = [0, *[int(r['processed_records']) for r in subset]]
        y = [0, *[int(r['retained_rows']) for r in subset]]
        assert y[-1] == 200 and all(a <= b for a, b in zip(y, y[1:]))
        ax.step(x, y, where='post', color=color, lw=1.4, label=name)
        ax.plot(x[-1], y[-1], 'o', color=color, ms=3.5)
    ax.axhline(200, color=GREY, lw=.6, ls='--', zorder=0)
    ax.set(xlabel='Processed candidate records', ylabel='Final retained entries',
           xlim=(0, 730), ylim=(0, 215), xticks=list(range(0, 701, 100)),
           yticks=[0, 50, 100, 150, 200])
    ax.grid(axis='y', color=GRID, lw=.5)
    ax.set_axisbelow(True)
    c.fig.legend(*ax.get_legend_handles_labels(), loc='lower center',
                 bbox_to_anchor=(.53, .01), ncol=5, frameon=False, fontsize=6.8,
                 handlelength=2, columnspacing=1.4)
    save(c, 'SupplementaryFigure2')


if __name__ == '__main__':
    QA.clear()
    figure()
    (ROOT/'CONSTRUCTION_ACCUMULATION_QA.json').write_text(json.dumps(QA, indent=2)+'\n')
