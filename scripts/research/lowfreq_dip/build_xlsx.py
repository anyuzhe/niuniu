import json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.utils import get_column_letter as L
rows=[]
for g in ['core','exits','dyn','env','fund']:
    rows+=json.load(open(f'allyears_{g}.json'))
order=['杠杆','对照','成本','融资利率','现金收益','闸门','持仓只数','持有天数','止损止盈','修复出场','按z深度动态杠杆','回撤后降杠杆','环境过滤','仓位调节','基本面过滤']
rows.sort(key=lambda r:(order.index(r['group']) if r['group'] in order else 99))
yrs=[str(y) for y in range(2008,2027)]
wb=Workbook(); ws=wb.active; ws.title='逐年收益'
hdr=['类别','尝试']+[y+('*' if y=='2026' else '') for y in yrs]+['年化','夏普','最大回撤','平均仓位','笔数','胜率','强平次数','最低保证金比']
ws.append(hdr)
thin=Side(style='thin',color='DDDDDD')
for r in rows:
    ys=[r['years'].get(y) for y in yrs]
    ys=[None if (v is None or v!=v or v==0.0) else v for v in ys]
    ws.append([r['group'],r['name']]+ys+[r['cagr'],r['sharpe'],r['dd'],r['expo'],r['n'],r['win'],r['liq'],r['minr']])
n=len(rows)+1
ny=len(yrs)
for c in range(1,len(hdr)+1):
    h=ws.cell(1,c); h.font=Font(bold=True,color='FFFFFF'); h.fill=PatternFill('solid',fgColor='305496'); h.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
for row in ws.iter_rows(min_row=2,max_row=n):
    for c in row:
        ci=c.column
        if 3<=ci<=2+ny or ci in (3+ny,5+ny,6+ny,8+ny): c.number_format='0.0%;[Red]-0.0%'
        elif ci==4+ny: c.number_format='0.00'
        elif ci==9+ny: c.number_format='0.00'
        if ci>2: c.alignment=Alignment(horizontal='right')
        c.border=Border(bottom=thin)
# baseline highlight
for row in ws.iter_rows(min_row=2,max_row=n):
    if row[1].value in ('基线 2x','基线 1x') or row[1].value.startswith('杠杆') :
        pass
for ci in range(3,3+ny):
    col=L(ci)
    ws.conditional_formatting.add(f'{col}2:{col}{n}',ColorScaleRule(start_type='num',start_value=-0.3,start_color='F8696B',mid_type='num',mid_value=0,mid_color='FFFFFF',end_type='num',end_value=0.5,end_color='63BE7B'))
ws.column_dimensions['A'].width=14; ws.column_dimensions['B'].width=40
for ci in range(3,3+ny): ws.column_dimensions[L(ci)].width=8
for ci in range(3+ny,3+ny+8): ws.column_dimensions[L(ci)].width=10
ws.freeze_panes='C2'; ws.auto_filter.ref=f'A1:{L(len(hdr))}{n}'; ws.row_dimensions[1].height=32
ws2=wb.create_sheet('说明')
for t in ['策略：z闸门（等权大盘20日收益/(60日日波动×√20) ≤ −1.5）× 个股布林下轨收复(E6) × 按20日跌幅排序，N=20等权，次日开盘买入，持有20个交易日。',
'成本：往返7.2bp + 每边1tick，分年代印花税/佣金；杠杆融资利率按年代 8.5%/7%/6%。',
'逐年收益 = 当年最后一个交易日净值 / 上年最后一个交易日净值 − 1；空白 = 当年没有开仓（2014、2020 闸门从未触发等）。',
'*2026 为未完整年度（截至数据末日）。',
'年化/夏普/回撤按全期 2008–2026，245 交易日/年。平均仓位=持仓市值/净值的时间均值。',
'警告1：面板只含当前仍在市股票，存在幸存者偏差，所有行都偏乐观，未量化。',
'警告2：约117个尝试均在同一份样本上完成，未做多重检验校正；表中“更好”的行不应当作样本外证据。',
'警告3：环境过滤/基本面过滤里看起来更高的行，大部分增益来自 2015 单一事件或少数年份，见逐年列。',
'警告4：“只在 z≤−2 交易”等行笔数少，逐年数字噪声大。']:
    ws2.append([t])
ws2.column_dimensions['A'].width=140
import sys
wb.save(sys.argv[1] if len(sys.argv)>1 else 'niuniu_dipbuy_all_variants_yearly.xlsx')
print(n-1,'rows')
