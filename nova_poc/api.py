from . import fixture
from nova.db.sqlalchemy import models
from sqlalchemy import or_, bindparam
from sqlalchemy.orm import joinedload_all, exc as orm_exc
import nova
from .baked import BakedQuery

def floating_ip_update(get_by_address, save_item, context, address, values):
    session = fixture.get_session()
    with session.begin():
        float_ip_ref = get_by_address(context, address, session)
        float_ip_ref.update(values)
        save_item(float_ip_ref, session)


def existing_save(obj, session):
    obj.save(session)

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
            query.filter_by(
                address=bindparam('address'))).params(address=address)
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
    session = kwargs.get('session') or fixture.get_session(use_slave=use_slave)
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
    session = kwargs.get('session') or fixture.get_session(use_slave=use_slave)
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only', False)

    baked = BakedQuery(lambda: session.query(model, *args))
    base_model = model

    default_deleted_value = base_model.__mapper__.c.deleted.default.arg
    if read_deleted == 'no':
        baked.bake(lambda query: query.filter(
                    base_model.deleted == default_deleted_value))
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        baked.bake(lambda query:
            query.filter(base_model.deleted != default_deleted_value))
    else:
        raise Exception("Unrecognized read_deleted value '%s'"
                            % read_deleted)

    if nova.context.is_user_context(context) and project_only:
        if project_only == 'allow_none':
            baked.bake(
                lambda query: query.
                    filter(
                        or_(
                            base_model.project_id == bindparam('project_id'),
                            base_model.project_id == None
                        )
                    )
            ).params(project_id=context.project_id)
        else:
            baked.bake(lambda query:
                query.filter_by(project_id=bindparam('project_id'))).\
                params(project_id=context.project_id)

    return baked
