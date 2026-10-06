#!/usr/bin/env python3
"""Build both direct-capture mocks and their matching archive; do not publish or deploy.

Responsibility: package the current capture jar over explicitly locked runtime bases.
Must not: substitute old capture images, push images or modify running services.
Contract: docs/CONTRACT.md and deploy/portainer/DIRECT-RABBIT.md.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True, help='Image prefix, e.g. ghcr.io/timaday/wiremock-lab')
    parser.add_argument('--tag', required=True, help='New unique tag for this build')
    args = parser.parse_args()
    build_directory = ROOT / 'target/direct-maven'
    subprocess.run(['mvn', '-B', '-ntp', f'-Dbenchmark.build.directory={build_directory}', 'package'],
                   cwd=ROOT, check=True)
    context = ROOT / 'target/direct-image'
    context.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(build_directory / 'capture.jar', context / 'capture.jar')
    lock = json.loads((ROOT / 'deploy/portainer/image-lock.json').read_text())
    build_args = []
    for runtime in ('official', 'headless', 'archive'):
        build_args += ['--build-arg', f'{runtime.upper()}_BASE={lock["images"][runtime]["reference"]}']
    images = {}
    for runtime in ('official', 'headless', 'archive'):
        image = f'{args.prefix}-{runtime}:{args.tag}'
        subprocess.run(['docker', 'build', '--file', str(Path(__file__).with_name('Dockerfile')),
                        '--target', f'direct-{runtime}', *build_args,
                        '--label', 'org.opencontainers.image.source=https://github.com/timaday/wiremock-benchmark',
                        '--tag', image, str(context)], check=True)
        images[runtime] = {'tag': image, 'id': subprocess.check_output(
            ['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()}
    (context / 'images.json').write_text(json.dumps(images, indent=2) + '\n')
    print(json.dumps(images, indent=2))


if __name__ == '__main__':
    main()
