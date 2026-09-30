"""Verify portable-lab smoke archives and provisioned monitoring (not a load verdict)."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request

ARCHIVE_CHECK = '''import sqlite3,json,zlib,base64,hashlib
run = RUN_DATA
db=sqlite3.connect('file:/archive/events.db?mode=ro',uri=True)
rows=db.execute('SELECT request_id,phase,body_bytes,body_sha256,payload_zlib FROM events WHERE run_id=?',(run['runId'],)).fetchall()
assert len(rows)==36,len(rows)
for request in run['requests']:
 events={row[1]:row for row in rows if row[0]==request['id']}
 assert set(events)=={'REQUEST','RESPONSE_PREPARED','SEND_COMPLETED'}
 for phase,key in [('REQUEST','requestSha256'),('RESPONSE_PREPARED','responseSha256')]:
  row=events[phase];body=base64.b64decode(json.loads(zlib.decompress(row[4]))['bodyBase64'])
  assert row[2]==len(body)==request['size']
  assert row[3]==hashlib.sha256(body).hexdigest()==request[key]
print(json.dumps({'runtime':run['runtime'],'requests':12,'events':len(rows),'integrityPassed':True}))
'''


def main(args):
    def query(expression):
        url=args.prometheus_url.rstrip('/')+'/api/v1/query?'+urllib.parse.urlencode({'query':expression})
        with urllib.request.urlopen(url,timeout=10) as response:
            data=json.load(response)
        assert data['status']=='success',expression
        return data['data']['result']

    # The fresh-stack check requires exactly this smoke's counters; do not mix load into it.
    expected={'up{job="wiremock"}':1, 'wiremock_http_completed_total':12,
              'wiremock_http_timing_missing_total':0, 'wiremock_http_errors_total':0,
              'wiremock_capture_pending':0, 'wiremock_capture_confirmed_total':36,
              'wiremock_http_duration_seconds_count':12}
    deadline=time.monotonic()+45
    while True:
        observed={name:query(name) for name in expected}
        ready=all(len(observed[name])==2 and all(float(item['value'][1])==value for item in observed[name])
                  for name,value in expected.items())
        if ready:break
        assert time.monotonic()<deadline,'Counters did not converge: '+json.dumps(observed)
        time.sleep(1)
    assert all(float(x['value'][1])>=72 for x in query('wiremock_http_duration_seconds_sum'))
    assert all(float(x['value'][1])>0 for x in query('wiremock_jvm_heap_used_bytes'))
    user=os.environ['GRAFANA_USER'];password=os.environ['GRAFANA_PASSWORD']
    auth=base64.b64encode((user+':'+password).encode()).decode()
    request=urllib.request.Request(args.grafana_url.rstrip('/')+'/api/dashboards/uid/wiremock-comparison',headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(request,timeout=10) as response:
        dashboard=json.load(response)['dashboard']
    assert dashboard['uid']=='wiremock-comparison' and len(dashboard['panels'])==17
    checked=0
    for panel in dashboard['panels']:
        for target in panel.get('targets',[]):
            expression=target['expr'].replace('$runtime','.*').replace('$__rate_interval','10m')
            if args.broker_mode=='pockethive' and expression.startswith('rabbitmq_'):continue
            assert query(expression),panel['title']
            checked+=1
    archives=[]
    runs=json.loads(args.results.read_text())
    assert {run['runtime'] for run in runs}=={'official','headless'} and len(runs)==2
    for run in runs:
        assert len(run['requests'])==12
        volume=args.stack+'_'+run['runtime']+'-archive'
        # Fail if absent; never create a substitute empty volume on the wrong node.
        subprocess.run(['docker','volume','inspect',volume],stdout=subprocess.DEVNULL,check=True)
        result=subprocess.run(['docker','run','--rm','-i','-v',volume+':/archive:ro','python:3.12-slim','python','-'],
            input=ARCHIVE_CHECK.replace('RUN_DATA',repr(run)),text=True,capture_output=True,check=True)
        archives.append(json.loads(result.stdout))
    summary={'stack':args.stack,'brokerMode':args.broker_mode,'archives':archives,
             'dashboardPanels':len(dashboard['panels']),'queriesReturningData':checked,
             'metrics':observed,'browserVisualCheck':'unverified','passed':True}
    args.output.write_text(json.dumps(summary,indent=2)+'\n')
    print('PASS: 24 client results, 72 exact archived captures, both metric targets, all configured dashboard queries')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for option in ['stack','prometheus-url','grafana-url']:p.add_argument('--'+option,required=True)
    p.add_argument('--broker-mode',choices=['standalone','pockethive'],required=True)
    p.add_argument('--results',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())
