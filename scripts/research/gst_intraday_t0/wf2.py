from wf import *
Y=('2021','2022')
def sh(tag,**kw):
    net,tk,w=run(kw.pop('times',T5),kw.pop('thr',20),years=Y,**kw); show(tag,net,tk,w,years=Y)
sh('base thr20'); sh('base thr30',thr=30); sh('base thr15',thr=15)
sh('7 times',times=['09:45','10:00','10:30','11:00','13:30','14:00','14:30'])
sh('afternoon only',times=['13:30','14:00','14:30'])
sh('morning only',times=['10:00','10:30'])
sh('+prev day',extra=('p_ret','p_last30','p_oc'))
sh('+vol',extra=('vol20','relvol','range_now'))
sh('+mkt extra',extra=('mkt_rel','mkt_30','mkt_vwap'))
sh('buy side 20',buy_thr=20); sh('buy side 40',buy_thr=40)
sh('lam 0.001',lam=0.001); sh('lam 0.1',lam=0.1)
