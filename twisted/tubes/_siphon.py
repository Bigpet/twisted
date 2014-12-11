# -*- test-case-name: twisted.tubes.test.test_tube.SeriesTest -*-
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Adapters for converting L{ITube} to L{IDrain} and L{IFount}.
"""

from collections import deque

from zope.interface import implementer

from .itube import IPause, IDrain, IFount, ITube
from .kit import Pauser, beginFlowingFrom, beginFlowingTo
from ._components import _registryAdapting

from twisted.python.failure import Failure
from twisted.internet.defer import Deferred

from twisted.python import log

whatever = object()
paused = object()

class DequeMetaIterable(object):
    """
    An iterable that iterates iterables by destructively traversing a mutable
    deque.
    """

    def __init__(self):
        self._deque = deque()
        self._suspended = False


    def __iter__(self):
        """
        I am my own iterator.

        @return: C{self}
        """
        return self


    def suspend(self):
        """
        Pretend to be empty until resume() is called.
        """
        self._suspended = True


    def resume(self):
        """
        
        """
        self._suspended = False


    def prepend(self, iterator):
        """
        
        """
        self._deque.appendleft(iterator)


    def append(self, iterator):
        """
        
        """
        self._deque.append(iterator)


    def clear(self):
        """
        
        """
        self._deque.clear()


    def __next__(self):
        """
        Get the next value in the leftmost iterator in the deque.
        """
        if self._suspended:
            return paused
        while self._deque:
            result = next(self._deque[0], whatever)
            if result is whatever:
                self._deque.popleft()
            else:
                return result
        raise StopIteration()

    next = __next__


class _SiphonPiece(object):
    """
    Shared functionality between L{_SiphonFount} and L{_SiphonDrain}
    """
    def __init__(self, siphon):
        self._siphon = siphon


    @property
    def _tube(self):
        """
        Expose the siphon's C{_tube} directly since many things will want to
        manipulate it.

        @return: L{ITube}
        """
        return self._siphon._tube



@implementer(IFount)
class _SiphonFount(_SiphonPiece):
    """
    Implementation of L{IFount} for L{_Siphon}.

    @ivar fount: the implementation of the L{IDrain.fount} attribute.  The
        L{IFount} which is flowing to this L{_Siphon}'s L{IDrain}
        implementation.

    @ivar drain: the implementation of the L{IFount.drain} attribute.  The
        L{IDrain} to which this L{_Siphon}'s L{IFount} implementation is
        flowing.
    """
    drain = None

    def __init__(self, siphon):
        super(_SiphonFount, self).__init__(siphon)

        def _actuallyPause():
            fount = self._siphon._tdrain.fount
            self._siphon._pending.suspend()
            if fount is None:
                return
            self._siphon._pauseBecausePauseCalled = fount.pauseFlow()

        def _actuallyResume():
            fp = self._siphon._pauseBecausePauseCalled
            self._siphon._pauseBecausePauseCalled = None

            self._siphon._pending.resume()
            self._siphon._unbufferIterator()

            # TODO: validate that the siphon's fount is always set consistently
            # with _pauseBecausePauseCalled.
            if fp is not None:
                fp.unpause()

        self._pauser = Pauser(_actuallyPause, _actuallyResume)


    def __repr__(self):
        """
        Nice string representation.
        """
        return "<Fount for {0}>".format(repr(self._siphon._tube))


    @property
    def outputType(self):
        """
        Relay the C{outputType} declared by the tube.

        @return: see L{IFount.outputType}
        """
        return self._tube.outputType


    def flowTo(self, drain):
        """
        Flow data from this L{_Siphon} to the given drain.

        @param drain: see L{IFount.flowTo}

        @return: an L{IFount} that emits items of the output-type of this
            siphon's tube.
        """
        result = beginFlowingTo(self, drain)
        if self._siphon._pauseBecauseNoDrain:
            pbnd = self._siphon._pauseBecauseNoDrain
            self._siphon._pauseBecauseNoDrain = None
            pbnd.unpause()
        self._siphon._unbufferIterator()
        return result


    def pauseFlow(self):
        """
        Pause the flow from the fount, or remember to do that when the fount is
        attached, if it isn't yet.

        @return: L{IPause}
        """
        return self._pauser.pause()


    def stopFlow(self):
        """
        Stop the flow from the fount to this L{_Siphon}, and stop delivering
        buffered items.
        """
        self._siphon._noMore(input=True, output=True)
        fount = self._siphon._tdrain.fount
        if fount is None:
            return
        fount.stopFlow()



@implementer(IPause)
class _PlaceholderPause(object):
    """
    L{IPause} provider that does nothing.
    """

    def unpause(self):
        """
        No-op.
        """



@implementer(IDrain)
class _SiphonDrain(_SiphonPiece):
    """
    Implementation of L{IDrain} for L{_Siphon}.
    """
    fount = None

    def __repr__(self):
        """
        Nice string representation.
        """
        return '<Drain for {0}>'.format(self._siphon._tube)


    @property
    def inputType(self):
        """
        Relay the tube's declared inputType.

        @return: see L{IDrain.inputType}
        """
        return self._tube.inputType


    def flowingFrom(self, fount):
        """
        This siphon will now have 'receive' called on it by the given fount.

        @param fount: see L{IDrain.flowingFrom}

        @return: see L{IDrain.flowingFrom}
        """
        beginFlowingFrom(self, fount)
        if self._siphon._pauseBecausePauseCalled:
            pbpc = self._siphon._pauseBecausePauseCalled
            self._siphon._pauseBecausePauseCalled = None
            if fount is None:
                pauseFlow = _PlaceholderPause
            else:
                pauseFlow = fount.pauseFlow
            self._siphon._pauseBecausePauseCalled = pauseFlow()
            pbpc.unpause()
        if fount is not None:
            if not self._siphon._canStillProcessInput:
                fount.stopFlow()
            # Is this the right place, or does this need to come after
            # _pauseBecausePauseCalled's check?
            if not self._siphon._everStarted:
                self._siphon._everStarted = True
                self._siphon._deliverFrom(self._tube.started)
        nextFount = self._siphon._tfount
        nextDrain = nextFount.drain
        if nextDrain is None:
            return nextFount
        return nextFount.flowTo(nextDrain)


    def receive(self, item):
        """
        An item was received.  Pass it on to the tube for processing.

        @param item: an item to deliver to the tube.
        """
        def tubeReceivedItem():
            return self._tube.received(item)
        self._siphon._deliverFrom(tubeReceivedItem)


    def flowStopped(self, reason):
        """
        This siphon's fount has communicated the end of the flow to this
        siphon.  This siphon should finish yielding its current buffer, then
        yield the result of it's C{_tube}'s C{stopped} method, then communicate
        the end of flow to its downstream drain.

        @param reason: the reason why our fount stopped the flow.
        """
        self._siphon._noMore(input=True, output=False)
        self._siphon._flowStoppingReason = reason
        def tubeStopped():
            return self._tube.stopped(reason)
        self._siphon._deliverFrom(tubeStopped)



class _Siphon(object):
    """
    A L{_Siphon} is an L{IDrain} and possibly also an L{IFount}, and provides
    lots of conveniences to make it easy to implement something that does fancy
    flow control with just a few methods.

    @ivar _tube: the L{Tube} which will receive values from this siphon and
        call C{deliver} to deliver output to it.  (When set, this will
        automatically set the C{siphon} attribute of said L{Tube} as well, as
        well as un-setting the C{siphon} attribute of the old tube.)

    @ivar _currentlyPaused: is this L{_Siphon} currently paused?  Boolean:
        C{True} if paused, C{False} if not.

    @ivar _pauseBecausePauseCalled: an L{IPause} from the upstream fount,
        present because pauseFlow has been called.

    @ivar _flowStoppingReason: If this is not C{None}, then call C{flowStopped}
        on the downstream L{IDrain} at the next opportunity, where "the next
        opportunity" is when all buffered input (values yielded from
        C{started}, C{received}, and C{stopped}) has been written to the
        downstream drain and we are unpaused.

    @ivar _everStarted: Has this L{_Siphon} ever called C{started} on its
        L{Tube}?
    @type _everStarted: L{bool}
    """

    def __init__(self, tube):
        """
        Initialize this L{_Siphon} with the given L{Tube} to control its
        behavior.
        """
        self._canStillProcessInput = True
        self._pauseBecausePauseCalled = None
        self._tube = None
        self._everStarted = False
        self._unbuffering = False
        self._flowStoppingReason = None
        self._pauseBecauseNoDrain = None

        self._tfount = _SiphonFount(self)
        self._tdrain = _SiphonDrain(self)
        self._tube = tube
        self._pending = DequeMetaIterable()


    def _noMore(self, input, output):
        """
        I am now unable to produce further input, or output, or both.

        @param input: L{True} if I can no longer produce input.

        @param output: L{True} if I can no longer produce output.
        """
        if input:
            self._canStillProcessInput = False
        if output:
            self._pending.clear()


    def __repr__(self):
        """
        Nice string representation.
        """
        return '<_Siphon for {0}>'.format(repr(self._tube))


    def _deliverFrom(self, deliverySource):
        """
        Deliver some items from a callable that will produce an iterator.

        @param deliverySource: a 0-argument callable that will return an
            iterable.
        """
        try:
            iterableOrNot = deliverySource()
        except:
            f = Failure()
            log.err(f, "Exception raised when delivering from {0!r}"
                    .format(deliverySource))
            self._tdrain.fount.stopFlow()
            downstream = self._tfount.drain
            if downstream is not None:
                downstream.flowStopped(f)
            return
        if iterableOrNot is None:
            return
        self._pending.append(iter(iterableOrNot))
        if self._tfount.drain is None:
            if self._pauseBecauseNoDrain is None:
                self._pauseBecauseNoDrain = self._tfount.pauseFlow()

        self._unbufferIterator()


    def _unbufferIterator(self):
        """
        Un-buffer some items buffered in C{self._pending} and actually deliver
        them, as long as we're not paused.
        """
        if self._unbuffering:
            return

        self._unbuffering = True

        for value in self._pending:
            if value is paused:
                break
            if isinstance(value, Deferred):
                (value
                 .addCallback(self._whenUnclogged,
                              somePause=self._tfount.pauseFlow())
                 .addErrback(log.err, "WHAT"))
            else:
                self._tfount.drain.receive(value)
        else:
            if self._flowStoppingReason:
                self._endOfLine(self._flowStoppingReason)

        self._unbuffering = False


    def _whenUnclogged(self, result, somePause):
        """
        When a Deferred fires with a result, this inserts the result of that
        Deferred into the head of the delivery queue and unpauses the pause
        associated that Deferred.

        @param result: The result to pass along.

        @param somePause: The pause to un-pause.
        """
        self._pending.prepend(iter([result]))
        somePause.unpause()


    def _endOfLine(self, flowStoppingReason):
        """
        We've reached the end of the line.  Immediately stop delivering all
        buffers and notify our downstream drain why the flow has stopped.
        """
        self._noMore(input=True, output=True)
        self._flowStoppingReason = None
        self._pending.clear()
        downstream = self._tfount.drain
        if downstream is not None:
            self._tfount.drain.flowStopped(flowStoppingReason)



def _tube2drain(tube):
    """
    An adapter that can convert an L{ITube} to an L{IDrain} by wrapping it in a
    L{_Siphon}.

    @param tube: L{ITube}

    @return: L{IDrain}
    """
    return _Siphon(tube)._tdrain



_tubeRegistry = _registryAdapting(
    (ITube, IDrain, _tube2drain),
)



