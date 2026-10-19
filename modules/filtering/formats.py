"""Standalone file reader for filtering collections; standard library only."""
import json


def read_collection(package):
    with package.open(package.entry) as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or not isinstance(document.get('items'), list) or not isinstance(document.get('sources'), list):
        raise ValueError('Collection requires items and complete source descriptions')
    for source in document['sources']:
        if source.get('entry') not in source.get('files', {}):
            raise ValueError('Collection source is missing its original entry')
        for key in source['files'].values():
            if key not in package.files:
                raise ValueError('Collection source file is not declared')
            with package.open(key):
                pass
    for item in document['items']:
        if type(item.get('source')) is not int or not 0 <= item['source'] < len(document['sources']) or not isinstance(item.get('object'), dict):
            raise ValueError('Collection item requires its complete original object and source')
    return document


class SourcePackage:
    """Read an original source via its collection file map."""
    def __init__(self, package, source):
        self._package, self._source = package, source
        self.id = package.id
        self.format, self.entry = source['format'], source['entry']
        self.files = tuple(source['files'])

    def open(self, key):
        return self._package.open(self._source['files'][key])

    def metadata(self):
        return self._package.metadata()
