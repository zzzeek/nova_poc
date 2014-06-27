from nova.db.sqlalchemy import models
from nova.openstack.common.db.sqlalchemy import session as sessionlib
import logging
import random
import socket
import struct
from nova import context

logging.basicConfig()

get_session = None
ctx = None

def _setup(url, logging):
    facade = sessionlib.EngineFacade(url,
                                        connection_debug=50 if logging else 0)
    eng = facade.get_engine()
    global get_session
    get_session = facade.get_session

    tables = [
            models.FixedIp.__table__,
            models.Instance.__table__,
            models.FloatingIp.__table__
    ]
    models.BASE.metadata.drop_all(eng, tables=tables)
    models.BASE.metadata.create_all(eng, tables=tables)

    global ctx
    ctx = context.get_admin_context()
    print("tables created")

def _endless_floating_ips():
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


def _insert_data(num):
    with get_session().begin() as trans:
        fixed_ips = [
            models.FixedIp(instance=models.Instance())
            for i in range(5)
        ]
        trans.session.add_all(fixed_ips)
        trans.session.flush()

        for id, values in zip(xrange(1, num), _endless_floating_ips()):
            fip = models.FloatingIp(id=id)
            fip.update(values)
            fip.fixed_ip_id = random.choice(fixed_ips).id
            trans.session.add(fip)

            if id % 1000 == 0:
                trans.session.flush()
    print("inserted %d sample floatingIP records" % num)


