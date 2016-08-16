""" demo file for simple 2d shallow water equations for parabolic bowl with steady rain """

from __future__ import division

from firedrake import *
from flooddrake import *

# Meshsize
n = 10
mesh = UnitSquareMesh(n, n)

# mixed function space
v_h = FunctionSpace(mesh, "DG", 1)
v_mu = FunctionSpace(mesh, "DG", 1)
v_mv = FunctionSpace(mesh, "DG", 1)
V = v_h * v_mu * v_mv

# setup free surface depth
g = Function(V)
x = SpatialCoordinate(V.mesh())
g.sub(0).assign(0.5)

# setup bed
bed = Function(V)
bed.sub(0).interpolate(2 * (pow(x[0] - 0.5, 2) + pow(x[1] - 0.5, 2)))

# setup actual depth
w = g.assign(g - bed)

# setup source (is only a depth function)
source = Function(v_h).assign(0.2)

# timestep
solution = Timestepper(V, bed, source, 0.025)

solution.stepper(0, 2, w, 0.025)
