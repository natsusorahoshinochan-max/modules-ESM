"""Explicit collection assembly and conversion using public package files."""
from copy import deepcopy
import json
from shutil import copyfileobj
from uuid import uuid4

from protein_workbench_public.module_api import Delivery
from .formats import FORMAT, read_candidates, read_collection


def collect(packages, selected, runtime, *, evaluations=(), parameters=None):
    """Copy selected objects and explicit evaluation packages into one delivery.

    Source identities are allocated once and preserved through collection operations.
    Splitting and rejoining the same recorded source keeps one evaluation context.
    """
    folder = runtime.workdir / uuid4().hex
    folder.mkdir()
    files, sources, locations, copied, archived = {}, [], {}, {}, {}
    for index, package in enumerate((*packages, *evaluations)):
        role = 'candidate' if index < len(packages) else 'evaluation'
        if package.id in copied:
            previous = copied[package.id]
            locations.update({(index, offset): source for offset, source in previous.items()})
            for source in set(previous.values()):
                if role not in sources[source]['roles']:
                    sources[source]['roles'].append(role)
            continue
        if package.format == FORMAT:
            document = read_collection(package)
            source_rows = document['sources']
            object_sources = {i: item['source'] for i, item in enumerate(document['items'])}
        else:
            source_rows = [{'id': uuid4().hex, 'format': package.format, 'entry': package.entry,
                            'files': {key: key for key in package.files}, 'roles': [role]}]
            object_sources = {row['item']: 0 for row in read_candidates((package,))} if role == 'candidate' else {}
        source_indices = {}
        for offset, source in enumerate(source_rows):
            identity = source['id']
            if identity not in archived:
                mapping = {}
                for count, (original, package_key) in enumerate(source['files'].items()):
                    if runtime.cancelled:
                        raise InterruptedError('Collection cancelled')
                    target = f'sources/{len(sources)}/{count}'
                    destination = folder / target
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(package_key) as reader, destination.open('wb') as writer:
                        copyfileobj(reader, writer)
                    mapping[original] = target
                    files[target] = str(destination.relative_to(runtime.workdir))
                archived[identity] = len(sources)
                sources.append(dict(source, files=mapping))
            source_index = archived[identity]
            if role not in sources[source_index]['roles']:
                sources[source_index]['roles'].append(role)
            source_indices[offset] = source_index
        remapped = {item: source_indices[source] for item, source in object_sources.items()}
        copied[package.id] = remapped
        locations.update({(index, item): source for item, source in remapped.items()})
    document = {'sources': sources, 'items': [
        {'source': locations[row['input'], row['item']], 'object': deepcopy(row['object'])} for row in selected],
        'selected': [{key: row[key] for key in ('input', 'item')} for row in selected],
        'parameters': deepcopy(parameters or {})}
    manifest = folder / 'manifest.json'
    manifest.write_text(json.dumps(document, allow_nan=False))
    files['manifest.json'] = str(manifest.relative_to(runtime.workdir))
    return Delivery(FORMAT, 'manifest.json', files)
