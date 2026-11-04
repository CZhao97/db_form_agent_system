"""Python figure: supported-output bounds and resources under common ceilings.

183 mm wide quantitative grid. Missing-assessment bounds are not confidence
intervals. All 50 assigned candidates remain in each method denominator.
"""
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE=Path(__file__).resolve().parent


def main():
    with (HERE.parent/'source_data/quality_cost_any/final_group_support_cost_summary.csv').open(encoding='utf-8-sig') as f:
        rows=[r for r in csv.DictReader(f) if r['group']=='all']
    plt.rcParams.update({'font.family':'Liberation Sans','font.size':8,'axes.titlesize':9,
                         'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':0.6,
                         'pdf.fonttype':42,'svg.fonttype':'none','legend.frameon':False})
    fig,axs=plt.subplots(2,2,figsize=(183/25.4,145/25.4))
    fig.subplots_adjust(left=.10,right=.98,top=.94,bottom=.17,wspace=.35,hspace=.48)
    methods=[('researcher_only','Researcher only','#6497A8','o'),('full','Researcher + Critique','#C68E89','s')]
    x=np.arange(3)
    for ax,judge,letter in zip(axs[0],('claude','gpt'),('a','b')):
        rs=sorted([r for r in rows if r['judge']==judge],key=lambda r:int(r['budget']))
        for arm,label,color,marker in methods:
            lo=np.array([int(r[arm+'_supported_confirmed_lower']) for r in rs])*2
            hi=np.array([int(r[arm+'_supported_confirmed_upper']) for r in rs])*2
            ax.fill_between(x,lo,hi,color=color,alpha=.18,linewidth=0)
            ax.plot(x,lo,color=color,marker=marker,lw=1.5,ms=5,label=label)
            ax.plot(x,hi,color=color,ls=':',lw=1)
            ax.annotate(f'{int(lo[-1]/2)}/50', (x[-1],lo[-1]), xytext=(7,0),
                        textcoords='offset points', color=color, va='center', fontsize=8)
        ax.set_xlim(-.15,2.5)
        ax.set_ylim(0,42);ax.set_yticks([0,10,20,30,40])
        ax.set_ylabel('Supported Confirmed / 50 (%)')
        ax.set_title('Claude assessment' if judge=='claude' else 'GPT assessment',loc='left',pad=12)
        ax.text(-.18,1.08,letter,transform=ax.transAxes,fontweight='bold',fontsize=11)
    rs=sorted([r for r in rows if r['judge']=='claude'],key=lambda r:int(r['budget']))
    ax=axs[1,0]
    for arm,label,color,marker in methods:
        vals=np.array([float(r[arm+'_mean_prefix_token_upper']) for r in rs])/1000
        ax.plot(x,vals,color=color,marker=marker,lw=1.5,ms=5)
        for xx,yy in zip(x,vals):
            offset=-13 if arm=='researcher_only' and xx==0 else 7
            ax.annotate(f'{yy:.0f}',(xx,yy),xytext=(0,offset),textcoords='offset points',ha='center',fontsize=8)
    ax.set_ylim(0,330);ax.set_ylabel('Mean accounted tokens (thousands)')
    ax.set_title('Resource use',loc='left',pad=12)
    ax.text(-.18,1.08,'c',transform=ax.transAxes,fontweight='bold',fontsize=11)
    ax=axs[1,1]
    for i,(arm,label,color,marker) in enumerate(methods):
        vals=[int(r[arm+'_supported_confirmed_upper'])-int(r[arm+'_supported_confirmed_lower']) for r in rs]
        xx=x+(i-.5)*.30
        ax.bar(xx,vals,width=.27,color=color,alpha=.75)
        for p,v in zip(xx,vals):ax.text(p,v+.12,str(v),ha='center',fontsize=8)
    ax.set_ylim(0,5.5);ax.set_ylabel('Confirmed outputs without assessment')
    ax.set_title('Missing assessments',loc='left',pad=12)
    ax.text(-.18,1.08,'d',transform=ax.transAxes,fontweight='bold',fontsize=11)
    for ax in axs.flat:
        ax.set_xticks(x,['100k','250k','500k']);ax.set_xlabel('Assigned token ceiling')
        ax.tick_params(width=.6,length=3);ax.grid(axis='y',color='#E8E8E8',lw=.5);ax.set_axisbelow(True)
    fig.legend(*axs[0,0].get_legend_handles_labels(),loc='lower center',bbox_to_anchor=(.5,.065),ncol=2)
    out=HERE.parent/'figures';out.mkdir(exist_ok=True)
    for ext in ('pdf','svg','png'):
        fig.savefig(out/f'quality_cost_common_ceiling.{ext}',dpi=300)
    plt.close(fig)


if __name__=='__main__':main()
