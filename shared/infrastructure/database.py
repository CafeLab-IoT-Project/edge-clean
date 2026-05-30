from pathlib import Path
import sys

from peewee import Model, SqliteDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_PATH = PROJECT_ROOT / "edge_clean.db"
db = SqliteDatabase(DATABASE_PATH)

class BaseModel(Model):
    class Meta:
        database = db

def init_db():
    db.connect(reuse_if_open=True)
    from iam.infrastructure.models import DeviceModel
    db.create_tables([DeviceModel], safe=True)
    db.close()

if __name__ == "__main__":
    init_db()
