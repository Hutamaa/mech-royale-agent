"""Survival-oriented Mech Royale bot v1. Standard library only."""
import math
import random
import mechfight as mf

PI = math.pi

def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

def norm(x, y):
    n = math.hypot(x, y)
    return (x/n, y/n) if n > 1e-8 else (0.0, 0.0)

def angle_diff(a,b):
    return (a-b+PI) % (2*PI)-PI

def direction(a,b):
    return math.atan2(b[1]-a[1], b[0]-a[0])

def intercept(me, target, velocity, speed, delay=0.0):
    """Constant-velocity prediction for linear projectiles."""
    dx = target[0]+velocity[0]*delay-me[0]
    dy = target[1]+velocity[1]*delay-me[1]
    dz = target[2]+velocity[2]*delay-me[2]
    vx,vy,vz = velocity
    aa = vx*vx+vy*vy+vz*vz-speed*speed
    bb = 2*(dx*vx+dy*vy+dz*vz)
    cc = dx*dx+dy*dy+dz*dz
    t = math.sqrt(cc)/max(speed,1)
    disc = bb*bb-4*aa*cc
    if disc >= 0 and abs(aa)>1e-7:
        roots = [(-bb+math.sqrt(disc))/(2*aa),(-bb-math.sqrt(disc))/(2*aa)]
        roots = [v for v in roots if v > 0]
        if roots: t=min(roots)
    elif abs(bb)>1e-7:
        r=-cc/bb
        if r>0: t=r
    return (target[0]+vx*(t+delay),target[1]+vy*(t+delay),target[2]+vz*(t+delay))

def mortar_solution(me, target, vel, speed, gravity):
    """Low ballistic arc to a constant-velocity target; None if out of range.

    Returns (yaw, pitch, predicted_target). World geometry is NOT checked.
    """
    dt=math.hypot(target[0]-me[0],target[1]-me[1])/max(1.,speed*.8)
    for _ in range(4):
        p=(target[0]+vel[0]*dt,target[1]+vel[1]*dt,target[2]+vel[2]*dt)
        flat=max(0.1,math.hypot(p[0]-me[0],p[1]-me[1]))
        height=p[2]-me[2]
        disc=speed**4-gravity*(gravity*flat**2+2*height*speed**2)
        if disc<0:
            return None
        pitch=math.atan2(speed*speed-math.sqrt(disc),gravity*flat)
        flight=flat/(max(.2,math.cos(pitch))*speed)
        dt=.5*dt+.5*flight
    p=(target[0]+vel[0]*dt,target[1]+vel[1]*dt,target[2]+vel[2]*dt)
    flat=max(.1,math.hypot(p[0]-me[0],p[1]-me[1]))
    height=p[2]-me[2]
    disc=speed**4-gravity*(gravity*flat**2+2*height*speed**2)
    if disc<0: return None
    pitch=math.atan2(speed*speed-math.sqrt(disc),gravity*flat)
    return math.atan2(p[1]-me[1],p[0]-me[0]),pitch,p

class Bot:
    name = 'Survivor-v8'

    def __init__(self, hello):
        self.config=hello['config']
        self.rng=random.Random(hello['seed'])
        self.last_goal=None
        self.last_goal_time=-100
        self.last_damage_time=-100
        self.last_health=None
        self.prev_pos=None
        self.stuck_ticks=0
        self.strafe_sign=1 if self.rng.random()<0.5 else -1
        self.laser_held=False
        self.target_id=None

    def act(self, obs):
        me=obs['self']; pos=me['pos']; x,y,z=pos
        t=obs['t']; hp=me['hp']; energy=me['energy']; maxhp=me['max_hp']
        weapons=me['weapons']
        enemies=[e for e in obs['mechs'] if e['kind']=='mech']
        npcs=[e for e in obs['mechs'] if e['kind']=='npc']
        zone=obs['zone']; center=zone['center']; next_center=zone['next_center']
        current_radius=zone['radius']; next_radius=zone['next_radius']
        remaining=max(0.0,zone['shrink_end']-t)
        # Use shrinking target only when approaching the scheduled shrink.
        safe_radius=max(10.0,next_radius-20.0)
        dist_next=distance(pos,next_center)
        dist_current=distance(pos,center)
        zone_urgent=(not me['in_zone'] or dist_current>current_radius-25 or
            (remaining < max(15.0, (dist_next-safe_radius)/max(7.,me['stats'].get('walk_speed',11.7))+12)))
        # Prefer a location close to the next center if threatened by shrinking zone.
        tx,ty=(next_center[0],next_center[1])
        action={'tick':obs['tick']}
        if obs.get('offer'):
            choices=obs['offer']['choices']
            # Durable defensive upgrades, and mobility, generally improve placements.
            priorities={'armor':110, 'regen':105, 'health':100, 'hp':95, 'speed':90,
                        'energy':80, 'boost':78, 'gun_damage':65, 'gun_rate':62,
                        'laser_damage':65, 'laser_charge':68, 'lightning_damage':62,
                        'sensors':25}
            def upgrade_score(c):
                k=c['id'].lower(); desc=c.get('desc','').lower()
                val=priorities.get(k,50)
                if 'armor' in k or 'damage taken' in desc: val+=65
                if 'regen' in k or 'regen' in desc: val+=50
                if 'hp' in k or 'health' in k or 'max hp' in desc: val+=40
                if 'speed' in k or 'speed' in desc: val+=25
                return val
            action['pick']=max(range(len(choices)),key=lambda i: upgrade_score(choices[i]))

        # Select nearby loot, but do not aggressively chase loot when under fire.
        have={w['kind'] for w in weapons if w}
        loot_priority={'laser':4,'mortar':3,'lightning':2,'gun':0}
        best_pickup=None
        for p in obs.get('pickups',[]):
            if p['kind'] in have: continue
            d=distance(pos,p['pos'])
            if abs(p['pos'][2]-z)>9: continue
            if best_pickup is None or loot_priority[p['kind']]*8-d*.25 > best_pickup[0]:
                best_pickup=(loot_priority[p['kind']]*8-d*.25,p,d)
        close_enemies=[(e,distance(pos,e['pos'])) for e in enemies]
        nearest_enemy=min((d for _,d in close_enemies),default=1e6)
        endangered=nearest_enemy<65 or any(ev['type']=='damaged' for ev in obs.get('events',[]))
        if any(ev['type']=='damaged' for ev in obs.get('events',[])):
            self.last_damage_time=t
        if best_pickup:
            _,p,d=best_pickup
            if d<self.config['loot']['pickup_radius'] and (None in weapons):
                action['take']=p['id']
            if d<60 and not zone_urgent and not endangered and (None in weapons):
                tx,ty=p['pos'][:2]
        # Prefer cubes directly accessible (valuable scaling).
        cubes=[]
        for cube in obs['cubes']:
            d=distance(pos,cube['pos'])
            if abs(cube['pos'][2]-z)<5:
                cubes.append((d,cube))
        if cubes and not zone_urgent and nearest_enemy>45:
            d,cube=min(cubes,key=lambda q:q[0])
            if d<65: tx,ty=cube['pos'][:2]

        # Supply drops can restore full health and energy in addition to giving 3 cubes.
        # Only contest when the area is reasonably clear; otherwise survival dominates.
        for drop in obs.get('drops', []):
            dd=distance(pos,drop['pos'])
            time_to_land=max(0,drop['lands_in'])
            travel_time=dd/max(6.0,me['stats'].get('walk_speed',11.7))
            potential=(hp < maxhp*.65 or me['cubes']<5 or energy<30)
            if (potential and not zone_urgent and nearest_enemy>75 and
                dd<100 and travel_time<time_to_land+18 and
                distance(drop['pos'],next_center)<safe_radius):
                tx,ty=drop['pos'][:2]
                break

        # Avoid going towards numerous enemies. Maintain distance while staying in next circle.
        nearest=min(enemies,key=lambda e:distance(pos,e['pos']),default=None)
        if nearest and not zone_urgent:
            d=distance(pos,nearest['pos'])
            if d<70:
                ex,ey=nearest['pos'][:2]
                away=norm(x-ex,y-ey)
                tangent=(-away[1]*self.strafe_sign,away[0]*self.strafe_sign)
                if d<35: tx,ty=x+away[0]*80+tangent[0]*20,y+away[1]*80+tangent[1]*20
                else: tx,ty=x+tangent[0]*80+away[0]*30,y+tangent[1]*80+away[1]*30
        if obs['tick']%100==0: self.strafe_sign*=-1

        # Zone-safe steering: do not step beyond the next circle while kiting.
        if distance((tx,ty),next_center)>safe_radius:
            ux,uy=norm(tx-next_center[0],ty-next_center[1])
            tx,ty=next_center[0]+safe_radius*ux,next_center[1]+safe_radius*uy
        ux,uy=norm(tx-x,ty-y)
        # Repel from close projectiles when their velocity heads toward us.
        dodge_x=dodge_y=0.0
        for pr in obs['projectiles']:
            p=pr['pos']; v=pr['vel']
            vx,vy=v[:2]; speed2=vx*vx+vy*vy
            if speed2<1: continue
            future=max(0.,min(.9, ((x-p[0])*vx+(y-p[1])*vy)/speed2))
            cx=p[0]+vx*future; cy=p[1]+vy*future
            miss=math.hypot(x-cx,y-cy)
            if miss<13 and math.hypot(x-p[0],y-p[1])<110:
                # Signed cross product is -(v cross (me-projectile)). Dodge away, not in.
                side=-1 if (x-p[0])*vy-(y-p[1])*vx>0 else 1
                dx,dy=norm(-vy*side,vx*side)
                scale=(13-miss)/13
                dodge_x+=dx*scale; dodge_y+=dy*scale
        ux,uy=norm(ux+dodge_x*2.2,uy+dodge_y*2.2)
        if self.prev_pos is not None and math.hypot(x-self.prev_pos[0],y-self.prev_pos[1])<.15 and math.hypot(ux,uy)>.5:
            self.stuck_ticks+=1
        else:self.stuck_ticks=max(0,self.stuck_ticks-2)
        self.prev_pos=(x,y)
        if self.stuck_ticks>12:
            ux,uy=-uy*self.strafe_sign,ux*self.strafe_sign
        action['move']=[ux,uy]
        # Boost is precious for jetting across obstacles and escaping immediate danger.
        # Don't boost continuously in the air: it prevents energy regeneration.
        action['boost']=(not me['grounded'] and energy>65 and self.stuck_ticks>10) or (zone_urgent and energy>40 and dist_next>40 and me['grounded'])
        action['jump']=bool(me['grounded'] and self.stuck_ticks>20 and obs['tick']%16==0)

        # Target selection: mostly fire on mechs; only farm NPCs/crates when safe.
        target=None; target_is_crate=False
        # Farming nearby crates/drones is viable when no mech is an immediate threat.
        # A cube grants permanent combat scaling; don't shoot distant enemies all game.
        farming=[]
        if not endangered and nearest_enemy>90 and not zone_urgent:
            farming += [(distance(pos,e['pos'])+20,e,False) for e in npcs if distance(pos,e['pos'])<95]
            farming += [(distance(pos,c['pos'])+32,c,True) for c in obs['crates'] if distance(pos,c['pos'])<115]
        if farming:
            _,target,target_is_crate=min(farming,key=lambda q:q[0])
        elif enemies:
            def enemy_score(e):
                d=distance(pos,e['pos'])
                persistence=-15 if e['id']==self.target_id else 0
                return d + (e.get('hp',maxhp)/maxhp)*30 + (35 if d>200 else 0)+persistence
            target=min(enemies,key=enemy_score)
        elif not endangered:
            options=[(distance(pos,e['pos'])+25,e,False) for e in npcs]
            options += [(distance(pos,c['pos'])+45,c,True) for c in obs['crates']]
            if options:
                _,target,target_is_crate=min(options,key=lambda q:q[0])
        self.target_id=target['id'] if target else None
        aim_yaw=math.atan2(next_center[1]-y,next_center[0]-x)
        aim_pitch=0.0
        fire=[False,False]
        if target:
            tp=target['pos']; d=distance(pos,tp)
            aim_z=tp[2]+(1.6 if target.get('kind')=='npc' else 4.5)
            if target_is_crate: aim_z=tp[2]+2
            # Choose efficient weapon among loaded slots.
            priority=[]
            for i,w in enumerate(weapons):
                if not w: continue
                kind=w['kind']; stats=w['stats']; cd=w.get('cooldown',0)
                if kind=='gun' and d<min(stats.get('range',230),220): priority.append((2.0,i,kind))
                elif kind=='laser' and d<stats.get('range',280) and (cd<0.11 or w.get('charge',0)>0): priority.append((4.0,i,kind))
                elif kind=='lightning' and d<stats.get('range',45)*.91 and cd<0.11: priority.append((3.8,i,kind))
                elif kind=='mortar' and 28<d<150 and cd<0.11: priority.append((2.5,i,kind))
            if priority:
                _,slot,kind=max(priority)
                weapon=weapons[slot]; stats=weapon['stats']
                muzzle=[x,y,z+me['stats'].get('muzzle_height',7)]
                v=target.get('vel',[0,0,0])
                if kind=='gun':
                    predicted=intercept(muzzle,[tp[0],tp[1],aim_z],v,stats.get('speed',252),delay=.07)
                elif kind=='laser':
                    predicted=(tp[0]+v[0]*.08,tp[1]+v[1]*.08,aim_z+v[2]*.08)
                elif kind=='mortar':
                    predicted=(tp[0],tp[1],aim_z)
                else:predicted=(tp[0],tp[1],aim_z)
                aim_yaw=direction(pos,predicted)
                flat=max(1.,distance(pos,predicted))
                height=predicted[2]-muzzle[2]
                aim_pitch=math.atan2(height,flat)
                mortar_valid=True
                if kind=='mortar':
                    # Mortar has a different launch height and gravitational drop.
                    tube=[x,y,z+me['stats'].get('height',9)+0.5]
                    sol=mortar_solution(tube,[tp[0],tp[1],aim_z],v,
                        stats.get('speed',72),self.config['weapons']['mortar'].get('gravity',22))
                    mortar_valid=(sol is not None)
                    if sol is not None: aim_yaw,aim_pitch,predicted=sol
                yaw_error=abs(angle_diff(aim_yaw,me['aim'][0]))
                pitch_error=abs(aim_pitch-me['aim'][1])
                aligned=yaw_error<max(.04,math.atan2(3.,max(15.,d))) and pitch_error<.15
                if kind=='laser':
                    charge=weapon.get('charge',0)
                    fire[slot]=charge<stats.get('charge',.75)-.05 or not aligned
                elif kind=='lightning':
                    # A 30-degree *cone* does not need single-bullet precision.
                    cone=math.radians(stats.get('cone_deg',30))*0.5
                    fire[slot]=(energy>stats.get('energy',3)+5 and
                        yaw_error<min(.17,cone-.035) and pitch_error<.25)
                elif kind=='mortar':fire[slot]=mortar_valid and aligned and d>30
                else:fire[slot]=aligned and weapon.get('ammo',1)>0
                # Concurrent gun fire is useful with direct-aim lasers/lightning,
                # but firing a gun along a high mortar arc just wastes ammunition.
                for i,w in enumerate(weapons):
                    if i!=slot and w and w['kind']=='gun' and kind!='mortar' and d<200 and aligned:
                        fire[i]=w.get('ammo',1)>0
        else:
            # Rotate vision when no enemies are visible.
            aim_yaw=(t*.6)%(2*PI)-PI
        action['aim']=[aim_yaw,max(-1.2,min(1.2,aim_pitch))]
        # A charged laser must release its trigger to shoot, even if the target
        # disappears at the exact moment of release.
        for i,w in enumerate(weapons):
            if w and w['kind']=='laser':
                charge=w.get('charge',0)
                if not target and charge>0.12:
                    fire[i]=False
        action['fire']=fire
        # Keep v4 reload policy unchanged: our surrogate ablation did not show
        # a survival benefit from changing it. Test ammo optimization separately.
        if any(w and w['kind']=='gun' and w.get('ammo',0)<=2 and w.get('reload',0)<=0 for w in weapons):
            action['reload']=True
        return action

mf.run(Bot)
