# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""TestOffloadMetadata: Integration test library to test offload metadata API for configured frontend."""

from unittest import TestCase, main

from goe.offload.registry import create_repository_client
from goe.orchestration import orchestration_constants
from goe.orchestration.execution_id import ExecutionId
from goe.persistence.models import (
    METADATA_ATTRIBUTES,
    OffloadMetadata,
)
from tests.integration.test_functions import (
    build_current_options,
    get_default_test_user,
)
from tests.testlib.test_framework.test_functions import (
    get_test_messages,
)

UNITTEST_METADATA_NAME = "INTTEST_METADATA_SALES"

METADATA_DICT_TEST_DEFAULTS = {
    "OFFLOAD_TYPE": "FULL",
    "HADOOP_OWNER": "SH_LONG_1234567890_NAME",
    "HADOOP_TABLE": "TABLE_LONG_1234567890_NAME",
    "OFFLOADED_OWNER": "SH_LONG_1234567890_NAME",
    "OFFLOADED_TABLE": "TABLE_LONG_1234567890_NAME",
    "INCREMENTAL_KEY": "COLUMN_LONG_1234567890_NAME",
    "INCREMENTAL_HIGH_VALUE": "LONG_1234567890_1234567890_VALUE",
    "INCREMENTAL_PREDICATE_TYPE": "RANGE",
    "INCREMENTAL_PREDICATE_VALUE": ["column(OBJECT_ID) < numeric(100)"],
    "OFFLOAD_BUCKET_COLUMN": "SOME_COLUMN",
    "OFFLOAD_SORT_COLUMNS": "SOME_COLUMN1,SOME_COLUMN2",
    "INCREMENTAL_RANGE": "PARTITION",
    "OFFLOAD_PARTITION_FUNCTIONS": "UDF1,UDF2",
    "COMMAND_EXECUTION": "UUID",
}

EXAMPLE_CHANNELS_METADATA_DICT = {
    "OFFLOAD_TYPE": "FULL",
    "HADOOP_OWNER": "SH",
    "HADOOP_TABLE": "CHANNELS",
    "OFFLOADED_OWNER": "SH",
    "OFFLOADED_TABLE": "CHANNELS",
    "INCREMENTAL_KEY": None,
    "INCREMENTAL_HIGH_VALUE": None,
    "INCREMENTAL_PREDICATE_TYPE": None,
    "INCREMENTAL_PREDICATE_VALUE": None,
    "OFFLOAD_BUCKET_COLUMN": None,
    "OFFLOAD_SORT_COLUMNS": None,
    "INCREMENTAL_RANGE": None,
    "OFFLOAD_PARTITION_FUNCTIONS": None,
    "COMMAND_EXECUTION": "UUID",
}

EXAMPLE_SALES_METADATA_DICT = {
    "OFFLOAD_TYPE": "INCREMENTAL",
    "HADOOP_OWNER": "SH",
    "HADOOP_TABLE": "SALES",
    "OFFLOADED_OWNER": "SH",
    "OFFLOADED_TABLE": "SALES",
    "OFFLOAD_SNAPSHOT": 76850168,
    "INCREMENTAL_KEY": "TIME_ID",
    "INCREMENTAL_HIGH_VALUE": "TO_DATE(' 2012-01-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')",
    "INCREMENTAL_PREDICATE_TYPE": "RANGE",
    "INCREMENTAL_PREDICATE_VALUE": None,
    "OFFLOAD_BUCKET_COLUMN": None,
    "OFFLOAD_SORT_COLUMNS": None,
    "INCREMENTAL_RANGE": "PARTITION",
    "OFFLOAD_PARTITION_FUNCTIONS": None,
    "COMMAND_EXECUTION": "UUID",
}
EXAMPLE_SALES_METADATA_DICT_HV2 = "TO_DATE(' 2012-02-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')"
EXAMPLE_SALES_METADATA_DICT_HV3 = "TO_DATE(' 2012-03-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')"

EXAMPLE_GOE_LIST_RANGE_DAY_DT_METADATA_DICT = {
    "OFFLOAD_TYPE": "INCREMENTAL",
    "HADOOP_OWNER": "SH_TEST",
    "HADOOP_TABLE": "GOE_LIST_RANGE_DAY_DT",
    "OFFLOADED_OWNER": "SH_TEST",
    "OFFLOADED_TABLE": "GOE_LIST_RANGE_DAY_DT",
    "OFFLOAD_SNAPSHOT": 69472864,
    "INCREMENTAL_KEY": "DT",
    "INCREMENTAL_HIGH_VALUE": "TO_DATE(' 2015-01-31 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')",
    "INCREMENTAL_PREDICATE_TYPE": "RANGE",
    "INCREMENTAL_PREDICATE_VALUE": None,
    "OFFLOAD_BUCKET_COLUMN": None,
    "OFFLOAD_SORT_COLUMNS": None,
    "INCREMENTAL_RANGE": "SUBPARTITION",
    "OFFLOAD_PARTITION_FUNCTIONS": None,
    "COMMAND_EXECUTION": "UUID",
}

EXAMPLE_STORY_PBO_DIM_METADATA_DICT = {
    "OFFLOAD_TYPE": "INCREMENTAL",
    "HADOOP_OWNER": "SH_TEST",
    "HADOOP_TABLE": "STORY_PBO_DIM",
    "OFFLOADED_OWNER": "SH_TEST",
    "OFFLOADED_TABLE": "STORY_PBO_DIM",
    "OFFLOAD_SNAPSHOT": 76853651,
    "INCREMENTAL_KEY": None,
    "INCREMENTAL_HIGH_VALUE": None,
    "INCREMENTAL_PREDICATE_TYPE": "PREDICATE",
    "INCREMENTAL_PREDICATE_VALUE": ['column(PROD_SUBCATEGORY) = string("Camcorders")'],
    "OFFLOAD_BUCKET_COLUMN": None,
    "OFFLOAD_SORT_COLUMNS": None,
    "INCREMENTAL_RANGE": None,
    "OFFLOAD_PARTITION_FUNCTIONS": None,
    "COMMAND_EXECUTION": "UUID",
}

EXAMPLE_STORY_PBO_R_INTRA_METADATA_DICT = {
    "OFFLOAD_TYPE": "INCREMENTAL",
    "HADOOP_OWNER": "SH_TEST",
    "HADOOP_TABLE": "STORY_PBO_R_INTRA",
    "OFFLOADED_OWNER": "SH_TEST",
    "OFFLOADED_TABLE": "STORY_PBO_R_INTRA",
    "OFFLOAD_SNAPSHOT": 76856298,
    "INCREMENTAL_KEY": "TIME_ID",
    "INCREMENTAL_HIGH_VALUE": "TO_DATE(' 2012-02-01 00:00:00', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')",
    "INCREMENTAL_PREDICATE_TYPE": "RANGE_AND_PREDICATE",
    "INCREMENTAL_PREDICATE_VALUE": [
        "((column(TIME_ID) >= datetime(2012-02-01) AND column(TIME_ID) < datetime(2012-03-01)) AND column(CHANNEL_ID) = numeric(2))"
    ],
    "OFFLOAD_BUCKET_COLUMN": None,
    "OFFLOAD_SORT_COLUMNS": None,
    "INCREMENTAL_RANGE": "PARTITION",
    "OFFLOAD_PARTITION_FUNCTIONS": None,
    "COMMAND_EXECUTION": "UUID",
}


class TestOffloadMetadata(TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = None
        self.messages = None
        self.db = None
        self.maxDiff = None

    def setUp(self):
        super().setUp()
        self.config = build_current_options()
        self.messages = get_test_messages(self.config, "TestOffloadMetadata")
        self.db = get_default_test_user()

    def test_metadata_by_client(self):
        """Tests we can interact with OffloadMetadata by client."""
        client = create_repository_client(
            self.config,
            self.messages,
            trace_action="repo_client(test_metadata_by_client)",
        )
        self._test_metadata(self._gen_test_metadata(table_name_suffix="_CLI"), client=client)

    def test_metadata_direct(self):
        """Tests we can interact with OffloadMetadata without creating a client."""
        self._test_metadata(
            self._gen_test_metadata(table_name_suffix="_DIR"),
            connection_options=self.config,
            messages=self.messages,
        )

    def test_generated_metadata(self):
        """Test that the metadata prepared with gen_offload_metadata goes through the standard test flow."""
        source_metadata = self._gen_test_metadata(table_name_suffix="_GM")
        source_metadata_dict = source_metadata.as_dict()
        attributes = {k: source_metadata_dict[v] for k, v in METADATA_ATTRIBUTES.items()}
        new_metadata = OffloadMetadata.from_attributes(
            connection_options=self.config, messages=self.messages, **attributes
        )
        self.assertIsInstance(new_metadata, OffloadMetadata)
        self.assertEqual(source_metadata_dict, new_metadata.as_dict(), "Generated metadata mismatch")
        self._test_metadata(new_metadata, connection_options=self.config, messages=self.messages)

    def test_is_subpartition_offload(self):
        channels_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_CHANNELS_METADATA_DICT)
        self.assertIsInstance(channels_metadata.is_subpartition_offload(), bool)
        self.assertEqual(channels_metadata.is_subpartition_offload(), False)

        sales_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_SALES_METADATA_DICT)
        self.assertIsInstance(sales_metadata.is_subpartition_offload(), bool)
        self.assertEqual(sales_metadata.is_subpartition_offload(), False)

        goe_list_range_day_dt_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_GOE_LIST_RANGE_DAY_DT_METADATA_DICT)
        self.assertIsInstance(goe_list_range_day_dt_metadata.is_subpartition_offload(), bool)
        self.assertEqual(goe_list_range_day_dt_metadata.is_subpartition_offload(), True)

    def test_is_hwm_in_hybrid_view(self):
        channels_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_CHANNELS_METADATA_DICT)
        self.assertIsInstance(channels_metadata.is_hwm_in_hybrid_view(), bool)
        self.assertEqual(channels_metadata.is_hwm_in_hybrid_view(), False)

        sales_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_SALES_METADATA_DICT)
        self.assertIsInstance(sales_metadata.is_hwm_in_hybrid_view(), bool)
        self.assertEqual(sales_metadata.is_hwm_in_hybrid_view(), True)

        pbo_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_STORY_PBO_DIM_METADATA_DICT)
        self.assertIsInstance(pbo_metadata.is_hwm_in_hybrid_view(), bool)
        self.assertEqual(pbo_metadata.is_hwm_in_hybrid_view(), True)

    def test_incremental_data_append_feature(self):
        """Verify incremental_data_append_feature across dimension, partition, subpartition, and predicate offloads."""
        channels_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_CHANNELS_METADATA_DICT)
        self.assertIsInstance(channels_metadata.incremental_data_append_feature(), str)
        self.assertNotIn("partition", channels_metadata.incremental_data_append_feature().lower())
        self.assertNotIn("sub", channels_metadata.incremental_data_append_feature().lower())
        self.assertNotIn("predicate", channels_metadata.incremental_data_append_feature().lower())

        sales_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_SALES_METADATA_DICT)
        self.assertIsInstance(sales_metadata.incremental_data_append_feature(), str)
        self.assertIn("partition", sales_metadata.incremental_data_append_feature().lower())
        self.assertNotIn("sub", sales_metadata.incremental_data_append_feature().lower())
        self.assertNotIn("predicate", sales_metadata.incremental_data_append_feature().lower())

        goe_list_range_day_dt_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_GOE_LIST_RANGE_DAY_DT_METADATA_DICT)
        self.assertIsInstance(goe_list_range_day_dt_metadata.incremental_data_append_feature(), str)
        self.assertIn(
            "partition",
            goe_list_range_day_dt_metadata.incremental_data_append_feature().lower(),
        )
        self.assertIn(
            "sub",
            goe_list_range_day_dt_metadata.incremental_data_append_feature().lower(),
        )
        self.assertNotIn(
            "predicate",
            goe_list_range_day_dt_metadata.incremental_data_append_feature().lower(),
        )

        pbo_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_STORY_PBO_DIM_METADATA_DICT)
        self.assertIsInstance(pbo_metadata.incremental_data_append_feature(), str)
        self.assertNotIn("partition", pbo_metadata.incremental_data_append_feature().lower())
        self.assertNotIn("sub", pbo_metadata.incremental_data_append_feature().lower())
        self.assertIn("predicate", pbo_metadata.incremental_data_append_feature().lower())

        intra_pbo_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_STORY_PBO_R_INTRA_METADATA_DICT)
        self.assertIsInstance(intra_pbo_metadata.incremental_data_append_feature(), str)
        self.assertIn("partition", intra_pbo_metadata.incremental_data_append_feature().lower())
        self.assertNotIn("sub", intra_pbo_metadata.incremental_data_append_feature().lower())
        self.assertIn("predicate", intra_pbo_metadata.incremental_data_append_feature().lower())

    def _convert_to_test_metadata(
        self,
        source_metadata,
        new_owner,
        new_name,
    ):
        """Generate some test data, using the metadata for SALES as a base and a description of the
        OFFLOAD_METADATA table to fill in the blanks...
        """
        test_metadata = source_metadata
        test_metadata["OFFLOADED_OWNER"] = new_owner
        test_metadata["OFFLOADED_TABLE"] = new_name
        test_metadata["HADOOP_TABLE"] = new_name
        for k, v in test_metadata.items():
            if v is None:
                test_metadata[k] = METADATA_DICT_TEST_DEFAULTS[k]
        return test_metadata

    def _gen_test_metadata(self, table_name_suffix=None):
        source_metadata = OffloadMetadata.from_legacy_dict(EXAMPLE_SALES_METADATA_DICT)
        new_metadata_dict = self._convert_to_test_metadata(
            source_metadata.as_dict(),
            self.db,
            UNITTEST_METADATA_NAME + (table_name_suffix or ""),
        )
        return OffloadMetadata.from_legacy_dict(new_metadata_dict)

    def _test_metadata(
        self,
        test_metadata: OffloadMetadata,
        client=None,
        connection_options=None,
        messages=None,
    ):
        """Tests we can get/change and delete OffloadMetadata"""
        execution_id = ExecutionId()
        repo_client = client or create_repository_client(
            connection_options or self.config,
            messages or self.messages,
        )
        cid = repo_client.start_command(
            execution_id,
            orchestration_constants.COMMAND_OFFLOAD,
            "test",
            '{"test": 123}',
        )

        test_metadata = test_metadata.with_updates(command_execution=execution_id)
        repo_client.set_offload_metadata(test_metadata)

        saved_metadata = repo_client.get_offload_metadata(
            self.db,
            test_metadata.offloaded_table,
        )
        self.assertIsInstance(saved_metadata, OffloadMetadata)
        self.assertEqual(
            test_metadata.as_dict(),
            saved_metadata.as_dict(),
            "Saved metadata mismatch when re-fetched",
        )

        test_metadata = test_metadata.with_updates(incremental_high_value=EXAMPLE_SALES_METADATA_DICT_HV2)
        repo_client.set_offload_metadata(test_metadata)
        saved_metadata = repo_client.get_offload_metadata(
            self.db,
            test_metadata.offloaded_table,
        )
        self.assertIsInstance(saved_metadata, OffloadMetadata)
        self.assertEqual(
            test_metadata.offload_snapshot,
            saved_metadata.offload_snapshot,
            "Saved metadata.offload_snapshot mismatch when re-fetched",
        )
        test_metadata_dict = test_metadata.as_dict()
        test_metadata_dict["INCREMENTAL_HIGH_VALUE"] = EXAMPLE_SALES_METADATA_DICT_HV3
        test_metadata = OffloadMetadata.from_legacy_dict(test_metadata_dict)
        repo_client.set_offload_metadata(test_metadata)
        saved_metadata = repo_client.get_offload_metadata(
            self.db,
            test_metadata.offloaded_table,
        )
        self.assertIsInstance(saved_metadata, OffloadMetadata)
        self.assertEqual(
            test_metadata.offload_snapshot,
            saved_metadata.offload_snapshot,
            "Saved metadata.offload_snapshot mismatch when re-fetched",
        )

        repo_client.drop_offload_metadata(self.db, test_metadata.offloaded_table)
        saved_metadata = repo_client.get_offload_metadata(
            self.db,
            test_metadata.offloaded_table,
        )
        self.assertIsNone(saved_metadata, "Metadata was not deleted")

        repo_client.end_command(cid, orchestration_constants.COMMAND_SUCCESS)


if __name__ == "__main__":
    main()
