"""
Improvements on Pyte.
"""
from __future__ import unicode_literals
from pyte.streams import Stream
from pyte.escape import NEL
from pyte import control as ctrl
from collections import defaultdict

from .log import logger

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

        # Start parser.
        self._parser = self._parser_generator()
        self._parser.send(None)
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
        """
        # Send all input to the parser coroutine.
        send = self._send

        for c in chars:
            send(c)

        # Call the '__after__' function, which is used to update the screen
        # height.
        self.listener.__after__(self)

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
        draw = listener.draw

        # In order to avoid getting KeyError exceptions below, we make sure that
        # these dictionaries resolve to 'Screen.dummy'
        basic = defaultdict(lambda: 'dummy', self.basic)
        escape = defaultdict(lambda: 'dummy', self.escape)
        sharp = defaultdict(lambda: 'dummy', self.sharp)
        percent = defaultdict(lambda: 'dummy', self.percent)
        csi = defaultdict(lambda: 'dummy', self.csi)

        ESC = ctrl.ESC
        CSI = ctrl.CSI
        CTRL_SEQUENCES_ALLOWED_IN_CSI = set([
            ctrl.BEL, ctrl.BS, ctrl.HT, ctrl.LF, ctrl.VT, ctrl.FF, ctrl.CR])
        NOT_DRAW = set([ESC, CSI, ctrl.NUL, ctrl.DEL]) | set(basic)

        def dispatch(event, *args, **flags):
            getattr(listener, event)(*args, **flags)

        while True:
            char = yield

            # Handle normal draw operations first. (All overhead here is the
            # most expensive.)
            while char not in NOT_DRAW:
                draw(char)
                char = yield

            if char == ESC:  # \x1b
                char = yield

                if char == '[':
                    char = CSI  # Go to CSI.
                else:
                    if char == '#':
                        dispatch(sharp[(yield)])
                    elif char == '%':
                        dispatch(percent[(yield)])
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
                        dispatch(escape[char])
                    continue  # Do not go to CSI.

            if char in basic:  # 'if', not 'elif', because we need to be
                               # able to jump here from Esc[ above in the CSI
                               # section below.
                dispatch(basic[char])

            elif char == CSI:  # \x9b
                current = ''
                params = []
                private = False

                while True:
                    char = yield
                    if char == '?':
                        private = True
                    elif char in CTRL_SEQUENCES_ALLOWED_IN_CSI:
                        dispatch(basic[char])
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
                                    dispatch(csi[char], *params, private=True)
                                else:
                                    dispatch(csi[char], *params)
                            except TypeError:
                                # Handler doesn't take params or private attribute.
                                # (Not the cleanest way to handle this, but
                                # it's safe and performant enough.)
                                logger.warning('Dispatch %s failed. params=%s, private=%s',
                                               params, private)
                            break  # Break outside CSI loop.
