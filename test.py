import nova
from nova.db.sqlalchemy import models
from nova.openstack.common.db.sqlalchemy import session as sessionlib
from sqlalchemy.orm import joinedload_all, exc as orm_exc
from sqlalchemy.orm import persistence
from sqlalchemy import inspect, or_, bindparam
import logging
import random
import socket
import struct
from nova import context
import functools
from sqlalchemy.orm.query import QueryContext

logging.basicConfig()

get_session = None
ctx = None


def setup():
    facade = sessionlib.EngineFacade("mysql://scott:tiger@localhost/test",
                                        connection_debug=50)
    eng = facade.get_engine()
    global get_session
    get_session = facade.get_session

    tables = [
            models.Instance.__table__,
            models.FloatingIp.__table__
    ]
    models.BASE.metadata.drop_all(eng, tables=tables)
    models.BASE.metadata.create_all(eng, tables=tables)

    global ctx
    ctx = context.get_admin_context()

def endless_floating_ips():
    while True:
        ip = socket.inet_ntoa(struct.pack('>I', random.randint(1, 0xffffffff)))
        yield {
            'address': ip,
            'fixed_ip_id': None,
            'project_id': 'fake_project_%s' % random.randint(1, 10000),
            'host': '%s.host.com' % ip.replace(".", "_"),
            'auto_assigned': False,
            'pool': 'fake_pool',
            'interface': 'fake_interface_%s' % random.randint(1, 10000),
        }


def insert_data():
    with get_session().begin() as trans:
        for id, values in zip(xrange(1, 10000), endless_floating_ips()):
            fip = models.FloatingIp(id=id)
            fip.update(values)
            trans.session.add(fip)
            if id % 1000 == 0:
                trans.session.flush()


def floating_ip_update(get_by_address, save_item, context, address, values):
    session = get_session()
    with session.begin():
        float_ip_ref = get_by_address(context, address, session)
        float_ip_ref.update(values)
        save_item(float_ip_ref, session)


def existing_save(obj, session):
    obj.save(session)

class FakeUOWTransaction(object):
    def __init__(self, session):
        self.session = session

def fast_save(obj, session):
    """fast_save().

    This is a quick prototype version of the "insert/update/delete row"
    helper proposed in
    https://bitbucket.org/zzzeek/sqlalchemy/issue/3100/sessionflush_object.

    The code below is pretty much the whole implementation - we skip everything
    within the unit of work process in order to handle a single row at a time.
    All the various checks that involve multiple objects being present
    are bypassed, including:

    * retreiving dirty/new/deleted objects for flush, registering them
      with a "flush context"
    * resolution of dependencies between mappings and possibly individual
      instances
    * resolution of relationships, including loading missing values we might
      need, synchronizing priamry key values into foreign key values
    * resolution of primary keys mutating into other values
    * resolution of other objects that might be conflicting with
      a primary key change here
    * logic to detect if the instance that we're flushing has been garbage
      collected already, and we are only dealing with a "ghost" state

    What's nice about this system is that we retain support for:

    * flushing of inheritance structures
    * the before_XXX / after_XXX mapper events still fire off
    * handy things like prefetching/postfetching of server side defaults
      etc. still work
    * the object continues along within the Session with it's full state
      intact and up to date.

    """
    state = inspect(obj)
    isinsert = state.key is None
    mapper = state.mapper
    states = [state]
    uowtransaction = FakeUOWTransaction(session)

    with session.begin(subtransactions=True) as transaction:
        uowtransaction.transaction = transaction
        persistence.save_obj(mapper, states, uowtransaction, single=True)
        if isinsert:
            instance_key = mapper._identity_key_from_state(state)
            state.key = instance_key
            session.identity_map.replace(state)
            session._new.pop(state)
        state._commit_all(state.dict, instance_dict=session.identity_map)
        session._register_altered(states)


def _floating_ip_get_by_address(context, address, session,
                                load_instances=True, use_first=True,
                                use_baked=False):
    """This is a port of nova.db.sqlalchemy.api._floating_ip_get_by_address.

    It includes conditionals which select for the behaviors that are currently
    within the function vs. alternate behaviors that feature better
    optimization.

    """

    if use_baked:
        result = model_query_baked(context, models.FloatingIp, session=session)
        result.bake(lambda query:
            query.filter_by(address=bindparam('address'))
        ).params(address=address)
    else:
        result = model_query_ordinary(
                    context, models.FloatingIp, session=session).\
                    filter_by(address=address)

    if load_instances:
        if use_baked:
            result.bake(lambda query:
                query.options(joinedload_all('fixed_ip.instance')))
        else:
            result = result.options(joinedload_all('fixed_ip.instance'))

    if use_baked:
        result = result.all()
        if not result:
            raise Exception("floating ip not found: %s" % address)
        else:
            result = result[0]
    elif use_first:
        result = result.first()
        if not result:
            raise Exception("floating ip not found: %s" % address)
    else:
        try:
            result = result.one()
        except orm_exc.NoResultFound:
            raise Exception("floating ip not found: %s" % address)

    return result

def model_query_ordinary(context, model, *args, **kwargs):
    """a restatement of the api.model_query() function."""

    use_slave = False
    session = kwargs.get('session') or get_session(use_slave=use_slave)
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only', False)

    query = session.query(model, *args)

    base_model = model

    default_deleted_value = base_model.__mapper__.c.deleted.default.arg
    if read_deleted == 'no':
        query = query.filter(base_model.deleted == default_deleted_value)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter(base_model.deleted != default_deleted_value)
    else:
        raise Exception("Unrecognized read_deleted value '%s'"
                            % read_deleted)

    if nova.context.is_user_context(context) and project_only:
        if project_only == 'allow_none':
            query = query.\
                filter(or_(base_model.project_id == context.project_id,
                           base_model.project_id == None))
        else:
            query = query.filter_by(project_id=context.project_id)

    return query

def model_query_baked(context, model, *args, **kwargs):
    """a restatement of the api.model_query() function which uses
    a 'baked' query, e.g. caches SQL strings"""

    use_slave = False
    session = kwargs.get('session') or get_session(use_slave=use_slave)
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only', False)

    baked = BakedQuery(lambda: session.query(model, *args))
    base_model = model

    default_deleted_value = base_model.__mapper__.c.deleted.default.arg
    if read_deleted == 'no':
        baked.bake(lambda query: query.filter(base_model.deleted == default_deleted_value))
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        baked.bake(lambda query: query.filter(base_model.deleted != default_deleted_value))
    else:
        raise Exception("Unrecognized read_deleted value '%s'"
                            % read_deleted)

    if nova.context.is_user_context(context) and project_only:
        if project_only == 'allow_none':
            baked.bake(lambda query:
                query.
                    filter(or_(base_model.project_id == bindparam('project_id'),
                               base_model.project_id == None))
            ).params(project_id=context.project_id)
        else:
            baked.bake(lambda query:
                query.filter_by(project_id=bindparam('project_id'))).\
                params(project_id=context.project_id)

    return baked

class BakedQuery(object):
    """an object that can produce a 'baked' Query, that is one where
    its ultimately generated SQL string is cached based on how the query
    has been constructed.

    """
    _bakery = {}

    def __init__(self, fn, args=()):
        if args:
            self._cache_key = tuple(args)
        else:
            self._cache_key = ()
        self.query = fn(*args)
        self._params = {}
        self._update_cache_key(fn)
        self.steps = []

    def _update_cache_key(self, fn):
        self._cache_key += (fn.func_code.co_filename,
                                    fn.func_code.co_firstlineno)

    @classmethod
    def baked(cls, fn):
        def decorate(*args):
            return BakedQuery(fn, args)
        return decorate

    def bake(self, fn):
        self._update_cache_key(fn)
        self.steps.append(fn)
        return self

    def _bake(self):
        query = self.query
        for step in self.steps:
            query = step(query)
        context = query._compile_context()
        del context.session
        del context.query
        self._bakery[self._cache_key] = context

    def params(self, **kw):
        self._params.update(kw)
        return self

    def __iter__(self):

        if self._cache_key not in self._bakery:
            self._bake()

        query = self.query

        query._execution_options = query._execution_options.union(
                        {"compiled_cache": self._bakery}
                    )
        baked_context = self._bakery[self._cache_key]
        context = QueryContext.__new__(QueryContext)
        context.__dict__.update(baked_context.__dict__)
        context.query = query
        context.session = query.session
        context.attributes = context.attributes.copy()

        context.statement.use_labels = True
        if query._autoflush and not query._populate_existing:
            query.session._autoflush()
        return query.params(self._params)._execute_and_instances(context)

    def all(self):
        return list(self)


def run_test(updater, all_ips):
    existing_ips = (random.choice(all_ips) for count in xrange(10000))
    updated_values = endless_floating_ips()

    for existing_address in existing_ips:
        updated = next(updated_values)
        del updated['address']
        updater(ctx, existing_address, updated)

setup()
insert_data()


run_test(
    functools.partial(
        floating_ip_update,
        lambda ctx, address, sess: _floating_ip_get_by_address(
                        ctx, address, sess,
                        load_instances=False, use_first=False, use_baked=True),
        fast_save,
    ),
    list(ip for ip, in get_session().query(models.FloatingIp.address))
)

