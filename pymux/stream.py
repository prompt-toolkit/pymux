"""
Improvements on Pyte.
"""
from __future__ import unicode_literals
from pyte.streams import Stream
from pyte.escape import NEL
from pyte import control as ctrl
from collections import defaultdict

from .log import logger

import re

__all__ = (
    'BetterStream',
)


class BetterStream(Stream):
    """
    Extension to the Pyte `Stream` class that also handles "Esc]<num>...BEL"
    sequences. This is used by xterm to set the terminal title.
    """
    escape = Stream.escape.copy()
    escape.update({
        # Call next_line instead of line_feed. We always want to go to the left
        # margin if we receive this, unlike \n, which goes one row down.
        # (Except when LNM has been set.)
        NEL: "next_line",
    })

    def __init__(self, screen):
        super(BetterStream, self).__init__()
        self.listener = screen

        self._validate_screen()

        # Create a regular expression pattern that matches everything what can
        # be considered plain text. This can be used as a very simple lexer
        # that can feed the "plain text part" as one token into the screen.
        special = set([ctrl.ESC, ctrl.CSI, ctrl.NUL, ctrl.DEL]) | set(self.basic)
        self._text_search = re.compile(
            '[^%s]+' % ''.join(re.escape(c) for c in special)).match

        # Start parser.
        self._parser = self._parser_generator()
        self._taking_plain_text = self._parser.send(None)
        self._send = self._parser.send

    def _validate_screen(self):
        """
        Check whether our Screen class has all the required callbacks.
        (We want to verify this statically, before feeding content to the
        screen.)
        """
        for d in [self.basic, self.escape, self.sharp, self.percent, self.csi]:
            for name in d.values():
                assert hasattr(self.listener, name), 'Screen is missing %r' % name

    def feed(self, chars):
        """
        Custom, much more efficient 'feed' function.
        Feed a string of characters to the parser.
        """
        # The original implementation of this function looked like this::
        #
        #     for c in chars:
        #         self._send(c)
        #
        # However, the implementation below does a big optimization. If the
        # parser is possibly expecting a chunk of text (when it is not inside a
        # ESC or CSI escape sequence), then we send that fragment directly to
        # the 'draw' method of the screen.

        # Local copy of functions. (For faster lookups.)
        send = self._send
        taking_plain_text = self._taking_plain_text
        text_search = self._text_search
        draw = self.listener.draw

        # Loop through the chars.
        i = 0
        count = len(chars)

        while i < count:
            # Reading plain text? Don't send characters one by one in the
            # generator, but optimize and send the whole chunk without
            # escapes directly to the listener.
            if taking_plain_text:
                match = text_search(chars, i)
                if match:
                    start, i = match.span()
                    draw(chars[start:i])
                else:
                    taking_plain_text = False

            # The parser expects just one character now. Just send the next one.
            else:
                taking_plain_text = send(chars[i])
                i += 1

        # Remember state for the next 'feed()'.
        self._taking_plain_text = taking_plain_text

    def _parser_generator(self):
        """
        Coroutine that processes VT100 output.

        It's actually a state machine, implemented as a coroutine. So all the
        'state' that we have is stored in local variables.

        This generator is not the most beautiful, but it is as performant as
        possible. When a process generates a lot of output (That is often much
        more than a person would give as input), then this will be the
        bottleneck, because it processes just one character at a time.

        We did many manual optimizations to this function in order to make it
        as efficient as possible. Don't change anything without profiling
        first.
        """
        listener = self.listener

        basic = self.basic
        escape = self.escape
        sharp = self.sharp
        percent = self.percent
        csi = self.csi

        ESC = ctrl.ESC
        CSI = ctrl.CSI
        CTRL_SEQUENCES_ALLOWED_IN_CSI = set([
            ctrl.BEL, ctrl.BS, ctrl.HT, ctrl.LF, ctrl.VT, ctrl.FF, ctrl.CR])

        def create_dispatch_dictionary(source_dict):
            # In order to avoid getting KeyError exceptions below, we make sure
            # that these dictionaries have a dummy handler.
            def dummy(*a, **kw):
                pass

            return defaultdict(
                lambda: dummy,
                dict((event, getattr(listener, attr)) for event, attr in source_dict.items()))

        basic_dispatch = create_dispatch_dictionary(basic)
        sharp_dispatch = create_dispatch_dictionary(sharp)
        percent_dispatch = create_dispatch_dictionary(percent)
        escape_dispatch = create_dispatch_dictionary(escape)
        csi_dispatch = create_dispatch_dictionary(csi)

        while True:
            char = yield True  # (`True` tells the 'send()' function that it
                               # is allowed to send chunks of plain text
                               # directly to the listener, instead of this generator.)

            if char == ESC:  # \x1b
                char = yield

                if char == '[':
                    char = CSI  # Go to CSI.
                else:
                    if char == '#':
                        sharp_dispatch[(yield)]()
                    elif char == '%':
                        percent_dispatch[(yield)]()
                    elif char in '()':
                        listener.set_charset((yield), mode=char)
                    elif char == ']':
                        data = []
                        while True:
                            c = yield
                            if c == '\07':
                                break
                            else:
                                data.append(c)
                        listener.square_close(''.join(data))
                    else:
                        escape_dispatch[char]()
                    continue  # Do not go to CSI.

            if char in basic:  # 'if', not 'elif', because we need to be
                               # able to jump here from Esc[ above in the CSI
                               # section below.
                basic_dispatch[char]()

            elif char == CSI:  # \x9b
                current = ''
                params = []
                private = False

                while True:
                    char = yield
                    if char == '?':
                        private = True
                    elif char in CTRL_SEQUENCES_ALLOWED_IN_CSI:
                        basic_dispatch[char]()
                    elif char in (ctrl.SP, '>'):
                        # Ignore '>' because of 'ESC[>c' (Send device attributes.)
                        pass
                    elif char.isdigit():
                        current += char
                    else:
                        params.append(min(int(current or 0), 9999))

                        if char == ';':
                            current = ''
                        else:
                            try:
                                if private:
                                    csi_dispatch[char](*params, private=True)
                                else:
                                    csi_dispatch[char](*params)
                            except TypeError:
                                # Handler doesn't take params or private attribute.
                                # (Not the cleanest way to handle this, but
                                # it's safe and performant enough.)
                                logger.warning('Dispatch %s failed. params=%s, private=%s',
                                               params, private)
                            break  # Break outside CSI loop.
