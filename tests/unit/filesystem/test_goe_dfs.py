# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for GOEDfs implementations, get_dfs_from_options factory dispatch, and URI helpers."""

import logging
from types import SimpleNamespace
from typing import Any
from unittest import TestCase, main

from goe.filesystem.goe_dfs import (
    DFS_TYPE_DIRECTORY,
    DFS_TYPE_FILE,
    UNSUPPORTED_URI_SCHEME_EXCEPTION_TEXT,
    VALID_OFFLOAD_FS_SCHEMES,
    CloudStorageDfsAdapter,
    GOEDfsException,
    gen_fs_uri,
    uri_component_split,
)
from goe.filesystem.goe_dfs_factory import get_dfs_from_options
from goe.filesystem.hdfs_client import HDFS_MODE_CLI, HDFS_MODE_WEBHDFS, HdfsClient
from goe.offload.offload_constants import BACKEND_DISTRO_CDH, DBTYPE_BIGQUERY, DBTYPE_HIVE
from goe.offload.offload_messages import OffloadMessages

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class TestGOEDfs(TestCase):
    """Base test harness exercising the GOEDfs interface in dry_run/do_not_connect mode."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.api: Any = None
        self.options: Any = None
        self.some_dir: str = ""
        self.some_file: str = ""
        self.some_local_file: str = ""

    def _test_chmod(self) -> None:
        try:
            self.api.chmod(self.some_dir, "755")
            self.api.chmod(self.some_dir, "g+w")
        except NotImplementedError:
            pass

    def _test_chgrp(self) -> None:
        try:
            self.api.chgrp(self.some_dir, "a-group")
        except NotImplementedError:
            pass

    def _test_container_exists(self) -> None:
        try:
            self.assertIn(
                self.api.container_exists("some-scheme", "some-container"),
                (True, False),
            )
            if self.options:
                self.assertTrue(
                    self.api.container_exists(
                        self.options.offload_fs_scheme,
                        self.options.offload_fs_container,
                    )
                )
                self.assertFalse(
                    self.api.container_exists(self.options.offload_fs_scheme, "this-is-defo-not-a-container")
                )
        except NotImplementedError:
            pass

    def _test_copy_from_local(self) -> None:
        self.api.copy_from_local(self.some_local_file, self.some_file)
        self.api.copy_from_local(self.some_local_file, self.some_file, overwrite=True)

    def _test_copy_to_local(self) -> None:
        self.api.copy_to_local(self.some_file, self.some_local_file)
        self.api.copy_to_local(self.some_file, self.some_local_file, overwrite=True)

    def _test_delete(self) -> None:
        self.api.delete(self.some_file)
        self.api.delete(self.some_dir, recursive=True)

    def _test_list_dir(self) -> None:
        listing = self.api.list_dir(self.some_dir)
        if listing:
            self.assertIsInstance(listing, list)

    def _test_mkdir(self) -> None:
        self.api.mkdir(self.some_dir)

    def _test_read(self) -> None:
        self.api.read(self.some_file)

    def _test_rename(self) -> None:
        try:
            self.api.rename(self.some_file, self.some_file + "_2")
        except NotImplementedError:
            pass

    def _test_rmdir(self) -> None:
        self.api.rmdir(self.some_dir)

    def _test_stat(self) -> None:
        stat = self.api.stat(self.some_dir)
        if stat:
            self.assertIsInstance(stat, dict)
            self.assertIn("type", stat)
            self.assertEqual(stat["type"], DFS_TYPE_DIRECTORY)
            self.assertIn("length", stat)
        stat = self.api.stat(self.some_file)
        if stat:
            self.assertIsInstance(stat, dict)
            self.assertIn("type", stat)
            self.assertEqual(stat["type"], DFS_TYPE_FILE)
            self.assertIn("length", stat)

    def _test_gen_fs_uri(self) -> None:
        def check_gen_fs_uri(
            expected_uri: str,
            path_prefix: str,
            db_path_suffix: str | None = None,
            scheme: str | None = None,
            container: str | None = None,
            backend_db: str | None = None,
            table_name: str | None = None,
        ) -> None:
            uri = gen_fs_uri(
                path_prefix,
                db_path_suffix=db_path_suffix,
                scheme=scheme,
                container=container,
                backend_db=backend_db,
                table_name=table_name,
            )
            self.assertIsInstance(uri, str)
            self.assertEqual(uri, expected_uri)

        check_gen_fs_uri("s3a://bucket/some-path", "some-path", scheme="s3a", container="bucket")
        check_gen_fs_uri(
            "gs://dev-bucket/some-path/dev-name/db_load/my-table",
            "some-path/dev-name",
            scheme="gs",
            container="dev-bucket",
            backend_db="db_load",
            table_name="my-table",
        )
        check_gen_fs_uri(
            "hdfs:///user/goe/db_load.db/my-table",
            "/user/goe",
            ".db",
            scheme="hdfs",
            backend_db="db_load",
            table_name="my-table",
        )
        check_gen_fs_uri(
            "/user/goe/db_load.db/my-table",
            "/user/goe",
            ".db",
            backend_db="db_load",
            table_name="my-table",
        )
        check_gen_fs_uri(
            "wasb://bucket@account.blob.blah/some-path",
            "some-path",
            scheme="wasb",
            container="bucket@account.blob.blah",
        )

    def _test_uri_component_split(self) -> None:
        def check_uri_component_split(
            path: str,
            expected_scheme: str,
            expected_container: str,
            expected_path: str,
        ) -> None:
            parts = uri_component_split(path)
            self.assertIsInstance(parts, tuple)
            self.assertEqual(len(parts), 3)
            self.assertEqual(parts[0], expected_scheme)
            self.assertEqual(parts[1], expected_container)
            self.assertEqual(parts[2], expected_path)

        check_uri_component_split("s3a://bucket/some-path/some-file", "s3a", "bucket", "/some-path/some-file")
        check_uri_component_split("gs://bucket/some-path/some-file", "gs", "bucket", "/some-path/some-file")
        check_uri_component_split(
            "hdfs://host:123/some-path/some-file",
            "hdfs",
            "host:123",
            "/some-path/some-file",
        )
        check_uri_component_split(
            "hdfs://ha-nameservice/some-path/some-file",
            "hdfs",
            "ha-nameservice",
            "/some-path/some-file",
        )
        check_uri_component_split("hdfs:///some-path/some-file", "hdfs", "", "/some-path/some-file")
        check_uri_component_split("/some-path/some-file", "", "", "/some-path/some-file")
        try:
            check_uri_component_split("not-a-scheme://bucket/some-path/some-file", "", "", "")
        except GOEDfsException as exc:
            if UNSUPPORTED_URI_SCHEME_EXCEPTION_TEXT not in str(exc):
                raise
        check_uri_component_split("://bucket/some-path/some-file", "", "", "://bucket/some-path/some-file")

    def _test_write(self) -> None:
        self.api.write(self.some_file, "some-contents-for-a-file")
        self.api.write(self.some_file, "some-contents-for-a-file", overwrite=True)

    def _run_all_tests(self) -> None:
        self._test_chmod()
        self._test_chgrp()
        self._test_container_exists()
        self._test_copy_from_local()
        self._test_copy_to_local()
        self._test_delete()
        self._test_list_dir()
        self._test_mkdir()
        self._test_read()
        self._test_rename()
        self._test_rmdir()
        self._test_stat()
        self._test_gen_fs_uri()
        self._test_uri_component_split()
        self._test_write()
        self.options = None


class TestWebHdfs(TestGOEDfs):
    """Dry-run test harness for HdfsClient in WebHDFS mode."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.api = None
        self.some_dir = "hdfs://some-path"
        self.some_file = "hdfs://some-path/a-file"
        self.some_local_file = "/tmp/temp_file.txt"

    def setUp(self) -> None:
        messages = OffloadMessages()
        self.api = HdfsClient(
            "a-host",
            12345,
            "a-user",
            mode=HDFS_MODE_WEBHDFS,
            dry_run=True,
            messages=messages,
            do_not_connect=True,
        )

    def test_all(self) -> None:
        if self.api:
            self._run_all_tests()


class TestCliHdfs(TestGOEDfs):
    """Dry-run test harness for HdfsClient in CLI mode."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.api = None
        self.some_dir = "hdfs://some-path"
        self.some_file = "hdfs://some-path/a-file"
        self.some_local_file = "/tmp/temp_file.txt"

    def setUp(self) -> None:
        messages = OffloadMessages()
        self.api = HdfsClient(
            "a-host",
            "a-user",
            mode=HDFS_MODE_CLI,
            dry_run=True,
            messages=messages,
            do_not_connect=True,
        )

    def test_all(self) -> None:
        self._run_all_tests()


class TestGOEGcs(TestGOEDfs):
    """Dry-run test harness for CloudStorageDfsAdapter with GCS scheme."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.api = None
        self.some_dir = "gs://a-bucket/some-path"
        self.some_file = "gs://a-bucket/some-path/a-file"
        self.some_local_file = "/tmp/temp_file.txt"

    def setUp(self) -> None:
        messages = OffloadMessages()
        self.api = CloudStorageDfsAdapter(messages, scheme="gs", dry_run=True, do_not_connect=True)

    def test_all(self) -> None:
        self._run_all_tests()


class TestGOES3(TestGOEDfs):
    """Dry-run test harness for CloudStorageDfsAdapter with S3 scheme."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.api = None
        self.some_dir = "s3://a-bucket/some-path"
        self.some_file = "s3://a-bucket/some-path/a-file"
        self.some_local_file = "/tmp/temp_file.txt"

    def setUp(self) -> None:
        messages = OffloadMessages()
        self.api = CloudStorageDfsAdapter(messages, scheme="s3", dry_run=True, do_not_connect=True)

    def test_all(self) -> None:
        self._run_all_tests()


class TestGOEAzure(TestGOEDfs):
    """Dry-run test harness for CloudStorageDfsAdapter with Azure WASB scheme."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.api = None
        self.some_dir = "wasb://a-bucket/some-path"
        self.some_file = "wasb://a-bucket/some-path/a-file"
        self.some_local_file = "/tmp/temp_file.txt"

    def setUp(self) -> None:
        messages = OffloadMessages()
        self.api = CloudStorageDfsAdapter(
            messages,
            scheme="wasb",
            azure_account_name="an-account-name",
            azure_account_key="an-account-key",
            azure_account_domain="a-domain",
            dry_run=True,
            do_not_connect=True,
        )

    def test_all(self) -> None:
        self._run_all_tests()


def test_get_dfs_from_options_dispatches_cloud_and_hdfs_adapters() -> None:
    """get_dfs_from_options returns CloudStorageDfsAdapter for cloud/local schemes and HdfsClient for Hadoop."""
    messages = OffloadMessages()
    for scheme in ("gs", "s3", "s3a", "wasb", "wasbs", "abfs", "abfss", "adl", "file"):
        cfg = SimpleNamespace(
            target=DBTYPE_BIGQUERY,
            backend_distribution=None,
            offload_fs_scheme=scheme,
            offload_fs_container="my-container",
            offload_fs_prefix="/stage",
            offload_fs_azure_account_name="acct",
            offload_fs_azure_account_key="key",
            offload_fs_azure_account_domain="blob.core.windows.net",
            hdfs_db_path_suffix=None,
            google_kms_key_name=None,
        )
        adapter = get_dfs_from_options(cfg, messages=messages, dry_run=True, do_not_connect=True)
        assert isinstance(adapter, CloudStorageDfsAdapter)

    hadoop_webhdfs_cfg = SimpleNamespace(
        target=DBTYPE_HIVE,
        backend_distribution=BACKEND_DISTRO_CDH,
        webhdfs_host="nn1.local",
        webhdfs_port=50070,
        hdfs_host="nn1.local",
        hadoop_ssh_user="hdfs",
        kerberos_service=None,
        webhdfs_verify_ssl=None,
        hdfs_db_path_suffix=".db",
        hdfs_data="/user/goe",
        offload_fs_scheme="hdfs",
    )
    hdfs_web = get_dfs_from_options(hadoop_webhdfs_cfg, messages=messages, dry_run=True, do_not_connect=True)
    assert isinstance(hdfs_web, HdfsClient)
    assert hdfs_web.mode == HDFS_MODE_WEBHDFS

    hdfs_cli = get_dfs_from_options(
        hadoop_webhdfs_cfg,
        messages=messages,
        force_ssh=True,
        dry_run=True,
        do_not_connect=True,
    )
    assert isinstance(hdfs_cli, HdfsClient)
    assert hdfs_cli.mode == HDFS_MODE_CLI


def test_removed_scheme_not_in_valid_offload_fs_schemes() -> None:
    """Verify removed filesystem schemes are excluded from VALID_OFFLOAD_FS_SCHEMES."""
    assert ("mapr" + "fs") not in VALID_OFFLOAD_FS_SCHEMES


if __name__ == "__main__":
    main()
