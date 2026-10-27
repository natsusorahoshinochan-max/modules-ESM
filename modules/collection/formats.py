"""Standalone file reader for object collections; standard library only."""
import json


def read_collection(package):
    with package.open(package.entry) as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or not isinstance(document.get('items'), list) or not isinstance(document.get('sources'), list):
        raise ValueError('Collection requires items and complete source descriptions')
    identities = set()
    for source in document['sources']:
        if not isinstance(source, dict) or not isinstance(source.get('id'), str) or not source['id'] or source['id'] in identities:
            raise ValueError('Collection sources require unique assigned identities')
        identities.add(source['id'])
        if not isinstance(source.get('format'), str) or not isinstance(source.get('roles'), list):
            raise ValueError('Collection sources require their actual format and roles')
        if source.get('entry') not in source.get('files', {}):
            raise ValueError('Collection source is missing its original entry')
        for key in source['files'].values():
            if key not in package.files:
                raise ValueError('Collection source file is not declared')
            with package.open(key):
                pass
    for item in document['items']:
        if not isinstance(item, dict) or type(item.get('source')) is not int or not 0 <= item['source'] < len(document['sources']) or not isinstance(item.get('object'), dict):
            raise ValueError('Collection item requires its complete original object and source')
    return document


class SourcePackage:
    """Read an original source via its collection file map."""
    def __init__(self, package, source):
        self._package, self._source = package, source
        self.id = package.id
        self.format, self.entry = source['format'], source['entry']
        self.files = tuple(source['files'])

    def file_key(self, key):
        mapped = self._source['files'][key]
        return self._package.file_key(mapped) if isinstance(self._package, SourcePackage) else mapped

    def open(self, key):
        return self._package.open(self._source['files'][key])

    def metadata(self):
        return self._package.metadata()


FORMAT = 'workbench.collection'

def read_document(package):
    with package.open(package.entry) as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError('Candidate entry must be an object')
    return value


def _require_candidate_files(source, obj):
    required = []
    if 'structure' in obj or source.format in ('workbench.structure_set','workbench.prediction','workbench.structure_confidence'):
        required.append(('structure', obj.get('structure'), True))
    if source.format == 'workbench.proteinmpnn_design':
        required.append(('backbone structure', obj.get('backbone', {}).get('structure'), True))
    if source.format == 'workbench.esm3_generation':
        required.append(('original native generation', obj.get('native'), False))
    for role, descriptor, structural in required:
        key = descriptor.get('file') if isinstance(descriptor, dict) else None
        if not isinstance(key, str) or key not in source.files or (structural and descriptor.get('format') not in ('pdb','mmcif')):
            raise ValueError(f'Candidate requires its complete declared {role} file')
        try:
            with source.open(key) as reader:
                reader.read(1)
        except OSError as error:
            raise ValueError(f'Candidate {role} file is unreadable: {key}') from error


def read_candidates(packages):
    result = []
    for index, package in enumerate(packages):
        document = read_collection(package) if package.format == FORMAT else read_document(package)
        if package.format == FORMAT:
            objects = [item['object'] for item in document['items']]
        elif package.format == 'workbench.comparison':
            objects = [document['subject']]
        elif package.format == 'workbench.sequence_backbone_evaluation':
            # Each supplied joint evaluation context is one indivisible candidate.
            objects = []
            for evaluation in document.get('evaluations', []):
                ids = evaluation.get('object_ids')
                original = {obj.get('id'):obj for obj in document.get('objects', [])}
                if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or any(identity not in original for identity in ids):
                    raise ValueError('Joint candidate requires complete explicitly evaluated objects')
                members = [original[identity] for identity in ids]
                joint = {'members': members, 'label': 'Joint sequence context: '+', '.join(obj.get('label', f'Sequence {i+1}') for i,obj in enumerate(members))}
                if joint not in objects:
                    objects.append(joint)
        else:
            objects = document.get('objects')
        if not isinstance(objects, list) or any(not isinstance(obj, dict) or ('members' not in obj and not isinstance(obj.get('id'), str)) for obj in objects):
            raise ValueError('Candidates require explicit complete objects')
        for offset, obj in enumerate(objects):
            source = SourcePackage(package, document['sources'][document['items'][offset]['source']]) if package.format == FORMAT else package
            _require_candidate_files(source, obj)
            result.append({'input': index, 'item': offset, 'object': obj})
    return result
