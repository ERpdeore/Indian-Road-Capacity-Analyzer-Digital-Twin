"""
Digital Model – Greenshields Traffic Simulation

This module implements a simple Greenshields speed‑density model.
It is classified as a Digital Model (not a Digital Twin) because:
- Data flows one‑way (detection → simulation)
- No real‑time streaming or bidirectional feedback
- No model updating based on new data

Jam density (kj) is a key parameter. The current value (170 PCU/km/lane)
is an assumption and requires field calibration.
"""

import math
import logging

logger = logging.getLogger(__name__)

class DigitalTwinEngine:
    def __init__(self, kj=170):
        """
        :param kj: Jam density (PCU/km/lane) – ASSUMPTION. Default 170.
        """
        self.kj = kj
        self._log_assumption()

    def _log_assumption(self):
        logger.warning(
            "Jam density kj = %s PCU/km/lane is an ASSUMPTION. "
            "Calibrate with local traffic data. "
            "Typical Indian urban values range 140‑180 PCU/km/lane (Chandra & Kumar, 2003).",
            self.kj
        )

    def run_simulation(self, demand_pcu, free_flow_speed, jam_density=None,
                       duration_sec=3600, dt=1):
        """
        Run Greenshields simulation for a given demand (PCU/hr) and road parameters.

        :param demand_pcu: Demand flow (PCU/hr) – treated as the current flow q.
        :param free_flow_speed: vf (km/h)
        :param jam_density: kj (PCU/km/lane) – if provided, overrides default.
        :param duration_sec: Simulation time (seconds)
        :param dt: Time step (seconds)
        :return: dict with speeds, densities, flows over time.
        """
        kj = jam_density if jam_density is not None else self.kj
        vf = free_flow_speed

        # Solve quadratic: q = vf * k * (1 - k/kj)
        # => (vf/kj)*k^2 - vf*k + q = 0
        a = vf / kj
        b = -vf
        c = demand_pcu
        disc = b**2 - 4*a*c

        if disc < 0:
            # Demand exceeds capacity – oversaturated
            k = kj
            v = 0.0
        else:
            k = (-b - math.sqrt(disc)) / (2 * a)
            # Clamp to [0, kj]
            if k < 0:
                k = 0.0
            elif k > kj:
                k = kj
                v = 0.0
            else:
                v = vf * (1 - k / kj)
        q = v * k

        # Generate time series (constant state for simplicity)
        times = list(range(0, duration_sec + 1, dt))
        speeds = [v] * len(times)
        densities = [k] * len(times)
        flows = [q] * len(times)

        return {
            "times": times,
            "speeds_kmh": speeds,
            "densities_pcu_km": densities,
            "flows_pcu_hr": flows,
            "steady_state": {
                "speed_kmh": v,
                "density_pcu_km": k,
                "flow_pcu_hr": q,
            },
            "kj_assumed": kj,
            "vf_assumed": vf,
            "demand_pcu_hr": demand_pcu,
        }
