# scripts/migrate_db.py
import boto3
import subprocess
from pathlib import Path
from leagueintel.storage.database import get_connection, create_tables
from leagueintel.config import S3_BUCKET, S3_KEY, DEFAULT_DB_PATH

s3 = boto3.client("s3", region_name="us-west-2")

# download
print("Downloading DB from S3...")
s3.download_file(S3_BUCKET, S3_KEY, str(DEFAULT_DB_PATH))

# migrate
print("Running migrations...")
conn = get_connection()
create_tables(conn)

# verify
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()
print("Tables:", [t[0] for t in tables])
conn.close()

# upload
print("Uploading back to S3...")
s3.upload_file(str(DEFAULT_DB_PATH), S3_BUCKET, S3_KEY)
print("Done.")
