# Copyright 2016 The GOE Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Standard Library
import logging
import sys


def validate_config():
    """"""
    try:
        # GOE
        from goe.config.config_file import check_config_path

        check_config_path()
    except Exception:
        print("failed to validate configuration.  Please check your installation")
        sys.exit(1)


async def validate_cache():
    """"""
    # GOE
    from goe.listener import utils
    from goe.listener.config import settings
    from goe.listener.config.logging import Logger

    try:
        logger = Logger.configure_logger()
        if settings.cache_enabled:
            cache = utils.cache.get_client()
            await cache.ping()
            logger.info("✅  successfully validated Redis connectivity.")
    except Exception as exc:
        logger.error("⚠️  Could not connect to redis backend.  retrying...")
        raise exc
    finally:
        if cache and settings.cache_enabled:
            await utils.cache.close_client()


def prestart() -> None:
    # Third Party Libraries
    from goelib_contrib.asyncer import runnify
    from tenacity import (
        after_log,
        before_log,
        retry,
        wait_fixed,
    )

    # GOE
    from goe.listener.config.logging import Logger

    logger = Logger.configure_logger()
    # max_tries = 60
    wait_seconds = 5

    @retry(
        # stop=stop_after_attempt(max_tries),
        wait=wait_fixed(wait_seconds),
        before=before_log(logger, logging.DEBUG),
        after=after_log(logger, logging.DEBUG),
    )
    async def _prestart():
        """"""
        await validate_cache()

    validate_config()
    runnify(_prestart)()


if __name__ == "__main__":
    prestart()
