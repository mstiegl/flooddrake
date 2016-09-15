from __future__ import division
from __future__ import absolute_import

from flooddrake.slope_modification import SlopeModification
from flooddrake.slope_limiter import SlopeLimiter
from flooddrake.flux import Interior_Flux, Boundary_Flux
from flooddrake.min_dx import MinDx
from flooddrake.adaptive_timestepping import AdaptiveTimestepping
from flooddrake.boundary_conditions import BoundaryConditions

from firedrake import *


class Timestepper(object):

    def __init__(self, V, bed, source, MaxTimestep=0.025, func=lambda x: 1,
                 boundary_conditions=None):

        self.b = bed

        # currently source term only works for constant
        self.source_term = source
        self.func = func

        # initialize time attribute
        self.t = 0

        self.mesh = V.mesh()

        # define solver
        self.v = TestFunction(V)

        # Compute global minimum of cell edge length
        self.delta_x = MinDx(self.mesh)

        self.AT = AdaptiveTimestepping(V, MaxTimestep)
        self.dt = MaxTimestep
        self.initial_dt = MaxTimestep
        self.Dt = Constant(self.dt)

        self.V = V

        # boundary conditions - default at solid wall for makers not given
        self.boundary_conditions = boundary_conditions
        if self.boundary_conditions is None:
            if self.mesh.geometric_dimension() == 1:
                self.boundary_conditions = [BoundaryConditions(1),
                                            BoundaryConditions(2)]
            if self.mesh.geometric_dimension() == 2:
                self.boundary_conditions = [BoundaryConditions(1),
                                            BoundaryConditions(2),
                                            BoundaryConditions(3),
                                            BoundaryConditions(4)]
        else:
            if self.mesh.geometric_dimension() == 1:
                markers = [1, 2]
                for bc in self.boundary_conditions:
                    markers.remove(bc.marker)
                for i in markers:
                    self.boundary_conditions.append(BoundaryConditions(i))
            if self.mesh.geometric_dimension() == 2:
                markers = [1, 2, 3, 4]
                for bc in self.boundary_conditions:
                    markers.remove(bc.marker)
                for i in markers:
                    self.boundary_conditions.append(BoundaryConditions(i))

        # define flux and state vectors
        if self.mesh.geometric_dimension() == 2:
            self.N = FacetNormal(self.mesh)
            self.b_, _1, _2 = split(self.b)
            self.v_h, self.v_mu, self.mv = split(self.V)
        if self.mesh.geometric_dimension() == 1:
            self.N = FacetNormal(self.mesh)[0]
            self.b_, _1 = split(self.b)
            self.v_h, self.v_mu = split(self.V)

        self.gravity = parameters["flooddrake"]["gravity"]

        self.SM = SlopeModification(self.V)
        self.SL = SlopeLimiter(self.b_, self.V)

        super(Timestepper, self).__init__()

    def __update_slope_modification(self):
        """ Updates slope modifier

        """

        self.w.assign(self.SM.Modification(self.w))

    def __update_slope_limiter(self):
        """ Updates slope limiter

        """

        self.w.assign(self.SL.Limiter(self.w))

    def __solver_setup(self):
        """ Sets up the solver

        """

        self.W = TrialFunction(self.V)

        if self.mesh.geometric_dimension() == 1:

            # index functions and spaces
            self.h, self.mu = self.w.sub(0), self.w.sub(1)

            # define velocities
            velocity = conditional(self.h <= 0, zero(self.mu.ufl_shape), (self.mu * self.mu) / self.h)

            self.F = as_vector((self.mu, (velocity + ((self.gravity / 2) * self.h * self.h))))

        if self.mesh.geometric_dimension() == 2:

            # index functions and spaces
            self.h, self.mu, self.mv = self.w.sub(0), self.w.sub(1), self.w.sub(2)

            # define velocities
            velocity = conditional(self.h <= 0, zero(self.mu.ufl_shape), (self.mu * self.mv) / self.h)
            velocity_u = conditional(self.h <= 0, zero(self.mu.ufl_shape), (self.mu * self.mu) / self.h)
            velocity_v = conditional(self.h <= 0, zero(self.mv.ufl_shape), (self.mv * self.mv) / self.h)

            self.F1 = as_vector((self.mu, (velocity_u + ((self.gravity / 2) * (self.h * self.h))), velocity))
            self.F2 = as_vector((self.mv, velocity, (velocity_v + ((self.gravity / 2) * (self.h * self.h)))))

        # height modification
        h_mod_plus = Max(0, self.h('+') - Max(0, self.b_('-') - self.b_('+')))
        h_mod_minus = Max(0, self.h('-') - Max(0, self.b_('+') - self.b_('-')))

        if self.mesh.geometric_dimension() == 2:

            velocity_u = conditional(self.h <= 0, zero(self.mu.ufl_shape), (self.mu) / self.h)
            velocity_v = conditional(self.h <= 0, zero(self.mv.ufl_shape), (self.mv) / self.h)

            # modified momentum
            mu_mod_plus = (h_mod_plus) * velocity_u('+')
            mu_mod_minus = (h_mod_minus) * velocity_u('-')
            mv_mod_plus = (h_mod_plus) * velocity_v('+')
            mv_mod_minus = (h_mod_minus) * velocity_v('-')

            # source modification
            self.delta_plus = as_vector((0,
                                        (self.gravity / 2) * ((h_mod_plus * h_mod_plus)-(self.h('+') * self.h('+'))) * self.N[0]('+'),
                                        (self.gravity / 2) * ((h_mod_plus * h_mod_plus)-(self.h('+') * self.h('+'))) * self.N[1]('+')))

            self.delta_minus = as_vector((0,
                                         (self.gravity / 2) * ((h_mod_minus * h_mod_minus)-(self.h('-') * self.h('-'))) * self.N[0]('+'),
                                         (self.gravity / 2) * ((h_mod_minus * h_mod_minus)-(self.h('-') * self.h('-'))) * self.N[1]('+')))

            # set up modified state vectors
            self.w_plus = as_vector((h_mod_plus, mu_mod_plus, mv_mod_plus))
            self.w_minus = as_vector((h_mod_minus, mu_mod_minus, mv_mod_minus))

        if self.mesh.geometric_dimension() == 1:

            velocity = conditional(self.h <= 0, zero(self.mu.ufl_shape), self.mu / self.h)

            # modified momentum
            mu_mod_plus = (h_mod_plus) * velocity('+')
            mu_mod_minus = (h_mod_minus) * velocity('-')

            # source modification
            self.delta_plus = as_vector((0,
                                        (self.gravity / 2) * ((h_mod_plus * h_mod_plus) - (self.h('+') * self.h('+'))) * self.N('+')))
            self.delta_minus = as_vector((0,
                                         (self.gravity / 2) * ((h_mod_minus * h_mod_minus) - (self.h('-') * self.h('-'))) * self.N('+')))

            # set up modified state vectors
            self.w_plus = as_vector((h_mod_plus, mu_mod_plus))
            self.w_minus = as_vector((h_mod_minus, mu_mod_minus))

        # Define Fluxes - these get overidden every step
        self.PosFlux = Interior_Flux(self.N('+'), self.V, self.w_plus, self.w_minus)
        self.NegFlux = Interior_Flux(self.N('-'), self.V, self.w_minus, self.w_plus)

        # Define Boundary Fluxes - one for each boundary marker
        self.BoundaryFlux = []
        for i in range(self.mesh.geometric_dimension() * 2):
            # put the state depths into the boundary values - remov if want to specify this
            if self.boundary_conditions[i].option == 'river':
                self.boundary_conditions[i].value.sub(0).assign(self.h)
            self.BoundaryFlux.append(Boundary_Flux(self.V, self.w, self.boundary_conditions[i].option, self.boundary_conditions[i].value))

        # Define source term - these get overidden every step
        if self.mesh.geometric_dimension() == 1:
            self.source = as_vector((-self.source_term*self.func(self.t), self.gravity * self.h * self.b_.dx(0)))
        if self.mesh.geometric_dimension() == 2:
            self.source = as_vector((-self.source_term*self.func(self.t), self.gravity * self.h * self.b_.dx(0), self.gravity * self.h * self.b_.dx(1)))

        # solver - try to make this only once in the new version - by just assigning different values to all variable functions
        if self.mesh.geometric_dimension() == 2:
            self.L = - dot(self.v, self.W) * dx
            self.a = (- dot(self.v, self.w) * dx +
                      self.Dt * (- dot(self.v.dx(0), self.F1) * dx -
                                 dot(self.v.dx(1), self.F2) * dx +
                                 (dot(self.v('-'), self.NegFlux) +
                                  dot(self.v('+'), self.PosFlux)) * dS +
                                 (dot(self.v, self.BoundaryFlux[0]) *
                                  ds(self.boundary_conditions[0].marker)) +
                                 (dot(self.v, self.BoundaryFlux[1]) *
                                  ds(self.boundary_conditions[1].marker)) +
                                 (dot(self.v, self.BoundaryFlux[2]) *
                                  ds(self.boundary_conditions[2].marker)) +
                                 (dot(self.v, self.BoundaryFlux[3]) *
                                  ds(self.boundary_conditions[3].marker)) +
                                 (dot(self.source, self.v)) * dx -
                                 (dot(self.v('-'), self.delta_minus) +
                                  dot(self.v('+'), self.delta_plus)) * dS))

        if self.mesh.geometric_dimension() == 1:
            self.L = - dot(self.v, self.W) * dx
            self.a = (- dot(self.v, self.w) * dx +
                      self.Dt * (- dot(self.v.dx(0), self.F) * dx +
                                 (dot(self.v('-'), self.NegFlux) +
                                  dot(self.v('+'), self.PosFlux)) * dS +
                                 (dot(self.v, self.BoundaryFlux[0]) *
                                  ds(self.boundary_conditions[0].marker)) +
                                 (dot(self.v, self.BoundaryFlux[1]) *
                                  ds(self.boundary_conditions[1].marker)) +
                                 (dot(self.source, self.v)) * dx -
                                 (dot(self.v('-'), self.delta_minus) +
                                  dot(self.v('+'), self.delta_plus)) * dS))

        self.w_ = Function(self.V)

        self.problem = LinearVariationalProblem(self.L, self.a, self.w_)
        self.solver = LinearVariationalSolver(self.problem,
                                              solver_parameters={'ksp_type': 'preonly',
                                                                 'sub_pc_type': 'ilu',
                                                                 'pc_type': 'bjacobi',
                                                                 'mat_type': 'aij'})

    def stepper(self, t_start, t_end, w, t_dump):
        """ Timesteps the shallow water equations from t_start to t_end using a 3rd order SSP Runge-Kutta scheme

                :param t_start: start time
                :type t_start: float

                :param t_end: end time
                :type t_end: float

                :param w: Current state vector function

                :param t_dump: time interval to write the free surface water depth to a .pvd file
                :type t_dump: float

        """

        self.w = w

        # setup the solver
        self.__solver_setup()

        # used as the original state vector in each RK3 step
        self.w_old = Function(self.V).assign(self.w)

        # initial slope modification
        self.__update_slope_modification()

        hout = Function(self.v_h)
        # free surface depth
        hout_file = File("h.pvd")
        # bed depth
        bout = Function(self.v_h).project(self.b_)
        bout_file = File("b.pvd")

        self.Project = Projector(self.h + self.b_, hout)
        self.Project.project()
        hout_file.write(hout)
        bout_file.write(bout)

        self.t = t_start

        # start counter of how many time dumps
        self.c = 1

        while self.t < t_end:

            # find new timestep
            self.dt = self.AT.FindTimestep(self.w)
            self.Dt.assign(self.dt)

            # check if remaining time to next time dump is less than timestep
            # correct if neeeded
            if self.dt + self.t > self.c * t_dump:
                self.dt = (self.c * t_dump) - self.t
                self.Dt.assign(self.dt)

            # check if remaining time to end time is less than timestep
            # correct if needed
            if (self.t <= (self.c + 1) * t_dump) and (self.dt + self.t > t_end):
                self.dt = t_end - self.t
                self.Dt.assign(self.dt)

            self.solver.solve()

            self.w.assign(self.w_)

            # slope limiter
            self.__update_slope_limiter()
            # slope modification
            self.__update_slope_modification()

            self.solver.solve()

            self.w.assign((3.0 / 4.0) * self.w_old + (1.0 / 4.0) * self.w_)

            # slope limiter
            self.__update_slope_limiter()
            # slope modification
            self.__update_slope_modification()

            self.solver.solve()

            self.w.assign((1.0 / 3.0) * self.w_old + (2.0 / 3.0) * self.w_)

            # slope limiter
            self.__update_slope_limiter()
            # slope modification
            self.__update_slope_modification()

            self.w_old.assign(self.w)

            # timstep complete - dump realisation if needed
            self.t += self.dt

            if self.t == self.c * t_dump:
                self.Project.project()
                hout_file.write(hout)
                bout_file.write(bout)

                self.c += 1

                self.dt = self.initial_dt
                self.Dt.assign(self.dt)

        # return timestep
        self.dt = self.initial_dt
        self.Dt.assign(self.dt)

        return self.w
