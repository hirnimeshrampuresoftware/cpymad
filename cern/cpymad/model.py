"""
Models encapsulate metadata for accelerator machines.

For more information about models, see :class:`Model`.

The following example demonstrates how to create a Model instance given that
you have model definition files ready on your file system:

.. code-block:: python

    >>> from cern.resource.file import FileResource
    >>> from cern.cpymad.model import Factory
    >>> load_model = Factory(FileResource('/path/to/model/definitions'))
    >>> model = load_model('LHC')
"""

from __future__ import absolute_import

import logging
import os

from . import madx
from . import util
from ..resource.file import FileResource


__all__ = [
    'Model',
    'Beam',
    'Optic',
    'Sequence',
    'Range',
    'Factory',
    'Locator',
]


def _deserialize(data, cls, *args):
    """Create an instance dictionary from a data dictionary."""
    return {key: cls(key, val, *args) for key, val in data.items()}


def _serialize(data):
    """Create a data dictionary from an instance dictionary."""
    return {key: val.data for key, val in data.items()}


class Model(object):

    """
    A model is a complete description of an accelerator machine.

    This class is used to bundle all metadata related to an accelerator and
    all its configurations. It takes care of loading the proper MAD-X files
    when needed.

    Model instances are created using :class:`Factory` instances which require
    a :class:`ResourceProvider` to iterate and load available model
    definitions.

    Instance variables
    ==================

    Only GET access is allowed to all instance variables at the moment.

    Model attributes
    ~~~~~~~~~~~~~~~~

    :ivar str name: model name
    :ivar dict beams: known :class:`Beam`s
    :ivar dict optics: known :class:`Optic`s
    :ivar dict sequences: known :class:`Sequence`s

    Underlying resources and handlers
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    :ivar Madx madx: handle to the MAD-X library
    :ivar dict _data: model definition data
    :ivar ResourceProvider _repo: resource access
    """

    def __init__(self, name, data, repo, madx):
        """
        Initialize a Model object.

        :param str name: model name
        :param dict data: model definition data
        :param ResourceProvider repo: resource repository
        :param Madx madx: MAD-X instance to use
        """
        # init instance variables
        self.name = name
        self._data = data
        self._repo = repo
        self.madx = madx
        self._loaded = False
        # create Beam/Optic/Sequence instances:
        self.beams = _deserialize(data['beams'], Beam, self)
        self.optics = _deserialize(data['optics'], Optic, self)
        self.sequences = _deserialize(data['sequences'], Sequence, self)

    def load(self):
        """Load model in MAD-X interpreter."""
        if self._loaded:
            return
        self._loaded = True
        self._load(*self._data['init-files'])
        for seq in self.sequences.values():
            seq.beam.load()

    def __repr__(self):
        return "{0}({1!r})".format(self.__class__.__name__, self.name)

    @property
    def data(self):
        """Get a serializable representation of this model."""
        data = self._data.copy()
        data['beams'] = _serialize(self.beams)
        data['optics'] = _serialize(self.optics)
        data['sequences'] = _serialize(self.sequences)
        return data

    @property
    def default_optic(self):
        """Get default Optic."""
        return self.optics[self._data['default-optic']]

    @property
    def default_sequence(self):
        """Get default Sequence."""
        return self.sequences[self._data['default-sequence']]

    # TODO: add setters for default_optic / default_sequence
    # TODO: remove default_sequence?

    def _load(self, *files):
        """Load MAD-X files in interpreter."""
        for file in files:
            with self._repo.get(file).filename() as fpath:
                self.madx.call(fpath)


class Beam(object):

    """
    Beam for :class:`Model`s.

    A beam defines the mass, charge, energy, etc. of the particles moved
    through the accelerator.

    Instance variables
    ==================

    :ivar str name: beam name
    :ivar dict data: beam parameters (keywords to BEAM command in MAD-X)

    Private:

    :ivar Model _model: owning model
    :ivar bool _loaded: beam has been initialized in MAD-X
    """

    def __init__(self, name, data, model):
        """Initialize instance variables."""
        self.name = name
        self.data = data
        self._model = model
        self._loaded = False

    def load(self):
        """Define the beam in MAD-X."""
        if self._loaded:
            return
        self._loaded = True
        self._model.load()
        self._model.madx.command.beam(**self.data)


class Optic(object):

    """
    Optic for :class:`Model`s.

    An optic (as far as I understand) defines a variant of the accelerator
    setup, e.g. different injection mechanisms.

    Instance variables
    ==================

    :ivar str name: optic name

    Private:

    :ivar dict _data: optic definition
    :ivar Model _model: owning model
    :ivar bool _loaded: beam has been initialized in MAD-X
    """

    def __init__(self, name, data, model):
        """Initialize instance variables."""
        self.name = name
        self.data = data
        self._model = model
        self._loaded = False

    def load(self):
        """Load the optic in the MAD-X process."""
        if self._loaded:
            return
        self._loaded = True
        self._model.load()
        self._model._load(*self.data.get('init-files', ()))


class Sequence(object):

    """
    Sequence for :class:`Model`s.

    A sequence defines an arrangement of beam line elements. It can be
    subdivided into multiple ranges.

    Instance variables
    ==================

    :ivar str name: sequence name
    :ivar dict ranges: known :class:`Range`s

    Private:

    :ivar dict _data:
    :ivar Model _model:
    """

    def __init__(self, name, data, model):
        """Initialize instance variables."""
        self.name = name
        self._data = data
        self._model = model
        self.ranges = _deserialize(data['ranges'], Range, self)

    def load(self):
        """Load model in MAD-X interpreter."""
        self._model.load()

    @property
    def data(self):
        """Get a serializable representation of this sequence."""
        data = self._data.copy()
        data['ranges'] = _serialize(self.ranges)
        return data

    @property
    def beam(self):
        """Get :class:`Beam` instance for this sequence."""
        return self._model.beams[self._data['beam']]

    @property
    def default_range(self):
        """Get default :class:`Range`."""
        return self.ranges[self._data['default-range']]

    def range(self, start, stop):
        """Create a :class:`Range` within (start, stop) for this sequence."""
        # TODO
        raise NotImplementedError()

    # MAD-X commands:

    def twiss(self, **kwargs):
        """Execute a TWISS command on the default range."""
        return self.default_range.twiss(**kwargs)

    def survey(self, **kwargs):
        """Run SURVEY on this sequence."""
        self.load()
        return self._model.madx.survey(sequence=self.name, **kwargs)

    def match(self, **kwargs):
        """Run MATCH on this sequence."""
        return self.default_range.match(**kwargs)


class Range(object):

    """
    Range for :class:`Model`s.

    A range is a subsequence of elements within a :class:`Sequence`.

    Instance variables
    ==================

    :ivar str name: sequence name

    Private:

    :ivar dict _data:
    :ivar Sequence _sequence:
    """

    def __init__(self, name, data, sequence):
        """Initialize instance variables."""
        self.name = name
        self.data = data
        self._sequence = sequence

    def load(self):
        """Load model in MAD-X interpreter."""
        self._sequence.load()

    @property
    def bounds(self):
        """Get a tuple (first, last)."""
        return (self.data["madx-range"]["first"],
                self.data["madx-range"]["last"])

    @property
    def offsets_file(self):
        """Get a :class:`ResourceProvider` for the offsets file."""
        if 'aper-offset' not in self.data:
            return None
        repo = self._sequence._model._repo
        return _repo.get(self.data['aper-offset'])

    def twiss(self, **kwargs):
        """Run TWISS on this range."""
        self.load()
        kw = self._set_twiss_init(kwargs)
        madx = self._sequence._model.madx
        result = madx.twiss(sequence=self._sequence.name,
                            range=self.bounds, **kw)
        return result

    def match(self, **kwargs):
        """Perform a MATCH operation on this range."""
        kw = self._set_twiss_init(kwargs)
        kw['twiss_init'] = {
            key: val
            for key, val in kw['twiss_init'].items()
            if util.is_match_param(key)
        }
        madx = self._sequence._model.madx
        return madx.match(sequence=self._sequence.name,
                          range=self.bounds, **kw)

    @property
    def initial_conditions(self):
        """
        Return a dict of all defined initial conditions.

        Each item is a dict of TWISS parameters.
        """
        return self.data['twiss-initial-conditions']

    @property
    def default_initial_conditions(self):
        """Return the default twiss initial conditions."""
        return self.initial_conditions[self.data['default-twiss']]

    def _set_twiss_init(self, kwargs):
        kw = kwargs.copy()
        twiss_init = kw.get('twiss_init', {}).copy()
        twiss_init.update(self.default_initial_conditions)
        kw['twiss_init'] = twiss_init
        return kw


def _get_logger(model_name):
    """Create a logger."""
    return logging.getLogger(__name__ + '.' + model_name)


class Factory(object):

    """
    Model instance factory.

    :ivar Locator locator: model definition locator and loader
    :ivar _Model: instanciates models
    :ivar _Madx: instanciates MAD-X interpreters
    :ivar _Logger: instanciates loggers
    """

    def __init__(self, locator):
        """Create Model factory using a specified model Locator."""
        self._locator = locator
        self._Model = Model
        self._Madx = madx.Madx
        self._Logger = _get_logger

    def _create(self, name, data, repo, madx, command_log, error_log):
        """
        Create Model instance based on ModelData.

        Parameters as in load_model (except for mdata).
        """
        if error_log is None:
            error_log = self._Logger(name)
        if madx is None:
            madx = self._Madx(command_log=command_log, error_log=error_log)
            madx.verbose(False)
        elif command_log is not None:
            raise ValueError("'command_log' cannot be used with 'madx'")
        model = self._Model(name, data, repo=repo, madx=madx)
        model.load()
        return model

    def __call__(self,
                 name,
                 # *,
                 # These should be passed as keyword-only parameters:,
                 madx=None,
                 command_log=None,
                 error_log=None):
        """
        Find model definition by name and create Model instance.

        :param str name: model name
        :param Madx madx: MAD-X instance to use
        :param str command_log: history file name; use only if madx is None!
        :param logging.Logger error_log:
        """
        data = self._locator.get_definition(name)
        repo = self._locator.get_repository(data)
        return self._create(name,
                            data,
                            repo=repo,
                            madx=madx,
                            command_log=command_log,
                            error_log=error_log)


class Locator(object):

    """
    Model locator for yaml files that contain multiple model definitions.

    These are the model definition files that are currently used by default
    for filesystem resources.

    Serves the purpose of locating models and returning corresponding
    resource providers.
    """

    def __init__(self, resource_provider):
        """
        Initialize a merged model locator instance.

        The resource_provider parameter must be a ResourceProvider instance
        that points to the filesystem location where the .cpymad.yml model
        files are stored.
        """
        self._repo = resource_provider

    def list_models(self, encoding='utf-8'):
        """
        Iterate all available models.

        Returns an iterable that may be a generator object.
        """
        for res_name in self._repo.listdir_filter(ext='.cpymad.yml'):
            mdefs = self._repo.yaml(res_name, encoding=encoding)
            for n, d in mdefs.items():
                if d['real']:
                    yield n

    def get_definition(self, name, encoding='utf-8'):
        """
        Get the first found model with the specified name.

        :returns: the model definition
        :raises ValueError: if no model with the given name is found.
        """
        for res_name in self._repo.listdir_filter(ext='.cpymad.yml'):
            mdefs = self._repo.yaml(res_name, encoding=encoding)
            mdef = mdefs.get(name)
            if mdef and mdef['real']:
                break
        else:
            raise ValueError("The model {!r} does not exist in the database"
                             .format(name))
        # Expand the model definition using its bases as specified by
        # 'extends'. This corresponds to a graph linearization:
        def get_bases(model_name):
            return mdefs[model_name].get('extends', [])
        mro = util.C3_mro(get_bases, name)
        expanded_mdef = {}
        for base in reversed(mro):
            util.deep_update(expanded_mdef, mdefs[base])
        return expanded_mdef

    def get_repository(self, data):
        """
        Get the resource loader for the given model.
        """
        # instantiate the resource providers for model resource data
        return self._repo.get(data['path-offset'])