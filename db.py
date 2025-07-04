# Import necessary components from peewee
from peewee import *
import os

# Extract components from the parsed URL
PG_NAME = os.getenv("PG_NAME")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")
PG_HOST = os.getenv("PG_HOST")
PG_PORT = os.getenv("PG_PORT")

if not PG_NAME or not PG_USER or not PG_PASSWORD or not PG_HOST or not PG_PORT:
    raise ValueError("One or more PostgreSQL environment variables are not set.")

# Initialize the PostgreSQL database connection using parsed components
db = PostgresqlDatabase(
    PG_NAME,
    user=PG_USER,
    password=PG_PASSWORD,
    host=PG_HOST,
    port=PG_PORT
)

# Model
class Appointment(Model):
    id = PrimaryKeyField()
    name = TextField()
    time = DateField()

    class Meta:
        database = db
        table_name = 'appointments'
