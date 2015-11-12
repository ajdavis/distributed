""" This file is experimental and may disappear without warning """
from __future__ import print_function, division, absolute_import

from itertools import product

import dask.dataframe as dd
from dask.base import tokenize
from tornado import gen

from .utils import sync, ignoring


@gen.coroutine
def _futures_to_dask_dataframe(executor, futures, divisions=None):
    columns = executor.submit(lambda df: df.columns, futures[0])
    if divisions is True:
        divisions = executor.map(lambda df: df.index.min(), futures)
        divisions.append(executor.submit(lambda df: df.index.max(), futures[-1]))
        divisions = yield executor._gather(divisions)
        if sorted(divisions) != divisions:
            divisions = [None] * (len(futures) + 1)
    elif divisions in (None, False):
        divisions = [None] * (len(futures) + 1)
    else:
        raise NotImplementedError()
    columns = yield columns._result()

    name = 'distributed-pandas-to-dask-' + tokenize(*futures)
    dsk = {(name, i): f for i, f in enumerate(futures)}

    raise gen.Return(dd.DataFrame(dsk, name, columns, divisions))


def futures_to_dask_dataframe(executor, futures, divisions=None):
    """ Convert a list of futures into a dask.dataframe

    Parameters
    ----------
    executor: Executor
        Executor through which we access the remote dataframes
    futures: iterable of Futures
        Futures that create dataframes to form the divisions
    divisions: bool
        Set to True if the data is cleanly partitioned along the index
    """
    return sync(executor.loop, _futures_to_dask_dataframe, executor, futures,
                divisions=divisions)

def get_dim(x, i):
    return x.shape[i]

def get_dtype(x):
    return x.dtype

@gen.coroutine
def _futures_to_dask_array(executor, futures, divisions=None):
    import dask.array as da
    import numpy as np
    futures = np.array(futures, dtype=object)

    slices = [((0,) * i + (slice(None, None),) + (0,) * (futures.ndim - i - 1))
              for i in range(futures.ndim)]
    chunks = [[executor.submit(get_dim, x, i) for x in futures[slc]]
              for i, slc in enumerate(slices)]
    dtype = executor.submit(get_dtype, futures.flat[0])

    chunks, dtype = yield executor._gather([chunks, dtype])
    chunks = tuple(map(tuple, chunks))

    name = 'array-from-futures-' + tokenize(*futures.flat)
    keys = list(product([name], *map(range, futures.shape)))
    values = list(futures.flat)
    dsk = dict(zip(keys, values))

    raise gen.Return(da.Array(dsk, name, chunks, dtype))


def futures_to_dask_array(executor, futures):
    """ Convert a nested list of futures into a dask.array

    The futures must satisfy the following:
    *  Evaluate to numpy ndarrays
    *  Be in a nested list of the same depth as the intended dimension
    *  Serve as individual chunks of the full dask array
    *  Have shapes consistent with how dask.array sets up chunks
       (all dimensions consistent across any particular direction)

    This function will block until all futures are accessible.  It queries the
    futures directly for shape and dtype information.

    Parameters
    ----------
    executor: Executor
        Executor through which we access the remote dataframes
    futures: iterable of Futures
        Futures that create arrays
    """
    return sync(executor.loop, _futures_to_dask_array, executor, futures)