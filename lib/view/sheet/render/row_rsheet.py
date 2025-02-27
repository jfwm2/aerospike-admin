# Copyright 2019 Aerospike, Inc.
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

from lib.view import terminal

from ..const import FieldAlignment
from .base_rsheet import BaseRField, BaseRSheetCLI


class RowRSheet(BaseRSheetCLI):
    # =========================================================================
    # Required overrides.

    def do_create_tuple_field(self, field, groups):
        raise NotImplementedError("Row styles doesn't support tuple fields")

    def do_create_field(self, field, groups, parent_key=None):
        return RFieldRow(self, field, groups, parent_key=parent_key)

    def do_render(self):
        render_fields = self.visible_rfields

        if not render_fields:
            return None

        n_records = self.n_records
        row_title_width = max(rfield.title_width for rfield in render_fields)
        row_aggr_width = max(rfield.aggregate_widths[0] + 1 for rfield in render_fields)
        column_widths = [
            max(rfield.widths[i] for rfield in render_fields) for i in range(n_records)
        ]
        has_aggregate = any(rfield.has_aggregate() for rfield in render_fields)
        title_indices = set([0])

        if self.title_repeat:
            terminal_width = self.terminal_size.columns
            title_incr = row_title_width + len(self.decleration.vertical_separator)
            cur_pos = title_incr
            n_repeats = 1
            need_column = True

            for i, column_width in enumerate(column_widths):
                if need_column or cur_pos + column_width < terminal_width:
                    cur_pos += column_width
                    need_column = False
                else:
                    title_indices.add(i)
                    cur_pos = title_incr + column_width
                    n_repeats += 1

            if has_aggregate:
                if cur_pos + row_aggr_width >= terminal_width:
                    title_indices.add("aggr")
                    n_repeats += 1

            total_row_title_width = n_repeats * title_incr
        else:
            total_row_title_width = row_title_width + len(
                self.decleration.vertical_separator
            )

        num_groups = 0 if not render_fields else render_fields[0].n_groups
        title_width = (
            total_row_title_width
            + (sum(column_widths) // num_groups)
            + ((n_records - 1) // num_groups) * len(self.decleration.vertical_separator)
            + row_aggr_width
        )
        render = []

        self._do_render_title(render, title_width)
        self._do_render_description(render, title_width, title_width - 10)

        # Render fields.

        # XXX - Add handling for Subgroups?
        terminal_height = self.terminal_size.lines
        title_field_keys = self.decleration.title_field_keys
        title_lines = [
            rfield
            for rfield in render_fields
            if rfield.decleration.key in title_field_keys
        ]

        if self.title_repeat:
            title_field_keys = self.decleration.title_field_keys
            title_lines = [
                rfield
                for rfield in render_fields
                if rfield.decleration.key in title_field_keys
            ]
            repeated_rfields = []

            for i, rfield in enumerate(
                rfield
                for rfield in render_fields
                if rfield.decleration.key not in title_field_keys
            ):
                if i % (terminal_height - 2) == 0:
                    repeated_rfields.extend(title_lines)

                repeated_rfields.append(rfield)

            render_fields = repeated_rfields

        num_groups = 0 if not render_fields else render_fields[0].n_groups
        has_aggregates = any(rfield.has_aggregate() for rfield in render_fields)
        hidden_count = 0

        for group_ix in range(num_groups):
            num_entries = render_fields[0].n_entries_in_group(group_ix)

            for render_field in render_fields:

                if render_field.decleration in self.group_hidden_fields[group_ix]:
                    hidden_count += 1
                    continue

                row = []
                for entry_ix in range(num_entries):
                    if entry_ix in title_indices:
                        row.append(render_field.get_title(row_title_width))

                    row.append(
                        render_field.entry_cell(
                            group_ix, entry_ix, column_widths[entry_ix]
                        )
                    )

                if has_aggregates:
                    row.append(render_field.aggregate_cell(group_ix))

                render.append(self.decleration.formatted_vertical_separator.join(row))

            if num_groups > 1 and group_ix < num_groups - 1:
                render.append(
                    self.decleration.formatted_horizontal_seperator * title_width
                )

        num_rows = len(render_fields) * num_groups - hidden_count
        self._do_render_n_rows(render, num_rows)

        return "\n".join(render) + "\n"

    # =========================================================================
    # Other methods.

    def _get_column_width(self, column_idx):
        return max(rfield.widths[column_idx] for rfield in self.visible_rfields)


class RFieldRow(BaseRField):
    # =========================================================================
    # Optional overrides.

    def do_prepare(self):
        """prepare is called after all fields have been initialized."""
        self._do_prepare_find_widths()

    # =========================================================================
    # Other methods.

    def _do_prepare_find_widths(self):
        self.title_width = len(self.decleration.title)
        self._do_prepare_find_aggregate_width()
        self.widths = []

        for group_converted in self.groups_converted:
            self.widths.extend(list(map(len, group_converted)))

    def _do_prepare_find_aggregate_width(self):
        if not self.has_aggregate:
            self.aggregate_widths = [0]
            return

        self.aggregate_widths = list(map(len, self.aggregates_converted))

    def get_title(self, width):
        line = self.decleration.title

        if self.is_ordered_by:
            orig_width = len(line)
            line = terminal.underline() + line + terminal.ununderline()
            extra_width = len(line) - orig_width
            width += extra_width

        return terminal.bold() + line.ljust(width) + terminal.unbold()

    def entry_cell(self, group_ix, entry_ix, width):
        cell = self._entry_cell_align(self.groups_converted[group_ix][entry_ix], width)
        format_name, formatter = self.entry_format(group_ix, entry_ix)

        if formatter is not None:
            cell = formatter(cell)

        return cell

    def _entry_cell_align(self, converted, width):
        if self.decleration.align is FieldAlignment.right:
            return converted.rjust(width)
        elif self.decleration.align is FieldAlignment.left:
            return converted.ljust(width)
        elif self.decleration.align is FieldAlignment.center:
            return converted.center(width)
        elif self.decleration.align is None:
            return converted.ljust(width)
        else:
            raise TypeError(
                "Unhandled FieldAlignment value: {}".format(self.decleration.align)
            )

    def aggregate_cell(self, group_ix):
        cell = self._entry_cell_align(
            self.aggregates_converted[group_ix], self.aggregate_widths[group_ix]
        )

        if self.aggregates[group_ix] is not None:
            cell = terminal.fg_blue() + cell + terminal.fg_not_blue()

            if self.is_grouped_by:
                cell = terminal.bold() + cell + terminal.unbold()

        return cell
