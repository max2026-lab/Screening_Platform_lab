from lawful_anomaly_screening.db.sqlite import init_db
from lawful_anomaly_screening.settings import load_settings


if __name__ == "__main__":
    init_db(load_settings().db_path)
