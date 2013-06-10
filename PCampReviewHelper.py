import string, qt, slicer

class PCampReviewHelper(object):
  @staticmethod
  def isSeriesOfInterest(desc):
    discardThose = ['SAG','COR','PURE','mapping','DWI','breath','3D DCE','loc','Expo','Map','MAP','POST']
    for d in discardThose:
      if string.find(desc,d)>=0:
        return False
    return True

  @staticmethod
  def abbreviateNames(longNames, fullMatch):
    shortNames = []
    firstADC = True
    for name in longNames:
      print(str(shortNames))
      if name in fullMatch:
        shortNames.append(name)
      elif string.find(name,'T2')>0:
        shortNames.append('T2')
      elif string.find(name,'T1')>0:
        shortNames.append('T1')
      elif string.find(name,'Apparent Diffusion Coefficient')>0:
        if firstADC:
          shortNames.append('ADCb500')
          firstADC = False
        else:
          shortNames.append('ADCb1400')
      else:
        shortNames.append('Subtract')
    return shortNames

  @staticmethod
  def setOffsetOnAllSliceWidgets(offset):
    layoutManager = slicer.app.layoutManager()
    widgetNames = layoutManager.sliceViewNames()
    for wn in widgetNames:
      widget = layoutManager.sliceWidget(wn)
      node = widget.mrmlSliceNode()
      node.SetSliceOffset(offset)

      sc = widget.mrmlSliceCompositeNode()
      sc.SetLinkedControl(1)
      sc.SetInteractionFlagsModifier(4+8+16)

  @staticmethod
  def setOpacityOnAllSliceWidgets(opacity):
    layoutManager = slicer.app.layoutManager()
    widgetNames = layoutManager.sliceViewNames()
    for wn in widgetNames:
      widget = layoutManager.sliceWidget(wn)
      sc = widget.mrmlSliceCompositeNode()
      sc.SetForegroundOpacity(opacity)
