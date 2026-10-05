import numpy as np
exec(open('stockport.py').read().split("print('格式")[0])
np.savez('s6_base.npz',valid=valid,zv=zv,fee=fee[:,0].astype(np.float32))
print('ok',valid.sum())
