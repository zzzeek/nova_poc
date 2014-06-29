ORM Performance Study
=====================

In this proof of concept we illustrate some techniques to improve upon
ORM performance in certain situations.     We focus on a single method
in the Nova API, ``floating_ip_update()``.

See the Wiki entry at `ORM Quick Wins Proof of Concept <>`_ for an introduction.

Win #1 - Tune Eager Loads (and loading overall)
------------------------------------------------

The first win, which is by far the easiest, is to tune the use of eager loads.
There is no doubt that Openstack developers are deeply familiar with
SQLAlchemy's eager loading feature, and overall most use of SQLAlchemy I have
seen in Openstack is at a fully expert level.   The purpose of illustrating the
performance overhead of one particular eagerload that I found in this method is not
to claim that Openstack developers aren't careful about tuning queries;
instead I want to illustrate just how dramatic the performance difference there
is when applying unused eager loads to this "many short hits" API pattern.
In my testing here, I illustrate that 10K calls to ``floating_ip_update()``
goes from 24 million Python function calls down to 1.9 million, just by
taking out an unneeded ``joinedload_all()``::

	Running scenario default
	Scenario default, total calls for 1000 operations: 24543047
	Scenario default, total time for 10000 operations: 222

	Running scenario default_optimized
	Scenario default_optimized, total calls for 1000 operations: 1881626
	Scenario default_optimized, total time for 10000 operations: 25

Besides eager loading, it's important to be aware of when full object
instances aren't needed at all.  An API method that wishes to return some
simple entity as a single dictionary can save lots of time both on database
round trip as well as ORM latency by loading indivdual columns, instead
of full instances.   The ORM applies a significant level of bookkeeping to
full blown instances, managing their state in an identity map and also tracking
changes to attributes, which involves upfront loading overhead as well.
The SQLAlchemy ``Query`` object has for many years supported read-only named
tuple objects, by turning this::

	obj = session.query(FixedIp).first()

into this::

	obj = session.query(FixedIp.address, FixedIp.host, FixedIp.reserved).first()

SQLAlchemy as of version 0.9 supports a new concept of a
`Column Bundle <http://docs.sqlalchemy.org/en/rel_0_9/orm/mapper_config.html#column-bundles>`_
which allows a series of columns like the above to be packaged into an object
interface, which can be customized to have methods on it and act like a model
object.   One direction we may be able to take is to automate this with
regards to Openstack models, so that one may say::

	obj = session.query(FixedIp.bundle).first()

Where the above would grant an object that in most ways acts just like
a ``FixedIp`` object that is read-only, is not maintained by any identity map
and loads with far less latency than a full ``FixedIp`` entity.  Notably, the
``Bundle`` concept does not have a clear path to support relationships or eager
loading at the moment, but for the common case where an Openstack API immediately
marshalls a single ORM entity into a "values"
dictionary, this pattern would dramatically reduce latency.

Win #2 - Persist Objects Directly without the Unit of Work
----------------------------------------------------------

This second win was oddly not as dramatic as I'd hoped, however it is helpful
and easy to implement nonetheless.   Openstack applications seem to rely a
lot on a pattern that involves short "save this object" methods.
When I first looked at oslo.db and saw that there is actually a ``.save()`` method
tacked onto the base model class.   This pattern is one that I mention a lot
in my talks, as I'm trying to sell the unit of work pattern as a more sophisticated
and powerful pattern.   But when the application is already broken into a series
of quick hits inside of separate transactions, the unit of work pattern becomes
more of a hindrance.

The unit of work is a sophisticated pattern of automation which knows how to
handle the persistence of extremely complicated graphs of interconnected
objects.   It does this job very well and it does it in a highly performant
way compared to how many curveballs it knows how to deal with, but if your method
needs to just UPDATE or INSERT a single row, or maybe a handful of simple rows,
then commit the whole transaction, the UOW can be overkill.

So for the quick "Save this object" pattern I've proposed the
`single flush_object() <https://bitbucket.org/zzzeek/sqlalchemy/issue/3100/sessionflush_object>`_,
feature for SQLAlchemy.   A function that has a small number of simple objects
to persist can call this method, and a trimmed down persist operation will take
place, bypassing the whole mechanics of flush and unit of work and going directly
to the mapper object's system of persisting a single object.  The mechanics of
attribute history, mapper events, and updating only those columns that have changed
can remain in place (or not, if we really want to cut out Python overhead).

Applying the "single flush object" pattern as implemented in the POC shows approximately a
12% improvement in call count overhead::

	Running scenario default_optimized
	Scenario default_optimized, total calls for 1000 operations: 1881626
	Scenario default_optimized, total time for 10000 operations: 25

	Running scenario fast_save
	Scenario fast_save, total calls for 1000 operations: 1685221
	Scenario fast_save, total time for 10000 operations: 22

Not that much!  But for those cases where ``object.save()`` is being used and there
is little to no reliance upon expensive relationship-persistence mechanics (e.g. if you can assign
``mychild.foo_id = myparent.id`` rather than getting the unit of work to do it
for you), this can save you some CPU.   Emitting an INSERT or UPDATE directly
is an option as well, which would save on some more overhead.  There's no issue
doing this while still using the ORM, especially for very simple operations
where the persist operation is the last thing performed.

Win #3 - Cache the construction of queries, rendering of SQL, result metadata using Baking
------------------------------------------------------------------------------------------

Something that has been in the works for a long time and has recently
seen lots of work in the past months is the "baked query" feature; this
pattern is ideal for Openstack's "many short queries" pattern, and allows
caching of the generation of SQL.  Recent versions of this pattern have
gotten very slick, and can cache virtually everything that happens Python-wise
from the construction of the ``Query`` object, to calling all the methods
on the query, to the query-objects construction of a Core SQL statement,
to the compilation of that statement as a string - all of these steps
are removed from the call-graph after the first such call.  In SQLAlchemy 1.0
I've also thrown in the construction of column metadata from the result set
too.   The pattern involves a bit more verbosity to that of constructing a
query, where here I've built off of some of the ideas of the
Pony ORM to use Python function information as the source of a cache key.
A query such as::

    result = model_query(
                context, models.FloatingIp, session=session).\
                filter_by(address=address)

would be expressed in "baked" form as::

	# note model_query is using the "baked" process internally as well
    result = model_query(context, models.FloatingIp, session=session)

    result.bake(lambda query:
        query.filter_by(
            address=bindparam('address'))).params(address=address)

In the above form, everything within each lambda is invoked only once,
the result of which becomes part of a cached value.

For this slight increase in verbosity, we get an improvement like this::

	Running scenario default_optimized
	Scenario default_optimized, total calls for 1000 operations: 1881626
	Scenario default_optimized, total time for 10000 operations: 25

	Running scenario baked
	Scenario baked, total calls for 1000 operations: 1052935
	Scenario baked, total time for 10000 operations: 16

That is, around a 40% improvement.

Putting together both "fast save" plus "baked" we get down to a full 50%
improvement vs. the plain optimized version::

	Running scenario fast_save_plus_baked
	Scenario fast_save_plus_baked, total calls for 1000 operations: 856035
	Scenario fast_save_plus_baked, total time for 10000 operations: 13

Running the POC
===============

The app install using usual ``setup.py`` tools, however the "nova" requirement
must be installed manually (I'm not sure of the best way to do this)::

	virtualenv /path/to/venv
	cd /path/to/nova
	/path/to/venv/bin/pip install -e .   # installs nova in venv
	cd /path/to/nova_poc
	/path/to/venv/bin/pip install -e .   # installs nova-poc in venv

Then there's a command line script::

	/path/to/venv/bin/nova-poc --help

	usage: nova-poc [-h] [--db DB] [--log]
	                [--scenario {all,default,default_optimized,fast_save,baked,fast_save_plus_baked}]
	                [--single]

	optional arguments:
	  -h, --help            show this help message and exit
	  --db DB               database URL
	  --log                 enable SQL logging
	  --scenario {all,default,default_optimized,fast_save,baked,fast_save_plus_baked}
	                        scenario to run
	  --single              Run only 100 iterations and dump out the Python
	                        profile


A full default run will look, with variation, something like the following::

	$ .venv/bin/nova-poc
	tables created
	inserted 10000 sample floatingIP records
	Running scenario default
	Scenario default, total calls for 1000 operations: 24590500
	Scenario default, total time for 10000 operations: 222
	Running scenario default_optimized
	Scenario default_optimized, total calls for 1000 operations: 1919669
	Scenario default_optimized, total time for 10000 operations: 24
	Running scenario fast_save
	Scenario fast_save, total calls for 1000 operations: 1723228
	Scenario fast_save, total time for 10000 operations: 22
	Running scenario baked
	Scenario baked, total calls for 1000 operations: 1176846
	Scenario baked, total time for 10000 operations: 17
	Running scenario fast_save_plus_baked
	Scenario fast_save_plus_baked, total calls for 1000 operations: 980035
	Scenario fast_save_plus_baked, total time for 10000 operations: 14