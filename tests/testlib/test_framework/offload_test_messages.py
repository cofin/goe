# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Wrapper over OffloadMessages that has useful methods for inspecting the messages or log."""

from goe.util.goe_log_fh import GOELogFileHandle


class OffloadTestMessages:
    def __init__(self, messages):
        self._messages = messages

    ###########################################################################
    # PRIVATE METHODS
    ###########################################################################

    ###########################################################################
    # PUBLIC METHODS
    ###########################################################################

    def get_lines_from_log(self, search_text, search_from_text="", max_matches=None, log_file: str = None) -> list:
        """Searches for text in the logfile starting from search_from_text
        or the top of the file if search_from_text is blank.
        Returns all matching lines (up to max_matches).
        Be careful adding logging to this method, we can't log search_text otherwise
        we put the very thing we are searching for in the log.
        """
        log_file = log_file or self.get_log_fh_name()
        if not log_file:
            return []
        start_found = bool(not search_from_text)
        matches = []
        with GOELogFileHandle(log_file, mode="r") as lf:
            for line in lf:
                if not start_found:
                    start_found = search_from_text in line
                elif search_text in line:
                    matches.append(line)
                    if max_matches and len(matches) >= max_matches:
                        return matches
        return matches

    def get_line_from_log(self, search_text, search_from_text="", log_file: str = None) -> str:
        matches = self.get_lines_from_log(
            search_text,
            search_from_text=search_from_text,
            max_matches=1,
            log_file=log_file,
        )
        return matches[0] if matches else None

    def text_in_messages(self, log_text) -> bool:
        return bool([_ for _ in self._messages.get_messages() if log_text in _])

    ###########################################################################
    # PASSTHROUGH PUBLIC METHODS
    ###########################################################################

    def close_log(self, *args, **kwargs):
        return self._messages.close_log(*args, **kwargs)

    def debug(self, *args, **kwargs):
        return self._messages.debug(*args, **kwargs)

    def get_log_fh(self):
        return self._messages.get_log_fh()

    def get_log_fh_name(self):
        return self._messages.get_log_fh_name()

    def get_events(self):
        return self._messages.get_events()

    def get_messages(self):
        return self._messages.get_messages()

    def info(self, *args, **kwargs):
        return self._messages.info(*args, **kwargs)

    def log(self, *args, **kwargs):
        return self._messages.log(*args, **kwargs)

    def warning(self, *args, **kwargs):
        return self._messages.warning(*args, **kwargs)

    @property
    def execution_id(self):
        return self._messages.execution_id

    @execution_id.setter
    def execution_id(self, new_value):
        self._messages.execution_id = new_value
