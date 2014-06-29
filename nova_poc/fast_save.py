from sqlalchemy.orm import persistence
from sqlalchemy import inspect

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
    uowtransaction = FakeUOWTransaction(session)

    with session.begin(subtransactions=True) as transaction:
        uowtransaction.transaction = transaction
        persistence.save_obj(mapper.base_mapper, [state],
            uowtransaction, single=True)
        if isinsert:
            instance_key = mapper._identity_key_from_state(state)
            state.key = instance_key
            session.identity_map.replace(state)
            session._new.pop(state)
        state._commit_all(state.dict, instance_dict=session.identity_map)
        session._register_altered([state])


