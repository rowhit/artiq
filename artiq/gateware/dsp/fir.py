from operator import add
from functools import reduce
import numpy as np
from migen import *


def halfgen4(up, n):
    """
    http://recycle.lbl.gov/~ldoolitt/halfband

    params:
        * `up` is the stopband width, as a fraction of input sampling rate
        * `n is the order of half-band filter to generate
    returns:
        * `a` is the full set of FIR coefficients, `4*n-1` long.
          implement wisely.
    """

    npt = n*40
    wmax = 2*np.pi*up
    wfit = (1 - np.linspace(0, 1, npt)[:, None]**2)*wmax

    target = .5*np.ones_like(wfit)
    basis = np.cos(wfit*np.arange(1, 2*n, 2))
    l = np.linalg.pinv(basis)@target

    weight = np.ones_like(wfit)
    for i in range(40):
        err = np.fabs(basis@l - .5)
        weight[err > .99*np.max(err)] *= 1 + 1.5/(i + 11)
        l = np.linalg.pinv(basis*weight)@(target*weight)
    a = np.c_[l, np.zeros_like(l)].ravel()[:-1]
    a = np.r_[a[::-1], 1, a]/2
    return a


class FIR(Module):
    """Full-rate finite impulse response filter.

    :param coefficients: integer taps.
    :param width: bit width of input and output.
    :param shift: scale factor (as power of two).
    """
    def __init__(self, coefficients, width=16, shift=None):
        self.width = width
        self.i = Signal((width, True))
        self.o = Signal((width, True))
        n = len(coefficients)
        self.latency = (n + 1)//2 + 1

        ###

        # Delay line: increasing delay
        x = [Signal((width, True)) for _ in range(n)]
        self.sync += [xi.eq(xj) for xi, xj in zip(x, [self.i] + x)]

        # Wire up output
        o = []
        for i, c in enumerate(coefficients):
            # simplify for halfband and symmetric filters
            if c == 0 or c in coefficients[i + 1:]:
                continue
            o.append(c*reduce(add, [
                xj for xj, cj in zip(x[::-1], coefficients) if cj == c
            ]))

        if shift is None:
            shift = width - 1
        self.sync += self.o.eq(reduce(add, o) >> shift)


class ParallelFIR(Module):
    """Full-rate parallelized finite impulse response filter.

    :param coefficients: integer taps.
    :param parallelism: number of samples per cycle.
    :param width: bit width of input and output.
    :param shift: scale factor (as power of two).
    """
    def __init__(self, coefficients, parallelism, width=16, shift=None):
        self.width = width
        self.parallelism = p = parallelism
        n = len(coefficients)
        # input and output: old to young, decreasing delay
        self.i = [Signal((width, True)) for i in range(p)]
        self.o = [Signal((width, True)) for i in range(p)]
        self.latency = (n + 1)//2//parallelism + 2  # minus .5

        ###

        # Delay line: young to old, increasing delay
        x = [Signal((width, True)) for _ in range(n + p - 1)]
        self.sync += [xi.eq(xj) for xi, xj in zip(x, self.i[::-1] + x)]

        if shift is None:
            shift = width - 1

        # wire up each output
        for j in range(p):
            o = []
            for i, c in enumerate(coefficients):
                # simplify for halfband and symmetric filters
                if c == 0 or c in coefficients[i + 1:]:
                    continue
                o.append(c*reduce(add, [
                    xj for xj, cj in zip(x[-1 - j::-1], coefficients) if cj == c
                ]))
            self.sync += self.o[j].eq(reduce(add, o) >> shift)