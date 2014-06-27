from sqlalchemy.orm.query import QueryContext

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
