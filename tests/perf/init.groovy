import groovy.json.JsonSlurper
import groovy.json.JsonOutput
import java.util.concurrent.atomic.AtomicLong

def cases = new JsonSlurper().parse(new File('/results/' + props.getProperty('run_id') + '/selected-cases.json'))
if (cases.isEmpty()) throw new IllegalArgumentException('Empty selected case catalogue')
props.put('bench.cases', cases)
props.put('bench.sequence', new AtomicLong())
if (props.getProperty('threads').toInteger() < 1 || props.getProperty('offered').toDouble() <= 0)
    throw new IllegalArgumentException('Engine rate and thread count must be positive')
long loadStart = props.getProperty('load_start_ms').toLong()
if (System.currentTimeMillis() > loadStart + 10000)
    throw new IllegalStateException('JMeter startup exceeded the declared 10-second allowance')
long duration = Math.ceil((props.getProperty('measure_end_ms').toLong() - System.currentTimeMillis()) / 1000.0) as long
if (duration <= 0) throw new IllegalStateException('Measurement window already ended')
props.setProperty('total_seconds', duration.toString())

props.setProperty('rate_per_min', (props.getProperty('offered').toBigDecimal() * 60).toPlainString())
