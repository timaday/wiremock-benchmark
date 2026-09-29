"""Injector identity derived from its pinned build dependency, shared by run and suite."""

from pathlib import Path
import xml.etree.ElementTree as ET

POM = Path(__file__).resolve().parents[1] / "tests/perf/gatling/pom.xml"
NS = {"m": "http://maven.apache.org/POM/4.0.0"}
DEPENDENCY = ET.parse(POM).find(
    ".//m:dependency[m:artifactId='gatling-charts-highcharts']", NS
)
GENERATOR = "gatling-" + DEPENDENCY.findtext("m:version", namespaces=NS)
ARRIVAL_MODEL = "Gatling constantUsersPerSec, one request per user"
