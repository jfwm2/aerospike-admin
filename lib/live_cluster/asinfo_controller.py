from lib.utils import util
from lib.base_controller import CommandHelp, ShellException

from .live_cluster_command_controller import LiveClusterCommandController


@CommandHelp(
    '"asinfo" provides raw access to the info protocol.',
    "  Options:",
    "    -v <command>   - The command to execute",
    "    -p <port>      - Port to use in the case of an XDR info command and XDR is",
    "                     not in asd",
    '    -l             - Replace semicolons ";" with newlines. If output does',
    '                     not contain semicolons "-l" will attempt to use',
    '                     colons ":" followed by commas ",".',
    "    --no_node_name - Force to display output without printing node names.",
)
class ASInfoController(LiveClusterCommandController):
    def __init__(self):
        self.modifiers = set(["with", "like"])

    @CommandHelp("Executes an info command.")
    def _do_default(self, line):
        mods = self.parse_modifiers(line)
        line = mods["line"]
        nodes = self.nodes

        value = None
        line_sep = False
        xdr = False
        show_node_name = True

        tline = line[:]

        try:
            while tline:
                word = tline.pop(0)
                if word == "-v":
                    value = tline.pop(0)
                elif word == "-l":
                    line_sep = True
                elif word == "-p":
                    port = tline.pop(0)
                    if port == "3004":  # ugly Hack
                        xdr = True
                elif word == "--no_node_name":
                    show_node_name = False
                else:
                    raise ShellException(
                        "Do not understand '%s' in '%s'" % (word, " ".join(line))
                    )
        except Exception:
            self.logger.warning(
                "Do not understand '%s' in '%s'" % (word, " ".join(line))
            )
            return
        if value is not None:
            value = value.translate(str.maketrans("", "", "'\""))

        if xdr:
            results = self.cluster.xdr_info(value, nodes=nodes)
        else:
            results = self.cluster.info(value, nodes=nodes)

        return util.Future(
            self.view.asinfo, results, line_sep, show_node_name, self.cluster, **mods
        )
