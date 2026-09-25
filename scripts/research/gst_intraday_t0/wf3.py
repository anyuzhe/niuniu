from wf import *
Y=('2021','2022')
def sh(tag,years=Y,**kw):
    net,tk,w=run(kw.pop('times'),kw.pop('thr',20),years=years,**kw); show(tag,net,tk,w,years=years)
for times in (['10:00'],['10:30'],['09:45','10:00','10:30'],['10:00','10:30'],['10:00','10:30','11:00'],['09:45'],['11:00']):
    for thr in (20,30):
        sh(f'{",".join(times)} thr{thr}',times=times,thr=thr)
sh('10:00,10:30 thr20 + buy40',times=['10:00','10:30'],thr=20,buy_thr=40)
sh('10:00,10:30 thr20 +prev day',times=['10:00','10:30'],thr=20,extra=('p_ret','p_last30','p_oc'))
sh('10:00,10:30 thr20 WF incl 2020',times=['10:00','10:30'],thr=20,years=('2020','2021','2022'))
