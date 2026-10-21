"""Select exact Windows 3.13 wheels and hashes from the existing uv lock.

Avoid re-resolving package versions against an index during cross packaging.
An optional mirror changes transport only; artifact hashes remain unchanged.
"""
import argparse
import os
import sys
import tomllib
import urllib.request
import urllib.error
from pathlib import Path
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import cpython_tags, compatible_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

parser = argparse.ArgumentParser()
parser.add_argument('exported', type=Path)
parser.add_argument('lockfile', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--roots', nargs='+')
parser.add_argument('--exclude-requirements', type=Path)
options = parser.parse_args()
exported, lockfile, output = options.exported, options.lockfile, options.output
environment = {**default_environment(), 'os_name':'nt','sys_platform':'win32','platform_system':'Windows','platform_machine':'AMD64','python_version':'3.13','python_full_version':'3.13.15','implementation_version':'3.13.15','extra':''}
tags = list(cpython_tags((3,13),abis=['cp313'],platforms=['win_amd64'])) + list(compatible_tags((3,13),interpreter='cp313',platforms=['win_amd64']))
priority = {tag:index for index,tag in enumerate(tags)}
packages = tomllib.loads(lockfile.read_text())['package']
included = None
if options.roots:
    by_name = {canonicalize_name(package['name']): package for package in packages}
    included = set()
    pending = [canonicalize_name(name) for name in options.roots]
    while pending:
        name = pending.pop()
        if name in included: continue
        included.add(name)
        pending.extend(canonicalize_name(item['name']) for item in by_name.get(name, {}).get('dependencies', []))
excluded = set()
if options.exclude_requirements:
    for line in options.exclude_requirements.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            excluded.add(canonicalize_name(line.split('@', 1)[0].strip()))
lines=[]
for line in exported.read_text().replace('\\\n',' ').splitlines():
    line=line.strip()
    if not line or line.startswith('#'): continue
    requirement=Requirement(line.split('--hash=')[0].strip())
    if requirement.marker and not requirement.marker.evaluate(environment): continue
    normalized = canonicalize_name(requirement.name)
    if included is not None and normalized not in included: continue
    if normalized in excluded: continue
    package=next(p for p in packages if canonicalize_name(p['name'])==canonicalize_name(requirement.name) and p['version'] in requirement.specifier)
    candidates=[]
    for wheel in package.get('wheels',[]):
        matches=parse_wheel_filename(wheel['url'].split('/')[-1])[3] & priority.keys()
        if matches: candidates.append((min(priority[tag] for tag in matches),wheel))
    if not candidates: raise RuntimeError(f'No Windows CPython 3.13 wheel: {requirement}')
    wheel=min(candidates,key=lambda row:row[0])[1]
    url=wheel['url']
    if os.environ.get('AICS_PYPI_MIRROR'):
        url=url.replace('https://files.pythonhosted.org/packages/',os.environ['AICS_PYPI_MIRROR'].rstrip('/')+'/packages/')
        try:
            with urllib.request.urlopen(urllib.request.Request(url,method='HEAD'),timeout=5): pass
        except urllib.error.HTTPError as error:
            if error.code == 404: url=wheel['url']
        except OSError:
            pass  # uv still performs its own bounded retries and hash check.
    lines.append(f"{requirement.name} @ {url} --hash={wheel['hash']}")
output.write_text('\n'.join(lines)+'\n')
print(f'Selected {len(lines)} verified Windows wheels')
