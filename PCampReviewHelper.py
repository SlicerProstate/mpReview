import string, qt, slicer, re

customLUT = ["0 background 0 0 0 0",\
"1 Tumor1 128 174 128 255",\
"2 Tumor2 241 214 145 255",\
"3 Tumor3 177 122 101 255",\
"4 Tumor4 111 184 210 255",\
"5 Tumor5 216 101 79 255",\
"6 Tumor6 221 130 101 255",\
"7 Tumor7 144 238 144 255",\
"8 Tumor8 192 104 88 255",\
"9 Tumor9 220 245 20 255",\
"10 Tumor10 78 63 0 255",\
"11 Normal1 255 250 220 255",\
"12 Normal2 230 220 70 255",\
"13 Normal3 200 200 235 255",\
"14 Normal4 250 250 210 255",\
"15 Normal5 244 214 49 255",\
"16 Normal6 0 151 206 255",\
"17 Normal7 216 101 79 255",\
"18 Normal8 183 156 220 255",\
"19 Normal9 183 214 211 255",\
"20 Normal10 152 189 207 255"]

class PCampReviewHelper(object):
  @staticmethod
  def isSeriesOfInterest(desc):
    discardThose = ['SAG','COR','PURE','mapping','DWI','breath','3D DCE','loc','Expo','Map','MAP','POST','ThreeParameter','AutoAIF','BAT','-Slope','PkRsqr']
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
  def abbreviateName(meta):
    try:
      descr = meta['SeriesDescription']
      seriesNumber = meta['SeriesNumber']
    except:
      descr = meta['DerivedSeriesDescription']
      seriesNumber = meta['DerivedSeriesNumber']
    abbr = 'Unknown'
    if descr.find('Apparent Diffusion Coeff')>=0:
      abbr = 'ADC'
    if descr.find('T2')>=0:
      abbr = 'T2'
    if descr.find('T1')>=0:
      abbr = 'T1'
    if descr.find('Ktrans')>=0:
      abbr = 'Ktrans'
    if descr.find('Ve')>=0:
      abbr = 've'
    if descr.find('MaxSlope')>=0:
      abbr = 'MaxSlope'
    if descr.find('TTP')>=0:
      abbr = 'TTP'
    if descr.find('Auc')>=0:
      abbr = 'AUC'
    if re.search('[a-zA-Z]',descr) == None:
      abbr = 'Subtract'
    return seriesNumber+'-'+abbr

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

  @staticmethod
  def infoPopup(message):
    messageBox = qt.QMessageBox()
    messageBox.information(None, 'Slicer mpMRI review', message)


  @staticmethod
  def addCustomLUTToScene():
    clut = slicer.vtkMRMLColorTableNode()
    clut.SetType(slicer.vtkMRMLColorTableNode.User)
    clut.SetSaveWithScene(False)
    clut.SetNumberOfColors(21)
    clut.GetLookupTable().SetTableRange(0,21)
    
    for item in customLUT:
      items = item.split(' ')
      clut.SetColor(int(items[0]),items[1],int(items[2]),int(items[3]),int(items[4]),int(items[5]))

    clut.SetName('PCampReviewColorLUT')
    clut.SetScene(slicer.mrmlScene)
    slicer.mrmlScene.AddNode(clut)

    return clut

  @staticmethod
  def saveCustomLUTToFile(fileName):
    
    f = open(fileName,'w')
    for item in customLUT:
      items = item.split(' ')
      f.write(item+'\n')

    f.close()
