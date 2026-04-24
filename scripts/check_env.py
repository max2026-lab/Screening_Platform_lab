from lawful_anomaly_screening.settings import load_settings


if __name__ == "__main__":
    settings = load_settings()
    print(
        {
            "db_path": str(settings.db_path),
            "baseline_path": str(settings.baseline_path),
            "logging_config_path": str(settings.logging_config_path),
            "export_precision_path": str(settings.export_precision_path),
            "endpoints_path": str(settings.endpoints_path),
            "preprocessing_config_path": str(settings.preprocessing_config_path),
        }
    )
