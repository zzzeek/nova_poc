ORM Performance Study
=====================

In this proof of concept we illustrate some techniques to improve upon
ORM performance in certain situations.     We focus on a single method
in the Nova API, ``floating_ip_update()``.

Introduction
------------

The Nova API, and probably the APIs of a lot of the other openstack
libraries, present a performance challenge not just to ORMs but
to a relational backend in general.  These APIs are presented as a series of many fine-
grained methods, each of which operates with its own database transaction
and Session.  This pattern works against the ORM Session's strengths, which are
oriented towards building up a complex graph of objects in a transaction
that can be manipulated and transparently synchronized with a relational
database with great accuracy.  Instead, with many small and isolated API
methods we see lots of individual Session objects spinning up, loading a few
rows from several tables, and then flushing out some of those rows, in
many cases just one of them, in the form of a single INSERT or UPDATE.

The Openstack app overall may be calling upon many API methods to
accomplish one task, but due to the fine-grained nature of the API, a
complex operation ends up being fragmented over many short-lived
transactions. This is not just difficult for ORMs but for relational
databases overall. Fetching many individual rows from disparate tables
in order to build up a structure is very time consuming, compared to a
similar case against a document store like MongoDB which can represent
all of that same data in a single document, which can be fetched with
lower latency than just one of those relational rows.  Breaking the
operation into many small transactions means that rows tend to be
loaded on a key-by-key basis, rather than being able to pull in all
the rows that will be needed for a complex operation at once.

This pattern is not only one that is present in Openstack, it is common
and in fact just came up on the mailing list the other day.   To the
degree the SQLAlchemy can be improved to better adapt to this situation
in Openstack, it will provide patterns and clarity to the community overall.

The proof of concept here will illustrate three wins that can be achieved
in Nova and other Openstack applications very expediently, with no significant
changes to application structure.

Win #1 - Tune Eager Loads (and loading overall)
------------------------------------------------

The first win, which is by far the easiest, is to tune the use of eager loads.
There is no doubt that Nova and Openstack developers are deeply familiar with
SQLAlchemy's eager loading feature, and overall most use of SQLAlchemy I have
seen in Openstack is at a fully expert level.   The purpose of illustrating the
performance overhead of one particular eagerload that I found in this method is not
to claim that Openstack developers aren't careful about tuning queries;
instead I want to illustrate just how dramatic the performance difference there
is when applying unused eager loads to this "many short hits" API pattern.
In my testing here, I illustrate that 10K calls to ``floating_ip_update()``
goes from 24 million Python function calls down to 1.9 million, just by
taking out an unneeded ``joinedload_all()``.

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

For the second win, we explore a pattern that is intrinsic to the Openstack
API approach, which is that there are a lot of short "save this object" methods.
When I first looked at oslo.db and saw that there is actually a ``.save()`` method
tacked onto the base model class.   This pattern is one that I mention a lot
in my talks, as I'm trying to sell the unit of work pattern as a more sophisticated
and powerful pattern.   But when the application is already broken into a series
of quick hits inside of separate transactions, the unit of work pattern becomes
more of a hindrance.

Unit of work has to deal with very elaborate scenarios, where a single
object represents rows in multiple tables at once, referring to other
collections and references that refer to many more rows, all of which
must be inserted/deleted and sometimes updated in very specific
orders, all  the while maintaining synchrony between foreign keys and
database-generated primary keys between rows, as well as between
what's known to be in the database vs. what's represented in the
Session.   To achieve this, it builds up a structure representing
everything that needs to be flushed, operates upon all members and
relationships between all those objects, sorts everything, then runs
through to emit all the SQL and synchronize between relationships as
it goes.

When a method is using a Session just to INSERT or UPDATE a single row only,
this is all overhead that is pretty wasteful.   I went through Nova's API
and found that lots of methods really only operate upon a single row on the
write side, though lots of others still do rely upon the unit of work to
synchronize and flush related items.  I did this by universally setting
all ``relationship()`` structures to viewonly=True and running tests, and
after observing dozens of failures, tried to pick apart a subset of relationships
that are needed for persistence.  Suffice to say that while Nova doesn't
need relationship-level persistence in all cases, it still relies heavily on the
advanced nature of ``relationship()`` and unit of work in many areas.

However, in a function like ``floating_ip_update()``, it's really just emitting
UPDATE for a single row.  Other functions that need to insert/update multiple rows
could similarly be slightly restructured to make each row explicit, rather than
going through the full UOW process.

To that end, I've proposed a new SQLAlchemy feature,
`Single flush_object() <https://bitbucket.org/zzzeek/sqlalchemy/issue/3100/sessionflush_object>`_,
which for previous versions of SQLAlchemy can be expressed using a new oslo.db
feature which pulls into semi-private SQLAlchemy APIs.   This system
would be provided as a variant of the existing ``object.save()`` approach
used by Nova and other Openstack APIs, for the case when only a single object
needs to be persisted (again noting, relationship persistence is one of the key
things that is skipped here).  The demonstration program illustrates this
recipe as applied to ``floating_ip_update()`` and it
















