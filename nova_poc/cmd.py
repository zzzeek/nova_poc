from argparse import ArgumentParser
import functools
from . import fixture
from . import fast_save
from . import api
from . import util
import random

def setup_for_scenarios(url, logging, num):
    fixture._setup(url, logging)
    fixture._insert_data(num)

def run_test(updater, all_ips, num):
    existing_ips = (random.choice(all_ips) for count in xrange(num))
    updated_values = fixture._endless_floating_ips()

    for count, existing_address in enumerate(existing_ips):
        updated = next(updated_values)
        del updated['address']
        updater(fixture.ctx, existing_address, updated)

def run_scenario(scenario, num):
    if scenario == 'all':
        run_scenario("default", num)
        run_scenario("default_optimized", num)
        run_scenario("fast_save", num)
        run_scenario("baked", num)
        run_scenario("fast_save_plus_baked", num)
        return

    print("Running scenario %s" % scenario)

    ip_addr_kw = dict(load_instances=True, use_first=True, use_baked=False)

    if scenario != "default":
        ip_addr_kw['load_instances'] = False
        ip_addr_kw['use_first'] = False

    if scenario in ("fast_save", "fast_save_plus_baked"):
        saver = fast_save.fast_save
    else:
        saver = api.existing_save

    if scenario in ("baked", "fast_save_plus_baked"):
        ip_addr_kw['use_baked'] = True

    data = list(ip for ip, in
                    fixture.get_session().query(api.models.FloatingIp.address))
    def go():
        run_test(
            functools.partial(
                api.floating_ip_update,
                lambda ctx, address, sess: api._floating_ip_get_by_address(
                                ctx, address, sess,
                                **ip_addr_kw),
                saver,
            ),
            data,
            num
        )
    with util.profiled() as result:
        go()
    print("Scenario %s, total calls %d" % (scenario, result[0]))

    with util.timeit() as result:
        go()
    print("Scenario %s, total time %d" % (scenario, result[0]))


def main(argv=None):
    parser = ArgumentParser()
    parser.add_argument("--db", type=str,
                default="mysql://scott:tiger@localhost/test",
                help="database URL")

    parser.add_argument("--log", action="store_true",
                help="enable SQL logging")

    parser.add_argument("--scenario",
                choices=["all", "default", "default_optimized",
                        "fast_save", "baked", "fast_save_plus_baked"],
                default="all",
                help="scenario to run")

    parser.add_argument("--num",
                type=int,
                default=10000,
                help="size of dataset to run on")

    options = parser.parse_args(argv)

    setup_for_scenarios(options.db, options.log, 10000)
    run_scenario(options.scenario, options.num)

if __name__ == '__main__':
    main()
