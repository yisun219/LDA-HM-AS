#!/usr/bin/env python3
"""A small, durable Humanize Flow runtime with no model/backend dependency."""
from __future__ import annotations
import argparse, hashlib, json, os, sys, tempfile, uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

class Phase(str, Enum):
    SETUP='Setup'; IDEA='Gen-Idea'; PLAN='Gen-Plan'; IMPLEMENTATION='Implementation'
    REVIEW='Regular Review'; ALIGN='Full Alignment'; RECOVERY='Drift Recovery'
    CODE_REVIEW='Code Review'; FINALIZE='Finalize'; METHODOLOGY='Methodology Analysis'
    COMPLETE='Complete'; MAX_ITER='MaxIter'; STOP='Stop'; UNEXPECTED='Unexpected'
class Verdict(str, Enum):
    ADVANCED='ADVANCED'; STALLED='STALLED'; REGRESSED='REGRESSED'; COMPLETE='COMPLETE'; BLOCKED='BLOCKED'
GATES = ('goal_locked','baseline_captured','plan_approved','scope_guard','acceptance_criteria',
         'positive_evidence','negative_evidence','tests_pass','artifact_integrity',
         'reviewer_independence','drift_check','regression_check','budget_check',
         'full_alignment','human_approval')
def now(): return datetime.now(timezone.utc).isoformat()
class FlowError(RuntimeError): pass
@dataclass
class Gate:
    name: str; status: str='TODO'; evidence: str=''; note: str=''
@dataclass
class Round:
    number: int; lane: str; objective: str; contract: str; summary: str=''; review: str=''
    verdict: str=''; builder_session: str=''; reviewer_session: str=''
@dataclass
class State:
    run_id: str; goal: str; branch: str; base_commit: str; phase: str=Phase.SETUP.value
    iteration: int=0; max_iterations: int=20; plan_hash: str=''; plan_approved: bool=False
    builder_session: str=''; reviewer_sessions: list[str]=field(default_factory=list)
    drift_counter: int=0; stagnant_rounds: int=0; circuit_breaker: bool=False; stop_reason: str=''
    gates: dict[str,Gate]=field(default_factory=dict); rounds: list[Round]=field(default_factory=list)
    artifacts: list[str]=field(default_factory=list); events: int=0
    def dump(self): return asdict(self)
    @classmethod
    def load(cls, raw):
        raw=dict(raw); raw['gates']={k:Gate(**v) for k,v in raw.get('gates',{}).items()}
        raw['rounds']=[Round(**x) for x in raw.get('rounds',[])]
        return cls(**raw)
class Store:
    def __init__(self, root):
        self.root=Path(root).resolve(); self.meta=self.root/'.humanize'
    def mkdir(self): (self.meta/'artifacts').mkdir(parents=True,exist_ok=True); (self.meta/'rounds').mkdir(parents=True,exist_ok=True)
    def save(self, state):
        self.mkdir(); fd,tmp=tempfile.mkstemp(prefix='state.',dir=self.meta)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as f: json.dump(state.dump(),f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.meta/'state.json')
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def load(self):
        with (self.meta/'state.json').open(encoding='utf8') as f: return State.load(json.load(f))
    def event(self,state,kind,**data):
        self.mkdir(); state.events+=1; record={'seq':state.events,'at':now(),'kind':kind,**data}
        with (self.meta/'events.jsonl').open('a',encoding='utf8') as f: f.write(json.dumps(record,sort_keys=True)+'\n')
    def artifact(self, relative, value):
        path=self.meta/relative; path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('w',encoding='utf8') as f: json.dump(value,f,indent=2,sort_keys=True); f.write('\n')
        return str(path.relative_to(self.root))
    @staticmethod
    def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
class Humanize:
    def __init__(self,root): self.store=Store(root); self.state=self.store.load()
    @classmethod
    def init(cls,root,goal,branch='main',base_commit='',max_iterations=20):
        store=Store(root); store.mkdir(); state=State(uuid.uuid4().hex,goal,branch,base_commit,max_iterations=max_iterations,gates={x:Gate(x) for x in GATES})
        state.gates['goal_locked']=Gate('goal_locked','PASS',note='set at init')
        state.gates['reviewer_independence']=Gate('reviewer_independence','PASS',note='fresh sessions enforced')
        store.event(state,'initialized',goal=goal,branch=branch); store.save(state); return cls(root)
    def save(self,kind,**data): self.store.event(self.state,kind,**data); self.store.save(self.state)
    def idea(self,directions,primary,alternatives=None,evidence=None):
        if self.state.phase not in (Phase.SETUP.value,Phase.IDEA.value): raise FlowError('idea is not allowed in '+self.state.phase)
        if not directions or primary not in directions: raise FlowError('primary must be supplied in directions')
        value={'goal':self.state.goal,'directions':directions,'primary':primary,'alternatives':alternatives or [x for x in directions if x!=primary],'objective_evidence':evidence or [],'implementation_forbidden':True,'created_at':now()}
        path=self.store.artifact('artifacts/idea.json',value); self.state.artifacts.append(path); self.state.phase=Phase.PLAN.value; self.save('idea_drafted',artifact=path); return path
    def plan(self,value,approve=False):
        if self.state.phase not in (Phase.PLAN.value,Phase.IDEA.value): raise FlowError('plan is not allowed in '+self.state.phase)
        required=('objective','acceptance_criteria','positive_tests','negative_tests','path_boundaries'); missing=[x for x in required if not value.get(x)]
        if missing: raise FlowError('plan missing: '+', '.join(missing))
        value={**value,'original_draft':value.get('original_draft',value),'updated_at':now()}; path=self.store.artifact('artifacts/plan.json',value)
        self.state.plan_hash=self.store.digest(value); self.state.artifacts.append(path); self.state.phase=Phase.IMPLEMENTATION.value; self.state.plan_approved=approve
        for x in ('scope_guard','acceptance_criteria','plan_approved'):
            self.state.gates[x].status='PASS' if (x!='plan_approved' or approve) else 'TODO'
        self.save('plan_written',artifact=path,approved=approve,plan_hash=self.state.plan_hash); return path
    def approve_plan(self):
        if not self.state.plan_hash: raise FlowError('write a plan first')
        self.state.plan_approved=True; self.state.gates['plan_approved'].status='PASS'; self.save('plan_approved',plan_hash=self.state.plan_hash)
    def round(self,lane,objective):
        if not self.state.plan_approved: raise FlowError('plan must be approved')
        if self.state.circuit_breaker or self.state.phase in (Phase.STOP.value,Phase.COMPLETE.value): raise FlowError('run is closed')
        if self.state.iteration>=self.state.max_iterations: self.state.phase=Phase.MAX_ITER.value; self.state.stop_reason='maximum iterations reached'; self.save('max_iterations'); raise FlowError(self.state.stop_reason)
        if lane not in ('mainline','blocking','queued'): raise FlowError('lane must be mainline, blocking, or queued')
        self.state.iteration+=1; self.state.builder_session=self.state.builder_session or 'builder-'+uuid.uuid4().hex[:12]
        value={'round':self.state.iteration,'lane':lane,'objective':objective,'goal':self.state.goal,'plan_hash':self.state.plan_hash,'builder_session':self.state.builder_session,'created_at':now()}
        path=self.store.artifact('rounds/%04d/contract.json'%self.state.iteration,value); self.state.rounds.append(Round(self.state.iteration,lane,objective,path,builder_session=self.state.builder_session)); self.state.phase=Phase.IMPLEMENTATION.value; self.save('round_started',round=self.state.iteration,artifact=path); return path
    def builder_stop(self,summary,paths=None,tests=None):
        if not self.state.rounds: raise FlowError('start a round first')
        current=self.state.rounds[-1]; value={'round':current.number,'summary':summary,'changed_paths':paths or [],'tests':tests or [],'plan_hash':self.state.plan_hash,'created_at':now()}; path=self.store.artifact('rounds/%04d/builder-summary.json'%current.number,value); current.summary=path; self.state.phase=Phase.REVIEW.value; self.save('builder_stopped',artifact=path); return path
    def review(self,verdict,summary,issues=None,evidence=None):
        current=self.current(); verdict=Verdict(verdict).value; reviewer='reviewer-'+uuid.uuid4().hex[:12]; self.state.reviewer_sessions.append(reviewer)
        value={'round':current.number,'reviewer_session':reviewer,'verdict':verdict,'summary':summary,'issues':issues or [],'evidence':evidence or [],'created_at':now()}; path=self.store.artifact('rounds/%04d/review.json'%current.number,value)
        current.review,current.reviewer_session,current.verdict=path,reviewer,verdict; self.apply_verdict(verdict); self.save('review_recorded',round=current.number,verdict=verdict,reviewer_session=reviewer,artifact=path); return path
    def apply_verdict(self,verdict):
        if verdict==Verdict.ADVANCED.value: self.state.stagnant_rounds=0; self.state.drift_counter=max(0,self.state.drift_counter-1); self.state.phase=Phase.IMPLEMENTATION.value
        elif verdict==Verdict.STALLED.value: self.state.stagnant_rounds+=1; self.state.phase=Phase.RECOVERY.value if self.state.stagnant_rounds>=2 else Phase.IMPLEMENTATION.value; self.stop('circuit breaker: three stalled rounds') if self.state.stagnant_rounds>=3 else None
        elif verdict==Verdict.REGRESSED.value: self.state.drift_counter+=1; self.state.stagnant_rounds=0; self.state.phase=Phase.RECOVERY.value
        elif verdict==Verdict.COMPLETE.value: self.state.phase=Phase.ALIGN.value
        else: self.state.phase=Phase.STOP.value; self.state.stop_reason='reviewer blocked the run'
    def gate(self,name,status,evidence='',note=''):
        if name not in self.state.gates: raise FlowError('unknown gate: '+name)
        status=status.upper()
        if status not in ('TODO','PASS','FAIL','BLOCKED','NA'): raise FlowError('invalid gate status')
        if status in ('PASS','NA') and not evidence and name not in ('goal_locked','reviewer_independence'): raise FlowError('passing gate needs evidence')
        self.state.gates[name]=Gate(name,status,evidence,note); self.save('gate_updated',gate=name,status=status,evidence=evidence)
    def human_approve(self): self.state.gates['human_approval']=Gate('human_approval','PASS',note='explicit CLI approval'); self.save('human_approved')
    def finalize(self):
        if not all(x.status in ('PASS','NA') for x in self.state.gates.values()): raise FlowError('all gates must pass or be NA')
        if not self.state.rounds or self.state.rounds[-1].verdict!=Verdict.COMPLETE.value: raise FlowError('fresh reviewer COMPLETE required')
        self.state.phase=Phase.FINALIZE.value; self.save('finalize_started')
    def complete(self):
        if self.state.phase!=Phase.FINALIZE.value: raise FlowError('run finalize first')
        self.state.phase=Phase.COMPLETE.value; self.save('completed')
    def resume(self): self.state=self.store.load(); self.save('resumed',phase=self.state.phase,iteration=self.state.iteration); return self
    def stop(self,reason): self.state.circuit_breaker=True; self.state.phase=Phase.STOP.value; self.state.stop_reason=reason
    def current(self):
        if not self.state.rounds: raise FlowError('start a round first')
        current=self.state.rounds[-1]
        if not current.summary: raise FlowError('builder must stop before review')
        return current
def cli():
    p=argparse.ArgumentParser(prog='humanize'); s=p.add_subparsers(dest='cmd',required=True)
    q=s.add_parser('init'); q.add_argument('root'); q.add_argument('--goal',required=True); q.add_argument('--branch',default='main'); q.add_argument('--base-commit',default=''); q.add_argument('--max-iterations',type=int,default=20)
    q=s.add_parser('idea'); q.add_argument('root'); q.add_argument('--primary',required=True); q.add_argument('--alternative',action='append',default=[]); q.add_argument('--evidence',action='append',default=[])
    q=s.add_parser('plan'); q.add_argument('root'); q.add_argument('--file',required=True); q.add_argument('--approve',action='store_true')
    q=s.add_parser('approve-plan'); q.add_argument('root'); q=s.add_parser('round'); q.add_argument('root'); q.add_argument('--lane',required=True); q.add_argument('--objective',required=True)
    q=s.add_parser('builder-stop'); q.add_argument('root'); q.add_argument('--summary',required=True); q.add_argument('--path',action='append',default=[]); q.add_argument('--test',action='append',default=[])
    q=s.add_parser('review'); q.add_argument('root'); q.add_argument('--verdict',choices=[x.value for x in Verdict],required=True); q.add_argument('--summary',required=True); q.add_argument('--issue',action='append',default=[]); q.add_argument('--evidence',action='append',default=[])
    q=s.add_parser('gate'); q.add_argument('root'); q.add_argument('--name',required=True); q.add_argument('--status',required=True); q.add_argument('--evidence',default=''); q.add_argument('--note',default='')
    for name in ('human-approve','finalize','complete','resume','status'): q=s.add_parser(name); q.add_argument('root')
    a=p.parse_args();
    try:
        if a.cmd=='init': out={'initialized':True}; Humanize.init(a.root,a.goal,a.branch,a.base_commit,a.max_iterations)
        else:
            h=Humanize(a.root)
            if a.cmd=='idea': out={'artifact':h.idea([a.primary,*a.alternative],a.primary,a.alternative,a.evidence)}
            elif a.cmd=='plan': out={'artifact':h.plan(json.loads(Path(a.file).read_text()),a.approve)}
            elif a.cmd=='approve-plan': h.approve_plan(); out={'approved':True}
            elif a.cmd=='round': out={'artifact':h.round(a.lane,a.objective)}
            elif a.cmd=='builder-stop': out={'artifact':h.builder_stop(a.summary,a.path,a.test)}
            elif a.cmd=='review': out={'artifact':h.review(a.verdict,a.summary,a.issue,a.evidence)}
            elif a.cmd=='gate': h.gate(a.name,a.status,a.evidence,a.note); out={'updated':a.name}
            elif a.cmd=='human-approve': h.human_approve(); out={'approved':True}
            elif a.cmd=='finalize': h.finalize(); out={'phase':h.state.phase}
            elif a.cmd=='complete': h.complete(); out={'phase':h.state.phase}
            elif a.cmd=='resume': h.resume(); out={'phase':h.state.phase,'iteration':h.state.iteration}
            elif a.cmd=='status': out=h.state.dump()
            else: raise AssertionError(a.cmd)
        print(json.dumps(out,indent=2,sort_keys=True)); return 0
    except (FlowError,OSError,ValueError,json.JSONDecodeError) as e: print('humanize: '+str(e),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(cli())
