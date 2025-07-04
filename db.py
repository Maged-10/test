# Import necessary components from peewee
from peewee import *
import datetime
import os
import urllib.parse # To parse the database URL

# --- Database Configuration ---
# IMPORTANT: The DATABASE_URL environment variable should be set in your deployment environment
# (e.g., Vercel, Railway, Heroku, etc.) or locally for development.
# Example format: postgresql://user:password@host:port/database_name
DATABASE_URL = os.getenv("POSTGRES_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set. Please set it to connect to PostgreSQL.")

# Parse the database URL
url = urllib.parse.urlparse(DATABASE_URL)

# Extract components from the parsed URL
DB_NAME = url.path[1:] # Remove leading '/'
DB_USER = url.username
DB_PASSWORD = url.password
DB_HOST = url.hostname
DB_PORT = url.port if url.port else 5432 # Default PostgreSQL port is 5432

# Initialize the PostgreSQL database connection using parsed components
db = PostgresqlDatabase(
    DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT
)

# --- Define Your Model (Table Schema) ---
class Appointment(Model):
    # Define columns corresponding to your 'appointments' table
    id = PrimaryKeyField()
    name = CharField()
    time = DateField()

    class Meta:
        database = db
        table_name = 'appointments'

# --- Database Operations (for testing/demonstration, can be removed if only used by main.py) ---

def connect_and_operate():
    """
    Connects to the database, creates tables (if they don't exist),
    inserts sample data, and retrieves data.
    This function is primarily for testing db.py directly.
    """
    try:
        db.connect()
        print("Successfully connected to the database.")

        db.create_tables([Appointment])
        print("Table 'appointments' ensured (created if not exists).")

        # --- Insert Sample Data ---
        print("\n--- Inserting sample data ---")
        if Appointment.select().count() == 0:
            Appointment.create(name='John Doe', time=datetime.date(2025, 7, 10))
            Appointment.create(name='Jane Smith', time=datetime.date(2025, 7, 11))
            Appointment.create(name='Alice Johnson', time=datetime.date(2025, 7, 10))
            print("Sample appointments inserted.")
        else:
            print("Appointments table already contains data. Skipping sample insertion.")

        # --- Retrieve All Data ---
        print("\n--- Retrieving all appointments ---")
        all_appointments = Appointment.select()
        for appointment in all_appointments:
            print(f"ID: {appointment.id}, Name: {appointment.name}, Time: {appointment.time}")

    except OperationalError as e:
        print(f"Database connection error: {e}")
        print("Please ensure your DATABASE_URL is correct and PostgreSQL is running.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if not db.is_closed():
            db.close()
            print("\nDatabase connection closed.")

# This block allows you to run db.py directly for testing the connection
if __name__ == "__main__":
    connect_and_operate()
