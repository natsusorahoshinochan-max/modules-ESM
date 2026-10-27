"""Standalone reader for delivered existing-metric analysis files."""
import json
import math


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def positions(value):
    if not isinstance(value, list) or not value:
        raise ValueError('Region requires a nonempty actual-position array')
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'chain', 'author_number', 'insertion_code'}
                or not isinstance(item['chain'], str) or type(item['author_number']) is not int
                or not isinstance(item['insertion_code'], str)):
            raise ValueError('Region requires actual chain, integer author number and insertion code')
    keys = [(p['chain'], p['author_number'], p['insertion_code']) for p in value]
    if len(set(keys)) != len(keys):
        raise ValueError('Region contains ambiguous repeated actual positions')
    return keys


def read_analysis(package):
    """Read independently of producer modules and source projects."""
    with package.open(package.entry) as reader:
        document = json.load(reader)
    if not isinstance(document.get('sources'), list) or not isinstance(document.get('analyses'), list):
        raise ValueError('Analysis requires source descriptions and analyses')
    for source in document['sources']:
        if source.get('entry') not in source.get('files', {}):
            raise ValueError('Analysis source requires its original entry')
        for key in source['files'].values():
            with package.open(key):
                pass
    for analysis in document['analyses']:
        values = analysis.get('input_values')
        if not isinstance(values, list) or not values or not all(finite(v) for v in values):
            raise ValueError('Analysis requires finite existing input values')
        axis = analysis.get('positions')
        if axis is not None and len(positions(axis)) != len(values):
            raise ValueError('Analysis position correspondence must cover every input value')
        if not isinstance(analysis.get('unit'), str) or not analysis['unit'] or not analysis.get('source_method'):
            raise ValueError('Analysis requires actual source method and unit')
        if not all(finite(analysis.get('statistics', {}).get(key)) for key in ('count', 'mean', 'minimum', 'maximum')):
            raise ValueError('Analysis requires finite statistics')
    return document
