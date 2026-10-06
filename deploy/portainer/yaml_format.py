"""Render Portainer YAML with sequences indented beneath their mapping keys."""
import yaml


class IndentedSafeDumper(yaml.SafeDumper):
    """Own sequence indentation only; preserve PyYAML's safe scalar serialization."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def stack_yaml(content):
    return yaml.dump(content, Dumper=IndentedSafeDumper, sort_keys=False)


def _string(dumper, value):
    return dumper.represent_scalar('tag:yaml.org,2002:str', value,
                                   style='|' if '\n' in value else None)


IndentedSafeDumper.add_representer(str, _string)
