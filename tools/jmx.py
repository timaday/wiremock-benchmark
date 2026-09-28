"""Build the checked-in standard JMeter plan. No custom load-generator implementation."""

from xml.etree.ElementTree import Element, SubElement, ElementTree, indent


def prop(node, name, value, kind="stringProp"):
    SubElement(node, kind, name=name).text = str(value)


def script(parent, name, file, kind):
    node = SubElement(
        parent,
        kind,
        guiclass="TestBeanGUI",
        testclass=kind,
        testname=name,
        enabled="true",
    )
    prop(node, "scriptLanguage", "groovy")
    prop(node, "filename", "/work/tests/" + file)
    prop(node, "cacheKey", "true")
    SubElement(parent, "hashTree")


root = Element("jmeterTestPlan", version="1.2", properties="5.0", jmeter="5.6.3")
tree = SubElement(root, "hashTree")
plan = SubElement(
    tree,
    "TestPlan",
    guiclass="TestPlanGui",
    testclass="TestPlan",
    testname="WireMock durable-capture benchmark",
    enabled="true",
)
prop(plan, "TestPlan.serialize_threadgroups", "false", "boolProp")
pt = SubElement(tree, "hashTree")
setup = SubElement(
    pt,
    "SetupThreadGroup",
    guiclass="SetupThreadGroupGui",
    testclass="SetupThreadGroup",
    testname="Measurement clock and fixtures",
    enabled="true",
)
for k, v in [
    ("ThreadGroup.num_threads", 1),
    ("ThreadGroup.ramp_time", 0),
    ("ThreadGroup.on_sample_error", "stoptest"),
]:
    prop(setup, k, v)
loop = SubElement(
    setup,
    "elementProp",
    name="ThreadGroup.main_controller",
    elementType="LoopController",
    guiclass="LoopControlPanel",
    testclass="LoopController",
    enabled="true",
)
prop(loop, "LoopController.loops", 1)
prop(loop, "LoopController.continue_forever", "false", "boolProp")
st = SubElement(pt, "hashTree")
script(st, "Initialize run", "init.groovy", "JSR223Sampler")
group = SubElement(
    pt,
    "ThreadGroup",
    guiclass="ThreadGroupGui",
    testclass="ThreadGroup",
    testname="Reusable arrival clients",
    enabled="true",
)
for k, v in [
    ("ThreadGroup.num_threads", "${__P(threads)}"),
    ("ThreadGroup.ramp_time", 20),
    ("ThreadGroup.delay", 0),
    ("ThreadGroup.duration", "${__P(total_seconds)}"),
    ("ThreadGroup.on_sample_error", "continue"),
]:
    prop(group, k, v)
prop(group, "ThreadGroup.scheduler", "true", "boolProp")
loop = SubElement(
    group,
    "elementProp",
    name="ThreadGroup.main_controller",
    elementType="LoopController",
    guiclass="LoopControlPanel",
    testclass="LoopController",
    enabled="true",
)
prop(loop, "LoopController.loops", -1)
prop(loop, "LoopController.continue_forever", "false", "boolProp")
gt = SubElement(pt, "hashTree")
timer = SubElement(
    gt,
    "ConstantThroughputTimer",
    guiclass="TestBeanGUI",
    testclass="ConstantThroughputTimer",
    testname="Per-client pacing across this engine",
    enabled="true",
)
prop(timer, "throughput", "${__P(rate_per_min)}")
prop(timer, "calcMode", 2, "intProp")
SubElement(gt, "hashTree")
http = SubElement(
    gt,
    "HTTPSamplerProxy",
    guiclass="HttpTestSampleGui",
    testclass="HTTPSamplerProxy",
    testname="${case_id}",
    enabled="true",
)
for k, v in [
    ("HTTPSampler.domain", "${__P(host)}"),
    ("HTTPSampler.port", 8080),
    ("HTTPSampler.protocol", "http"),
    ("HTTPSampler.method", "POST"),
    ("HTTPSampler.path", "/bench/${case_id}"),
    ("HTTPSampler.implementation", "HttpClient4"),
    ("HTTPSampler.connect_timeout", 10000),
    ("HTTPSampler.response_timeout", 30000),
]:
    prop(http, k, v)
for k, v in [
    ("HTTPSampler.postBodyRaw", "true"),
    ("HTTPSampler.use_keepalive", "true"),
    ("HTTPSampler.follow_redirects", "false"),
]:
    prop(http, k, v, "boolProp")
args = SubElement(
    http, "elementProp", name="HTTPsampler.Arguments", elementType="Arguments"
)
col = SubElement(args, "collectionProp", name="Arguments.arguments")
arg = SubElement(col, "elementProp", name="", elementType="HTTPArgument")
prop(arg, "HTTPArgument.always_encode", "false", "boolProp")
prop(arg, "Argument.value", "${body}")
prop(arg, "Argument.metadata", "=")
ht = SubElement(gt, "hashTree")
script(ht, "Select exact workload", "request.groovy", "JSR223PreProcessor")
script(ht, "Check body and capture digests", "assert.groovy", "JSR223PostProcessor")
headers = SubElement(
    ht,
    "HeaderManager",
    guiclass="HeaderPanel",
    testclass="HeaderManager",
    testname="Correlation",
    enabled="true",
)
hc = SubElement(headers, "collectionProp", name="HeaderManager.headers")
for name, value in [
    ("Content-Type", "application/json"),
    ("X-Bench-Id", "${bench_id}"),
    ("X-Bench-Run", "${__P(run_id)}"),
]:
    h = SubElement(hc, "elementProp", name="", elementType="Header")
    prop(h, "Header.name", name)
    prop(h, "Header.value", value)
SubElement(ht, "hashTree")
indent(root)
ElementTree(root).write(
    "tests/perf/benchmark.jmx", encoding="UTF-8", xml_declaration=True
)
