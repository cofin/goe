# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Native BigQuery load job configuration for GOE staged and direct loads."""

from google.cloud import bigquery

from goe.offload.offload_constants import FILE_STORAGE_FORMAT_AVRO, FILE_STORAGE_FORMAT_PARQUET

PARQUET_DECIMAL_TARGET_TYPES = [
    bigquery.DecimalTargetType.NUMERIC,
    bigquery.DecimalTargetType.BIGNUMERIC,
    bigquery.DecimalTargetType.STRING,
]
STAGING_SOURCE_FORMATS = {
    FILE_STORAGE_FORMAT_AVRO: bigquery.SourceFormat.AVRO,
    FILE_STORAGE_FORMAT_PARQUET: bigquery.SourceFormat.PARQUET,
}


def build_staging_load_job_config(
    staging_format: str,
    kms_key_name: str | None,
    labels: dict[str, str],
    *,
    write_disposition: str = bigquery.WriteDisposition.WRITE_TRUNCATE,
) -> bigquery.LoadJobConfig:
    """Return a BigQuery LoadJobConfig for GOE Avro or Parquet loads.

    No explicit schema is set: the staged files are self-describing, matching the schema inference of the
    external table so string-staged columns remain STRING for validate_type_conversions.
    """
    if staging_format not in STAGING_SOURCE_FORMATS:
        raise ValueError(f"Unsupported BigQuery staging format: {staging_format}")
    job_config = bigquery.LoadJobConfig(
        source_format=STAGING_SOURCE_FORMATS[staging_format],
        write_disposition=write_disposition,
        labels=labels,
    )
    if staging_format == FILE_STORAGE_FORMAT_PARQUET:
        job_config.decimal_target_types = PARQUET_DECIMAL_TARGET_TYPES
    if kms_key_name:
        job_config.destination_encryption_configuration = bigquery.EncryptionConfiguration(kms_key_name=kms_key_name)
    return job_config
