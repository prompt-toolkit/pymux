"""
Improvements on Pyte.
"""
from __future__ import unicode_literals
from pyte.streams import Stream
from pyte.escape import NEL
from pyte import ctrl
from collections import defaultdict

__all__ = (
    'BetterStream',
)


class BetterStream(Stream):
    """
    Extension to the Pyte `Stream` class that also handles "Esc]<num>...BEL"
    sequences. This is used by xterm to set the terminal title.
    """
    csi = {
        'n': 'cpr',  # Cursor position request.
        'c': 'send_device_attributes',  # csi > Ps c
    }
    csi.update(Stream.csi)

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

        # Start parser.
        self._parser = self._parser_generator()
        self._parser.send(None)

    def feed(self, chars):  # TODO: Handle exceptions.
        """
        Custom, much more efficient 'feed' function.
        """
        # Send all input to the parser coroutine.
        send = self._parser.send

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
        NUL_OR_DEL = (ctrl.NUL, ctrl.DEL)
        CTRL_SEQUENCES_ALLOWED_IN_CSI = (
            ctrl.BEL, ctrl.BS, ctrl.HT, ctrl.LF, ctrl.VT, ctrl.FF, ctrl.CR)

        def dispatch(event, *args, **flags):
            getattr(listener, event)(*args, **flags)

        while True:
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
                            if private:
                                dispatch(csi[char], *params, private=True)
                            else:
                                dispatch(csi[char], *params)
                            break  # Break outside CSI loop.

            elif char not in NUL_OR_DEL:
                draw(char)
