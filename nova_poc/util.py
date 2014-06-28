import cProfile
import pstats
import contextlib
import time


@contextlib.contextmanager
def profiled(dump=False):
    result = [-1]
    pr = cProfile.Profile()
    pr.enable()
    yield result
    pr.disable()

    ps = pstats.Stats(pr)
    if dump:
        ps.sort_stats('cumulative')
        ps.print_stats()
        # ps.print_callers()
    result[0] = ps.total_calls

@contextlib.contextmanager
def timeit():
    result = [-1]
    now = time.time()
    yield result
    result[0] = time.time() - now
