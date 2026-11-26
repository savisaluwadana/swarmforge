-- R3: retain exact canonical Metrics response as well as relational counters.
BEGIN;
ALTER TABLE run_metrics ADD COLUMN result_json jsonb NOT NULL CHECK(jsonb_typeof(result_json)='object');
COMMIT;
