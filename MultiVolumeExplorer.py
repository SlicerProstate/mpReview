import string, math
import slicer
from vtk import VTK_MAJOR_VERSION, vtkChart, vtkTable, vtkAxis, vtkFloatArray, vtkImageExtractComponents
from ctk import ctkSliderWidget, ctkVTKChartView
from qt import QWidget, QFormLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel, QCheckBox, QTimer, QSizePolicy, QVBoxLayout


class MultiVolumeExplorer(object):

  EVENTS = ["MouseMoveEvent", "EnterEvent", "LeaveEvent"]

  @staticmethod
  def SetBgFgVolumes(bg, fg):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetReferenceActiveVolumeID(bg)
    selectionNode.SetReferenceSecondaryVolumeID(fg)
    appLogic.PropagateVolumeSelection()

  def __init__(self, parent):
    self.parent = parent
    self.__mvNode = None

  def setup(self, parent=None):

    w = QWidget()
    self.layout = QFormLayout()
    w.setLayout(self.layout)
    parent.addRow(w)
    w.show()

    self.playButton = QPushButton('Play')
    self.playButton.toolTip = 'Iterate over multivolume frames'
    self.playButton.checkable = True

    self.__mdSlider = ctkSliderWidget()

    self.styleObserverTags = []
    self.sliceWidgetsPerStyle = {}
    self.refreshObservers()

    self.xLogScaleCheckBox = QCheckBox()
    self.xLogScaleCheckBox.setChecked(0)

    self.yLogScaleCheckBox = QCheckBox()
    self.yLogScaleCheckBox.setChecked(0)

    self.createMultiVolumeSelector()
    hbox = QHBoxLayout()
    hbox.addWidget(QLabel('Input MultiVolume'))
    hbox.addWidget(self.__mvSelector)
    self.layout.addRow(hbox)

    hbox = QHBoxLayout()
    hbox.addWidget(self.playButton)
    b = QWidget()
    vbox = QVBoxLayout()
    b.setLayout(vbox)
    vbox.addWidget(self.xLogScaleCheckBox, 0, QSizePolicy.MinimumExpanding)
    vbox.addWidget(self.yLogScaleCheckBox, 0, QSizePolicy.MinimumExpanding)
    hbox.addWidget(b)
    b = QWidget()
    vbox = QVBoxLayout()
    b.setLayout(vbox)
    vbox.addWidget(QLabel('log scale(X axis)'))
    vbox.addWidget(QLabel('log scale(Y axis)'))
    hbox.addWidget(b)
    self.layout.addRow(hbox)

    self.setupChart(w)
    # self.layout.addRow(self.chartView)

    self.timer = QTimer()
    self.timer.setInterval(50)

    self.setupConnections()

  def setupChart(self, parent):
    self.chartView = ctkVTKChartView()
    self.__chart = self.chartView.chart()
    self.__chartTable = vtkTable()
    self.__xArray = vtkFloatArray()
    self.__yArray = vtkFloatArray()
    self.__xArray.SetName('')
    self.__yArray.SetName('signal intensity')
    self.__chartTable.AddColumn(self.__xArray)
    self.__chartTable.AddColumn(self.__yArray)
    self.chartView.show()

  def createMultiVolumeSelector(self):
    self.__mvSelector = slicer.qMRMLNodeComboBox()
    self.__mvSelector.nodeTypes = ['vtkMRMLMultiVolumeNode']
    self.__mvSelector.setMRMLScene(slicer.mrmlScene)
    self.__mvSelector.addEnabled = 0

  def setupConnections(self):
    self.timer.connect('timeout()', self.goToNext)
    self.parent.connect('mrmlSceneChanged(vtkMRMLScene*)', self.onVCMRMLSceneChanged)
    self.playButton.connect('toggled(bool)', self.onPlayButtonToggled)
    self.__mvSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onInputChanged)
    self.__mdSlider.connect('valueChanged(double)', self.onSliderChanged)
    self.xLogScaleCheckBox.connect('stateChanged(int)', self.onXLogScaleRequested)
    self.yLogScaleCheckBox.connect('stateChanged(int)', self.onYLogScaleRequested)

  def onXLogScaleRequested(self,checked):
    self.__chart.GetAxis(1).SetLogScale(checked)

  def onYLogScaleRequested(self,checked):
    self.__chart.GetAxis(0).SetLogScale(checked)

  def onSliderChanged(self, newValue):
    newValue = int(newValue)

    if self.__mvNode is not None:
      mvDisplayNode = self.__mvNode.GetDisplayNode()
      mvDisplayNode.SetFrameComponent(int(newValue))

  def onVCMRMLSceneChanged(self, mrmlScene):
    self.__mvSelector.setMRMLScene(slicer.mrmlScene)
    self.onInputChanged()

  def onInputChanged(self):
    self.__mvNode = self.__mvSelector.currentNode()

    if self.__mvNode is not None:
      self.playButton.setEnabled(True)

      self.SetBgFgVolumes(self.__mvNode.GetID(), None)

      nFrames = self.__mvNode.GetNumberOfFrames()
      self.__mdSlider.minimum = 0
      self.__mdSlider.maximum = nFrames-1

      self.__xArray.SetNumberOfTuples(nFrames)
      self.__xArray.SetNumberOfComponents(1)
      self.__xArray.Allocate(nFrames)
      self.__xArray.SetName('frame')
      self.__yArray.SetNumberOfTuples(nFrames)
      self.__yArray.SetNumberOfComponents(1)
      self.__yArray.Allocate(nFrames)
      self.__yArray.SetName('signal intensity')

      self.__chartTable = vtkTable()
      self.__chartTable.AddColumn(self.__xArray)
      self.__chartTable.AddColumn(self.__yArray)
      self.__chartTable.SetNumberOfRows(nFrames)

      multiVolumeImageData = self.__mvNode.GetImageData()
      for frameNumber in range(nFrames):
        extract = vtkImageExtractComponents()
        if VTK_MAJOR_VERSION <= 5:
          extract.SetInput(multiVolumeImageData)
        else:
          extract.SetInputData(multiVolumeImageData)
        extract.SetComponents(frameNumber)
        extract.Update()
        extract.GetOutput()

      self.__mvLabels = string.split(self.__mvNode.GetAttribute('MultiVolume.FrameLabels'),',')
      if len(self.__mvLabels) != nFrames:
        return
      for l in range(nFrames):
        self.__mvLabels[l] = float(self.__mvLabels[l])
    else:
      self.playButton.setEnabled(False)
      self.__mvLabels = []

  def onPlayButtonToggled(self, checked):
    if checked:
      self.timer.start()
      self.playButton.text = 'Stop'
    else:
      self.timer.stop()
      self.playButton.text = 'Play'

  def goToNext(self):
    currentElement = self.__mdSlider.value
    currentElement += 1
    if currentElement > self.__mdSlider.maximum:
      currentElement = 0
    self.__mdSlider.value = currentElement

  def refreshObservers(self):
    self.removeObservers()
    layoutManager = slicer.app.layoutManager()
    sliceNodeCount = slicer.mrmlScene.GetNumberOfNodesByClass('vtkMRMLSliceNode')
    for nodeIndex in xrange(sliceNodeCount):
      sliceNode = slicer.mrmlScene.GetNthNodeByClass(nodeIndex, 'vtkMRMLSliceNode')
      sliceWidget = layoutManager.sliceWidget(sliceNode.GetLayoutName())
      if sliceWidget:
        style = sliceWidget.sliceView().interactorStyle()
        self.sliceWidgetsPerStyle[style] = sliceWidget
        for event in self.EVENTS:
          tag = style.AddObserver(event, self.processEvent)
          self.styleObserverTags.append([style,tag])

  def removeObservers(self):
    for observer,tag in self.styleObserverTags:
      observer.RemoveObserver(tag)
    self.styleObserverTags = []
    self.sliceWidgetsPerStyle = {}

  def processEvent(self, observer, event):
    if self.__mvNode is None or event == 'LeaveEvent' or not self.sliceWidgetsPerStyle.has_key(observer):
      return

    mvImage = self.__mvNode.GetImageData()
    nComponents = self.__mvNode.GetNumberOfFrames()

    sliceWidget = self.sliceWidgetsPerStyle[observer]
    sliceLogic = sliceWidget.sliceLogic()
    interactor = observer.GetInteractor()
    xy = interactor.GetEventPosition()
    xyz = sliceWidget.sliceView().convertDeviceToXYZ(xy)

    bgLayer = sliceLogic.GetBackgroundLayer()

    volumeNode = bgLayer.GetVolumeNode()
    if not volumeNode or volumeNode.GetID() != self.__mvNode.GetID():
      return
    if volumeNode != self.__mvNode:
      return

    xyToIJK = bgLayer.GetXYToIJKTransform()
    ijkFloat = xyToIJK.TransformDoublePoint(xyz)
    ijk = []
    for element in ijkFloat:
      try:
        index = int(round(element))
      except ValueError:
        index = 0
      ijk.append(index)

    if not self.isExtentValid(mvImage, ijk):
      return

    # get the vector of values at IJK
    for componentNumber in range(nComponents):
      val = mvImage.GetScalarComponentAsDouble(ijk[0],ijk[1],ijk[2],componentNumber)
      if math.isnan(val):
        val = 0
      self.__chartTable.SetValue(componentNumber, 0, self.__mvLabels[componentNumber])
      self.__chartTable.SetValue(componentNumber, 1, val)

    self.__chart.RemovePlot(0)
    self.__chart.GetAxis(0).SetTitle('signal intensity')

    tag = str(self.__mvNode.GetAttribute('MultiVolume.FrameIdentifyingDICOMTagName'))
    units = str(self.__mvNode.GetAttribute('MultiVolume.FrameIdentifyingDICOMTagUnits'))
    xTitle = tag+', '+units
    self.__chart.GetAxis(1).SetTitle(xTitle)
    self.__chart.GetAxis(0).SetBehavior(vtkAxis.AUTO)

    plot = self.__chart.AddPlot(vtkChart.LINE)
    if VTK_MAJOR_VERSION <= 5:
      plot.SetInput(self.__chartTable, 0, 1)
    else:
      plot.SetInputData(self.__chartTable, 0, 1)

    if self.xLogScaleCheckBox.checkState() == 2:
      title = self.__chart.GetAxis(1).GetTitle()
      self.__chart.GetAxis(1).SetTitle('log of '+title)

    if self.yLogScaleCheckBox.checkState() == 2:
      title = self.__chart.GetAxis(0).GetTitle()
      self.__chart.GetAxis(0).SetTitle('log of '+title)

  def isExtentValid(self, mvImage, ijk):
    isValid = True
    extent = mvImage.GetExtent()
    if not (extent[0] <= ijk[0] <= extent[1] and
            extent[2] <= ijk[1] <= extent[3] and
            extent[4] <= ijk[2] <= extent[5]):
      isValid = False
    return isValid