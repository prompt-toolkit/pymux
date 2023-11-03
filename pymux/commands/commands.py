import os
import re
import shlex
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, TypeVar

import docopt
from prompt_toolkit.application.current import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding.vi_state import InputMode
from pymux.arrangement import LayoutTypes
from pymux.commands.aliases import ALIASES
from pymux.commands.utils import wrap_argument
from pymux.format import format_pymux_string
from pymux.key_mappings import (
    prompt_toolkit_key_to_vt100_key,
    pymux_key_to_prompt_toolkit_key_sequence,
)
from pymux.layout import focus_down, focus_left, focus_right, focus_up
from pymux.log import logger
from pymux.options import SetOptionError

if TYPE_CHECKING:
    from pymux.main import Pymux

__all__ = [
    "call_command_handler",
    "get_documentation_for_command",
    "get_option_flags_for_command",
    "handle_command",
    "has_command_handler",
]

_VariablesList = List[str]
_VariablesDict = Dict[str, Any]
_PymuxHandler = Callable[["Pymux", _VariablesList], None]
_PymuxDictHandler = Callable[["Pymux", _VariablesDict], None]

# Global mapping of pymux commands to their handlers.
COMMANDS_TO_HANDLERS: Dict[str, _PymuxHandler] = {}

COMMANDS_TO_HELP: Dict[str, str] = {}
COMMANDS_TO_OPTION_FLAGS: Dict[str, List[str]] = {}


def has_command_handler(command: str) -> bool:
    return command in COMMANDS_TO_HANDLERS


def get_documentation_for_command(command: str) -> Optional[str]:
    """
    Return the help text for this command, or None if the command is not known.
    """
    if command in COMMANDS_TO_HELP:
        return "Usage: %s %s" % (command, COMMANDS_TO_HELP.get(command, ""))

    return None


def get_option_flags_for_command(command: str) -> List[str]:
    "Return a list of options (-x flags) for this command."
    return COMMANDS_TO_OPTION_FLAGS.get(command, [])


def handle_command(pymux: "Pymux", input_string: str) -> None:
    """
    Handle command.
    """
    input_string = input_string.strip()
    logger.info("handle command: %s %s.", input_string, type(input_string))

    if input_string and not input_string.startswith("#"):  # Ignore comments.
        try:
            parts = shlex.split(input_string)
        except ValueError as e:
            # E.g. missing closing quote.
            pymux.show_message("Invalid command %s: %s" % (input_string, e))
        else:
            call_command_handler(parts[0], pymux, parts[1:])


def call_command_handler(
    command: str, pymux: "Pymux", arguments: _VariablesList
) -> None:
    """
    Execute command.

    :param arguments: List of options.
    """
    # Resolve aliases.
    command = ALIASES.get(command, command)

    try:
        handler = COMMANDS_TO_HANDLERS[command]
    except KeyError:
        pymux.show_message("Invalid command: %s" % (command,))
    else:
        try:
            handler(pymux, arguments)
        except CommandException as e:
            pymux.show_message(e.message)


_F = TypeVar("_F", bound=_PymuxDictHandler)


def cmd(name: str, options: str = "") -> Callable[[_F], _F]:
    """
    Decorator for all commands.

    Commands will receive (pymux, variables) as input.
    Commands can raise CommandException.
    """
    # Validate options.
    if options:
        try:
            docopt.docopt(
                "Usage:\n    %s %s"
                % (
                    name,
                    options,
                ),
                [],
            )
        except SystemExit:
            pass

    def decorator(func: _F) -> _F:
        def command_wrapper(pymux: "Pymux", arguments: _VariablesList) -> None:
            # Hack to make the 'bind-key' option work.
            # (bind-key expects a variable number of arguments.)
            if name == "bind-key" and "--" not in arguments:
                # Insert a double dash after the first non-option.
                for i, p in enumerate(arguments):
                    if not p.startswith("-"):
                        arguments.insert(i + 1, "--")
                        break

            # Parse options.
            try:
                received_options: Dict[str, str] = docopt.docopt(
                    "Usage:\n    %s %s" % (name, options), arguments, help=False
                )  # Don't interpret the '-h' option as help.
            except SystemExit:
                raise CommandException("Usage: %s %s" % (name, options))

            # Call handler.
            func(pymux, received_options)

            # Invalidate all clients, not just the current CLI.
            pymux.invalidate()

        COMMANDS_TO_HANDLERS[name] = command_wrapper
        COMMANDS_TO_HELP[name] = options

        # Get list of option flags.
        flags = re.findall(r"-[a-zA-Z0-9]\b", options)
        COMMANDS_TO_OPTION_FLAGS[name] = flags

        return func

    return decorator


class CommandException(Exception):
    "When raised from a command handler, this message will be shown."

    def __init__(self, message: str) -> None:
        self.message = message


#
# The actual commands.
#


@cmd("break-pane", options="[-d]")
def break_pane(pymux: "Pymux", variables: _VariablesDict) -> None:
    dont_focus_window = variables["-d"]

    pymux.arrangement.break_pane(set_active=not dont_focus_window)
    pymux.invalidate()


@cmd("select-pane", options="(-L|-R|-U|-D|-t <pane-id>)")
def select_pane(pymux: "Pymux", variables: _VariablesDict) -> None:
    if variables["-t"]:
        pane_id = variables["<pane-id>"]
        w = pymux.arrangement.get_active_window()

        if pane_id == ":.+":
            w.focus_next()
        elif pane_id == ":.-":
            w.focus_previous()
        else:
            # Select pane by index.
            try:
                pane_id_int = int(pane_id[1:])
                w.active_pane = w.panes[pane_id_int]
            except (IndexError, ValueError):
                raise CommandException("Invalid pane.")

    else:
        if variables["-L"]:
            h = focus_left
        if variables["-U"]:
            h = focus_up
        if variables["-D"]:
            h = focus_down
        if variables["-R"]:
            h = focus_right

        h(pymux)


@cmd("select-window", options="(-t <target-window>)")
def select_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Select a window. E.g:  select-window -t :3
    """
    window_id = variables["<target-window>"]

    def invalid_window():
        raise CommandException("Invalid window: %s" % window_id)

    if window_id.startswith(":"):
        try:
            number = int(window_id[1:])
        except ValueError:
            invalid_window()
        else:
            w = pymux.arrangement.get_window_by_index(number)
            if w:
                pymux.arrangement.set_active_window(w)
            else:
                invalid_window()
    else:
        invalid_window()


@cmd("move-window", options="(-t <dst-window>)")
def move_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Move window to a new index.
    """
    dst_window = variables["<dst-window>"]
    try:
        new_index = int(dst_window)
    except ValueError:
        raise CommandException("Invalid window index: %r" % (dst_window,))

    # Check first whether the index was not yet taken.
    if pymux.arrangement.get_window_by_index(new_index):
        raise CommandException("Can't move window: index in use.")

    # Save index.
    w = pymux.arrangement.get_active_window()
    pymux.arrangement.move_window(w, new_index)


@cmd("rotate-window", options="[-D|-U]")
def rotate_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    if variables["-D"]:
        pymux.arrangement.rotate_window(count=-1)
    else:
        pymux.arrangement.rotate_window()


@cmd("swap-pane", options="(-D|-U)")
def swap_pane(pymux: "Pymux", variables: _VariablesDict) -> None:
    pymux.arrangement.get_active_window().rotate(with_pane_after_only=variables["-U"])


@cmd("kill-pane")
def kill_pane(pymux: "Pymux", variables: _VariablesDict) -> None:
    pane = pymux.arrangement.get_active_pane()
    pymux.kill_pane(pane)


@cmd("kill-window")
def kill_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Kill all panes in the current window."
    for pane in pymux.arrangement.get_active_window().panes:
        pymux.kill_pane(pane)


@cmd("suspend-client")
def suspend_client(pymux: "Pymux", variables: _VariablesDict) -> None:
    connection = pymux.get_connection()

    if connection:
        connection.suspend_client_to_background()


@cmd("clock-mode")
def clock_mode(pymux: "Pymux", variables: _VariablesDict) -> None:
    pane = pymux.arrangement.get_active_pane()
    if pane:
        pane.clock_mode = not pane.clock_mode


@cmd("last-pane")
def last_pane(pymux: "Pymux", variables: _VariablesDict) -> None:
    w = pymux.arrangement.get_active_window()
    prev_active_pane = w.previous_active_pane

    if prev_active_pane:
        w.active_pane = prev_active_pane


@cmd("next-layout")
def next_layout(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Select next layout."
    pane = pymux.arrangement.get_active_window()
    if pane:
        pane.select_next_layout()


@cmd("previous-layout")
def previous_layout(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Select previous layout."
    pane = pymux.arrangement.get_active_window()
    if pane:
        pane.select_previous_layout()


@cmd("new-window", options="[(-n <name>)] [(-c <start-directory>)] [<executable>]")
def new_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    executable = variables["<executable>"]
    start_directory = variables["<start-directory>"]
    name = variables["<name>"]

    pymux.create_window(executable, start_directory=start_directory, name=name)


@cmd("next-window")
def next_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Focus the next window."
    pymux.arrangement.focus_next_window()


@cmd("last-window")
def _(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Go to previous active window."
    w = pymux.arrangement.get_previous_active_window()

    if w:
        pymux.arrangement.set_active_window(w)


@cmd("previous-window")
def previous_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Focus the previous window."
    pymux.arrangement.focus_previous_window()


@cmd("select-layout", options="<layout-type>")
def select_layout(pymux: "Pymux", variables: _VariablesDict) -> None:
    layout_type = variables["<layout-type>"]

    try:
        layout_type_obj: LayoutTypes = LayoutTypes(layout_type_obj)
    except ValueError:
        pymux.arrangement.get_active_window().select_layout(layout_type_obj)
    else:
        raise CommandException("Invalid layout type.")


@cmd("rename-window", options="<name>")
def rename_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Rename the active window.
    """
    pymux.arrangement.get_active_window().chosen_name = variables["<name>"]


@cmd("rename-pane", options="<name>")
def rename_pane(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Rename the active pane.
    """
    pymux.arrangement.get_active_pane().chosen_name = variables["<name>"]


@cmd("rename-session", options="<name>")
def rename_session(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Rename this session.
    """
    pymux.session_name = variables["<name>"]


@cmd("split-window", options="[-v|-h] [(-c <start-directory>)] [<executable>]")
def split_window(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Split horizontally or vertically.
    """
    executable = variables["<executable>"]
    start_directory = variables["<start-directory>"]

    # The tmux definition of horizontal is the opposite of prompt_toolkit.
    pymux.add_process(
        executable, vsplit=variables["-h"], start_directory=start_directory
    )


@cmd(
    "resize-pane", options="[(-L <left>)] [(-U <up>)] [(-D <down>)] [(-R <right>)] [-Z]"
)
def resize_pane(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Resize/zoom the active pane.
    """
    try:
        left = int(variables["<left>"] or 0)
        right = int(variables["<right>"] or 0)
        up = int(variables["<up>"] or 0)
        down = int(variables["<down>"] or 0)
    except ValueError:
        raise CommandException("Expecting an integer.")

    w = pymux.arrangement.get_active_window()

    if w:
        w.change_size_for_active_pane(up=up, right=right, down=down, left=left)

        # Zoom in/out.
        if variables["-Z"]:
            w.zoom = not w.zoom


@cmd("detach-client")
def detach_client(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Detach client.
    """
    pymux.detach_client(get_app())


@cmd("confirm-before", options="[(-p <message>)] <command>")
def confirm_before(pymux: "Pymux", variables: _VariablesDict) -> None:
    client_state = pymux.get_client_state()

    client_state.confirm_text = variables["<message>"] or ""
    client_state.confirm_command = variables["<command>"]


@cmd("command-prompt", options="[(-p <message>)] [(-I <default>)] [<command>]")
def command_prompt(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Enter command prompt.
    """
    client_state = pymux.get_client_state()

    if variables["<command>"]:
        # When a 'command' has been given.
        client_state.prompt_text = (
            variables["<message>"] or "(%s)" % variables["<command>"].split()[0]
        )
        client_state.prompt_command = variables["<command>"]

        client_state.prompt_mode = True
        client_state.prompt_buffer.reset(
            Document(format_pymux_string(pymux, variables["<default>"] or ""))
        )

        get_app().layout.focus(client_state.prompt_buffer)
    else:
        # Show the ':' prompt.
        client_state.prompt_text = ""
        client_state.prompt_command = ""

        get_app().layout.focus(client_state.command_buffer)

    # Go to insert mode.
    get_app().vi_state.input_mode = InputMode.INSERT


@cmd("send-prefix")
def send_prefix(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Send prefix to active pane.
    """
    process = pymux.arrangement.get_active_pane().process

    for k in pymux.key_bindings_manager.prefix:
        vt100_data = prompt_toolkit_key_to_vt100_key(k)
        process.write_input(vt100_data)


@cmd("bind-key", options="[-n] <key> [--] <command> [<arguments>...]")
def bind_key(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Bind a key sequence.
    -n: Not necessary to use the prefix.
    """
    key = variables["<key>"]
    command = variables["<command>"]
    arguments = variables["<arguments>"]
    needs_prefix = not variables["-n"]

    try:
        pymux.key_bindings_manager.add_custom_binding(
            key, command, arguments, needs_prefix=needs_prefix
        )
    except ValueError:
        raise CommandException("Invalid key: %r" % (key,))


@cmd("unbind-key", options="[-n] <key>")
def unbind_key(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Remove key binding.
    """
    key = variables["<key>"]
    needs_prefix = not variables["-n"]

    pymux.key_bindings_manager.remove_custom_binding(key, needs_prefix=needs_prefix)


@cmd("send-keys", options="<keys>...")
def send_keys(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Send key strokes to the active process.
    """
    pane = pymux.arrangement.get_active_pane()

    if pane.display_scroll_buffer:
        raise CommandException("Cannot send keys. Pane is in copy mode.")

    for key in variables["<keys>"]:
        # Translate key from pymux key to prompt_toolkit key.
        try:
            keys_sequence = pymux_key_to_prompt_toolkit_key_sequence(key)
        except ValueError:
            raise CommandException("Invalid key: %r" % (key,))

        # Translate prompt_toolkit key to VT100 key.
        for k in keys_sequence:
            pane.process.write_key(k)


@cmd("copy-mode", options="[-u]")
def copy_mode(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Enter copy mode.
    """
    go_up = variables["-u"]  # Go in copy mode and page-up directly.
    # TODO: handle '-u'

    pane = pymux.arrangement.get_active_pane()
    pane.enter_copy_mode()


@cmd("paste-buffer")
def paste_buffer(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Paste clipboard content into buffer.
    """
    pane = pymux.arrangement.get_active_pane()
    pane.process.write_input(get_app().clipboard.get_data().text, paste=True)


@cmd("source-file", options="<filename>")
def source_file(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Source configuration file.
    """
    filename = os.path.expanduser(variables["<filename>"])
    try:
        with open(filename, "r") as f:
            for line in f:
                handle_command(pymux, line)
    except IOError as e:
        raise CommandException("IOError: %s" % (e,))


@cmd("set-option", options="<option> <value>")
def set_option(pymux: "Pymux", variables: _VariablesDict, window: bool = False) -> None:
    name = variables["<option>"]
    value = variables["<value>"]

    if window:
        option = pymux.window_options.get(name)
    else:
        option = pymux.options.get(name)

    if option:
        try:
            option.set_value(pymux, value)
        except SetOptionError as e:
            raise CommandException(e.message)
    else:
        raise CommandException("Invalid option: %s" % (name,))


@cmd("set-window-option", options="<option> <value>")
def set_window_option(pymux: "Pymux", variables: _VariablesDict) -> None:
    set_option(pymux, variables, window=True)


@cmd("display-panes")
def display_panes(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Display the pane numbers."
    pymux.display_pane_numbers = True


@cmd("display-message", options="<message>")
def display_message(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Display a message."
    message = variables["<message>"]
    client_state = pymux.get_client_state()
    client_state.message = message


@cmd("clear-history")
def clear_history(pymux: "Pymux", variables: _VariablesDict) -> None:
    "Clear scrollback buffer."
    pane = pymux.arrangement.get_active_pane()

    if pane.display_scroll_buffer:
        raise CommandException("Not available in copy mode")
    else:
        pane.process.screen.clear_history()


@cmd("list-keys")
def list_keys(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Display all configured key bindings.
    """
    # Create help string.
    result = []

    for k, custom_binding in pymux.key_bindings_manager.custom_bindings.items():
        needs_prefix, key = k

        result.append(
            "bind-key %3s %-10s %s %s"
            % (
                ("-n" if needs_prefix else ""),
                key,
                custom_binding.command,
                " ".join(map(wrap_argument, custom_binding.arguments)),
            )
        )

    # Display help in pane.
    result_str = "\n".join(sorted(result))
    pymux.get_client_state().layout_manager.display_popup("list-keys", result_str)


@cmd("list-panes")
def list_panes(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Display a list of all the panes.
    """
    w = pymux.arrangement.get_active_window()
    active_pane = w.active_pane

    result = []

    for i, p in enumerate(w.panes):
        process = p.process

        result.append(
            "%i: [%sx%s] [history %s/%s] %s"
            % (
                i,
                process.sx,
                process.sy,
                min(pymux.history_limit, process.screen.line_offset + process.sy),
                pymux.history_limit,
                ("(active)" if p == active_pane else ""),
            )
        )

    # Display help in pane.
    result_str = "\n".join(sorted(result))
    pymux.get_client_state().layout_manager.display_popup("list-keys", result_str)


@cmd("show-buffer")
def show_buffer(pymux: "Pymux", variables: _VariablesDict) -> None:
    """
    Display the clipboard content.
    """
    text = get_app().clipboard.get_data().text
    pymux.get_client_state().layout_manager.display_popup("show-buffer", text)


# Check whether all aliases point to real commands.
for k in ALIASES.values():
    assert k in COMMANDS_TO_HANDLERS
