import cloudinary
import cloudinary.api
import datetime
import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env from project root directory
project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / ".env")

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# Calculate the UTC timestamp for 7 days ago (timezone-aware)
seven_days_ago = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)

# Prepare deletion list and pagination cursor
public_ids_to_delete = []
next_cursor = None

print("🔍 Fetching resources tagged with 'temp-screenshot'...")

while True:
    params = {
        "tag": "temp-screenshot",
        "type": "upload",
        "max_results": 500
    }
    if next_cursor:
        params["next_cursor"] = next_cursor

    result = cloudinary.api.resources_by_tag(**params)

    for resource in result.get("resources", []):
        created_at = datetime.datetime.strptime(resource["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.UTC)
        if created_at < seven_days_ago:
            public_ids_to_delete.append(resource["public_id"])

    next_cursor = result.get("next_cursor")
    if not next_cursor:
        break

print(f"🧹 Total resources eligible for deletion: {len(public_ids_to_delete)}")

# Delete in batches (max 100 per request)
batch_size = 100
deleted_count = 0

for i in range(0, len(public_ids_to_delete), batch_size):
    batch = public_ids_to_delete[i:i + batch_size]
    cloudinary.api.delete_resources(batch)
    print(f"✅ Deleted {len(batch)} resources (Total so far: {deleted_count + len(batch)})")
    deleted_count += len(batch)

print(f"\n🎉 Cleanup complete. Total deleted: {deleted_count}")
