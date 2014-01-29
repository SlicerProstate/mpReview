
class pqWidget(object):
  """
  A "QWidget"-like widget class that manages provides some
  helper functionality (signals, slots...)
  """
  def __init__(self):
    self.connections = {} # list of slots per signal

  def connect(self,signal,slot):
    """pseudo-connect - signal is arbitrary string and slot if callable"""
    if not self.connections.has_key(signal):
      self.connections[signal] = []
    self.connections[signal].append(slot)

  def disconnect(self,signal,slot):
    """pseudo-disconnect - remove the connection if it exists"""
    if self.connections.has_key(signal):
      if slot in self.connections[signal]:
        self.connections[signal].remove(slot)

  def emit(self,signal,args):
    """pseudo-emit - calls any slots connected to signal"""
    if self.connections.has_key(signal):
      for slot in self.connections[signal]:
        slot(*args)

