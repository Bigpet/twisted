# -*- test-case-name: twisted.tubes.test.test_fan -*-
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""

"""

from itertools import count

from zope.interface import implementer

from .pauser import Pauser
from .itube import IDrain, IFount, IPause
from twisted.python.components import proxyForInterface
from twisted.tubes.begin import beginFlowingTo
from twisted.tubes.begin import beginFlowingFrom


@implementer(IDrain)
class _InDrain(object):
    """
    
    """

    inputType = None

    fount = None

    def __init__(self, fanIn):
        """
        
        """
        self._in = fanIn
        self._pauseBecauseNoDrain = None


    def flowingFrom(self, fount):
        """
        
        """
        beginFlowingFrom(self, fount)
        # Except the fount is having similar thoughts about us as a drain, and
        # this can only happen in one order or the other. right now siphon
        # takes care of it.
        self._checkNoDrainPause()
        return None


    def _checkNoDrainPause(self):
        """
        
        """
        pbnd = self._pauseBecauseNoDrain
        self._pauseBecauseNoDrain = None
        # Do this _before_ unpausing the old one; if it's a new fount, the
        # order doesn't matter, but if it's the old fount, then doing it in
        # this order ensures it never actually unpauses, we just hand off one
        # pause for the other.
        if self.fount is not None and self._in.fount.drain is None:
            self._pauseBecauseNoDrain = self.fount.pauseFlow()
        if pbnd is not None:
            pbnd.unpause()


    def receive(self, item):
        """
        
        """
        return self._in.fount.drain.receive(item)


    def flowStopped(self, reason):
        """
        
        """
        return self._in.fount.drain.flowStopped(reason)



@implementer(IFount)
class _InFount(object):
    """
    
    """

    outputType = None

    drain = None

    def __init__(self, fanIn):
        """
        
        """
        self._in = fanIn


    def flowTo(self, drain):
        """
        
        """
        result = beginFlowingTo(self, drain)
        for drain in self._in._drains:
            drain._checkNoDrainPause()
        return result


    def pauseFlow(self):
        """
        
        """
        subPauses = []
        for drain in self._in._drains:
            # XXX wrong because drains could be added and removed
            subPauses.append(drain.fount.pauseFlow())
        return _AggregatePause(subPauses)


    def stopFlow(self):
        """
        
        """
        for drain in self._in._drains:
            drain.fount.stopFlow()



@implementer(IPause)
class _AggregatePause(object):
    """
    
    """

    def __init__(self, subPauses):
        """
        
        """
        self._subPauses = subPauses


    def unpause(self):
        """
        
        """
        for subPause in self._subPauses:
            subPause.unpause()



class In(object):
    """
    
    """
    def __init__(self):
        """
        
        """
        self._fount = _InFount(self)
        self._drains = []
        self._subdrain = None


    @property
    def fount(self):
        """
        
        """
        return self._fount


    def newDrain(self):
        """
        
        """
        it = _InDrain(self)
        self._drains.append(it)
        return it



@implementer(IFount)
class _OutFount(object):
    """

    """
    drain = None

    outputType = None

    def __init__(self, pauser, stopper):
        """
        
        """
        self._pauser = pauser
        self._stopper = stopper


    def flowTo(self, drain):
        """
        
        """
        return beginFlowingTo(self, drain)


    def pauseFlow(self):
        """
        
        """
        return self._pauser.pause()


    def stopFlow(self):
        """
        
        """
        self._stopper(self)



@implementer(IDrain)
class _OutDrain(object):
    """
    
    """

    fount = None

    def __init__(self, founts, inputType, outputType):
        """
        
        """
        self._pause = None
        self._paused = False

        self._founts = founts

        def _actuallyPause():
            if self._paused:
                raise NotImplementedError()
            self._paused = True
            if self.fount is not None:
                self._pause = self.fount.pauseFlow()

        def _actuallyResume():
            p = self._pause
            self._pause = None
            self._paused = False
            if p is not None:
                p.unpause()

        self._pauser = Pauser(self._actuallyPause, self._actuallyResume)

        self.inputType = inputType
        self.outputType = outputType


    def flowingFrom(self, fount):
        """
        
        """
        if self._paused:
            p = self._pause
            if fount is not None:
                self._pause = fount.pauseFlow()
            else:
                self._pause = None
            if p is not None:
                p.unpause()
        self.fount = fount


    def receive(self, item):
        """
        
        """
        for fount in self._founts[:]:
            if fount.drain is not None:
                fount.drain.receive(item)


    def flowStopped(self, reason):
        """
        
        """
        for fount in self._founts[:]:
            if fount.drain is not None:
                fount.drain.flowStopped(reason)



class Out(object):
    """
    
    """
    def __init__(self, inputType=None, outputType=None):
        """
        
        """
        self._founts = []
        self._drain = _OutDrain(self._founts, inputType=inputType,
                                outputType=outputType)


    @property
    def drain(self):
        """
        
        """
        return self._drain


    def newFount(self):
        """
        
        """
        f = _OutFount(self._drain._pauser, self._founts.remove)
        self._founts.append(f)
        return f



class Thru(proxyForInterface(IDrain, "_outDrain")):
    """
    
    """

    def __init__(self, drains):
        """
        
        """
        self._in = In()
        self._out = Out()

        self._drains = list(drains)
        self._founts = list(None for drain in self._drains)
        self._outFounts = list(self._out.newFount() for drain in self._drains)
        self._inDrains = list(self._in.newDrain() for drain in self._drains)
        self._outDrain = self._out.drain


    def flowingFrom(self, fount):
        """
        
        """
        super(Thru, self).flowingFrom(fount)
        for idx, appDrain, outFount, inDrain in zip(
                count(), self._drains, self._outFounts, self._inDrains):
            appFount = outFount.flowTo(appDrain)
            if appFount is None:
                appFount = self._founts[idx]
            else:
                self._founts[idx] = appFount
            appFount.flowTo(inDrain)
        nextFount = self._in.fount

        # Literally copy/pasted from _SiphonDrain.flowingFrom.  Hmm.
        nextDrain = nextFount.drain
        if nextDrain is None:
            return nextFount
        return nextFount.flowTo(nextDrain)
