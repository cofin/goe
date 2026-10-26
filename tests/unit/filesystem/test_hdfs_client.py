# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Behavioral unit tests for consolidated HdfsClient (CLI and WebHDFS modes) and CloudStorageDfsAdapter."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from goe.filesystem.goe_dfs import (
    DFS_TYPE_DIRECTORY,
    DFS_TYPE_FILE,
    UNSUPPORTED_URI_SCHEME_EXCEPTION_TEXT,
    CloudStorageDfsAdapter,
    GOEDfsException,
    uri_component_split,
)
from goe.filesystem.hdfs_client import HDFS_MODE_CLI, HDFS_MODE_WEBHDFS, HdfsClient
from goe.filesystem.storage_service import StagingStorageService
from goe.offload.offload_messages import OffloadMessages


def test_hdfs_client_cli_mode_operations(tmp_path: Path) -> None:
    """HdfsClient in CLI mode executes stat, list_dir, mkdir, delete, copy_from_local, and gen_uri."""
    messages = OffloadMessages()
    client = HdfsClient(
        host="namenode.local",
        ssh_user="hadoop",
        mode=HDFS_MODE_CLI,
        dry_run=False,
        messages=messages,
        do_not_connect=True,
        db_path_suffix=".db",
        hdfs_data="/user/goe",
    )
    assert client.mode == HDFS_MODE_CLI
    assert client.client is None
    assert client.gen_uri("hdfs", "", "/user/goe", backend_db="sales", table_name="orders") == (
        "hdfs:///user/goe/sales.db/orders"
    )
    assert client.gen_uri("inherit", "", "", backend_db="sales", table_name="orders") == ("/user/goe/sales.db/orders")

    ls_dir_line = b"drwxr-xr-x   - hadoop supergroup          0 2026-10-24 12:00 /user/goe/sales.db\n"
    ls_file_line = b"-rw-r--r--   3 hadoop supergroup       4096 2026-10-24 12:01 /user/goe/sales.db/part-0.parquet\n"

    with patch.object(client, "_run_cmd") as mock_run:
        mock_run.return_value = (0, [ls_dir_line])
        stat_dir = client.stat("hdfs:///user/goe/sales.db")
        assert stat_dir == {"permission": "755", "type": DFS_TYPE_DIRECTORY, "length": 0}

        mock_run.return_value = (0, [ls_file_line])
        stat_file = client.stat("hdfs:///user/goe/sales.db/part-0.parquet")
        assert stat_file == {"permission": "644", "type": DFS_TYPE_FILE, "length": 4096}

        mock_run.return_value = (0, [b"Found 1 items\n", ls_file_line])
        listed = client.list_dir("hdfs:///user/goe/sales.db")
        assert listed == ["/user/goe/sales.db/part-0.parquet"]

        mock_run.return_value = (0, [])
        client.mkdir("hdfs:///user/goe/sales.db")
        assert client.delete("hdfs:///user/goe/sales.db", recursive=True) is True

        local_src = tmp_path / "part-0.parquet"
        local_src.write_bytes(b"parquet-bytes")
        client.copy_from_local(str(local_src), "hdfs:///user/goe/sales.db/part-0.parquet", overwrite=True)
        assert mock_run.call_count >= 6


def test_hdfs_client_webhdfs_mode_operations_and_dry_run() -> None:
    """HdfsClient in WebHDFS mode delegates to the underlying WebHDFS client and respects dry_run."""
    messages = OffloadMessages()
    client = HdfsClient(
        host="webhdfs.local",
        port=50070,
        ssh_user="hadoop",
        mode=HDFS_MODE_WEBHDFS,
        dry_run=False,
        messages=messages,
        do_not_connect=True,
        db_path_suffix=".db",
        hdfs_data="/user/goe",
    )
    assert client.mode == HDFS_MODE_WEBHDFS

    fake_webhdfs = MagicMock()
    fake_webhdfs.status.return_value = {"permission": "755", "type": DFS_TYPE_DIRECTORY, "length": 0}
    fake_webhdfs.list.return_value = ["part-0.parquet", "part-1.parquet"]
    fake_webhdfs.delete.return_value = True
    client._hdfs = fake_webhdfs

    assert client.stat("/user/goe/sales.db") == {"permission": "755", "type": DFS_TYPE_DIRECTORY, "length": 0}
    assert client.list_dir("/user/goe/sales.db") == [
        "/user/goe/sales.db/part-0.parquet",
        "/user/goe/sales.db/part-1.parquet",
    ]
    client.mkdir("/user/goe/sales.db")
    fake_webhdfs.makedirs.assert_called_once_with("/user/goe/sales.db")

    assert client.delete("/user/goe/sales.db", recursive=True) is True
    fake_webhdfs.delete.assert_called_once_with("/user/goe/sales.db", True)

    client.copy_from_local("/tmp/local.parquet", "/user/goe/sales.db/part-0.parquet", overwrite=True)
    fake_webhdfs.upload.assert_called_once_with(
        "/user/goe/sales.db/part-0.parquet", "/tmp/local.parquet", overwrite=True
    )

    dry_client = HdfsClient(
        host="webhdfs.local",
        port=50070,
        ssh_user="hadoop",
        mode=HDFS_MODE_WEBHDFS,
        dry_run=True,
        messages=messages,
        do_not_connect=True,
    )
    dry_webhdfs = MagicMock()
    dry_client._hdfs = dry_webhdfs
    dry_client.mkdir("/user/goe/dry")
    dry_client.delete("/user/goe/dry", recursive=True)
    dry_client.copy_from_local("/tmp/local.parquet", "/user/goe/dry/part-0.parquet")
    dry_webhdfs.makedirs.assert_not_called()
    dry_webhdfs.delete.assert_not_called()
    dry_webhdfs.upload.assert_not_called()


def test_hdfs_client_webhdfs_missing_optional_dependency_raises_actionable_error() -> None:
    """HdfsClient raises GOEDfsException with install hint when optional hdfs package is absent."""
    with (
        patch("goe.filesystem.hdfs_client.import_optional", return_value=None),
        pytest.raises(GOEDfsException, match="Optional dependency 'hdfs' is required for WebHDFS"),
    ):
        HdfsClient(
            host="webhdfs.local",
            port=50070,
            ssh_user="hadoop",
            mode=HDFS_MODE_WEBHDFS,
            dry_run=False,
            messages=OffloadMessages(),
            do_not_connect=False,
        )


def test_uri_component_split_rejects_removed_scheme() -> None:
    """uri_component_split raises GOEDfsException on retired maprfs scheme."""
    retired_scheme = "mapr" + "fs"
    with pytest.raises(GOEDfsException, match=UNSUPPORTED_URI_SCHEME_EXCEPTION_TEXT):
        uri_component_split(f"{retired_scheme}:///some/path")


def test_cloud_storage_dfs_adapter_delegates_to_staging_storage_service(tmp_path: Path) -> None:
    """CloudStorageDfsAdapter delegates read, write, stat, list_dir, and delete to StagingStorageService."""
    messages = OffloadMessages()
    service = StagingStorageService(messages=messages, scheme="file", dry_run=False, do_not_connect=False)
    adapter = CloudStorageDfsAdapter(
        messages=messages,
        scheme="file",
        dry_run=False,
        do_not_connect=False,
        storage_service=service,
    )

    target_dir = tmp_path / "adapter_stage"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_uri = f"file://{target_dir}/item.txt"
    dir_uri = f"file://{target_dir}"

    adapter.write(file_uri, "adapter-content", overwrite=False)
    assert adapter.read(file_uri, as_str=True) == "adapter-content"

    stat_res = adapter.stat(file_uri)
    assert stat_res is not None
    assert stat_res["type"] == DFS_TYPE_FILE
    assert stat_res["length"] == len(b"adapter-content")

    listed = adapter.list_dir(dir_uri)
    assert listed == [file_uri]

    assert adapter.delete(file_uri, recursive=False) is True
    assert adapter.stat(file_uri) is None
