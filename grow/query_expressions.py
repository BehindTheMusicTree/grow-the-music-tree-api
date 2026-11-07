from django.db.models import BooleanField, Func


class InSubquery(Func):
    """Membership in an uncorrelated result, materialized once on PostgreSQL."""

    output_field = BooleanField()
    arity = 2

    def as_sql(self, compiler, connection, **extra_context):
        value, value_params = compiler.compile(self.source_expressions[0])
        selection, selection_params = compiler.compile(self.source_expressions[1])
        if connection.vendor == "postgresql":
            # The InitPlan prevents a semi-join from moving large model graphs ahead of
            # a bounded selection, or repeatedly traversing it inside a scalar lookup.
            sql = f"{value} = ANY(ARRAY{selection})"
        elif connection.vendor == "sqlite":
            sql = f"{value} IN {selection}"
        else:
            raise NotImplementedError(f"No materialized selection query for {connection.vendor}")
        return sql, [*value_params, *selection_params]
