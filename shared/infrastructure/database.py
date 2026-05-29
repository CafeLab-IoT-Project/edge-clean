from peewee import SqliteDatabase

db = SqliteDatabase('edge_clean.db')

def init_db():
    db.connect()
    from iam.infrastructure.models import Device
    db.create_tables([Device], safe=True)
    db.close()