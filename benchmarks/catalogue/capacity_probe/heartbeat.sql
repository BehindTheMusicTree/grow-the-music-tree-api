-- What a probe Postgres is doing right now, printed by probe.sh's monitor every minute (psql -At, so no headers).
SELECT 'active  ' || pid || ' ' || date_trunc('second', now() - query_start) || ' ' || coalesce(wait_event, '-') || ' '
       || left(regexp_replace(query, '\s+', ' ', 'g'), 100)
FROM pg_stat_activity
WHERE state = 'active' AND backend_type = 'client backend' AND pid <> pg_backend_pid();

SELECT 'index   ' || relid::regclass || ' ' || coalesce(index_relid::regclass::text, '-') || ' ' || phase
       || ' blocks ' || blocks_done || '/' || blocks_total || ' tuples ' || tuples_done || '/' || tuples_total
FROM pg_stat_progress_create_index;

SELECT 'copy    ' || relid::regclass || ' tuples ' || tuples_processed || ' bytes ' || bytes_processed
FROM pg_stat_progress_copy;

SELECT 'analyze ' || relid::regclass || ' ' || phase FROM pg_stat_progress_analyze;
