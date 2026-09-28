long seq = props.get('bench.sequence').getAndIncrement()
def cases = props.get('bench.cases')
def c = cases[(int)(seq % cases.size())]
String id = props.getProperty('run_id') + '-' + String.format('%02d%010d', props.getProperty('engine_id').toInteger(), seq)
String prefix = '{"id":"' + id + '","padding":"'
String body = prefix + 'x'.repeat(c.size - prefix.length() - 2) + '"}'
vars.put('bench_id', id)
vars.put('case_id', c.id)
vars.put('delay_ms', c.delay.toString())
vars.put('payload_bytes', c.size.toString())
vars.put('body', body)
vars.putObject('case_spec', c)
