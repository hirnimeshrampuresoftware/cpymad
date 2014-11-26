"""
Cython implementation of the model api.
"""

from __future__ import absolute_import

import collections
import logging
import os

from . import madx
from . import util
from ..resource.file import FileResource


__all__ = [
    'Model',
    'Factory',
    'Locator',
]


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
        # create Beam/Optic/Sequence instances:
        self.beams = util.map_dict(data['beams'], Beam, self)
        self.optics = util.map_dict(data['optics'], Optic, self)
        self.sequences = util.map_dict(data['sequences'], Sequence, self)
        # initialize MAD-X:
        self._load(*self._data['init-files'])

    def __repr__(self):
        return "{0}({1!r})".format(self.__class__.__name__, self.name)

    @property
    def data(self):
        """Return model definition dictionary (can be serialized as YAML)."""
        # TODO: generate dictionary from instance variables
        return self._data

    @property
    def default_optic(self):
        """Get default optic name."""
        return self.optics[self._data['default-optic']]

    @property
    def default_sequence(self):
        """Get default sequence name."""
        return self.sequences[self._data['default-sequence']]

    # TODO: add setters for default_optic / default_sequence
    # TODO: remove default_sequence?

    def _load(self, *files):
        """
        Load MAD-X files.

        :param tuple files: file names to be loaded from resource repository.
        """
        for file in *files:
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
        self._model.madx.beam(**self.data)



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
        self._data = data
        self._model = model
        self._loaded = False

    def load(self):
        """Load the optic in the MAD-X process."""
        if self._loaded:
            return
        self._model._load(*self._data.get('init-files', ()))
        self._loaded = True


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

    Keep track whether TWISS/APERTURE commands have been called:

    :ivar bool _aperture_called:
    :ivar bool _twiss_called:
    """

    def __init__(self, name, data, model):
        """Initialize instance variables."""
        self.name = name
        self._data = data
        self._model = model
        self._twiss_called = False
        self._aperture_called = False
        self.ranges = util.map_dict(data['ranges'], Range, self)

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
        pass

    # MAD-X commands:

    def twiss(self, **kwargs):
        """Execute a TWISS command on the default range."""
        return self.default_range.twiss(**kwargs)

    def aperture(self, **kwargs):
        """Execute a TWISS command on the default range."""
        return self.default_range.aperture(**kwargs)

    def survey(self, **kwargs):
        """Execute a TWISS command on the default range."""
        return self.default_range.aperture(**kwargs)

    def _prepare_aperture(self):
        if self._aperture_called:
            return
        if not self._twiss_called:
            self.twiss()
        self._load(*self._data['aperfiles'])
        self._aperture_called = True


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
        self._data = data
        self._sequence = sequence

    @property
    def bounds(self):
        return (self._data["madx-range"]["first"],
                self._data["madx-range"]["last"])

    @property
    def offsets(self):
        if 'aper-offset' not in self._data:
            return None
        repo = self._sequence._model._repo
        return _repo.get(self._data['aper-offset'])

    def twiss(self, **kwargs):
        """Run TWISS on this range."""
        kw = self.get_twiss_initial(None, kwargs)
        result = self.madx.twiss(sequence=self.sequence.name,
                                 range=self.bounds, **kw)
        if _range == ('#s', '#e'):
            # we say that when the "full" range has been selected,
            # we can set this to true. Needed for e.g. aperture calls
            self._sequence._twiss_called = True
        return result

    def survey(self, **kwargs):
        """Run SURVEY on this range."""
        kw = self.get_twiss_initial(None, kwargs)
        return self.madx.survey(sequence=self._sequence.name,
                                range=self.bounds, **kw)

    def aperture(self, **kwargs):
        """Run APERTURE on this range."""
        self._sequence._prepare_aperture()
        offsets = self.offsets
        if 'offsets' not in kwargs and offsets:
            with offsets.filename() as _offsets:
                return self._madx.aperture(sequence=self._sequence.name,
                                           range=self.bounds,
                                           offsets=_offsets, **kwargs)
        else:
            return self._madx.aperture(sequence=self._sequence.name,
                                       range=self.bounds, **kwargs)

    def match(self, **kwargs):
        """
        Perform a MATCH operation.

        See :func:`cern.madx.match` for a description of the parameters.
        """
        kw = self.get_twiss_initial(None, {})
        kw = {key: val
              for key, val in twiss_init.items()
              if util.is_match_param(key)}
        kw.update(kwargs)
        return self.twiss(sequence=self._sequence.name,
                          range=self.bounds, **kw)

    def get_twiss_initial(self, name=None, kwargs=None):
        """Return the twiss initial conditions."""
        if name is None:
            name = self._data['default-twiss']
        result = self._data['twiss-initial-conditions'][name]
        if kwargs is not None:
            result = result.copy()
            result.update(kwargs)
        return result


class Factory(object):

    """
    Model instance factory.

    :ivar Locator locator: model definition locator and loader
    :ivar _Model: Model class
    :ivar _Madx: Madx class
    """

    def __init__(self, locator):
        """Create Model factory using a specified ModelLocator."""
        self._locator = locator
        self._Model = Model
        self._Madx = Madx

    def _create(self, name, data, repo, madx, command_log, error_log):
        """
        Create Model instance based on ModelData.

        Parameters as in load_model (except for mdata).
        """
        if error_log is None:
            error_log = logging.getLogger(__name__)
        if madx is None:
            madx = Madx(command_log=command_log, error_log=error_log)
            madx.verbose(False)
        elif command_log is not None:
            raise ValueError("'command_log' cannot be used with 'madx'")
        return self._Model(name, data, repo=repo, madx=madx)

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
        :param str sequence: Name of the initial sequence to use
        :param str optics: Name of optics to load, string or list of strings.
        :param Madx madx: MAD-X instance to use
        :param str command_log: history file name; use only if madx is None!
        :param logging.Logger error_log:
        """
        data = self._model_locator.get_definition(name)
        repo = self._model_locator.get_repository(data)
        return self._create(name,
                            data,
                            repo=repo,
                            madx=madx,
                            command_log=command_log,
                            error_log=error_log)


class Locator(ModelLocator):

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
        repo_offs = data['path-offsets']['repository-offset']
        # the repository location may be overwritten by dbdirs:
        for dbdir in data.get('dbdirs', []):
            if os.path.isdir(dbdir):
                return FileResource(os.path.join(dbdir, repo_offs))
        return self._repo.get('repdata').get(repo_offs)
