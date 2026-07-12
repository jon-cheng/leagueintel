# scripts/migrate_db.py
import boto3
import subprocess
from pathlib import Path
from leagueintel.storage.database import get_connection, create_tables
from leagueintel.storage.views import create_views
from leagueintel.config import S3_BUCKET, S3_KEY, DEFAULT_DB_PATH

# Use the leagueintel_admin AWS CLI profile (has S3 read/write) rather than
# the default credential chain — that chain would pick up the .env keys
# for leagueintel-app, which is deliberately read-only in production.
session = boto3.Session(profile_name="leagueintel_admin")
s3 = session.client("s3", region_name="us-west-2")

# download
print("Downloading DB from S3...")
s3.download_file(S3_BUCKET, S3_KEY, str(DEFAULT_DB_PATH))

# migrate
print("Running migrations...")
conn = get_connection()
create_tables(conn)
create_views(conn)

# verify
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()
views = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
).fetchall()
print("Tables:", [t[0] for t in tables])
print("Views:", [v[0] for v in views])
conn.close()

# upload
print("Uploading back to S3...")
s3.upload_file(str(DEFAULT_DB_PATH), S3_BUCKET, S3_KEY)
print("Done.")
