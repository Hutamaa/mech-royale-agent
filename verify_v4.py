#!/usr/bin/env python3
"""One-change regression tests for v2 -> v4. No simulated match outcomes.

Runs identical recorded observations and constructed bullet approach scenarios.
The replay does not react to bot actions. A PASS is not a placement estimate.
"""
import argparse
import ast
import copy
import gzip
import json
import math
from pathlib import Path
import sys


def load_bot(path):
    path = Path(path).resolve()
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    tree = ast.parse(path.read_text(), filename=str(path))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == 'run'
    )]
    scope = {'__name__': '__offline_test__'}
    exec(compile(tree, str(path), 'exec'), scope)
    return scope['Bot']


def close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a-b) < tol
    return a == b


def make_scenario(example, lateral):
    o=copy.deepcopy(example)
    x,y,z=o['self']['pos']
    o['self']['grounded']=True
    o['self']['in_zone']=True
    o['self']['vel']=[0,0,0]
    o['zone'].update({'center':[x,y], 'next_center':[x+100,y],
                      'radius':500., 'next_radius':450.,
                      'shrink_end':10000.})
    o['t']=20.
    o['tick']=400
    for k in ('mechs','crates','cubes','pickups','drops','events','sounds','beams'):
        o[k]=[]
    o['offer']=None
    o['projectiles']=[]
    if lateral:
        # Projectile travels right, passing +/-5 meters from player in ~0.27s.
        o['projectiles']=[{'id':123, 'kind':'gun',
                            'pos':[x-20,y+lateral*5,z+3],
                            'vel':[75.,0.,0.]}]
    return o


def run(kit):
    with gzip.open(kit/'check'/'stream.jsonl.gz','rt') as f:
        msgs=[json.loads(line) for line in f]
    hello=next(m for m in msgs if m['type']=='hello')
    hello['map']['dir']=str((kit/'arena').resolve())
    frames=[m for m in msgs if m['type']=='obs']
    root=Path(__file__).resolve().parent
    Base=load_bot(root/'test_assets'/'v2_reference.py')
    New=load_bot(root/'example_bot.py')
    base=Base(copy.deepcopy(hello))
    new=New(copy.deepcopy(hello))
    altered=0
    others_changed=0
    changes_with_no_projectiles=0
    for o in frames:
        a=base.act(copy.deepcopy(o)); b=new.act(copy.deepcopy(o))
        if a['tick'] != o['tick'] or b['tick'] != o['tick']:
            raise AssertionError('wrong tick')
        for key in set(a)|set(b):
            if key=='move': continue
            if not close(a.get(key),b.get(key)):
                others_changed+=1
                raise AssertionError(f'unintended behavior change at tick {o["tick"]}: {key}')
        if not close(a['move'],b['move']):
            altered+=1
            if not o['projectiles']: changes_with_no_projectiles+=1
    assert not changes_with_no_projectiles, 'Unrelated movement changed without projectiles'
    print(f'Recorded replay: {len(frames)} frames, changed movement: {altered}; '
          f'other actions changed: {others_changed}')
    print(f'Frames with projectile: {sum(bool(o["projectiles"]) for o in frames)}')
    print('Recorded observations are fixed; no placement score can be inferred.')

    # Set a fixed eastward movement goal and shoot synthetic bullets eastward.
    # The v2 avoidance correction moves toward the bullet lane, v4 moves away.
    for sign in (-1,+1):
        clear=make_scenario(frames[0],0)
        threat=make_scenario(frames[0],sign)
        bc=Base(copy.deepcopy(hello)).act(copy.deepcopy(clear))
        bt=Base(copy.deepcopy(hello)).act(copy.deepcopy(threat))
        nc=New(copy.deepcopy(hello)).act(copy.deepcopy(clear))
        nt=New(copy.deepcopy(hello)).act(copy.deepcopy(threat))
        assert close(bc['move'],nc['move']), 'No-threat motion changed'
        # Projectile y = me.y + sign*5, so away is -sign.
        legacy_delta=bt['move'][1]-bc['move'][1]
        fixed_delta=nt['move'][1]-nc['move'][1]
        assert legacy_delta*sign>0.1, f'Baseline expected to dodge toward shot lane {sign}: {legacy_delta}'
        assert fixed_delta*sign< -0.1, f'v4 should dodge away from lane {sign}: {fixed_delta}'
        for k in set(bt)|set(nt):
            if k!='move':
                assert close(bt.get(k),nt.get(k)), f'non-movement action changed: {k}'
        print(f'Bullet passes {"north" if sign>0 else "south"}: '
              f'baseline lateral delta {legacy_delta:+.3f}; v4 {fixed_delta:+.3f} (away)')
    print('PASS — regression checks (not a match simulation)')


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--kit',type=Path,default=Path('../mechfight-kit'))
    a=p.parse_args()
    run(a.kit.expanduser().resolve())
