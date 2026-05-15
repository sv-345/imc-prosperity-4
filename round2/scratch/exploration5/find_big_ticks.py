"""Find ticks where PnL jumps $500+ in ONE tick.
These are the hidden-alpha events the user is pointing at.
"""
from __future__ import annotations
import json, io, csv, pathlib
import numpy as np

LOGS = [
    ('iter23-303257', '/tmp/prosperity_logs/303257/312201.json'),
    ('iter23-303280', '/tmp/prosperity_logs/303280/312224.json'),
    ('iter23-314059', '/tmp/prosperity_logs/314059/323026.log'),
    ('iter23-314132', '/tmp/prosperity_logs/314132/323099.log'),
    ('tb1-313880', '/tmp/prosperity_logs/313880/322847.json'),
    ('tb1-313935', '/tmp/prosperity_logs/313935/322902.json'),
    ('tb1-313995', '/tmp/prosperity_logs/313995/322962.json'),
    ('tb1-316361', '/tmp/prosperity_logs/316361/325335.log'),
    ('iter26-316156', '/tmp/prosperity_logs/316156/325130.log'),
    ('iter26-316195', '/tmp/prosperity_logs/316195/325169.log'),
    ('iter26-316247', '/tmp/prosperity_logs/316247/325221.log'),
    ('iter26-316311', '/tmp/prosperity_logs/316311/325285.log'),
]


def load_pnl(path):
    p = pathlib.Path(path)
    # .log files are JSON-wrapped server outputs; .json files are the stored result
    t = p.read_text()
    try:
        d = json.loads(t)
    except:
        return None, None
    gl = d.get('graphLog', '')
    pnl = []
    for l in gl.split('\n'):
        if not l or l.startswith('timestamp'): continue
        parts = l.split(';')
        if len(parts) == 2:
            try: pnl.append((int(parts[0]), float(parts[1])))
            except: pass
    # Per-product PnL from activitiesLog
    act = csv.DictReader(io.StringIO(d.get('activitiesLog', '')), delimiter=';')
    osm = []; pep = []
    for r in act:
        try: ts = int(r['timestamp'])
        except: continue
        try: p_ = float(r.get('profit_and_loss', 0))
        except: p_ = 0
        try: m = float(r.get('mid_price', 0))
        except: m = 0
        if r['product'] == 'ASH_COATED_OSMIUM':
            osm.append((ts, p_, m))
        else:
            pep.append((ts, p_, m))
    return osm, pep


def main():
    for name, path in LOGS:
        osm, pep = load_pnl(path)
        if osm is None: continue
        print(f"\n=== {name} ===")
        # Big OSM jumps
        big_osm = []
        for i in range(1, len(osm)):
            d = osm[i][1] - osm[i-1][1]
            if abs(d) >= 200:
                big_osm.append((osm[i][0], d, osm[i][2]))
        # Big PEP jumps
        big_pep = []
        for i in range(1, len(pep)):
            d = pep[i][1] - pep[i-1][1]
            if abs(d) >= 200:
                big_pep.append((pep[i][0], d, pep[i][2]))
        if big_osm:
            print(f"  OSM big jumps (|Δ|≥$200):")
            for ts, d, mid in big_osm[:10]:
                print(f"    ts={ts}  Δ=${d:+.1f}  mid={mid}")
        if big_pep:
            print(f"  PEP big jumps (|Δ|≥$200):")
            for ts, d, mid in big_pep[:10]:
                print(f"    ts={ts}  Δ=${d:+.1f}  mid={mid}")
        # Also biggest positive ΔPnL OSM
        osm_deltas = [(osm[i][0], osm[i][1]-osm[i-1][1], osm[i][2]) for i in range(1, len(osm))]
        osm_top = sorted(osm_deltas, key=lambda x: -x[1])[:5]
        print(f"  OSM top 5 positive single-tick Δ:")
        for ts, d, mid in osm_top:
            print(f"    ts={ts}  Δ=${d:+.1f}  mid={mid}")


if __name__ == "__main__":
    main()
