import datetime
import six
from decimal import Decimal
from django.core import serializers
from django.db import models
from django.utils.encoding import force_str

__all__ = ['serialize', 'flatten']


def serialize_model(obj, fields=None, include=None, exclude=None, fixup=None):
    include = include or []
    exclude = exclude or []

    fields = list(fields) if fields else [f.name for f in obj._meta.concrete_model._meta.local_fields]
    fields = [f for f in fields if f not in exclude]
    for i in include:
        if isinstance(i, (tuple, six.string_types)):
            fields.append(i)

    # If there are any duplicated items in `fields`, the latter one will override the former one during the following
    # querying of field values.

    data = {}
    for f in fields:
        if isinstance(f, tuple):
            k, v = f
            if callable(v):
                data[k] = v(obj)
            elif isinstance(v, dict):
                data[k] = serialize(getattr(obj, k), **v)
        else:
            v = getattr(obj, f)
            if isinstance(v, (datetime.datetime, datetime.date, datetime.time, Decimal)):
                data[f] = f'{v}'
            else:
                data[f] = force_str(v, strings_only=True)

    if fixup:
        data = fixup(data)

    return data


def serialize(src, fields=None, include=None, exclude=None, fixup=None, query_filter=None):
    """
    Serialize Model or a QuerySet instance to Python primitives.

    By default, all the model fields (and only the model fields) are serialized. If the field is a Python primitive, it
    is serialized as such, otherwise it is converted to string in utf-8 encoding.

    If `fields` is specified, it is a list of attribute descriptions to be serialized, replacing the default (all model
    fields). If `include` is specified, it is a list of attribute descriptions to add to the default list. If `exclude`
    is specified, it is a list of attribute descriptions to remove from the default list.

    Each attribute description can be either:

      * a string - includes a correspondingly named attribute of the object being serialized (eg. `name`, or
        `created_at`); this can be a model field, a property, class variable or anything else that's an attribute on
        the instance

      * a tuple, where the first element is a string key and the second is a function taking one argument - function
        will be run with the object being serialized as the argument, and the function result will be included in the
        result, with the key being the first tuple element

      * a tuple, where the first element is a related model attribute name and the second is a dictionary - related
        model instance(s) will be serialized recursively and added as sub-object(s) to the object being serialized;
        the dictionary may specify `fields`, `include`, `exclude` and `fixup` options for the related models following
        the same semantics as for the object being serialized.

    The `fixup` argument, if defined, is a function taking two arguments, the object being serialized, and the
    serialization result dict, and returning the modified serialization result. It's useful in cases where it's
    necessary to modify the result of the automatic serialization, but its use is discouraged if the same result can
    be obtained through the attribute descriptions.

    Example::

        serialize(obj, fields=[
            'name',   # obj.name
            'dob',    # obj.dob
            ('age', lambda obj: date.today() - obj.dob),
            ('jobs', dict(   # for job in obj.jobs.all()
                fields=[
                    'title',  # job.title
                    'from',   # job.from
                    'to',     # job.to,
                    ('duration', lambda job: job.to - job.from),
                ]
            ))
        ])

    Returns: a dict (if a single model instance was serialized) or a list of dicts (if a QuerySet was serialized) with
    the serialized data. The data returned is suitable for JSON serialization using Django's JSON serializer.
    """

    def subs(subsrc):
        return serialize(subsrc, fields=fields, include=include, exclude=exclude, fixup=fixup,
                         query_filter=query_filter)

    if isinstance(src, (models.Manager, models.query.QuerySet)):
        src = src.filter(query_filter) if query_filter else src.all()
        return [subs(i) for i in src]

    if isinstance(src, (list, set)):
        return [subs(i) for i in src]

    if isinstance(src, dict):
        return {k: subs(v) for k, v in src.items()}

    if isinstance(src, models.Model):
        return serialize_model(src, fields=fields, include=include, exclude=exclude, fixup=fixup)

    return src


def flatten(attname):
    """
    Fixup helper for serialize.

    Given an attribute name, returns a fixup function suitable for serialize() that will pull all items from the
    sub-dict and into the main dict. If any of the keys from the sub-dict already exist in the main dict, they'll
    be overwritten.
    """

    def fixup(data):
        for k, v in data[attname].items():
            data[k] = v
        del data[attname]
        return data

    return fixup
