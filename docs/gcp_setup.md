# Google Cloud Platform Setup for a BigQuery Target

- [Overview](#overview)
- [Example Commands](#example-commands)
- [Managed Spark version implications](#managed-spark-version-implications)
- [Self-managed Spark and the Cloud Storage connector](#self-managed-spark-and-the-cloud-storage-connector)
- [Compute Engine Virtual Machine](#compute-engine-virtual-machine)
- [Generating Dataset DDL](#generating-dataset-ddl)

## Overview

This page details Google Cloud Platform (GCP) components required, with recommended minimal privileges, to use GOE in your GCP project.

### Service Account

A service account should be provisioned from the GCP project. This service account can be used by any service that will execute GOE commands, for example it could be attached to a Google Compute Engine (GCE) virtual machine (VM).

#### Authentication (Application Default Credentials)

GOE does not need service account private key files. BigQuery, Cloud KMS, Cloud Storage, and GOE's `gs://` log files all authenticate with [Application Default Credentials (ADC)](https://cloud.google.com/docs/authentication/application-default-credentials), optionally impersonating the GOE service account:

| Where GOE runs | ADC source | Additional configuration |
| :------------- | :--------- | :----------------------- |
| Compute Engine VM, GKE with Workload Identity, Cloud Run | Attached service account (metadata server) | None (recommended) |
| Operator workstation or CI runner | `gcloud auth application-default login`, or the credential file created by the CI system | `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=<GOE service account email>` |
| On-premises host or another cloud | [Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation-with-other-providers) credential configuration file (`"type": "external_account"`, not a key) referenced by `GOOGLE_APPLICATION_CREDENTIALS` | Optionally `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` |

GOE reads these `offload.env` settings:

- `GOOGLE_CLOUD_PROJECT`: project for BigQuery jobs and Cloud Storage requests. When unset GOE uses the ADC project, then `BIGQUERY_DATASET_PROJECT`.
- `GOOGLE_CLOUD_QUOTA_PROJECT`: optional quota/billing project for user or impersonated credentials.
- `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`: optional service account that GOE impersonates for BigQuery, Cloud KMS, Cloud Storage, and `gcloud dataproc` commands. The ADC principal needs `roles/iam.serviceAccountTokenCreator` on that service account and the `iamcredentials.googleapis.com` API must be enabled.
- `GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT`: optional service account that `gcloud dataproc` commands impersonate instead of `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`.
- `GOOGLE_DATAPROC_SERVICE_ACCOUNT`: runtime service account for Managed Spark serverless batches (`--service-account`). It is not used for permanent clusters, whose jobs run as the cluster VM service account.

The `gcloud` CLI keeps its own credentials, separate from ADC. When an impersonation service account is configured GOE adds `--impersonate-service-account` to every `gcloud dataproc` command; otherwise `gcloud` uses its active account.

Check the active identities and run the GOE credential preflight with:

```shell
gcloud auth list
gcloud auth application-default print-access-token > /dev/null && echo "ADC OK"
goe connect
```

`goe connect` prints the credential type, principal, impersonated service account, project, and quota project under "Google Cloud credentials", and warns when ADC resolves to a service account key.

### Cloud Storage Bucket

A Google Cloud Storage (GCS) bucket is required to stage data before ingesting it into BigQuery. Ensure the bucket is in a location compatible with the target BigQuery dataset.

### Managed Service for Apache Spark

For tables of a non-trivial size, GOE uses Spark to copy data from the source database to cloud storage. In a GCP setting this is likely to be provided by one of two services:

1. Managed Service for Apache Spark (serverless)
1. Managed Service for Apache Spark (permanent)

### Roles

The role names below are used throughput this page but can be changed to suit company policies. These roles will provide adequate access to stage data in cloud storage and load it into BigQuery.

| Role                | Mandatory | Purpose                                                                         |
| :------------------ | :-------: | :------------------------------------------------------------------------------ |
| `goe_gcs_role`           |     Y     | - Permissions to read/write on the GOE staging bucket.                            |
| `goe_bq_core_role`       |     Y     | - Core permissions to interact with BigQuery, list datasets/tables/etc.<br />- No data read/write permissions.<br />- Will be granted at the project level. |
| `goe_bq_app_role`        |     Y     | - Permissions to read/write data in the final dataset.<br />- Optionally can include table create/drop permissions.<br />- Locked down at dataset level. |
| `goe_bq_stg_role`        |     Y     | - Permissions to read data and create/drop staging tables in the staging dataset.<br />- Locked down at dataset level. |
| `goe_spark_role`           |     N     | - Permissions to interact with a permanent Managed Service for Apache Spark (permanent). |
| `goe_spark_serverless_role`  |     N     | - Permissions to interact with Managed Service for Apache Spark (serverless).     |

### Compute Engine Virtual Machine

To work interactively with GOE you need to be able run commands with appropriate permissions. We recommend attaching the service account to a GCE virtual machine and running all GOE commands from the VM. This is preferable to downloading service account keys.

The virtual machine requires limited resources as most of the intensive work is done by Spark and BigQuery.

## Example Commands

These examples can be used to create the components described above.

### Helper Variables

Note that the location below must be compatible with the BigQuery dataset location.

```shell
PROJECT=<your-project>
REGION=<your-region>
SVC_ACCOUNT=<your-service-account-name>
BUCKET=<your-bucket>
LOCATION=<your-location> # EU, US or ${REGION}
TARGET_DATASET=<your-target-dataset>
```

### Service Account

```shell
gcloud iam service-accounts create ${SVC_ACCOUNT} \
--project ${PROJECT} \
--description="GOE service account"

gcloud services enable iamcredentials.googleapis.com --project=${PROJECT}
```

Optionally allow an operator or CI identity to impersonate the GOE service account with `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`:

```shell
gcloud iam service-accounts add-iam-policy-binding ${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--project=${PROJECT} \
--member=user:<operator-email> \
--role=roles/iam.serviceAccountTokenCreator
```

### Cloud Storage Bucket

```shell
gcloud storage buckets create gs://${BUCKET} --project ${PROJECT} \
--location=${LOCATION} \
--uniform-bucket-level-access
```

### Managed Service for Apache Spark (serverless)

Optional commands if using Managed Service for Apache Spark (serverless).

```shell
gcloud compute networks subnets update ${SUBNET} \
--project=${PROJECT} --region=${REGION} \
--enable-private-ip-google-access

gcloud projects add-iam-policy-binding ${PROJECT} \
--member=serviceAccount:${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--role=roles/dataproc.worker
```

In this example the GOE service account is also the serverless runtime service account (`GOOGLE_DATAPROC_SERVICE_ACCOUNT`). The identity that submits a batch needs `roles/iam.serviceAccountUser` on the runtime service account only, not project-wide:

```shell
gcloud iam service-accounts add-iam-policy-binding ${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--project=${PROJECT} \
--member=serviceAccount:${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--role=roles/iam.serviceAccountUser
```

### Managed Service for Apache Spark (permanent)

Optional commands if using Managed Service for Apache Spark (permanent).

Enable required services:

```shell
gcloud services enable dataproc.googleapis.com --project ${PROJECT}
gcloud services enable iamcredentials.googleapis.com --project=${PROJECT}
```

Values supplied below are examples only, changes will likely be required for each use case:

```shell
SUBNET=<your-subnet>
CLUSTER_NAME=<cluster-name>
DP_SVC_ACCOUNT=goe-managed-spark
ZONE=<your-zone>

gcloud iam service-accounts create ${DP_SVC_ACCOUNT} \
--project=${PROJECT} \
--description="GOE Managed Spark service account"

gcloud projects add-iam-policy-binding ${PROJECT} \
--member=serviceAccount:${DP_SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--role=roles/dataproc.worker

gcloud compute networks subnets update ${SUBNET} \
--project=${PROJECT} --region=${REGION} \
--enable-private-ip-google-access

gcloud dataproc clusters create ${CLUSTER_NAME} \
--project ${PROJECT} --region ${REGION} --zone ${ZONE} \
--bucket ${BUCKET} \
--subnet projects/${PROJECT}/regions/${REGION}/subnetworks/${SUBNET} \
--no-address \
--single-node \
--service-account=${DP_SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--master-machine-type n2-standard-16 --master-boot-disk-size 1000 \
--image-version 2.1-debian11
```

### Roles

#### goe_gcs_role

Note that the role grant is bound to the staging bucket. No project-wide access is granted.

```shell
gcloud iam roles create goe_gcs_role --project ${PROJECT} \
--title="GOE Cloud Storage Access" \
--description="GOE permissions to access staging Cloud Storage bucket" \
--permissions=storage.buckets.get,\
storage.objects.create,storage.objects.delete,\
storage.objects.get,storage.objects.list \
--stage=GA

gcloud storage buckets add-iam-policy-binding gs://${BUCKET} \
--member=serviceAccount:${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--role=projects/${PROJECT}/roles/${ROLE}
```

#### goe_bq_core_role

Note that this role is granted at the project level.

```shell
gcloud iam roles create goe_bq_core_role --project ${PROJECT} \
--title="GOE Core BigQuery Access" \
--description="GOE permissions for core access to BigQuery" \
--permissions=bigquery.datasets.get,\
bigquery.jobs.create,\
bigquery.tables.get,\
bigquery.tables.list \
--stage=GA

gcloud projects add-iam-policy-binding ${PROJECT} \
--member=serviceAccount:${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--role=projects/${PROJECT}/roles/goe_bq_core_role
```

If GOE is permitted to create datasets then add these privileges:

```shell
gcloud iam roles update goe_bq_core_role --project ${PROJECT} \
--add-permissions=bigquery.datasets.create
```

#### goe_bq_app_role

Note that the role grant is bound to the target BigQuery dataset. No project-wide access is granted. The `bq` utility is used to grant the role because `gcloud` does not support these granular grants.

***

__NOTE:__ The target dataset must be created *before* executing these commands (see [Generating Dataset DDL](#generating-dataset-ddl) for details).

***

```shell
gcloud iam roles create goe_bq_app_role --project ${PROJECT} \
--title="GOE Data Update Access" \
--description="Grants GOE permissions to read and modify data in an application dataset" \
--permissions=bigquery.tables.getData,\
bigquery.tables.updateData \
--stage=GA

echo "GRANT \`projects/${PROJECT}/roles/goe_bq_app_role\` ON SCHEMA ${TARGET_DATASET}
TO \"serviceAccount:${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com\";
" | bq query --project_id=${PROJECT} --nouse_legacy_sql --location=${LOCATION}
```

If GOE is permitted to create tables then add these privileges:

```shell
gcloud iam roles update goe_bq_app_role --project ${PROJECT} \
--add-permissions=bigquery.tables.create,bigquery.tables.update
```

If GOE is permitted to drop tables then add these privileges:

```shell
gcloud iam roles update goe_bq_app_role --project ${PROJECT} \
--add-permissions=bigquery.tables.delete
```

#### goe_bq_stg_role

Note that the role grant is bound to the staging BigQuery dataset (which has the same name as the target dataset but with a "_load" suffix). No project-wide access is granted. The `bq` utility is used to grant the role because `gcloud` does not support these granular grants.

***

__NOTE:__ The staging dataset must be created *before* executing these commands (see [Generating Dataset DDL](#generating-dataset-ddl) for details).

***

```shell
gcloud iam roles create goe_bq_stg_role --project ${PROJECT} \
--title="GOE Data Staging Access" \
--description="Grants GOE permissions to manage objects in a staging dataset" \
--permissions=bigquery.tables.create,\
bigquery.tables.delete,\
bigquery.tables.getData \
--stage=GA

echo "GRANT \`projects/${PROJECT}/roles/goe_bq_stg_role\` ON SCHEMA ${TARGET_DATASET}_load
TO \"serviceAccount:${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com\";
" | bq query --project_id=${PROJECT} --nouse_legacy_sql --location=${LOCATION}
```

#### goe_spark_role

```shell
gcloud iam roles create goe_spark_role --project ${PROJECT} \
--title="GOE Managed Spark Access" --description="GOE Managed Spark Access" \
--permissions=dataproc.clusters.get,dataproc.clusters.use,\
dataproc.jobs.create,dataproc.jobs.get \
--stage=GA

gcloud projects add-iam-policy-binding ${PROJECT} \
--member=serviceAccount:${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--role=projects/${PROJECT}/roles/goe_spark_role
```

Jobs submitted to a permanent cluster run as the cluster VM service account, so this role grants no `iam.serviceAccounts.*` permissions. If GOE impersonates a different service account for `gcloud` commands (`GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` or `GOOGLE_DATAPROC_IMPERSONATE_SERVICE_ACCOUNT`), grant `goe_spark_role` to that service account instead.

#### goe_spark_serverless_role

```shell
gcloud iam roles create goe_spark_serverless_role --project ${PROJECT} \
--title="GOE Managed Spark Access" --description="GOE Managed Spark Access" \
--permissions=dataproc.batches.create,dataproc.batches.get \
--stage=GA

gcloud projects add-iam-policy-binding ${PROJECT} \
--member=serviceAccount:${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
--role=projects/${PROJECT}/roles/goe_spark_serverless_role
```

## Managed Spark version implications

### Avro driver support

The version of Spark in the Managed Spark environment dictates the version of the Avro driver to use:

| GOOGLE_DATAPROC_BATCHES_VERSION | Avro driver                            |
| :------------------------------ | :------------------------------------- |
| 1.1                             | org.apache.spark:spark-avro_2.12:3.3.0 |
| 1.2                             | org.apache.spark:spark-avro_2.12:3.5.1 |
| 2.1                             | org.apache.spark:spark-avro_2.13:3.5.1 |
| 2.2                             | org.apache.spark:spark-avro_2.13:3.5.3 |

`OFFLOAD_TRANSPORT_SPARK_PROPERTIES` should be updated accordingly.

### GOE Spark Listener

The GOE Spark listener is used to collect performance metrics from the Spark jobs created by Offload. The listener is only invoked when using the Spark transport method.

| GOOGLE_DATAPROC_BATCHES_VERSION | Listener JAR file                     |
| :------------------------------ | :------------------------------------ |
| 1.1                             | goe-spark-3.3.0-listener_2.12-1.0.jar |
| 1.2                             | goe-spark-3.5.1-listener_2.12-1.0.jar |
| 2.1                             | goe-spark-3.5.1-listener_2.13-1.0.jar |
| 2.2                             | goe-spark-3.5.3-listener_2.13-1.0.jar |

The correct JAR file should be copied into place inside the `$OFFLOAD_HOME/lib/` directory, e.g.:

```shell
cp ${OFFLOAD_HOME}/lib/goe-spark-3.5.3-listener_2.13-1.0.jar ${OFFLOAD_HOME}/lib/goe-spark-listener.jar
```

## Self-managed Spark and the Cloud Storage connector

Managed Spark already includes a Cloud Storage connector that authenticates as the runtime or cluster service account. Spark clusters outside Managed Spark (`spark-submit`, Livy, or Spark Thrift Server transports) need the [Cloud Storage connector](https://github.com/GoogleCloudDataproc/hadoop-connectors/blob/branch-3.0.x/gcs/CONFIGURATION.md#authentication) 3.0.x (`gcs-connector-3.0.20-shaded.jar`, Java 11 or later) with ADC:

```text
spark.hadoop.fs.gs.auth.type=APPLICATION_DEFAULT
spark.hadoop.fs.gs.auth.impersonation.service.account=<GOE service account email>
```

- `fs.gs.auth.type=APPLICATION_DEFAULT` uses the metadata server on Google Cloud, or the file named by `GOOGLE_APPLICATION_CREDENTIALS`. Off Google Cloud, distribute a Workload Identity Federation credential configuration file to every node and set `spark.executorEnv.GOOGLE_APPLICATION_CREDENTIALS` and `spark.yarn.appMasterEnv.GOOGLE_APPLICATION_CREDENTIALS` to its path.
- `fs.gs.auth.impersonation.service.account` is optional; the ADC principal needs `roles/iam.serviceAccountTokenCreator` on that service account.
- The 2.x key properties (`fs.gs.auth.service.account.enable`, `.email`, `.keyfile`, `.private.key`, `.private.key.id`) were removed in connector 3.0.0 and must not be used.

Set these through `OFFLOAD_TRANSPORT_SPARK_PROPERTIES`. The Spark distribution built by `make spark-target` (`tools/transport/Makefile`) already sets `spark.hadoop.fs.gs.auth.type APPLICATION_DEFAULT`.

## Compute Engine Virtual Machine

Values supplied below are examples only. Changes are likely to be required for each use case:

```shell
INSTANCE_NAME=goe-node
ZONE=<instance-zone>
SUBNET=<your-subnet>

gcloud compute instances create ${INSTANCE_NAME} \
  --project=${PROJECT} \
  --zone=${ZONE} \
  --machine-type=e2-medium \
  --network-interface=stack-type=IPV4_ONLY,subnet=${SUBNET},no-address \
  --boot-disk-device-name=${INSTANCE_NAME} \
  --boot-disk-size=20 \
  --boot-disk-type=pd-balanced \
  --boot-disk-auto-delete \
  --image-project=debian-cloud \
  --image-family=debian-11 \
  --metadata=enable-oslogin=true \
  --maintenance-policy=MIGRATE \
  --provisioning-model=STANDARD \
  --service-account=${SVC_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com \
  --scopes=https://www.googleapis.com/auth/cloud-platform
```

## Generating Dataset DDL

DDL to create BigQuery datasets can be generated using the `--ddl-file` Offload option. For example:

```shell
goe offload -t schema1.table1 --create-backend-db --ddl-file=/tmp/schema1.table1.sql
```

After running the command above the file `/tmp/schema1.table1.sql` will contain:

- BigQuery DDL to create target dataset `schema1`
- BigQuery DDL to create staging dataset `schema1_load`
- BigQuery DDL to create table `schema1.table1.sql`
