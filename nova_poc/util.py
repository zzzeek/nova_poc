import cProfile
import StringIO
import pstats
import contextlib
import time


@contextlib.contextmanager
def profiled():
    result = [-1]
    pr = cProfile.Profile()
    pr.enable()
    yield result
    pr.disable()
    ps = pstats.Stats(pr)
    result[0] = ps.total_calls

    # s = StringIO.StringIO()
    # ps = pstats.Stats(pr, stream=s)
    # ps.sort_stats('cumulative')
    # ps.print_stats()
    # ps.print_callers()

@contextlib.contextmanager
def timeit():
    result = [-1]
    now = time.time()
    yield result
    result[0] = time.time() - now
