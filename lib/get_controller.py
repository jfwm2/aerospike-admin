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

import copy
from distutils.version import LooseVersion
from lib.utils import common, util, constants


def get_sindex_stats(cluster, nodes="all", for_mods=[]):
    stats = cluster.info_sindex(nodes=nodes)

    sindex_stats = {}
    if stats:
        for host, stat_list in stats.items():
            if not stat_list or isinstance(stat_list, Exception):
                continue

            namespace_set = {stat["ns"] for stat in stat_list}
            try:
                namespace_set = set(util.filter_list(namespace_set, for_mods[:1]))
            except Exception:
                pass

            sindex_set = {stat["indexname"] for stat in stat_list}
            try:
                sindex_set = set(util.filter_list(sindex_set, for_mods[1:2]))
            except Exception:
                pass

            for stat in stat_list:
                if not stat or stat["ns"] not in namespace_set:
                    continue

                ns = stat["ns"]
                set_ = stat["set"]
                indexname = stat["indexname"]

                if not indexname or not ns or indexname not in sindex_set:
                    continue

                sindex_key = "%s %s %s" % (ns, set_, indexname)

                if sindex_key not in sindex_stats:
                    sindex_stats[sindex_key] = {}
                sindex_stats[sindex_key] = cluster.info_sindex_statistics(
                    ns, indexname, nodes=nodes
                )
                for node in sindex_stats[sindex_key].keys():
                    if not sindex_stats[sindex_key][node] or isinstance(
                        sindex_stats[sindex_key][node], Exception
                    ):
                        continue
                    for key, value in stat.items():
                        sindex_stats[sindex_key][node][key] = value
    return sindex_stats


class GetDistributionController:
    def __init__(self, cluster):
        self.modifiers = set(["with", "for"])
        self.cluster = cluster

    def do_distribution(self, histogram_name, nodes="all"):
        histogram = self.cluster.info_histogram(histogram_name, nodes=nodes)
        return common.create_histogram_output(histogram_name, histogram)

    def do_object_size(self, byte_distribution=False, bucket_count=5, nodes="all"):

        histogram_name = "objsz"

        if not byte_distribution:
            return self.do_distribution(histogram_name, nodes=nodes)

        histogram = util.Future(
            self.cluster.info_histogram, histogram_name, logarithmic=True, nodes=nodes
        ).start()
        builds = util.Future(self.cluster.info, "build", nodes=nodes).start()
        histogram = histogram.result()
        builds = builds.result()

        return common.create_histogram_output(
            histogram_name,
            histogram,
            byte_distribution=True,
            bucket_count=bucket_count,
            builds=builds,
        )


class GetLatenciesController:
    def __init__(self, cluster):
        self.cluster = cluster

    # Returns a tuple (latencies, latency) of lists that contain nodes that
    #  support latencies cmd and nodes that do not.
    def get_latencies_and_latency_nodes(self, nodes="all"):
        latencies_nodes = []
        latency_nodes = []
        builds = self.cluster.info_build_version(nodes=nodes)

        for node, build in builds.items():
            if isinstance(build, Exception):
                continue
            if common.is_new_latencies_version(build):
                latencies_nodes.append(node)
            else:
                latency_nodes.append(node)
        return latencies_nodes, latency_nodes

    def _copy_latency_data_to_latencies_table(
        self, latencies_table, latency_table, context
    ):
        latencies_data = util.get_nested_value_from_dict(
            latencies_table, context, None, dict
        )
        latency_data = util.get_nested_value_from_dict(
            latency_table, context, None, dict
        )

        if latencies_data is None:
            return latency_data

        # Make every new entry start out with 'N/A' for all values
        for idx in range(len(latencies_data["values"])):
            for jdx in range(len(latencies_data["values"][idx])):
                latencies_data["values"][idx][jdx] = "N/A"

        if latency_data is None:
            return

        # See if any columns in latencies_data match latency_data and copy them
        # over.
        for col_idx, col in enumerate(latencies_data["columns"]):
            if col in latency_data["columns"]:
                val_idx = latency_data["columns"].index(col)
                for vals_idx in range(len(latencies_data["values"])):
                    latencies_data["values"][vals_idx][col_idx] = latency_data[
                        "values"
                    ][vals_idx][val_idx]

    # Merges latency tables into latencies table.  This is needed because a
    # latencies table can have different columns.
    def merge_latencies_and_latency_tables(self, latencies_table, latency_table):
        if not latencies_table:
            return latency_table
        if not latency_table:
            return latencies_table

        # Make an entry in latencies_table for every entry in latency_table
        for latencies_address in latencies_table:
            if latencies_table[latencies_address]:
                for latency_address in latency_table:
                    # Create entry with same schema as latencies_table
                    latencies_table[latency_address] = copy.deepcopy(
                        latencies_table[latencies_address]
                    )
                break

        # Go through latency data and copy appropriate values over
        for latency_address in latency_table:
            latencies_entry = latencies_table[latency_address]
            for histogram_name in latencies_entry:
                histogram_data = latencies_entry[histogram_name]
                if "total" in histogram_data:
                    self._copy_latency_data_to_latencies_table(
                        latencies_table,
                        latency_table,
                        [latency_address, histogram_name, "total"],
                    )
                if "namespace" in histogram_data:
                    namespaces = histogram_data["namespace"]
                    for namespace in namespaces:
                        self._copy_latency_data_to_latencies_table(
                            latencies_table,
                            latency_table,
                            [latency_address, histogram_name, "namespace", namespace],
                        )

        return latencies_table

    def get_namespace_set(self, nodes):
        namespace_set = set()
        namespaces = self.cluster.info_namespaces(nodes=nodes)
        namespaces = list(namespaces.values())

        for namespace in namespaces:
            if isinstance(namespace, Exception):
                continue
            namespace_set.update(namespace)
        return namespace_set

    def get_all(self, nodes, buckets, exponent_increment, verbose, ns_set=None):
        latencies_nodes, latency_nodes = self.get_latencies_and_latency_nodes()
        latencies = None

        if ns_set is None:
            ns_set = self.get_namespace_set(nodes)

        # all nodes support "show latencies"
        if len(latency_nodes) == 0:
            latencies = self.cluster.info_latencies(
                nodes=nodes,
                buckets=buckets,
                exponent_increment=exponent_increment,
                verbose=verbose,
                ns_set=ns_set,
            )
        # No nodes support "show latencies"
        elif len(latencies_nodes) == 0:
            latencies = self.cluster.info_latency(nodes=latency_nodes, ns_set=ns_set)
        # Some nodes support latencies and some do not
        else:
            latency = util.Future(
                self.cluster.info_latency, nodes=latency_nodes, ns_set=ns_set
            ).start()
            latencies = util.Future(
                self.cluster.info_latencies,
                nodes=latencies_nodes,
                buckets=buckets,
                exponent_increment=exponent_increment,
                verbose=verbose,
                ns_set=ns_set,
            ).start()
            latency = latency.result()
            latencies = latencies.result()
            latencies = self.merge_latencies_and_latency_tables(latencies, latency)

        return latencies


class GetConfigController:
    def __init__(self, cluster):
        self.cluster = cluster

    def get_all(self, flip=True, nodes="all"):
        futures = [
            (
                "service",
                (util.Future(self.get_service, flip=flip, nodes=nodes).start()),
            ),
            (
                "namespace",
                (util.Future(self.get_namespace, flip=flip, nodes=nodes).start()),
            ),
            (
                "network",
                (util.Future(self.get_network, flip=flip, nodes=nodes).start()),
            ),
            ("xdr", (util.Future(self.get_xdr, flip=flip, nodes=nodes).start())),
            ("dc", (util.Future(self.get_dc, flip=flip, nodes=nodes).start())),
            (
                "cluster",
                (util.Future(self.get_cluster, flip=flip, nodes=nodes).start()),
            ),
            ("roster", (util.Future(self.get_roster, flip=flip, nodes=nodes).start())),
            ("racks", (util.Future(self.get_racks, flip=flip, nodes=nodes).start())),
        ]
        config_map = dict(((k, f.result()) for k, f in futures))

        return config_map

    def get_service(self, flip=True, nodes="all"):
        service_configs = self.cluster.info_get_config(nodes=nodes, stanza="service")
        for node in service_configs:
            if isinstance(service_configs[node], Exception):
                service_configs[node] = {}

        return service_configs

    def get_network(self, flip=True, nodes="all"):
        hb_configs = util.Future(
            self.cluster.info_get_config, nodes=nodes, stanza="network.heartbeat"
        ).start()
        info_configs = util.Future(
            self.cluster.info_get_config, nodes=nodes, stanza="network.info"
        ).start()
        nw_configs = util.Future(
            self.cluster.info_get_config, nodes=nodes, stanza="network"
        ).start()

        network_configs = {}
        hb_configs = hb_configs.result()
        for node in hb_configs:
            try:
                if isinstance(hb_configs[node], Exception):
                    network_configs[node] = {}
                else:
                    network_configs[node] = hb_configs[node]
            except Exception:
                pass

        info_configs = info_configs.result()
        for node in info_configs:
            try:
                if isinstance(info_configs[node], Exception):
                    continue
                else:
                    network_configs[node].update(info_configs[node])
            except Exception:
                pass

        nw_configs = nw_configs.result()
        for node in nw_configs:
            try:
                if isinstance(nw_configs[node], Exception):
                    continue
                else:
                    network_configs[node].update(nw_configs[node])
            except Exception:
                pass

        return network_configs

    def get_namespace(self, flip=True, nodes="all", for_mods=[]):
        namespaces = self.cluster.info_namespaces(nodes=nodes)
        namespace_set = set()

        for namespace in namespaces.values():
            if isinstance(namespace, Exception):
                continue

            namespace_set.update(namespace)

        namespace_list = util.filter_list(namespace_set, for_mods)
        ns_configs = {}

        for index, namespace in enumerate(namespace_list):
            node_configs = self.cluster.info_get_config(
                stanza="namespace",
                namespace=namespace,
                namespace_id=index,
                nodes=nodes,
            )
            for node, node_config in list(node_configs.items()):
                if (
                    not node_config
                    or isinstance(node_config, Exception)
                    or namespace not in node_config
                ):
                    continue

                if node not in ns_configs:
                    ns_configs[node] = {}

                ns_configs[node][namespace] = node_config[namespace]

        if flip:
            ns_configs = util.flip_keys(ns_configs)

        return ns_configs

    def get_xdr5_nodes(self, nodes="all"):
        xdr5_nodes = []
        builds = self.cluster.info_build_version(nodes=nodes)

        for node, build in builds.items():
            if isinstance(build, Exception):
                continue
            if LooseVersion(constants.SERVER_NEW_XDR5_VERSION) <= LooseVersion(build):
                xdr5_nodes.append(node)

        return xdr5_nodes

    # XDR configs >= AS Server 5.0
    def get_xdr5(self, flip=True, nodes="all"):
        # get xdr5 nodes and remote port
        xdr_configs = {}
        xdr5_nodes = self.get_xdr5_nodes(nodes)

        if not xdr5_nodes:
            return xdr_configs

        xdr5_nodes = [address.split(":")[0] for address in xdr5_nodes]

        return self.get_xdr(nodes=xdr5_nodes)

    def get_old_xdr_nodes(self, nodes="all"):
        old_xdr_nodes = []
        builds = self.cluster.info_build_version(nodes=nodes)

        for node, build in builds.items():
            if isinstance(build, Exception):
                continue
            if LooseVersion(constants.SERVER_NEW_XDR5_VERSION) > LooseVersion(build):
                old_xdr_nodes.append(node)

        return old_xdr_nodes

    # XDR configs < AS Server 5.0
    def get_old_xdr(self, flip=True, nodes="all"):
        xdr_configs = {}
        nodes = self.get_old_xdr_nodes(nodes)

        if not nodes:
            return xdr_configs

        return self.get_xdr(nodes=nodes)

    def get_xdr(self, flip=True, nodes="all"):
        xdr_configs = {}
        configs = self.cluster.info_XDR_get_config(nodes=nodes)

        if configs:
            for node, config in configs.items():
                if isinstance(config, Exception):
                    continue

                xdr_configs[node] = config

        return xdr_configs

    def get_dc(self, flip=True, nodes="all"):
        configs = self.cluster.info_dc_get_config(nodes=nodes)
        for node in configs:
            if isinstance(configs[node], Exception):
                configs[node] = {}

        dc_configs = {}
        if configs:
            for node, node_config in configs.items():
                if not node_config or isinstance(node_config, Exception):
                    continue

                dc_configs[node] = node_config

            if flip:
                dc_configs = util.flip_keys(dc_configs)

        return dc_configs

    def get_cluster(self, flip=True, nodes="all"):

        configs = util.Future(
            self.cluster.info_get_config, nodes=nodes, stanza="cluster"
        ).start()

        configs = configs.result()
        cl_configs = {}
        if configs:
            for node, config in configs.items():
                if not config or isinstance(config, Exception):
                    continue

                cl_configs[node] = config

        return cl_configs

    def get_roster(self, flip=True, nodes="all"):

        configs = util.Future(self.cluster.info_roster, nodes=nodes).start()

        configs = configs.result()
        roster_configs = {}
        if configs:
            for node, config in configs.items():
                if not config or isinstance(config, Exception):
                    continue

                roster_configs[node] = config

            if flip:
                roster_configs = util.flip_keys(roster_configs)

        return roster_configs

    def get_racks(self, flip=True, nodes="all"):

        configs = util.Future(self.cluster.info_racks, nodes=nodes).start()

        configs = configs.result()
        rack_configs = {}

        if configs:
            for node, config in configs.items():
                if not config or isinstance(config, Exception):
                    continue

                rack_configs[node] = config

            if flip:
                rack_configs = util.flip_keys(rack_configs)

        return rack_configs


class GetStatisticsController:
    def __init__(self, cluster):
        self.cluster = cluster

    def get_all(self, nodes="all"):
        futures = [
            ("service", (util.Future(self.get_service, nodes=nodes).start())),
            ("namespace", (util.Future(self.get_namespace, nodes=nodes).start())),
            ("set", (util.Future(self.get_sets, nodes=nodes).start())),
            ("bin", (util.Future(self.get_bins, nodes=nodes).start())),
            ("sindex", (util.Future(self.get_sindex, nodes=nodes).start())),
            ("xdr", (util.Future(self.get_xdr, nodes=nodes).start())),
            ("dc", (util.Future(self.get_dc, nodes=nodes).start())),
        ]
        stat_map = dict(((k, f.result()) for k, f in futures))

        return stat_map

    def get_service(self, nodes="all"):
        service_stats = self.cluster.info_statistics(nodes=nodes)
        return service_stats

    def get_namespace(self, nodes="all", for_mods=[]):
        namespaces = self.cluster.info_namespaces(nodes=nodes)
        namespace_set = set()

        for namespace in namespaces.values():
            if isinstance(namespace, Exception):
                continue

            namespace_set.update(namespace)

        namespace_list = util.filter_list(namespace_set, for_mods)
        futures = [
            (
                namespace,
                util.Future(
                    self.cluster.info_namespace_statistics, namespace, nodes=nodes
                ).start(),
            )
            for namespace in namespace_list
        ]
        ns_stats = {}

        for namespace, stat_future in futures:
            ns_stats[namespace] = stat_future.result()

            for _k in list(ns_stats[namespace].keys()):
                if not ns_stats[namespace][_k]:
                    ns_stats[namespace].pop(_k)

        return ns_stats

    def get_sindex(self, nodes="all", for_mods=[]):
        sindex_stats = get_sindex_stats(self.cluster, nodes, for_mods)
        return sindex_stats

    def get_sets(self, nodes="all", for_mods=[]):
        sets = self.cluster.info_set_statistics(nodes=nodes)

        set_stats = {}
        for host_id, key_values in sets.items():
            if isinstance(key_values, Exception) or not key_values:
                continue

            namespace_set = {ns_set[0] for ns_set in key_values.keys()}

            try:
                namespace_set = set(util.filter_list(namespace_set, for_mods[:1]))
            except Exception:
                pass

            sets = {ns_set[1] for ns_set in key_values.keys()}
            try:
                sets = set(util.filter_list(sets, for_mods[1:2]))
            except Exception:
                pass

            for key, values in key_values.items():

                if key[0] not in namespace_set or key[1] not in sets:
                    continue

                if key not in set_stats:
                    set_stats[key] = {}
                host_vals = set_stats[key]

                if host_id not in host_vals:
                    host_vals[host_id] = {}
                hv = host_vals[host_id]
                hv.update(values)

        return set_stats

    def get_bins(self, nodes="all", for_mods=[]):
        bin_stats = self.cluster.info_bin_statistics(nodes=nodes)
        new_bin_stats = {}

        for node_id, bin_stat in bin_stats.items():
            if not bin_stat or isinstance(bin_stat, Exception):
                continue

            namespace_set = set(util.filter_list(bin_stat.keys(), for_mods))

            for namespace, stats in bin_stat.items():
                if namespace not in namespace_set:
                    continue
                if namespace not in new_bin_stats:
                    new_bin_stats[namespace] = {}
                ns_stats = new_bin_stats[namespace]

                if node_id not in ns_stats:
                    ns_stats[node_id] = {}
                node_stats = ns_stats[node_id]

                node_stats.update(stats)

        return new_bin_stats

    def get_xdr(self, nodes="all"):
        xdr_stats = self.cluster.info_XDR_statistics(nodes=nodes)
        return xdr_stats

    def get_dc(self, nodes="all"):
        all_dc_stats = self.cluster.info_all_dc_statistics(nodes=nodes)
        dc_stats = {}
        for host, stats in all_dc_stats.items():
            if not stats or isinstance(stats, Exception):
                continue
            for dc, stat in stats.items():
                if dc not in dc_stats:
                    dc_stats[dc] = {}

                try:
                    dc_stats[dc][host].update(stat)
                except KeyError:
                    dc_stats[dc][host] = stat
        return dc_stats

    def _check_key_for_gt(self, d={}, keys=(), v=0, is_and=False, type_check=int):
        if not keys:
            return True
        if not d:
            return False
        if not isinstance(keys, tuple):
            keys = (keys,)
        if is_and:
            if all(util.get_value_from_dict(d, k, v, type_check) > v for k in keys):
                return True
        else:
            if any(util.get_value_from_dict(d, k, v, type_check) > v for k in keys):
                return True
        return False


class GetFeaturesController:
    def __init__(self, cluster):
        self.cluster = cluster

    def get_features(self, nodes="all"):
        service_stats = util.Future(self.cluster.info_statistics, nodes=nodes).start()
        ns_stats = util.Future(
            self.cluster.info_all_namespace_statistics, nodes=nodes
        ).start()
        service_configs = util.Future(
            self.cluster.info_get_config, stanza="service", nodes=nodes
        ).start()
        ns_configs = util.Future(
            self.cluster.info_get_config, stanza="namespace", nodes=nodes
        ).start()
        cl_configs = util.Future(
            self.cluster.info_get_config, stanza="cluster", nodes=nodes
        ).start()

        service_stats = service_stats.result()
        ns_stats = ns_stats.result()
        service_configs = service_configs.result()
        ns_configs = ns_configs.result()
        cl_configs = cl_configs.result()

        return common.find_nodewise_features(
            service_stats=service_stats,
            ns_stats=ns_stats,
            service_configs=service_configs,
            ns_configs=ns_configs,
            cluster_configs=cl_configs,
        )


class GetPmapController:
    def __init__(self, cluster):
        self.cluster = cluster

    def _get_namespace_data(self, namespace_stats, cluster_keys):
        ns_info = {}

        # stats to fetch
        stats = ["dead_partitions", "unavailable_partitions"]

        for ns, nodes in namespace_stats.items():

            for node, params in nodes.items():
                if isinstance(params, Exception):
                    continue

                if cluster_keys[node] not in ns_info:
                    ns_info[cluster_keys[node]] = {}

                d = ns_info[cluster_keys[node]]
                if ns not in d:
                    d[ns] = {}

                d = d[ns]
                if node not in d:
                    d[node] = {}

                for s in stats:
                    util.set_value_in_dict(
                        d[node], s, util.get_value_from_dict(params, (s,))
                    )

        return ns_info

    def _get_pmap_data(self, pmap_info, ns_info, cluster_keys, node_ids):
        pid_range = 4096  # each namespace is divided into 4096 partition
        pmap_data = {}
        ns_available_part = {}

        # format : (index_ptr, field_name, default_index)
        # required fields present in all versions
        required_fields = [
            ("namespace_index", "namespace", 0),
            ("partition_index", "partition", 1),
            ("state_index", "state", 2),
            ("replica_index", "replica", 3),
        ]

        # fields present in version < 3.15.0
        optional_old_fields = [
            ("origin_index", "origin", 4),
            ("target_index", "target", 5),
        ]

        # fields present in version >= 3.15.0
        optional_new_fields = [("working_master_index", "working_master", None)]

        for _node, partitions in pmap_info.items():
            node_pmap = dict()
            ck = cluster_keys[_node]
            node_id = node_ids[_node]

            if isinstance(partitions, Exception):
                continue

            f_indices = {}

            # Setting default indices in partition fields for server < 3.8.4
            for t in required_fields + optional_old_fields + optional_new_fields:
                f_indices[t[0]] = t[2]

            # First row might be header, we need to check and set indices if its header row
            index_set = False

            for item in partitions.split(";"):
                fields = item.split(":")

                if not index_set:
                    # pmap format contains headers from server 3.8.4 onwards
                    index_set = True

                    if all(i[1] in fields for i in required_fields):
                        for t in required_fields:
                            f_indices[t[0]] = fields.index(t[1])

                        if all(i[1] in fields for i in optional_old_fields):
                            for t in optional_old_fields:
                                f_indices[t[0]] = fields.index(t[1])
                        elif all(i[1] in fields for i in optional_new_fields):
                            for t in optional_new_fields:
                                f_indices[t[0]] = fields.index(t[1])

                        continue

                ns, pid, state, replica = (
                    fields[f_indices["namespace_index"]],
                    int(fields[f_indices["partition_index"]]),
                    fields[f_indices["state_index"]],
                    int(fields[f_indices["replica_index"]]),
                )

                if f_indices["working_master_index"]:
                    working_master = fields[f_indices["working_master_index"]]
                    origin = target = None
                else:
                    origin, target = (
                        fields[f_indices["origin_index"]],
                        fields[f_indices["target_index"]],
                    )
                    working_master = None

                if pid not in range(pid_range):
                    print(
                        "For {0} found partition-ID {1} which is beyond legal partitions(0...4096)".format(
                            ns, pid
                        )
                    )
                    continue

                if ns not in node_pmap:
                    node_pmap[ns] = {
                        "master_partition_count": 0,
                        "prole_partition_count": 0,
                    }

                if ck not in ns_available_part:
                    ns_available_part[ck] = {}

                if ns not in ns_available_part[ck]:
                    ns_available_part[ck][ns] = {}
                    ns_available_part[ck][ns]["available_partition_count"] = 0

                if working_master:
                    if node_id == working_master:
                        # Working master
                        node_pmap[ns]["master_partition_count"] += 1

                    elif replica == 0 or state == "S" or state == "D":
                        # Eventual master or replicas
                        node_pmap[ns]["prole_partition_count"] += 1

                elif replica == 0:
                    if origin == "0":
                        # Working master (Final and proper master)
                        node_pmap[ns]["master_partition_count"] += 1

                    else:
                        # Eventual master
                        node_pmap[ns]["prole_partition_count"] += 1

                else:
                    if target == "0":
                        if state == "S" or state == "D":
                            node_pmap[ns]["prole_partition_count"] += 1

                    else:
                        # Working master (Acting master)
                        node_pmap[ns]["master_partition_count"] += 1

            pmap_data[_node] = node_pmap

        for _node, _ns_data in pmap_data.items():
            ck = cluster_keys[_node]

            for ns, params in _ns_data.items():
                params["cluster_key"] = ck

                try:
                    params.update(ns_info[ck][ns][_node])
                except Exception:
                    pass

        return pmap_data

    def get_pmap(self, nodes="all"):
        getter = GetStatisticsController(self.cluster)
        node_ids = util.Future(self.cluster.info, "node", nodes=nodes).start()
        pmap_info = util.Future(
            self.cluster.info, "partition-info", nodes=nodes
        ).start()
        service_stats = util.Future(getter.get_service, nodes=nodes).start()
        namespace_stats = util.Future(getter.get_namespace, nodes=nodes).start()

        service_stats = service_stats.result()

        cluster_keys = {}
        for node in service_stats.keys():
            if not service_stats[node] or isinstance(service_stats[node], Exception):
                cluster_keys[node] = "N/E"
            else:
                cluster_keys[node] = util.get_value_from_dict(
                    service_stats[node], ("cluster_key"), default_value="N/E"
                )

        namespace_stats = namespace_stats.result()
        ns_info = self._get_namespace_data(namespace_stats, cluster_keys)
        node_ids = node_ids.result()
        pmap_info = pmap_info.result()

        pmap_data = self._get_pmap_data(pmap_info, ns_info, cluster_keys, node_ids)

        return pmap_data


class GetUsersController:
    def __init__(self, cluster):
        self.cluster = cluster

    def get_users(self, nodes="all"):
        users_data = self.cluster.admin_query_users(nodes=nodes)
        return users_data

    def get_user(self, username, nodes="all"):
        user_data = self.cluster.admin_query_user(username, nodes=nodes)
        return user_data


class GetRolesController:
    def __init__(self, cluster):
        self.cluster = cluster

    def get_roles(self, nodes="all"):
        roles_data = self.cluster.admin_query_roles(nodes=nodes)
        return roles_data

    def get_role(self, role_name, nodes="all"):
        role_data = self.cluster.admin_query_role(role_name, nodes=nodes)
        return role_data


class GetUdfController:
    def __init__(self, cluster):
        self.cluster = cluster

    def get_udfs(self, nodes="all"):
        roles_data = self.cluster.info_udf_list(nodes=nodes)
        return roles_data


class GetSIndexController:
    def __init__(self, cluster):
        self.cluster = cluster

    def get_sindexs(self, nodes="all"):
        sindex_data = self.cluster.info_sindex(nodes=nodes)
        return sindex_data
