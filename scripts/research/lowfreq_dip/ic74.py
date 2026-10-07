import numpy as np, lib74 as Y, time
t=time.time(); R=Y.rows(); print(R.shape, time.time()-t); np.save('rows74.npy', R)
