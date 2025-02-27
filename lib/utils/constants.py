# Copyright 2013-2021 Aerospike, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os

ADMIN_HOME = os.path.expanduser("~") + "/.aerospike/"

CONFIG_SERVICE = "service"
CONFIG_NETWORK = "network"
CONFIG_NAMESPACE = "namespace"
CONFIG_XDR = "xdr"
CONFIG_DC = "dc"
CONFIG_CLUSTER = "cluster"

STAT_SERVICE = "service"
STAT_SETS = "set"
STAT_NAMESPACE = "namespace"
STAT_XDR = "xdr"
STAT_DC = "dc"
STAT_BINS = "bin"
STAT_SINDEX = "sindex"

SUMMARY_SERVICE = "service"
SUMMARY_NETWORK = "network"
SUMMARY_NAMESPACE = "namespace"
SUMMARY_SETS = "sets"
SUMMARY_XDR = "xdr"
SUMMARY_DC = "dc"
SUMMARY_SINDEX = "sindex"


SHOW_RESULT_KEY = "show_result"
COUNT_RESULT_KEY = "count_result"
TOTAL_ROW_HEADER = "total"
END_ROW_KEY = "End"

DT_FMT = "%b %d %Y %H:%M:%S"

CLUSTER_FILE = 0
SERVER_FILE = 1
SYSTEM_FILE = 2
JSON_FILE = 3

COLLECTINFO_SEPERATOR = "\n====ASCOLLECTINFO====\n"
COLLECTINFO_PROGRESS_MSG = "Data collection for %s%s  in progress..."


class Enumeration(set):
    def __getattr__(self, name):
        if name in self:
            return name
        raise AttributeError

    def __getitem__(self, name):
        if name in self:
            return name
        raise AttributeError


AuthMode = Enumeration(
    [
        # Use internal authentication only.  Hashed password is stored on the server.
        # Do not send clear password. This is the default.
        "INTERNAL",
        # Use external authentication (like LDAP).  Specific external authentication is
        # configured on server.  If TLS defined, send clear password on node login via TLS.
        # Throw exception if TLS is not defined.
        "EXTERNAL",
        # Use external authentication (like LDAP).  Specific external authentication is
        # configured on server.  Send clear password on node login whether or not TLS is defined.
        # This mode should only be used for testing purposes because it is not secure authentication.
        "EXTERNAL_INSECURE",
    ]
)

AdminMode = Enumeration(
    [
        # Connect to live cluster
        "LIVE_CLUSTER",
        # Analyse collectinfo
        "COLLECTINFO_ANALYZER",
        # Analyse Aerospike logs
        "LOG_ANALYZER",
    ]
)


# server versions with critical changes
SERVER_QUOTAS_FIRST_VERSION = "5.6"
SERVER_NEW_LATENCIES_CMD_FIRST_VERSION = "5.1"
SERVER_NEW_XDR5_VERSION = "5.0"
SERVER_NEW_HISTOGRAM_FIRST_VERSION = "4.2"
