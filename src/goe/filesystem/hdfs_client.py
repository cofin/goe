# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Consolidated on-premises Hadoop HDFS client supporting CLI (SSH) and WebHDFS modes."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime
from getpass import getuser
from os.path import basename
from os.path import exists as file_exists
from subprocess import PIPE, STDOUT
from typing import Any

from google.api_core import retry
from requests import Session
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from goe.filesystem.goe_dfs import (
    DFS_RETRY_TIMEOUT,
    DFS_TYPE_DIRECTORY,
    DFS_TYPE_FILE,
    GOE_DFS_HDFS,
    GOE_DFS_WEBHDFS,
    OFFLOAD_FS_SCHEME_INHERIT,
    OFFLOAD_FS_SCHEMES_REQUIRING_CONTAINER,
    GOEDfs,
    GOEDfsDeleteNotComplete,
    GOEDfsException,
    gen_fs_uri,
)
from goe.util.module_loader import import_optional
from goe.util.string_utils import is_number

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

HDFS_MODE_CLI = "cli"
HDFS_MODE_WEBHDFS = "webhdfs"


def get_hdfs_session(verify: bool | str | None = None, user: str | None = None) -> Session:
    """Construct a requests Session configured for WebHDFS SSL verification and user parameter."""
    disable_warnings(InsecureRequestWarning)
    session = Session()
    session.verify = verify if verify is not None else False
    if user:
        if not isinstance(session.params, dict):
            session.params = {}
        session.params["user.name"] = user
    return session


class HdfsClient(GOEDfs):
    """Unified Hadoop HDFS client supporting SSH CLI (`hdfs dfs`) and WebHDFS REST modes."""

    def __init__(
        self,
        host: str | None = None,
        port_or_user: int | str | None = None,
        hdfs_user: str | None = None,
        use_kerberos: bool = False,
        verify_ssl_cert: bool | str | None = None,
        *,
        port: int | str | None = None,
        ssh_user: str | None = None,
        mode: str | None = None,
        kerberos_enabled: bool | None = None,
        verify_ssl: bool | str | None = None,
        tmp_dir: str = "/tmp",
        dry_run: bool = False,
        messages: Any = None,
        do_not_connect: bool = False,
        db_path_suffix: str | None = None,
        hdfs_data: str | None = None,
        **kwargs: Any,
    ) -> None:
        resolved_mode, resolved_port, resolved_user = self._resolve_init_args(
            port_or_user=port_or_user,
            hdfs_user=hdfs_user,
            port=port,
            ssh_user=ssh_user,
            mode=mode,
        )
        resolved_kerberos = kerberos_enabled if kerberos_enabled is not None else bool(use_kerberos)
        resolved_verify_ssl = verify_ssl if verify_ssl is not None else verify_ssl_cert

        super().__init__(messages, dry_run=dry_run, do_not_connect=do_not_connect)

        self._mode = resolved_mode
        self._host = host or ""
        self._port = resolved_port
        self._user = resolved_user
        self._kerberos_enabled = resolved_kerberos
        self._verify_ssl = resolved_verify_ssl
        self._tmp_dir = tmp_dir
        self._db_path_suffix = db_path_suffix
        self._hdfs_data = hdfs_data
        self._url: str | None = None
        self._hdfs: Any = None
        self.backend_dfs = "HDFS"

        if self._mode == HDFS_MODE_WEBHDFS:
            assert self._host, "HDFS namenode host is required for WebHDFS mode"
            assert self._port, "WebHDFS port is required for WebHDFS mode"
            self.dfs_mechanism = GOE_DFS_WEBHDFS
            self._hdfs = self._init_webhdfs_client(
                self._host,
                self._port,
                self._user,
                self._kerberos_enabled,
                self._verify_ssl,
                **kwargs,
            )
        else:
            self.dfs_mechanism = GOE_DFS_HDFS

    def __str__(self) -> str:
        if self._mode == HDFS_MODE_WEBHDFS:
            return self._url or f"{self._host}:{self._port}"
        return f"{self._user}@{self._host}"

    @staticmethod
    def dfs_cmd(as_string: bool = False) -> list[str] | str:
        """Return the `hdfs dfs` command tokens or space-joined command string."""
        dfs: list[str] = ["hdfs", "dfs"]
        if as_string:
            return " ".join(dfs)
        return dfs

    @property
    def mode(self) -> str:
        """Return the active HDFS transport mode ('cli' or 'webhdfs')."""
        return self._mode

    @property
    def client(self) -> Any:
        """Return the underlying WebHDFS client when in webhdfs mode, or None in cli mode."""
        if self._mode == HDFS_MODE_CLI:
            logger.warning("Attempting to access 'client' in ssh based HdfsClient")
            return None
        return self._hdfs

    def chgrp(self, dfs_path: str, group: str) -> None:
        """Change group ownership of an HDFS path."""
        assert dfs_path and group
        assert isinstance(dfs_path, str)
        logger.info("chgrp(%s, %s)", dfs_path, group)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run and self._hdfs is not None:
                self._hdfs.set_owner(dfs_path, group=group)
            return
        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-chgrp", group, norm_path]
        returncode, output = self._run_cmd(cmd)
        self._check_returncode(returncode, output)

    def chmod(self, dfs_path: str, mode: str) -> None:
        """Change permissions on an HDFS path using octal (755) or symbolic (g+w) mode."""
        assert dfs_path and mode and (re.match(r"^\d+$", mode) or re.match(r"^[ugo]+[+\-][rwx]+$", mode))
        assert isinstance(dfs_path, str)
        logger.info("chmod(%s, %s)", dfs_path, mode)
        if self._mode == HDFS_MODE_WEBHDFS:
            if self.stat(dfs_path):
                perms = self.get_perms(dfs_path)
                if re.match(r"^\d+$", mode):
                    new_mode = mode
                elif re.match(r"^[ugo]+[+\-][rwx]+$", mode):
                    mode_delta = self.octstr_from_human_perm_delta(mode)
                    new_mode = self.apply_mode_delta(str(perms), mode_delta, self.regex_mode_delta(mode)[1])
                else:
                    raise GOEDfsException(f'Invalid chmod mode "{mode}"')
                if not self._dry_run and self._hdfs is not None and str(perms) != str(new_mode):
                    self._hdfs.set_permission(dfs_path, new_mode)
            return
        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-chmod", mode, norm_path]
        returncode, output = self._run_cmd(cmd)
        self._check_returncode(returncode, output)

    def container_exists(self, scheme: str, container: str) -> bool:
        """Check whether a container exists (only supported in CLI mode for container-based schemes)."""
        if self._mode == HDFS_MODE_WEBHDFS:
            raise NotImplementedError("container_exists() not implemented for WebHdfs")
        assert scheme and container
        if scheme in OFFLOAD_FS_SCHEMES_REQUIRING_CONTAINER:
            return bool(self.stat(self.gen_uri(scheme, container, "")))
        return False

    def copy_from_local(self, local_path: str, dfs_path: str, overwrite: bool = False) -> None:
        """Upload a local file to HDFS."""
        assert local_path
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("copy_from_local(%s, %s)", local_path, dfs_path)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run and self._hdfs is not None:
                try:
                    res = self._hdfs.upload(dfs_path, local_path, overwrite=overwrite)
                    self.debug(f"copy_from_local() returned: {res}")
                except Exception as exc:
                    if "already exists" in str(exc) and not overwrite:
                        raise GOEDfsException(f"Cannot copy file over existing file: {dfs_path}") from exc
                    raise
            return

        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        base_file = basename(local_path)
        hadoop_temp_file = self._temp_file(base_file)
        scp_cmd = self._scp_to(self._user, self._host, local_path, hadoop_temp_file)
        self.debug("SCP command: " + " ".join(scp_cmd))
        returncode, output = self._run_cmd(scp_cmd)
        self._check_returncode(returncode, output)
        try:
            cfl_opts = (["-f"] if overwrite else []) + [hadoop_temp_file, norm_path]
            cfl_cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-copyFromLocal"] + cfl_opts
            self.debug("SSH command: " + " ".join(cfl_cmd))
            returncode, output = self._run_cmd(cfl_cmd)
            self._check_returncode(returncode, output)
        finally:
            rm_cmd = self._ssh(self._user, self._host) + ["rm", "-f", hadoop_temp_file]
            returncode, output = self._run_cmd(rm_cmd)
            self._check_returncode(returncode, output)

    def copy_to_local(self, dfs_path: str, local_path: str, overwrite: bool = False) -> None:
        """Download an HDFS file to a local path."""
        logger.info("copy_to_local(%s, %s)", dfs_path, local_path)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run and self._hdfs is not None:
                if file_exists(local_path) and not overwrite:
                    raise GOEDfsException(f"Cannot copy file over existing file: {local_path}")
                res = self._hdfs.download(dfs_path, local_path, overwrite=overwrite)
                self.debug(f"copy_to_local() returned: {res}")
            return

        if self._can_short_circuit_ssh(self._user, self._host):
            hadoop_temp_file = local_path
        else:
            hadoop_temp_file = self._temp_file(basename(local_path))

        if file_exists(local_path) and not overwrite:
            raise GOEDfsException(f"Cannot copy file over existing file: {local_path}")

        try:
            cfl_opts = [dfs_path, hadoop_temp_file]
            cfl_cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-copyToLocal"] + cfl_opts
            self.debug("SSH command: " + " ".join(cfl_cmd))
            returncode, output = self._run_cmd(cfl_cmd)
            self._check_returncode(returncode, output)

            if not self._can_short_circuit_ssh(self._user, self._host):
                scp_cmd = self._scp_from(self._user, self._host, hadoop_temp_file, local_path)
                self.debug("SCP command: " + " ".join(scp_cmd))
                returncode, output = self._run_cmd(scp_cmd)
                self._check_returncode(returncode, output)
        finally:
            if not self._can_short_circuit_ssh(self._user, self._host):
                rm_cmd = self._ssh(self._user, self._host) + ["rm", "-f", hadoop_temp_file]
                returncode, output = self._run_cmd(rm_cmd)
                self._check_returncode(returncode, output)

    @retry.Retry(
        predicate=retry.if_exception_type(GOEDfsDeleteNotComplete),
        deadline=DFS_RETRY_TIMEOUT,
    )
    def delete(self, dfs_path: str, recursive: bool = False) -> bool | None:
        """Delete an HDFS file or directory."""
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("delete(%s, %s)", dfs_path, recursive)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run and self._hdfs is not None:
                res = self._hdfs.delete(dfs_path, recursive)
                scheme, _, _ = self._uri_component_split(dfs_path)
                self._post_cloud_delete_wait(scheme)
                if scheme in OFFLOAD_FS_SCHEMES_REQUIRING_CONTAINER and self.stat(dfs_path):
                    self.debug(f"{scheme} delete incomplete, retrying")
                    raise GOEDfsDeleteNotComplete
                return bool(res)
            return None

        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        rm_flags = ["-rm", "-f", "-r", norm_path] if recursive else ["-rm", "-f", norm_path]
        cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + rm_flags
        returncode, output = self._run_cmd(cmd)
        self._check_returncode(returncode, output)
        if not self._dry_run:
            scheme, _, _ = self._uri_component_split(dfs_path)
            self._post_cloud_delete_wait(scheme)
            if scheme in OFFLOAD_FS_SCHEMES_REQUIRING_CONTAINER and self.stat(dfs_path):
                self.debug(f"{scheme} delete incomplete, retrying")
                raise GOEDfsDeleteNotComplete
        return True

    def gen_uri(
        self,
        scheme: str,
        container: str,
        path_prefix: str,
        backend_db: str | None = None,
        table_name: str | None = None,
        container_override: str | None = None,
    ) -> str:
        """Generate an HDFS URI for a database/table path."""
        if not scheme or scheme == OFFLOAD_FS_SCHEME_INHERIT:
            return gen_fs_uri(
                self._hdfs_data or "",
                self._db_path_suffix,
                backend_db=backend_db,
                table_name=table_name,
            )
        prefix = (self._hdfs_data or "") if path_prefix is None else path_prefix
        use_container = container if scheme in OFFLOAD_FS_SCHEMES_REQUIRING_CONTAINER else None
        return gen_fs_uri(
            prefix,
            self._db_path_suffix,
            scheme=scheme,
            container=container_override or use_container,
            backend_db=backend_db,
            table_name=table_name,
        )

    def list_dir(self, dfs_path: str) -> list[str] | None:
        """List directory contents at dfs_path."""
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("list_dir(%s)", dfs_path)
        if self._mode == HDFS_MODE_WEBHDFS:
            if self._hdfs is not None:
                return [os.path.join(dfs_path, item) for item in self._hdfs.list(dfs_path)]
            return None
        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-ls", norm_path]
        returncode, output = self._run_cmd(cmd, force_run=True)
        self._check_returncode(returncode, output)
        return [line[line.find(b"/") :].strip().decode() for line in output if self._valid_ls_line(line)]

    def mkdir(self, dfs_path: str) -> None:
        """Create a directory (and parents) at dfs_path."""
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("mkdir(%s)", dfs_path)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run and self._hdfs is not None:
                self._hdfs.makedirs(dfs_path)
            return
        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-mkdir", "-p", norm_path]
        returncode, output = self._run_cmd(cmd)
        self._check_returncode(returncode, output)

    def read(self, dfs_path: str, as_str: bool = False) -> bytes | str | None:
        """Read file contents from HDFS as bytes or string."""
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("read(%s)", dfs_path)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run and self._hdfs is not None:
                with self._hdfs.read(dfs_path) as reader:
                    content = reader.read()
                    return content.decode() if as_str else content
            return None
        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-cat", norm_path]
        returncode, output = self._run_cmd(cmd, force_run=True)
        self._check_returncode(returncode, output)
        content = b"".join(output) if output else b""
        return content.decode() if as_str else content

    def rename(self, hdfs_src_path: str, hdfs_dst_path: str) -> None:
        """Rename or move an HDFS file or directory."""
        assert hdfs_src_path and hdfs_dst_path
        logger.info("rename(%s, %s)", hdfs_src_path, hdfs_dst_path)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run and self._hdfs is not None:
                self._hdfs.rename(hdfs_src_path, hdfs_dst_path)
            return
        if not self._dry_run:
            cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-mv", hdfs_src_path, hdfs_dst_path]
            returncode, output = self._run_cmd(cmd)
        else:
            returncode, output = 0, []
        self._check_returncode(returncode, output)

    def rmdir(self, dfs_path: str, recursive: bool = False) -> bool | None:
        """Remove an HDFS directory."""
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("rmdir(%s, %s)", dfs_path, recursive)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run:
                return self.delete(dfs_path, recursive=recursive)
            return None
        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        if recursive:
            return self.delete(norm_path, recursive=recursive)
        cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-rmdir", norm_path]
        returncode, output = self._run_cmd(cmd)
        self._check_returncode(returncode, output)
        return True

    def stat(self, dfs_path: str) -> dict[str, Any] | None:
        """Return stat metadata dict (`permission`, `type`, `length`) for an HDFS path."""
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("stat(%s)", dfs_path)
        if self._mode == HDFS_MODE_WEBHDFS:
            if self._hdfs is None:
                return None
            try:
                return self._hdfs.status(dfs_path, strict=True)
            except Exception as exc:
                if "File does not exist:" in str(exc):
                    return None
                raise
        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        cmd = self._ssh(self._user, self._host) + list(self.dfs_cmd()) + ["-ls", "-d", norm_path]
        returncode, output = self._run_cmd(cmd, force_run=True)
        if returncode == 0:
            tidy_output = [line.strip().decode() for line in output if self._valid_ls_line(line)]
            if not tidy_output:
                self.debug(f"Stat command: {cmd}")
                self.debug(f"Stat raw text: {output}")
                return None
            tokens = tidy_output[0].split()
            if tokens:
                file_type = DFS_TYPE_DIRECTORY if tokens[0] and tokens[0][0] == "d" else DFS_TYPE_FILE
                file_length = int(tokens[4]) if len(tokens) > 4 and tokens[4] and is_number(tokens[4]) else None
                return {
                    "permission": self.convert_rwx_perms_to_oct_str(tokens[0]),
                    "type": file_type,
                    "length": file_length,
                }
        else:
            self.debug(f"Stat command: {cmd}")
            self.debug(f"Stat raw text: {output}")
        return None

    def write(self, dfs_path: str, data: str | bytes, overwrite: bool = False) -> None:
        """Write bytes or string content to an HDFS path."""
        assert dfs_path
        assert isinstance(dfs_path, str)
        logger.info("write(%s, data, %s)", dfs_path, overwrite)
        if self._mode == HDFS_MODE_WEBHDFS:
            if not self._dry_run and self._hdfs is not None:
                try:
                    self._hdfs.write(dfs_path, data, overwrite)
                except Exception as exc:
                    if "already exists" in str(exc) and not overwrite:
                        raise GOEDfsException(f"Cannot copy file over existing file: {dfs_path}") from exc
                    raise
            return

        norm_path = self._normalize_hdfs_path(self._user, self._host, dfs_path)
        local_temp_file = self._temp_file()
        if isinstance(data, bytes):
            with open(local_temp_file, "wb") as handle_b:
                handle_b.write(data)
        else:
            with open(local_temp_file, "w", encoding="utf-8") as handle_t:
                handle_t.write(data)
        try:
            self.copy_from_local(local_temp_file, norm_path, overwrite=overwrite)
        finally:
            rm_cmd = ["rm", "-f", local_temp_file]
            returncode, output = self._run_cmd(rm_cmd)
            self._check_returncode(returncode, output)

    @staticmethod
    def regex_mode_delta(mode: str) -> tuple[str, ...]:
        """Parse symbolic permission delta mode like 'g+rw' into ('g', '+', 'rw')."""
        match = re.match(r"([ugo]+)([+\-])([rwx]+)", mode)
        if not match or len(match.groups()) != 3:
            raise GOEDfsException(f'Invalid chmod delta mode "{mode}"')
        return match.groups()

    def octstr_from_human_perm_delta(self, mode: str) -> str:
        """Convert symbolic permission delta mode into a 3-digit octal string."""
        perm_values = {"r": 4, "w": 2, "x": 1}
        ugo_values = {"u": 0, "g": 0, "o": 0}
        mode_groups = self.regex_mode_delta(mode)
        int_perm = sum(perm_values[perm] for perm in set(mode_groups[2]))
        if mode_groups[1] == "-":
            ugo_values = {"u": 7, "g": 7, "o": 7}
            int_perm = 7 - int_perm
        for ugo in mode_groups[0]:
            ugo_values[ugo] = int_perm
        return f"{ugo_values['u']}{ugo_values['g']}{ugo_values['o']}"

    @staticmethod
    def apply_mode_delta(octstr_mode: str, octstr_delta: str, mode_op: str) -> str:
        """Apply an octal permission delta ('+' or '-') to an existing octal permission string."""
        assert mode_op in ("+", "-")
        if mode_op == "+":
            return oct(int(octstr_mode, 8) | int(octstr_delta, 8))[2:]
        return oct(int(octstr_mode, 8) & int(octstr_delta, 8))[2:]

    @staticmethod
    def _resolve_init_args(
        *,
        port_or_user: int | str | None,
        hdfs_user: str | None,
        port: int | str | None,
        ssh_user: str | None,
        mode: str | None,
    ) -> tuple[str, int | str | None, str | None]:
        if mode is not None:
            norm_mode = mode.lower()
            if norm_mode not in (HDFS_MODE_CLI, HDFS_MODE_WEBHDFS):
                raise GOEDfsException(f"Unsupported HDFS client mode: {mode}")
            resolved_port = port if port is not None else (port_or_user if isinstance(port_or_user, int) else None)
            resolved_user = ssh_user or hdfs_user or (port_or_user if isinstance(port_or_user, str) else None)
            return norm_mode, resolved_port, resolved_user

        if (
            port is not None
            or isinstance(port_or_user, int)
            or (isinstance(port_or_user, str) and port_or_user.isdigit())
        ):
            resolved_port = port if port is not None else port_or_user
            resolved_user = ssh_user or hdfs_user
            return HDFS_MODE_WEBHDFS, resolved_port, resolved_user

        resolved_user = ssh_user or (port_or_user if isinstance(port_or_user, str) else hdfs_user)
        return HDFS_MODE_CLI, None, resolved_user

    def _init_webhdfs_client(
        self,
        hdfs_namenode: str,
        webhdfs_port: int | str,
        hdfs_user: str | None,
        use_kerberos: bool,
        verify_ssl_cert: bool | str | None = None,
        **kwargs: Any,
    ) -> Any:
        protocol = "https" if verify_ssl_cert is not None and verify_ssl_cert is not False else "http"
        namenodes = [node.strip() for node in hdfs_namenode.split(",") if node.strip()]
        self._url = f"{protocol}://{namenodes[0]}:{webhdfs_port}"
        if self._do_not_connect:
            return None

        hdfs_kerberos_mod = import_optional(
            "hdfs.ext.kerberos",
            extra="hadoop",
            feature="WebHDFS client connectivity",
        )
        if hdfs_kerberos_mod is None or not hasattr(hdfs_kerberos_mod, "KerberosClient"):
            raise GOEDfsException(
                "Optional dependency 'hdfs' is required for WebHDFS connectivity. Install the 'hadoop' extra."
            )

        if use_kerberos:
            req_kerberos_mod = import_optional(
                "requests_kerberos",
                extra="hadoop",
                feature="WebHDFS Kerberos authentication",
            )
            if req_kerberos_mod is None or not hasattr(req_kerberos_mod, "HTTPKerberosAuth"):
                raise GOEDfsException(
                    "Optional dependency 'requests-kerberos' is required for Kerberos WebHDFS authentication."
                )
            auth_user = None
            get_auth = req_kerberos_mod.HTTPKerberosAuth(mutual_authentication=req_kerberos_mod.OPTIONAL)
            mutual_auth_err = getattr(req_kerberos_mod, "MutualAuthenticationError", Exception)
        else:
            auth_user = hdfs_user
            get_auth = None
            mutual_auth_err = Exception

        if len(namenodes) > 1:
            self.debug("Multiple WebHDFS namenodes detected, determining active namenode to use")
            session = get_hdfs_session(verify=verify_ssl_cert, user=auth_user)
            active_found = False
            for namenode in namenodes:
                namenode_url = (
                    f"{protocol}://{namenode}:{webhdfs_port}/jmx?qry=Hadoop:service=NameNode,name=NameNodeStatus"
                )
                try:
                    response = session.get(namenode_url, auth=get_auth)
                    if response.status_code == 200:
                        beans = response.json().get("beans") or []
                        if beans and str(beans[0].get("State", "")).lower() == "active":
                            self._url = f"{protocol}://{namenode}:{webhdfs_port}"
                            active_found = True
                            break
                except (ConnectionError, mutual_auth_err) as exc:
                    self.notice(f"WebHDFS active namenode check failed for {namenode} with connection error")
                    self.debug(f"Namenode {namenode} connection error: {exc!s}")
            if not active_found:
                self.warning(
                    f"Multiple WebHDFS namenodes detected, unable to determine active node, defaulting to {namenodes[0]}"
                )

        kerberos_client_cls = hdfs_kerberos_mod.KerberosClient
        session = get_hdfs_session(verify=verify_ssl_cert, user=auth_user)
        return kerberos_client_cls(self._url, session=session, **kwargs)

    @staticmethod
    def _ssh(ssh_user: str | None, host: str) -> list[str]:
        if ssh_user == getuser() and host == "localhost":
            return []
        target = f"{ssh_user}@{host}" if ssh_user else host
        return ["ssh", "-tq", target]

    def _can_short_circuit_ssh(self, ssh_user: str | None, host: str) -> bool:
        return self._ssh(ssh_user, host) == []

    def _normalize_hdfs_path(self, ssh_user: str | None, host: str, dfs_path: str) -> str:
        if self._can_short_circuit_ssh(ssh_user, host):
            return dfs_path
        return "'" + dfs_path.strip("'") + "'"

    @staticmethod
    def _scp_from(ssh_user: str | None, host: str, from_path: str, to_path: str) -> list[str]:
        if ssh_user == getuser() and host == "localhost":
            return ["scp", from_path, to_path]
        return ["scp", f"{ssh_user}@{host}:{from_path}", to_path]

    @staticmethod
    def _scp_to(ssh_user: str | None, host: str, from_path: str, to_path: str) -> list[str]:
        if ssh_user == getuser() and host == "localhost":
            return ["scp", from_path, to_path]
        return ["scp", from_path, f"{ssh_user}@{host}:{to_path}"]

    def _temp_file(self, base_file: str = "goe_temp") -> str:
        return f"{self._tmp_dir}/{base_file}.{datetime.now().strftime('%y%j%H%M%S%f')}"

    def _check_returncode(self, returncode: int, output: list[bytes]) -> None:
        self.debug(f"Return code: {returncode}")
        if returncode:
            self.log(f"Output: {output!s}")
            decoded = b"\n".join(output).decode(errors="replace")
            raise GOEDfsException(f'Required shell command failed with return code "{returncode}"\n{decoded}')

    def _run_cmd(self, cmd: list[str], force_run: bool = False) -> tuple[int, list[bytes]]:
        logger.info("cmd: " + " ".join(cmd))
        if self._dry_run and (not force_run or self._do_not_connect):
            return 0, []
        with subprocess.Popen(cmd, stdout=PIPE, stderr=STDOUT) as proc:
            assert proc.stdout is not None
            output = [line for line in proc.stdout if not self._ignorable_stderr(line)]
            cmd_returncode = proc.wait()
            logger.debug("output: %s", b"\n".join(output).decode(errors="replace"))
            logger.debug("returncode: %s", cmd_returncode)
        return cmd_returncode, output

    @staticmethod
    def _valid_ls_line(ls_line: bytes | str) -> bool:
        use_line = ls_line.decode() if isinstance(ls_line, bytes) else ls_line
        return bool(use_line and use_line.find("/") >= 0 and use_line[0] in ("-", "d"))

    @staticmethod
    def _ignorable_stderr(stderr_line: bytes) -> bool:
        return bool(stderr_line and b"Pseudo-terminal will not be allocated" in stderr_line)


__all__ = [
    "HDFS_MODE_CLI",
    "HDFS_MODE_WEBHDFS",
    "HdfsClient",
    "get_hdfs_session",
]
