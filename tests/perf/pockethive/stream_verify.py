"""Bounded-memory verifier for the explicitly defined endurance dataset format."""
import argparse,csv,gzip,hashlib,importlib.util,json,re,sqlite3,time,zlib
from collections import Counter
from datetime import datetime
from pathlib import Path

def stamp(s):return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
def percentile(hist,p):
 target=int(sum(hist.values())*p);total=0
 for value,count in sorted(hist.items()):
  total+=count
  if total>target:return value
 raise ValueError('Empty histogram')

def verify(args):
 manifest=json.loads((args.bundle/'benchmark.json').read_text());assert manifest['mode']=='endurance'
 expected=manifest['expectedRequests'];rows=expected//4;run=manifest['runId'];cases=manifest['cases']
 assert expected==rows*4
 with (args.bundle/'datasets/shared.csv').open() as f:
  count=0
  for seq,row in enumerate(csv.DictReader(f)):
   case=cases[seq%len(cases)]
   assert row=={'sequence':f'{seq:010d}','caseId':case['id'],'size':str(case['size'])}
   count+=1
  assert count==rows
 spec=importlib.util.spec_from_file_location('fixtures',args.canonical_repo/'tools/fixtures.py');fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
 assert not args.database.exists();db=sqlite3.connect(args.database)
 db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA synchronous=OFF');db.execute('PRAGMA cache_size=-65536');db.execute('PRAGMA temp_store=FILE')
 db.execute('CREATE TABLE results(id TEXT PRIMARY KEY,size INTEGER,request_sha TEXT,response_sha TEXT,offered REAL,collected REAL,valid INTEGER) WITHOUT ROWID')
 count=0;errors=Counter();headers=Counter();pipeline=Counter();lane_min={};lane_max={};batch=[]
 case_headers={case['id']:Counter() for case in cases};case_errors=Counter()
 with gzip.open(args.results,'rt') as f:
  for line in f:
   r=json.loads(line);count+=1;identifier=r['bench_id'];valid_id=re.fullmatch(re.escape(run)+r'-(0[0-3])(\d{10})',identifier)
   if not valid_id or int(valid_id[2])>=rows:
    errors['unexpectedId']+=1;continue
   lane=int(valid_id[1]);seq=int(valid_id[2]);case=cases[seq%len(cases)];size=case['size']
   empty=json.dumps({'id':identifier,'padding':''},separators=(',',':'))
   body=json.dumps({'id':identifier,'padding':'x'*(size-len(empty))},separators=(',',':'))
   request_hash=hashlib.sha256(body.encode()).hexdigest();response_hash=hashlib.sha256(fixtures.response(case['template'],size,identifier).encode()).hexdigest()
   checks={'status':r['status']==200 and r['outcome']=='http_response','path':r['path']=='/bench/'+case['id'],'requestHash':r['request_sha256']==request_hash,'responseHash':r['response_sha256']==response_hash}
   case_headers[case['id']][r['http_header_duration_ms']]+=1
   if not all(checks.values()):case_errors[case['id']]+=1
   for key,ok in checks.items():
    if not ok:errors[key]+=1
   offered=stamp(r['offered_at']);collected=stamp(r['collected_at']);headers[r['http_header_duration_ms']]+=1;pipeline[round((collected-offered)*1000)]+=1
   lane_min[lane]=min(lane_min.get(lane,offered),offered);lane_max[lane]=max(lane_max.get(lane,offered),offered)
   batch.append((identifier,size,request_hash,response_hash,offered,collected,int(all(checks.values()))))
   if len(batch)>=10000:
    before=db.total_changes;db.executemany('INSERT OR IGNORE INTO results VALUES(?,?,?,?,?,?,?)',batch);errors['duplicateId']+=len(batch)-(db.total_changes-before);db.commit();batch=[]
   if count%100000==0:print(json.dumps({'phase':'verify-results','count':count}),flush=True)
 if batch:
  before=db.total_changes;db.executemany('INSERT OR IGNORE INTO results VALUES(?,?,?,?,?,?,?)',batch);errors['duplicateId']+=len(batch)-(db.total_changes-before);db.commit()
 unique=db.execute('SELECT count(*) FROM results').fetchone()[0];valid=db.execute('SELECT count(*) FROM results WHERE valid=1').fetchone()[0]
 db.execute('ATTACH DATABASE ? AS capture',(f'file:{args.archive}?mode=ro',))
 capture_count=db.execute('SELECT count(*) FROM capture.events WHERE run_id=?',(run,)).fetchone()[0]
 malformed=db.execute("SELECT count(*) FROM (SELECT request_id FROM capture.events WHERE run_id=? GROUP BY request_id HAVING count(*) !=3 OR sum(phase='REQUEST') !=1 OR sum(phase='RESPONSE_PREPARED') !=1 OR sum(phase='SEND_COMPLETED') !=1)",(run,)).fetchone()[0]
 capture_mismatch=db.execute("SELECT count(*) FROM capture.events e LEFT JOIN results r ON e.request_id=r.id WHERE e.run_id=? AND (r.id IS NULL OR (e.phase='REQUEST' AND (e.body_bytes!=r.size OR e.body_sha256!=r.request_sha)) OR (e.phase='RESPONSE_PREPARED' AND (e.body_bytes!=r.size OR e.body_sha256!=r.response_sha)))",(run,)).fetchone()[0]
 start=max(lane_min.values())+manifest['warmupSeconds'];duration=manifest['measurementSeconds'];end=start+duration
 bins={'REQUEST':[0]*(duration//60),'SEND_COMPLETED':[0]*(duration//60)};seen=0
 for phase,compressed in db.execute("SELECT phase,payload_zlib FROM capture.events WHERE run_id=? AND phase IN ('REQUEST','SEND_COMPLETED')",(run,)):
  prefix=zlib.decompressobj().decompress(compressed,4096);m=re.search(rb'"timestampMs":(\d+)',prefix);assert m,'Missing canonical capture timestamp'
  t=int(m[1])/1000
  if start<=t<end:bins[phase][int((t-start)//60)]+=1
  seen+=1
  if seen%500000==0:print(json.dumps({'phase':'verify-capture-timing','count':seen}),flush=True)
 metrics=json.loads(args.metrics.read_text());delivery_ok=metrics['enabled'] and metrics['brokerConnected'] and metrics['errors']==metrics['pending']==0 and metrics['committed']==metrics['confirmed']
 summary={'runId':run,'expected':expected,'collected':count,'unique':unique,'valid':valid,'missing':expected-unique,'errors':dict(errors),'captureEvents':capture_count,'malformedCaptureIds':malformed,'captureMismatchEvents':capture_mismatch,'captureDelivery':metrics,'measurementStartEpoch':start,'measurementSeconds':duration,'laneArrivalSpansSeconds':{str(k):lane_max[k]-lane_min[k] for k in lane_min},'lanesCoverWindow':len(lane_min)==4 and all(t>=end for t in lane_max.values()),'httpHeaderLatencyMs':{n:percentile(headers,p) for n,p in [('p50',.5),('p95',.95),('p99',.99)]},'pipelineLatencyMs':{n:percentile(pipeline,p) for n,p in [('p50',.5),('p95',.95),('p99',.99)]}}
 summary['observedOfferedRps']=db.execute('SELECT count(*) FROM results WHERE offered>=? AND offered<?',(start,end)).fetchone()[0]/duration
 summary['validCollectedRps']=db.execute('SELECT count(*) FROM results WHERE valid=1 AND collected>=? AND collected<?',(start,end)).fetchone()[0]/duration
 summary['serverReceivedRps']=sum(bins['REQUEST'])/duration;summary['serverCompletedRps']=sum(bins['SEND_COMPLETED'])/duration
 summary['perMinuteServerCompletedRps']=[n/60 for n in bins['SEND_COMPLETED']]
 summary['integrityPassed']=count==unique==valid==expected and not any(errors.values()) and capture_count==expected*3 and malformed==capture_mismatch==0 and delivery_ok
 summary['ratePassed']=summary['lanesCoverWindow'] and summary['validCollectedRps']>=1000 and min(summary['perMinuteServerCompletedRps'])>=1000
 summary['cases']=[dict(case,requests=sum(case_headers[case['id']].values()),errors=case_errors[case['id']],httpHeaderLatencyMs={n:percentile(case_headers[case['id']],p) for n,p in [('p50',.5),('p95',.95),('p99',.99)]}) for case in cases]
 args.output.write_text(json.dumps(summary,indent=2)+'\n');db.close();print(json.dumps(summary),flush=True)
 return 0 if summary['integrityPassed'] and summary['ratePassed'] else 2
if __name__=='__main__':
 p=argparse.ArgumentParser()
 for name in ['bundle','results','archive','metrics','canonical-repo','database','output']:p.add_argument('--'+name,required=True,type=Path)
 raise SystemExit(verify(p.parse_args()))
