"""Transactional, checksum-verified migration runner for canonical SQL."""
import argparse
import hashlib
import os
import re
from pathlib import Path
import psycopg

LOCK=734182901


def migrate(dsn, directory):
    paths=sorted(Path(directory).glob("[0-9][0-9][0-9]_*.sql"))
    if not paths:
        raise ValueError("no migrations found")
    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)",(LOCK,))
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
            applied=dict(conn.execute("SELECT version,checksum FROM schema_migrations").fetchall())
            if not set(applied)<=set(p.name for p in paths):
                raise ValueError("applied migration missing from checkout")
            for path in paths:
                raw=path.read_bytes()
                checksum=hashlib.sha256(raw).hexdigest()
                if path.name in applied:
                    if applied[path.name]!=checksum:
                        raise ValueError("migration checksum mismatch: "+path.name)
                    continue
                sql=raw.decode("utf-8")
                sql,n1=re.subn(r"(?im)^BEGIN;\s*$","",sql,count=1)
                sql,n2=re.subn(r"(?im)^COMMIT;\s*$","",sql,count=1)
                if n1!=1 or n2!=1:
                    raise ValueError("migration must have BEGIN/COMMIT wrapper")
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations(version,checksum) VALUES (%s,%s)",(path.name,checksum))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--directory",default="db")
    args=p.parse_args()
    migrate(os.environ["DATABASE_URL"],args.directory)
    print("Schema migrations applied and verified")


if __name__=="__main__":
    main()
