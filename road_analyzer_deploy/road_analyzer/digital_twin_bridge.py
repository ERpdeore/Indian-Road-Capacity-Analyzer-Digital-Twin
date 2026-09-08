import math
import logging

logger = logging.getLogger(__name__)

class DigitalTwinEngine:
    def __init__(self, kj=170):
        self.kj = kj
        logger.warning("Using Python Greenshields fallback. Jam density kj = %s is an ASSUMPTION.", kj)

    def run_simulation(self, demand_pcu, free_flow_speed, jam_density=None, duration_sec=60, dt=1):
        kj = jam_density if jam_density is not None else self.kj
        vf = free_flow_speed

        a = vf / kj
        b = -vf
        c = demand_pcu
        disc = b**2 - 4*a*c

        if disc < 0:
            k = kj
            v = 0.0
        else:
            k = (-b - math.sqrt(disc)) / (2 * a)
            if k < 0:
                k = 0.0
            elif k > kj:
                k = kj
                v = 0.0
            else:
                v = vf * (1 - k / kj)
        q = v * k

        return {
            "steady_state": {
                "speed_kmh": v,
                "density_pcu_km": k,
                "flow_pcu_hr": q,
            }
        }
