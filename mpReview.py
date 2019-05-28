from __future__ import division
import os, json, xml.dom.minidom, string, glob, re, math
import vtk, qt, ctk, slicer
import logging
import CompareVolumes
from Editor import EditorWidget
from EditorLib import EditorLib
import SimpleITK as sitk
import sitkUtils
import datetime
from slicer.ScriptedLoadableModule import *

from mpReviewPreprocessor import mpReviewPreprocessorLogic

from qSlicerMultiVolumeExplorerModuleWidget import qSlicerMultiVolumeExplorerSimplifiedModuleWidget
from qSlicerMultiVolumeExplorerModuleHelper import qSlicerMultiVolumeExplorerModuleHelper as MVHelper

from SlicerDevelopmentToolboxUtils.mixins import ModuleWidgetMixin, ModuleLogicMixin
from SlicerDevelopmentToolboxUtils.helpers import WatchBoxAttribute
from SlicerDevelopmentToolboxUtils.widgets import TargetCreationWidget, XMLBasedInformationWatchBox
from SlicerDevelopmentToolboxUtils.icons import Icons


class mpReview(ScriptedLoadableModule, ModuleWidgetMixin):

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "mpReview"
    parent.categories = ["Informatics"]
    parent.dependencies = ["SlicerDevelopmentToolbox"]
    parent.contributors = ["Andrey Fedorov (SPL)", "Robin Weiss (U. of Chicago)", "Alireza Mehrtash (SPL)",
                           "Christian Herz (SPL)"]
    parent.helpText = """
    Multiparametric Image Review (mpReview) module is intended to support review and annotation of multiparametric
    image data. The driving use case for the development of this module was review and segmentation of the regions of
    interest in prostate cancer multiparametric MRI.
    """
    parent.acknowledgementText = """
    Supported by NIH U24 CA180918 (PIs Fedorov & Kikinis) and U01CA151261 (PI Fennessy)
    """ # replace with organization, grant and thanks.
    self.parent = parent

    # Add this test to the SelfTest module's list for discovery when the module
    # is created.  Since this module may be discovered before SelfTests itself,
    # create the list if it doesn't already exist.
    try:
      slicer.selfTests
    except AttributeError:
      slicer.selfTests = {}

  def runTest(self):
    return


class mpReviewWidget(ScriptedLoadableModuleWidget, ModuleWidgetMixin):

  PIRADS_VIEWFORM_URL = 'https://docs.google.com/forms/d/1Xwhvjn_HjRJAtgV5VruLCDJ_eyj1C-txi8HWn8VyXa4/viewform'
  QA_VIEWFORM_URL = 'https://docs.google.com/forms/d/18Ni2rcooi60fev5mWshJA0yaCzHYvmXPhcG2-jMF-uw/viewform'

  @property
  def inputDataDir(self):
    return self.dataDirButton.directory

  @inputDataDir.setter
  def inputDataDir(self, directory):
    logging.debug('Directory selected: %s' % directory)
    if not os.path.exists(directory):
      directory = None
      self.dataDirButton.text = "Choose data directory"
      truncatedPath = None
    else:
      truncatedPath = ModuleLogicMixin.truncatePath(directory)
      self.dataDirButton.text = truncatedPath
      self.dataDirButton.caption = directory
      self.setSetting('InputLocation', directory)
      self.checkAndSetLUT()
      self.updateStudyTable()
    self.informationWatchBox.setInformation("CurrentDataDir", truncatedPath, toolTip=directory)

  def __init__(self, parent = None):
    ScriptedLoadableModuleWidget.__init__(self, parent)
    self.resourcesPath = os.path.join(slicer.modules.mpreview.path.replace(self.moduleName+".py",""), 'Resources')
    self.qaFormURL = ''
    self.piradsFormURL = ''

    # TODO: figure out why module/class hierarchy is different
    # between developer builds ans packages
    try:
      # for developer build...
      self.editUtil = EditorLib.EditUtil.EditUtil()
    except AttributeError:
      # for release package...
      self.editUtil = EditorLib.EditUtil()
    # mrml node for invoking command line modules
    self.CLINode = None
    self.logic = mpReviewLogic()
    self.multiVolumeExplorer = None

    # set up temporary directory
    self.tempDir = os.path.join(slicer.app.temporaryPath, 'mpReview-tmp')
    self.logic.createDirectory(self.tempDir, message='Temporary directory location: ' + self.tempDir)
    self.fiducialLabelPropagateModel = None
    self.modulePath = os.path.dirname(slicer.util.modulePath(self.moduleName))

  def getAllSliceWidgets(self):
    widgetNames = self.layoutManager.sliceViewNames()
    return [self.layoutManager.sliceWidget(wn) for wn in widgetNames]

  def setOffsetOnAllSliceWidgets(self, offset):
    for widget in self.getAllSliceWidgets():
      node = widget.mrmlSliceNode()
      node.SetSliceOffset(offset)

  def linkAllSliceWidgets(self, link):
    for widget in self.getAllSliceWidgets():
      sc = widget.mrmlSliceCompositeNode()
      sc.SetLinkedControl(link)
      sc.SetInteractionFlagsModifier(4+8+16)

  def setOpacityOnAllSliceWidgets(self, opacity):
    for widget in self.getAllSliceWidgets():
      sc = widget.mrmlSliceCompositeNode()
      sc.SetForegroundOpacity(opacity)

  def updateViewRenderer (self):
    for widget in self.getAllSliceWidgets():
      view = widget.sliceView()
      view.scheduleRender()

  def setupIcons(self):
    self.studySelectionIcon = self.createIcon('icon-studyselection_fit.png')
    self.segmentationIcon = self.createIcon('icon-segmentation_fit.png')
    self.completionIcon = self.createIcon('icon-completion_fit.png')

  def setupTabBarNavigation(self):
    self.tabWidget = qt.QTabWidget()
    self.layout.addWidget(self.tabWidget)

    self.studyAndSeriesSelectionWidget = qt.QWidget()
    self.segmentationWidget = qt.QWidget()
    self.completionWidget = qt.QWidget()

    self.studyAndSeriesSelectionWidgetLayout = qt.QGridLayout()
    self.segmentationWidgetLayout = qt.QVBoxLayout()
    self.completionWidgetLayout = qt.QFormLayout()

    self.studyAndSeriesSelectionWidget.setLayout(self.studyAndSeriesSelectionWidgetLayout)
    self.segmentationWidget.setLayout(self.segmentationWidgetLayout)
    self.completionWidget.setLayout(self.completionWidgetLayout)

    self.tabWidget.setIconSize(qt.QSize(85, 30))

    self.tabWidget.addTab(self.studyAndSeriesSelectionWidget, self.studySelectionIcon, '')
    self.tabWidget.addTab(self.segmentationWidget, self.segmentationIcon, '')
    self.tabWidget.addTab(self.completionWidget, self.completionIcon, '')

    self.setTabsEnabled([1,2], False)

  def onTabWidgetClicked(self, currentIndex):
    if self.currentTabIndex == currentIndex:
      return
    setNewIndex = False
    if currentIndex == 0:
      setNewIndex = self.onStep1Selected()
    if currentIndex == 1:
      setNewIndex = self.onStep2Selected()
    if currentIndex == 2:
      setNewIndex = self.onStep3Selected()
    if setNewIndex:
      self.currentTabIndex = currentIndex

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    self.setupIcons()
    self.setupInformationFrame()
    self.setupTabBarNavigation()

    self.parameters = {}

    self.crosshairNode = slicer.mrmlScene.GetNthNodeByClass(0, 'vtkMRMLCrosshairNode')

    self.setupDataAndStudySelectionUI()
    self.setupSeriesSelectionView()
    self.setupSegmentationToolsUI()
    self.setupCompletionUI()
    self.setupConnections()
    # self.layout.addStretch(1)

    self.volumesLogic = slicer.modules.volumes.logic()

    # these are the PK maps that should be loaded
    self.pkMaps = ['Ktrans','Ve','Auc','TTP','MaxSlope']
    self.volumeNodes = {}
    self.refSelectorIgnoreUpdates = False
    self.selectedStudyName = None

    self.dataDirButton.directory = self.getSetting('InputLocation')
    self.currentTabIndex = 0

  def setupInformationFrame(self):

    watchBoxInformation = [WatchBoxAttribute('StudyID', 'Study ID:'),
                           WatchBoxAttribute('PatientName', 'Name:', 'PatientName'),
                           WatchBoxAttribute('StudyDate', 'Study Date:', 'StudyDate'),
                           WatchBoxAttribute('PatientID', 'PID:', 'PatientID'),
                           WatchBoxAttribute('CurrentDataDir', 'Current Data Dir:'),
                           WatchBoxAttribute('PatientBirthDate', 'DOB:', 'PatientBirthDate')]

    self.informationWatchBox = XMLBasedInformationWatchBox(watchBoxInformation, columns=2)

    self.layout.addWidget(self.informationWatchBox)

  def setupDataAndStudySelectionUI(self):
    self.dataDirButton = ctk.ctkDirectoryButton()
    self.studyAndSeriesSelectionWidgetLayout.addWidget(qt.QLabel("Data directory:"), 0, 0, 1, 1)
    self.studyAndSeriesSelectionWidgetLayout.addWidget(self.dataDirButton, 0, 1, 1, 2)

    self.customLUTInfoIcon = self.createHelperLabel()
    self.studyAndSeriesSelectionWidgetLayout.addWidget(self.customLUTInfoIcon, 0, 2, 1, 1, qt.Qt.AlignRight)
    self.customLUTInfoIcon.hide()
    self.setupStudySelectionView()

  def createHelperLabel(self, toolTipText=""):
    label = self.createLabel("", pixmap=Icons.info.pixmap(qt.QSize(23, 20)), toolTip=toolTipText)
    label.setCursor(qt.Qt.PointingHandCursor)
    return label

  def setupStudySelectionView(self):
    self.studiesGroupBox = ctk.ctkCollapsibleGroupBox()
    self.studiesGroupBox.title = "Studies"
    studiesGroupBoxLayout = qt.QGridLayout()
    self.studiesGroupBox.setLayout(studiesGroupBoxLayout)
    self.studiesView, self.studiesModel = self.createListView('StudiesTable', ['Study ID'])
    self.studiesView.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
    studiesGroupBoxLayout.addWidget(self.studiesView)
    self.studyAndSeriesSelectionWidgetLayout.addWidget(self.studiesGroupBox, 2, 0, 1, 3)

  def setupSeriesSelectionView(self):
    self.seriesGroupBox = qt.QGroupBox("Series")
    seriesGroupBoxLayout = qt.QGridLayout()
    self.seriesGroupBox.setLayout(seriesGroupBoxLayout)
    self.seriesView, self.seriesModel = self.createListView('SeriesTable', ['Series ID'])
    self.seriesView.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
    self.selectAllSeriesButton = self.createButton('Select All')
    self.deselectAllSeriesButton = self.createButton('Deselect All')
    self.selectAllSeriesButton.setEnabled(False)
    self.deselectAllSeriesButton.setEnabled(False)
    seriesGroupBoxLayout.addWidget(self.seriesView, 0, 0, 1, 2)
    seriesGroupBoxLayout.addWidget(self.createHLayout([self.selectAllSeriesButton,  self.deselectAllSeriesButton]),
                                   1, 0, 1, 2)
    self.studyAndSeriesSelectionWidgetLayout.addWidget(self.seriesGroupBox, 3, 0, 1, 3)

  def setupSegmentationToolsUI(self):
    self.refSelector = qt.QComboBox()
    self.segmentationWidgetLayout.addWidget(self.createHLayout([qt.QLabel("Reference image: "), self.refSelector]))
    self.setupMultiVolumeExplorerUI()
    self.setupLabelMapEditorUI()
    self.setupAdvancedSegmentationSettingsUI()
    self.setupFiducialsUI()
    # keep here names of the views created by CompareVolumes logic
    self.viewNames = []
    self.segmentationWidgetLayout.addStretch(1)

  def setupMultiVolumeExplorerUI(self):
    self.multiVolumeExplorerArea = ctk.ctkCollapsibleButton()
    self.multiVolumeExplorerArea.text = "MultiVolumeExplorer"
    self.multiVolumeExplorerArea.collapsed = True
    self.multiVolumeExplorer = mpReviewMultiVolumeExplorer(qt.QFormLayout(self.multiVolumeExplorerArea))
    self.multiVolumeExplorer.setup()
    self.segmentationWidgetLayout.addWidget(self.multiVolumeExplorerArea)

  def setupLabelMapEditorUI(self):
    self.setupEditorWidget()

    self.structuresView = slicer.util.findChildren(self.editorWidget.volumes, 'StructuresView')[0]

    self.editorParameterNode = EditorLib.EditUtil.EditUtil.getParameterNode()
    self.editorParameterNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.onEditorWidgetParameterNodeChanged)

    self.addCustomEditorButtons()
    self.editorWidget.toolsColor.colorSpin.setEnabled(False)
    self.editorWidget.toolsColor.colorPatch.setEnabled(False)

    self.editorParameterNode = self.editUtil.getParameterNode()
    self.editorParameterNode.SetParameter('propagationMode', str(slicer.vtkMRMLApplicationLogic.LabelLayer))
    self.modelsVisibility = True

    self.buildModelsButton = qt.QPushButton('Make')
    self.modelsVisibilityButton = self.createButton('Hide', checkable=True)
    self.labelMapVisibilityButton = self.createButton('Hide', checkable=True)
    self.labelMapOutlineButton = self.createButton('Outline', checkable=True)
    self.enableJumpToROI = qt.QCheckBox("Jump to ROI")
    self.enableJumpToROI.checked = True
    editorControls = self.getEditorControls()
    modelsFrame = self.createHLayout([qt.QLabel('Structure Models: '), self.buildModelsButton,
                                      self.modelsVisibilityButton, self.labelMapVisibilityButton,
                                      self.labelMapOutlineButton, self.enableJumpToROI])
    self.buildModelsButton.hide()
    self.modelsVisibilityButton.hide()

    perStructureFrame = slicer.util.findChildren(self.editorWidget.volumes, 'PerStructureVolumesFrame')[0]
    perStructureFrame.collapsed = False
    perStructureFrame.layout().addWidget(editorControls)
    perStructureFrame.layout().addWidget(modelsFrame)

  def setupEditorWidget(self):
    editorWidgetParent = slicer.qMRMLWidget()
    editorWidgetParent.setLayout(qt.QVBoxLayout())
    editorWidgetParent.setMRMLScene(slicer.mrmlScene)
    self.editorWidget = EditorWidget(parent=editorWidgetParent)
    self.editorWidget.setup()
    try:
      self.editorWidget.segmentEditorLabel.hide()
      self.editorWidget.infoIconLabel.hide()
    except AttributeError:
      pass
    self.segmentationWidgetLayout.addWidget(editorWidgetParent)
    self.hideUnwantedEditorUIElements()

  def hideUnwantedEditorUIElements(self):
    toHide = {}
    toHide[self.editorWidget.volumes] = ['AllButtonsFrameButton', 'ReplaceModelsCheckBox', 'MasterVolumeFrame',
                                         'MergeVolumeFrame', 'SplitStructureButton']
    toHide[self.editorWidget.editBoxFrame] = ['WandEffectToolButton', 'LevelTracingEffectToolButton',
                                              'RectangleEffectToolButton', 'IdentifyIslandsEffectToolButton',
                                              'ChangeIslandEffectToolButton', 'RemoveIslandsEffectToolButton',
                                              'SaveIslandEffectToolButton', 'RowFrame4', 'RowFrame3', 'RowFrame2',
                                              'RowFrame1']
    for widget, o in toHide.iteritems():
      for objectName in o:
        try:
          slicer.util.findChildren(widget, objectName)[0].hide()
        except AttributeError:
          continue

  def getEditorControls(self):
    editBoxFrame = self.editorWidget.editBoxFrame
    effectButtonFrame = slicer.util.findChildren(editBoxFrame, 'RowFrame1')[0]
    buttons = [c for c in effectButtonFrame.children() if isinstance(c, qt.QToolButton)]
    buttons.append(slicer.util.findChildren(editBoxFrame, 'DilateEffectToolButton')[0])
    undoButton = slicer.util.findChildren(editBoxFrame, 'PreviousCheckPointToolButton')[0]
    redoButton = slicer.util.findChildren(editBoxFrame, 'NextCheckPointToolButton')[0]

    undoRedo = self.createHLayout([qt.QLabel("Undo/Redo:"), undoButton, redoButton])
    undoRedo.layout().setAlignment(qt.Qt.AlignLeft)

    effectButtons = self.createHLayout(buttons)
    effectButtons.layout().setAlignment(qt.Qt.AlignRight)

    hbox = self.createHLayout([undoRedo, effectButtons])
    return hbox

  def addCustomEditorButtons(self):
    volumesFrame = self.editorWidget.volumes
    buttonsFrame = slicer.util.findChildren(volumesFrame, 'ButtonsFrame')[0]

    buttonsFrameLayout = buttonsFrame.layout()

    redWidget = self.layoutManager.sliceWidget('Red')
    controller = redWidget.sliceController()
    moreButton = slicer.util.findChildren(controller, 'MoreButton')[0]
    moreButton.toggle()

    self.deleteStructureButton = qt.QPushButton('Delete')
    self.propagateButton = qt.QPushButton('Propagate')
    self.createFiducialsButton = qt.QPushButton('Create Fiducials')

    buttonsFrameLayout.addWidget(self.deleteStructureButton)
    buttonsFrameLayout.addWidget(self.propagateButton)
    buttonsFrameLayout.addWidget(self.createFiducialsButton)
    self.propagateButton.hide()

  def setupAdvancedSegmentationSettingsUI(self):
    self.advancedSettingsArea = ctk.ctkCollapsibleButton()
    self.advancedSettingsArea.text = "Advanced Settings"
    self.advancedSettingsArea.collapsed = True

    self.setupSingleMultiViewSettingsUI()
    self.setupViewerOrientationSettingsUI()
    self.setupLabelTranslationSettingsUI()

    self.ignoreTranslate = False

    # Create a transform node
    self.transformNode = slicer.vtkMRMLLinearTransformNode()
    self.transformNode.SetName('mpReview-transform')
    slicer.mrmlScene.AddNode(self.transformNode)

    advancedSettingsLayout = qt.QFormLayout(self.advancedSettingsArea)
    advancedSettingsLayout.addRow("Show series: ", self.groupWidget)
    advancedSettingsLayout.addRow('View orientation: ', self.orientationBox)
    advancedSettingsLayout.addRow(self.translateArea)
    self.segmentationWidgetLayout.addWidget(self.advancedSettingsArea)

  def setupSingleMultiViewSettingsUI(self):
    self.multiView = qt.QRadioButton('All')
    self.singleView = qt.QRadioButton('Reference only')
    self.multiView.setChecked(True)
    self.groupWidget = qt.QGroupBox()
    self.groupLayout = qt.QFormLayout(self.groupWidget)
    self.groupLayout.addRow(self.multiView, self.singleView)
    self.viewButtonGroup = qt.QButtonGroup()
    self.viewButtonGroup.addButton(self.multiView, 1)
    self.viewButtonGroup.addButton(self.singleView, 2)

  def setupViewerOrientationSettingsUI(self):
    self.orientationBox = qt.QGroupBox()
    orientationBoxLayout = qt.QFormLayout()
    self.orientationBox.setLayout(orientationBoxLayout)
    self.orientationButtons = {}
    self.orientations = ("Axial", "Sagittal", "Coronal")
    for orientation in self.orientations:
      self.orientationButtons[orientation] = self.createRadioButton(orientation, checked=orientation=="Axial")
      orientationBoxLayout.addWidget(self.orientationButtons[orientation])
    self.currentOrientation = 'Axial'

  def setupLabelTranslationSettingsUI(self):
    self.translateArea = ctk.ctkCollapsibleButton()
    self.translateArea.text = "Translate Selected Label Map"
    translateAreaLayout = qt.QFormLayout(self.translateArea)

    self.translateLR = self.createSliderWidget(minimum=-200, maximum=200)
    self.translatePA = self.createSliderWidget(minimum=-200, maximum=200)
    self.translateIS = self.createSliderWidget(minimum=-200, maximum=200)

    translateAreaLayout.addRow("Translate LR: ", self.translateLR)
    translateAreaLayout.addRow("Translate PA: ", self.translatePA)
    translateAreaLayout.addRow("Translate IS: ", self.translateIS)

    self.hardenTransformButton = self.createButton("Harden Transform", enabled=False)
    translateAreaLayout.addRow(self.hardenTransformButton)
    self.translateArea.collapsed = 1

  def setupFiducialsUI(self):
    self.fiducialsArea = ctk.ctkCollapsibleButton()
    self.fiducialsArea.text = "Fiducials"
    self.fiducialsArea.collapsed = True

    self.fiducialsWidget = TargetCreationWidget()
    self.fiducialsWidget.targetListSelectorVisible = True
    self.segmentationWidgetLayout.addWidget(self.fiducialsWidget)

  def setupCompletionUI(self):
    self.piradsButton = qt.QPushButton("PI-RADS v2 review form")
    self.completionWidgetLayout.addWidget(self.piradsButton)

    self.qaButton = qt.QPushButton("Quality Assurance form")
    self.completionWidgetLayout.addWidget(self.qaButton)

    self.saveButton = qt.QPushButton("Save")
    self.completionWidgetLayout.addWidget(self.saveButton)
    '''
      self.piradsButton = qt.QPushButton("PI-RADS review")
      self.layout.addWidget(self.piradsButton)
      # self.piradsButton.connect('clicked()',self.onPiradsClicked)
      '''

  def setupConnections(self):

    def setupButtonConnections():
      self.dataDirButton.directorySelected.connect(lambda: setattr(self, "inputDataDir", self.dataDirButton.directory))
      self.selectAllSeriesButton.connect('clicked()', lambda: self.selectAllSeries(True))
      self.deselectAllSeriesButton.connect('clicked()', lambda: self.selectAllSeries(False))
      self.deleteStructureButton.connect('clicked()', self.onDeleteStructure)
      self.propagateButton.connect('clicked()', self.onPropagateROI)
      self.createFiducialsButton.connect('clicked()', self.onCreateFiducialsButtonClicked)
      self.hardenTransformButton.connect('clicked(bool)', self.onHardenTransform)
      self.buildModelsButton.connect("clicked()", self.onBuildModels)
      self.modelsVisibilityButton.connect("toggled(bool)", self.onModelsVisibilityButton)
      self.labelMapVisibilityButton.connect("toggled(bool)", self.onLabelMapVisibilityButton)
      self.labelMapOutlineButton.connect('toggled(bool)', self.setLabelOutline)
      self.piradsButton.connect('clicked()', self.onPIRADSFormClicked)
      self.qaButton.connect('clicked()', self.onQAFormClicked)
      self.saveButton.connect('clicked()', self.onSaveClicked)
      for orientation in self.orientations:
        self.orientationButtons[orientation].connect("clicked()", lambda o=orientation: self.setOrientation(o))
      self.viewButtonGroup.connect('buttonClicked(int)', self.onViewUpdateRequested)

    def setupSliderConnections():
      self.translateLR.connect('valueChanged(double)', self.onTranslate)
      self.translatePA.connect('valueChanged(double)', self.onTranslate)
      self.translateIS.connect('valueChanged(double)', self.onTranslate)
      self.multiVolumeExplorer.frameSlider.connect('valueChanged(double)', self.onSliderChanged)

    def setupViewConnections():
      self.studiesView.selectionModel().connect('currentChanged(QModelIndex, QModelIndex)', self.onStudySelected)
      self.seriesView.connect('clicked(QModelIndex)', self.onSeriesSelected)
      self.structuresView.connect("activated(QModelIndex)", self.onStructureClicked)

    def setupOtherConnections():
      self.refSelector.connect('currentIndexChanged(int)', self.onReferenceChanged)
      self.tabWidget.connect('currentChanged(int)',self.onTabWidgetClicked)

    setupButtonConnections()
    setupSliderConnections()
    setupViewConnections()
    setupOtherConnections()

  def onEditorWidgetParameterNodeChanged(self, caller, event=-1):
    effectName = caller.GetParameter("effect")
    toolbox = self.editorWidget.toolsBox
    if effectName in ["PaintEffect", "DrawEffect"]:
      toolOption = toolbox.currentOption
      attributes = ["radius", "paintOver", "thresholdPaint", "sphere", "smudge", "pixelMode"]
      for attr in attributes:
        if hasattr(toolOption, attr):
          getattr(toolOption, attr).hide()
    try:
      slicer.util.findChildren(self.editorWidget.toolsBox.optionsFrame, "EditorHelpButton")[0].hide()
    except IndexError:
      pass

  def enter(self):
    userName = self.getSetting('UserName')
    self.piradsFormURL = self.getSetting('piradsFormURL')
    self.qaFormURL = self.getSetting('qaFormURL')

    if userName is None or userName == '':
      # prompt the user for ID (last name)
      self.namePrompt = qt.QDialog()
      self.namePromptLayout = qt.QVBoxLayout()
      self.namePrompt.setLayout(self.namePromptLayout)
      self.nameLabel = qt.QLabel('Enter your last name:', self.namePrompt)
      import getpass
      self.nameText = qt.QLineEdit(getpass.getuser(), self.namePrompt)
      self.nameButton = qt.QPushButton('OK', self.namePrompt)
      self.nameButton.connect('clicked()', self.onNameEntered)
      self.namePromptLayout.addWidget(self.nameLabel)
      self.namePromptLayout.addWidget(self.nameText)
      self.namePromptLayout.addWidget(self.nameButton)
      self.namePrompt.exec_()
    else:
      self.parameters['UserName'] = userName

    if self.piradsFormURL is None or self.piradsFormURL == '':
      # prompt the user for the review form
      # Note: it is expected that the module uses the form of the structure as
      # in http://goo.gl/nT1z4L. The known structure of the form is used to
      # pre-populate the fields corresponding to readerName, studyName and
      # lesionID.
      self.URLPrompt = qt.QDialog()
      self.URLPromptLayout = qt.QVBoxLayout()
      self.URLPrompt.setLayout(self.URLPromptLayout)
      self.URLLabel = qt.QLabel('Enter PI-RADS review form URL:', self.URLPrompt)
      # replace this if you are using a different form
      self.URLText = qt.QLineEdit(self.PIRADS_VIEWFORM_URL)
      self.URLButton = qt.QPushButton('OK', self.URLPrompt)
      self.URLButton.connect('clicked()', self.onPIRADSURLEntered)
      self.URLPromptLayout.addWidget(self.URLLabel)
      self.URLPromptLayout.addWidget(self.URLText)
      self.URLPromptLayout.addWidget(self.URLButton)
      self.URLPrompt.exec_()

      if self.qaFormURL is None or self.qaFormURL == '':
        # prompt the user for the review form
        # Note: it is expected that the module uses the form of the structure as
        # in http://goo.gl/nT1z4L. The known structure of the form is used to
        # pre-populate the fields corresponding to readerName, studyName and
        # lesionID.
        self.URLPrompt = qt.QDialog()
        self.URLPromptLayout = qt.QVBoxLayout()
        self.URLPrompt.setLayout(self.URLPromptLayout)
        self.URLLabel = qt.QLabel('Enter QA review form URL:', self.URLPrompt)
        # replace this if you are using a different form
        self.URLText = qt.QLineEdit(self.QA_VIEWFORM_URL)
        self.URLButton = qt.QPushButton('OK', self.URLPrompt)
        self.URLButton.connect('clicked()', self.onQAURLEntered)
        self.URLPromptLayout.addWidget(self.URLLabel)
        self.URLPromptLayout.addWidget(self.URLText)
        self.URLPromptLayout.addWidget(self.URLButton)
        self.URLPrompt.exec_()

    '''
    # ask where is the input
    if inputLocation == None or inputLocation == '':
      self.dirPrompt = qt.QDialog()
      self.dirPromptLayout = qt.QVBoxLayout()
      self.dirPrompt.setLayout(self.dirPromptLayout)
      self.dirLabel = qt.QLabel('Choose the directory with the input data:', self.dirPrompt)
      self.dirButton = ctk.ctkDirectoryButton(self.dirPrompt)
      self.dirButtonDone = qt.QPushButton('OK', self.dirPrompt)
      self.dirButtonDone.connect('clicked()', self.onInputDirEntered)
      self.dirPromptLayout.addWidget(self.dirLabel)
      self.dirPromptLayout.addWidget(self.dirButton)
      self.dirPromptLayout.addWidget(self.dirButtonDone)
      self.dirPrompt.exec_()
    else:
      self.parameters['InputLocation'] = inputLocation
      logging.debug('Setting inputlocation in settings to '+inputLocation)
    # ask where to keep the results
    if resultsLocation == None or resultsLocation == '':
      self.dirPrompt = qt.QDialog()
      self.dirPromptLayout = qt.QVBoxLayout()
      self.dirPrompt.setLayout(self.dirPromptLayout)
      self.dirLabel = qt.QLabel('Choose the directory to store the results:', self.dirPrompt)
      self.dirButton = ctk.ctkDirectoryButton(self.dirPrompt)
      self.dirButtonDone = qt.QPushButton('OK', self.dirPrompt)
      self.dirButtonDone.connect('clicked()', self.onResultsDirEntered)
      self.dirPromptLayout.addWidget(self.dirLabel)
      self.dirPromptLayout.addWidget(self.dirButton)
      self.dirPromptLayout.addWidget(self.dirButtonDone)
      self.dirPrompt.exec_()
    else:
      self.parameters['ResultsLocation'] = resultsLocation
    '''

  def checkAndSetLUT(self):
    # Default to module color table
    self.colorFile = os.path.join(self.resourcesPath, "Colors/mpReviewColors.csv")
    self.customLUTInfoIcon.show()
    self.customLUTInfoIcon.toolTip = 'Using Default LUT'

    # Check for custom LUT
    lookupTableLoc = os.path.join(self.inputDataDir, 'SETTINGS', self.inputDataDir.split(os.sep)[-1] + '-LUT.csv')
    logging.debug('Checking for lookup table at : ' + lookupTableLoc)
    if os.path.isfile(lookupTableLoc):
      # use custom color table
      self.colorFile = lookupTableLoc
      self.customLUTInfoIcon.toolTip = 'Project-Specific LUT Found'

    # Set merge volume in structureListWidget to None so Editor doesn't get confused by missing node
    # This may be the first time we get here, in which case editorWidget is not
    # created yet.  If it has been created, structureListWidget.merge is probably set to
    # something that has been removed from the scene by onStep3Select.
    try:
      self.editorWidget.helper.structureListWidget.merge = None
    except AttributeError:
      pass

    # setup the color table, make sure mpReview LUT is a singleton
    allColorTableNodes = slicer.util.getNodes('vtkMRMLColorTableNode*').values()
    for ctn in allColorTableNodes:
      if ctn.GetName() == 'mpReview':
        slicer.mrmlScene.RemoveNode(ctn)
        break

    self.mpReviewColorNode, self.structureNames = self.logic.loadColorTable(self.colorFile)

  def onNameEntered(self):
    name = self.nameText.text
    if len(name)>0:
      self.setSetting('UserName', name)
      self.namePrompt.close()
      self.parameters['UserName'] = name

  def onQAURLEntered(self):
    url = self.URLText.text
    if len(url)>0:
      self.setSetting('qaFormURL',url)
      self.URLPrompt.close()
      self.qaFormURL = url

  def onPIRADSURLEntered(self):
    url = self.URLText.text
    if len(url)>0:
      self.setSetting('piradsFormURL',url)
      self.URLPrompt.close()
      self.piradsFormURL = url

  # def onResultsDirEntered(self):
  #   path = self.dirButton.directory
  #   if len(path)>0:
  #     self.setSetting('ResultsLocation',path)
  #     self.dirPrompt.close()
  #     self.parameters['ResultsLocation'] = path

  def onViewUpdateRequested(self, id):
    # Skip if not in a ref image yet
    if self.refSeriesNumber == '-1':
      return

    # Be sure the viewers are linked, they should be but who knows
    self.linkAllSliceWidgets(1)

    layoutNode = slicer.util.getNode('*LayoutNode*')
    if id == 1:
       # If view all
      layoutNode.SetViewArrangement(layoutNode.SlicerLayoutUserView)
    if id == 2:
      # If view ref only
      layoutNode.SetViewArrangement(layoutNode.SlicerLayoutOneUpRedSliceView)

  def onSeriesSelected(self, modelIndex):
    logging.debug('Row selected: '+self.seriesModel.item(modelIndex.row(),0).text())
    selectionModel = self.seriesView.selectionModel()
    logging.debug('Selection model says row is selected: '+str(selectionModel.isRowSelected(modelIndex.row(),
                                                                                            qt.QModelIndex())))
    logging.debug('Row number: '+str(modelIndex.row()))
    self.updateSegmentationTabAvailability()

  def updateSegmentationTabAvailability(self):
    self.setTabsEnabled([1], any(sItem.checkState() == 2 for sItem in self.seriesItems))

  def onPIRADSFormClicked(self):
    self.webView = qt.QWebView()
    self.webView.settings().setAttribute(qt.QWebSettings.DeveloperExtrasEnabled, True)
    self.webView.connect('loadFinished(bool)', self.webViewFormLoadedCallback)
    self.webView.show()
    preFilledURL = self.piradsFormURL
    preFilledURL += '?entry.1455103354='+self.getSetting('UserName')
    preFilledURL += '&entry.347120626='+self.selectedStudyName
    preFilledURL += '&entry.1734306468='+str(self.editorWidget.toolsColor.colorSpin.value)
    u = qt.QUrl(preFilledURL)
    self.webView.setUrl(u)

  # https://docs.google.com/forms/d/18Ni2rcooi60fev5mWshJA0yaCzHYvmXPhcG2-jMF-uw/viewform?entry.1920755914=READER&entry.204001910=STUDY
  def onQAFormClicked(self):
    self.webView = qt.QWebView()
    self.webView.settings().setAttribute(qt.QWebSettings.DeveloperExtrasEnabled, True)
    self.webView.connect('loadFinished(bool)', self.webViewFormLoadedCallback)
    self.webView.show()
    preFilledURL = self.qaFormURL
    preFilledURL += '?entry.1920755914='+self.getSetting('UserName')
    preFilledURL += '&entry.204001910='+self.selectedStudyName
    print('Pre-filled URL:'+preFilledURL)
    u = qt.QUrl(preFilledURL)
    self.webView.setUrl(u)

  def webViewFormLoadedCallback(self,ok):
    if not ok:
      logging.debug('page did not load')
      return
    page = self.webView.page()
    frame = page.mainFrame()
    document = frame.documentElement()
    element = document.findFirst('entry.2057130045')
    element.setAttribute("value", self.parameters['UserName'])

  def onSaveClicked(self):
    """ Elements that will be saved:
        * segmentation: label map
        * w/l for each volume
        Convention: create a directory for each type of resource saved,
        then subdirectory for each scan that was analyzed
    """

    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    username = self.getSetting('UserName')

    savedMessage = self.saveSegmentations(timestamp, username)# save w/l settings for all non-label volume nodes
    '''
    volumeNodes = slicer.util.getNodes('vtkMRMLScalarVolumeNode*')
    logging.debug('All volume nodes: '+str(volumeNodes))
    for key in volumeNodes.keys():
      vNode = volumeNodes[key]
      if vNode.GetAttribute('LabelMap') == '1':
        continue
      seriesNumber = string.split(key,':')[0]
      logging.debug('W/L for series '+seriesNumber+' is '+str(vNode.GetDisplayNode().GetWindow()))
      f = open(wlSettingsDir+'/'+seriesNumber+'-wl.txt','w')
      f.write(str(vNode.GetDisplayNode().GetWindow())+' '+str(vNode.GetDisplayNode().GetLevel()))
      f.close()
    '''

    savedMessage += "\n " + self.saveTargets(username, timestamp)
    slicer.util.infoDisplay(savedMessage, windowTitle="mpReview")

  def saveSegmentations(self, timestamp, username):
    wlSettingsDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'WindowLevelSettings')
    self.logic.createDirectory(wlSettingsDir)
    # save all label nodes (there should be only one per volume!)
    labelNodes = slicer.util.getNodes('*-label*')
    logging.debug('All label nodes found: ' + str(labelNodes))
    savedMessage = 'Segmentations for the following series were saved:\n\n'
    for label in labelNodes.values():

      labelSeries = label.GetName().split(':')[0]
      labelName = label.GetName().split(':')[1]

      # structure is root -> study -> resources -> series # ->
      # Segmentations/Reconstructions/OncoQuant -> files
      segmentationsDir = os.path.join(self.inputDataDir, self.selectedStudyName,
                                      'RESOURCES', labelSeries, 'Segmentations')
      self.logic.createDirectory(segmentationsDir)

      structureName = labelName[labelName[:-6].rfind("-") + 1:-6]
      # Only save labels with known structure names
      if any(structureName == s for s in self.structureNames):
        logging.debug("structure name is: %s" % structureName)
        uniqueID = username + '-' + structureName + '-' + timestamp

        labelFileName = os.path.join(segmentationsDir, uniqueID + '.nrrd')

        sNode = slicer.vtkMRMLVolumeArchetypeStorageNode()
        sNode.SetFileName(labelFileName)
        sNode.SetWriteFileFormat('nrrd')
        sNode.SetURI(None)
        success = sNode.WriteData(label)
        if success:
          savedMessage = savedMessage + label.GetName() + '\n'
          logging.debug(label.GetName() + ' has been saved to ' + labelFileName)

    return savedMessage

  def saveTargets(self, username, timestamp):
    savedMessage = ""
    fiducialsNode = self.fiducialsWidget.currentNode
    if fiducialsNode:
      targetsDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'Targets')
      self.logic.createDirectory(targetsDir)
      targetFileName = username+'-'+timestamp+'.fcsv'
      path = os.path.join(targetsDir, targetFileName)
      if slicer.util.saveNode(fiducialsNode, path):
        savedMessage = 'Fiducials were saved'
    return savedMessage

  def onBuildModels(self):
    """make models of the structure label nodesvolume"""
    if self.refSeriesNumber != '-1':
      ref = self.refSeriesNumber
      refLongName = self.seriesMap[ref]['LongName']
      labelNodes = slicer.util.getNodes('*'+refLongName+'*-label*')

      numNodes = slicer.mrmlScene.GetNumberOfNodesByClass( "vtkMRMLModelHierarchyNode" )
      outHierarchy = None

      for n in xrange(numNodes):
        node = slicer.mrmlScene.GetNthNodeByClass( n, "vtkMRMLModelHierarchyNode" )
        if node.GetName() == 'mpReview-'+refLongName:
          outHierarchy = node
          break

      # Remove the previous models
      if outHierarchy:
        collection = vtk.vtkCollection()
        outHierarchy.GetChildrenModelNodes(collection)
        n = collection.GetNumberOfItems()
        if n != 0:
          for i in xrange(n):
            modelNode = collection.GetItemAsObject(i)
            slicer.mrmlScene.RemoveNode(modelNode)

      # if models hierarchy does not exist, create it.
      else:
        outHierarchy = slicer.vtkMRMLModelHierarchyNode()
        outHierarchy.SetScene( slicer.mrmlScene )
        outHierarchy.SetName( 'mpReview-'+refLongName )
        slicer.mrmlScene.AddNode( outHierarchy )

      progress = self.createProgressDialog(maximum=len(labelNodes))
      step = 0
      for label in labelNodes.values():
        labelName =  label.GetName().split(':')[1]
        structureName = labelName[labelName[:-6].rfind("-")+1:-6]
        # Only save labels with known structure names
        if any(structureName in s for s in self.structureNames):
          parameters = {}
          parameters["InputVolume"] = label.GetID()
          parameters['FilterType'] = "Sinc"
          parameters['GenerateAll'] = True

          parameters["JointSmoothing"] = False
          parameters["SplitNormals"] = True
          parameters["PointNormals"] = True
          parameters["SkipUnNamed"] = True

          # create models for all labels
          parameters["StartLabel"] = -1
          parameters["EndLabel"] = -1

          parameters["Decimate"] = 0
          parameters["Smooth"] = 0

          parameters["ModelSceneFile"] = outHierarchy

          progress.labelText = '\nMaking Model for %s' % structureName
          progress.setValue(step)
          slicer.app.processEvents()
          if progress.wasCanceled:
            break

          try:
            modelMaker = slicer.modules.modelmaker
            self.CLINode = slicer.cli.run(modelMaker, self.CLINode,
                           parameters, wait_for_completion=True)
          except AttributeError:
            qt.QMessageBox.critical(slicer.util.mainWindow(),'Editor', 'The ModelMaker module is not available'
                                                                       '<p>Perhaps it was disabled in the application '
                                                                       'settings or did not load correctly.')
        step += 1
      progress.close()
        #

      if outHierarchy:
        collection = vtk.vtkCollection()
        outHierarchy.GetChildrenModelNodes(collection)
        n = collection.GetNumberOfItems()
        if n != 0:
          for i in xrange(n):
            modelNode = collection.GetItemAsObject(i)
            displayNode = modelNode.GetDisplayNode()
            displayNode.SetSliceIntersectionVisibility(1)
            displayNode.SetSliceIntersectionThickness(2)
          self.modelsVisibilityButton.checked = False
          self.updateViewRenderer()

  def removeAllModels(self):
    modelHierarchyNodes = []
    numNodes = slicer.mrmlScene.GetNumberOfNodesByClass( "vtkMRMLModelHierarchyNode" )
    for n in xrange(numNodes):
      node = slicer.mrmlScene.GetNthNodeByClass( n, "vtkMRMLModelHierarchyNode")
      if node.GetName()[:12] == 'mpReview-':
        modelHierarchyNodes.append(node)

    for hierarchyNode in modelHierarchyNodes:
      modelNodes = vtk.vtkCollection()
      hierarchyNode.GetChildrenModelNodes(modelNodes)
      for i in range(modelNodes.GetNumberOfItems()) :
          slicer.mrmlScene.RemoveNode(modelNodes.GetItemAsObject(i))
      slicer.mrmlScene.RemoveNode(hierarchyNode)

    self.modelsVisibilityButton.checked = False
    self.modelsVisibilityButton.setText('Hide')

  def setLabelOutline(self, toggled):
    # Update button text
    if toggled:
      self.labelMapOutlineButton.setText('Filled')
    else:
      self.labelMapOutlineButton.setText('Outline')

    # Set outline on widgets
    self.editUtil.setLabelOutline(toggled)

  def onModelsVisibilityButton(self,toggled):
    if self.refSeriesNumber != '-1':
      ref = self.refSeriesNumber
      refLongName = self.seriesMap[ref]['LongName']

      outHierarchy = None
      numNodes = slicer.mrmlScene.GetNumberOfNodesByClass( "vtkMRMLModelHierarchyNode" )
      for n in xrange(numNodes):
        node = slicer.mrmlScene.GetNthNodeByClass( n, "vtkMRMLModelHierarchyNode" )
        if node.GetName() == 'mpReview-'+refLongName:
          outHierarchy = node
          break

      if outHierarchy:
        collection = vtk.vtkCollection()
        outHierarchy.GetChildrenModelNodes(collection)
        n = collection.GetNumberOfItems()
        if n != 0:
          for i in xrange(n):
            modelNode = collection.GetItemAsObject(i)
            displayNode = modelNode.GetDisplayNode()
            displayNode.SetSliceIntersectionVisibility(0 if toggled else 1)
            self.modelsVisibilityButton.setText('Show' if toggled else 'Hide')
          self.updateViewRenderer()

  def onLabelMapVisibilityButton(self, toggled):
    self.labelMapVisibilityButton.setText('Show' if toggled else 'Hide')
    sliceLogics = self.layoutManager.mrmlSliceLogics()
    for n in range(sliceLogics.GetNumberOfItems()):
      sliceLogic = sliceLogics.GetItemAsObject(n)
      widget = self.layoutManager.sliceWidget(sliceLogic.GetName())
      redCompositeNode = widget.mrmlSliceCompositeNode()
      redCompositeNode.SetLabelOpacity(0.0 if toggled else 1.0)

  def checkAndLoadLabel(self, seriesNumber, volumeName):
    globPath = os.path.join(self.resourcesDir,str(seriesNumber),"Segmentations",
                            self.getSetting('UserName')+'*')
    previousSegmentations = glob.glob(globPath)
    if not len(previousSegmentations):
      return False,None

    #fileName = previousSegmentations[-1]

    # Iterate over segmentation files and choose the latest for each structure
    latestSegmentations = {}
    for segmentation in previousSegmentations:
        actualFileName = os.path.split(segmentation)[1]
        structureName = actualFileName.split("-")[1] # expectation: username-structure-timestamp.nrrd
        # this is to support legacy segmentations that did not use this
        # specific LUT, and where labels are specified by numbers
        # Use the structure name as defined by the corresponding label ID in
        # the selected LUT
        if structureName not in self.structureNames and int(structureName)<len(self.structureNames):
          structureName = self.structureNames[int(structureName)]
        timeStamp = int(actualFileName.split("-")[2][:-5])
        if structureName not in latestSegmentations.keys():
          latestSegmentations[structureName] = segmentation
        else:
          storedSegmentation = latestSegmentations[structureName]
          storedTimeStamp = int(storedSegmentation[storedSegmentation.rfind("-")+1:-5])
          if timeStamp > storedTimeStamp:
            latestSegmentations[structureName] = segmentation

    for structure,fileName in latestSegmentations.iteritems():
      (success,label) = slicer.util.loadLabelVolume(fileName, returnNode=True)
      if not success:
        return False,None
      logging.debug('Setting loaded label name to '+volumeName)
      label.SetName(volumeName+'-'+structure+'-label')
      label.RemoveAllDisplayNodeIDs()

      dNode = slicer.vtkMRMLLabelMapVolumeDisplayNode()
      slicer.mrmlScene.AddNode(dNode)
      dNode.SetAndObserveColorNodeID(self.mpReviewColorNode.GetID())
      label.SetAndObserveDisplayNodeID(dNode.GetID())

      logging.debug('Label loaded, storage node is '+label.GetStorageNode().GetID())

    return True

  def setTabsEnabled(self, indexes, enabled):
    for index in indexes:
      self.tabWidget.childAt(1, 1).setTabEnabled(index, enabled)

  def checkStep2or3Leave(self):
    if self.currentTabIndex in [1,2]:
      continueCurrentStep = self.showExitStep3Or4Warning()
      if continueCurrentStep:
        self.tabWidget.setCurrentIndex(self.currentTabIndex)
        return True
      else:
        self.removeAllModels()
    return False

  def onStep1Selected(self):
    if self.checkStep2or3Leave() is True:
      return False
    self.setCrosshairEnabled(False)

    self.editorParameterNode.SetParameter('effect', 'DefaultTool')
    if len(self.studiesView.selectedIndexes()) > 0:
      self.onStudySelected(self.studiesView.selectedIndexes()[0])
    self.updateSegmentationTabAvailability()
    return True

  def updateStudyTable(self):
    self.studiesModel.clear()
    if self.logic.wasmpReviewPreprocessed(self.inputDataDir):
      self.fillStudyTable()
    else:
      self.notifyUserAboutMissingEligibleData()

  def notifyUserAboutMissingEligibleData(self):
    outputDirectory = os.path.abspath(self.inputDataDir) + "_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    mbox = qt.QMessageBox()
    mbox.icon = qt.QMessageBox.Question
    mbox.text = "The selected directory is not eligible for using with mpReview.\n\n" \
                "Do you want to parse the directory and preprocess found DICOM data?\n\n" \
                "Output directory (browse to change): \n\n%s\n\n" \
                "NOTE: The original DICOM data will not be modified." % outputDirectory
    okButton = mbox.addButton(qt.QMessageBox.Ok)
    browseButton = self.createButton("Browse", icon=ctk.ctkDirectoryButton().icon)
    mbox.addButton(browseButton, qt.QMessageBox.ActionRole)
    mbox.addButton(qt.QMessageBox.Cancel)
    mbox.exec_()
    selectedButton = mbox.clickedButton()
    if selectedButton in [browseButton, okButton]:
      if selectedButton is browseButton:
        selectedDir = qt.QFileDialog.getExistingDirectory(None, self.inputDataDir)
        if selectedDir and selectedDir != self.inputDataDir:
          outputDirectory = selectedDir
        else:
          if selectedDir == self.inputDataDir:
            slicer.util.warningDisplay("The output directory cannot be the input data directory Please choose another "
                                       "directory.", windowTitle="mpReview")
          return self.updateStudyTable()
      success = self.invokePreProcessing(outputDirectory)
      if success:
        self.dataDirButton.directory = outputDirectory
      else:
        slicer.util.infoDisplay("No DICOM data could be processed. Please select another directory.",
                                windowTitle="mpReview")

  def updateSeriesTable(self):
    self.seriesItems = []
    self.seriesModel.clear()
    for s in sorted([int(x) for x in self.seriesMap.keys()]):
      seriesText = str(s) + ':' + self.seriesMap[str(s)]['LongName']
      sItem = qt.QStandardItem(seriesText)
      self.seriesItems.append(sItem)
      self.seriesModel.appendRow(sItem)
      sItem.setCheckable(1)
      if self.logic.isSeriesOfInterest(seriesText):
        sItem.setCheckState(2)
    self.updateSegmentationTabAvailability()

  def fillStudyTable(self):
    self.studyItems = []
    self.seriesModel.clear()
    dirs = self.logic.getStudyNames(self.inputDataDir)
    dirs.sort()
    progress = self.createProgressDialog(maximum=len(dirs))
    for studyIndex, studyName in enumerate(dirs, start=1):
      if os.path.isdir(os.path.join(self.inputDataDir, studyName)) and studyName != 'SETTINGS':
        sItem = qt.QStandardItem(studyName)
        self.studyItems.append(sItem)
        self.studiesModel.appendRow(sItem)
        logging.debug('Appended to model study ' + studyName)
        progress.setValue(studyIndex)
        slicer.app.processEvents()
    # TODO: unload all volume nodes that are already loaded
    progress.close()
    if len(self.studyItems) == 1:
      modelIndex = self.studiesModel.index(0,0)
      self.studiesView.selectionModel().setCurrentIndex(modelIndex, self.studiesView.selectionModel().Select)
      self.studiesView.selectionModel().select(modelIndex, self.studiesView.selectionModel().Select)

  def invokePreProcessing(self, outputDirectory):
    self.mpReviewPreprocessorLogic = mpReviewPreprocessorLogic()
    self.progress = self.createProgressDialog()
    self.progress.canceled.connect(lambda : self.mpReviewPreprocessorLogic.cancelProcess())
    self.logic.createDirectory(outputDirectory)
    success = self.mpReviewPreprocessorLogic.importAndProcessData(self.inputDataDir, outputDir=outputDirectory,
                                                                  copyDICOM=True,
                                                                  progressCallback=self.updateProgressBar)
    self.progress.canceled.disconnect(lambda : self.mpReviewPreprocessorLogic.cancelProcess())
    self.progress.close()
    return success

  def updateProgressBar(self, **kwargs):
    ModuleWidgetMixin.updateProgressBar(self, progress=self.progress, **kwargs)

  def onStudySelected(self, modelIndex):
    self.studiesGroupBox.collapsed = True
    logging.debug('Row selected: '+self.studiesModel.item(modelIndex.row(),0).text())
    selectionModel = self.studiesView.selectionModel()
    logging.debug('Selection model says row is selected: '+str(selectionModel.isRowSelected(modelIndex.row(),
                                                                                            qt.QModelIndex())))
    logging.debug('Row number: '+str(modelIndex.row()))

    self.setTabsEnabled([2], False)

    self.logic.cleanupDir(self.tempDir)

    # Block the signals to master selector while removing the old nodes.
    # If signals are not blocked, a new volume node is selected automatically
    # on delete of a previously selected one leading to "Create merge ..."
    # popup.
    # structureListWidget seems to be a little sticky and will also get confused
    # by nodes being removed from the scene.
    self.editorWidget.helper.masterSelector.blockSignals(True)
    self.editorWidget.helper.mergeSelector.blockSignals(True)
    self.editorWidget.helper.structureListWidget.merge = None

    # if any volumes have been loaded (we returned back from a previous step)
    # then remove all of them from the scene
    allVolumeNodes = slicer.util.getNodes('vtkMRML*VolumeNode*')
    for node in allVolumeNodes.values():
      slicer.mrmlScene.RemoveNode(node)

    self.editorWidget.helper.masterSelector.blockSignals(False)
    self.editorWidget.helper.mergeSelector.blockSignals(False)

    self.selectedStudyName = self.studiesModel.item(modelIndex.row(),0).text()
    self.parameters['StudyName'] = self.selectedStudyName

    self.resourcesDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'RESOURCES')

    self.progress = self.createProgressDialog(maximum=len(os.listdir(self.resourcesDir)))
    self.seriesMap, metaFile = self.logic.loadMpReviewProcessedData(self.resourcesDir,
                                                                    updateProgressCallback=self.updateProgressBar)
    self.informationWatchBox.sourceFile = metaFile
    self.informationWatchBox.setInformation("StudyID", self.selectedStudyName)

    self.updateSeriesTable()

    self.selectAllSeriesButton.setEnabled(True)
    self.deselectAllSeriesButton.setEnabled(True)

    self.progress.delete()
    self.setTabsEnabled([1], True)

  def onStep2Selected(self):
    if self.currentTabIndex == 2:
      self.setCrosshairEnabled(self.refSelector.currentText not in ["", "None"])
      return True
    self.setTabsEnabled([2],True)

    self.editorWidget.enter()

    self.resetTranslate()

    checkedItems = [x for x in self.seriesItems if x.checkState()]

    self.volumeNodes = {}
    self.labelNodes = {}
    selectedSeriesNumbers = []
    self.refSeriesNumber = '-1'

    logging.debug('Checked items:')
    ref = None

    self.refSelector.clear()

    # reference selector can have None (initially)
    # user should select reference, which triggers creation of the label and

    # initialization of the editor widget

    self.refSelector.addItem('None')

    # ignore refSelector events until the selector is populated!
    self.refSelectorIgnoreUpdates = True

    # Loading progress indicator
    progress = self.createProgressDialog(maximum=len(checkedItems))
    nLoaded = 0

    # iterate over all selected items and add them to the reference selector
    selectedSeries = {}
    for i in checkedItems:
      text = i.text()

      progress.labelText = text
      progress.setValue(nLoaded)
      slicer.app.processEvents()
      nLoaded += 1

      seriesNumber = text.split(':')[0]
      shortName = self.seriesMap[seriesNumber]['ShortName']
      longName = self.seriesMap[seriesNumber]['LongName']

      fileName = self.seriesMap[seriesNumber]['NRRDLocation']
      (success,volume) = slicer.util.loadVolume(fileName,returnNode=True)
      if success:
        if volume.GetClassName() == 'vtkMRMLScalarVolumeNode':
          self.seriesMap[seriesNumber]['Volume'] = volume
          self.seriesMap[seriesNumber]['Volume'].SetName(shortName)
        elif volume.GetClassName() == 'vtkMRMLMultiVolumeNode':
          self.seriesMap[seriesNumber]['MultiVolume'] = volume
          self.seriesMap[seriesNumber]['MultiVolume'].SetName(shortName+'_multivolume')
          self.seriesMap[seriesNumber]['FrameNumber'] = volume.GetNumberOfFrames()-1
          scalarVolumeNode = MVHelper.extractFrame(None, self.seriesMap[seriesNumber]['MultiVolume'],
                                                         self.seriesMap[seriesNumber]['FrameNumber'])
          scalarVolumeNode.SetName(shortName)
          self.seriesMap[seriesNumber]['Volume'] = scalarVolumeNode
      else:
        logging.debug('Failed to load image volume!')
        return True
      self.checkAndLoadLabel(seriesNumber, shortName)
      try:
        if self.seriesMap[seriesNumber]['MetaInfo']['ResourceType'] == 'OncoQuant':
          dNode = volume.GetDisplayNode()
          dNode.SetWindowLevel(5.0,2.5)
          dNode.SetAndObserveColorNodeID('vtkMRMLColorTableNodeFileColdToHotRainbow.txt')
        else:
          self.refSelector.addItem(text)
      except:
        self.refSelector.addItem(text)

      if longName.find('T2')>=0 and longName.find('AX')>=0:
        ref = int(seriesNumber)

      selectedSeries[seriesNumber] = self.seriesMap[seriesNumber]
      logging.debug('Processed '+longName)

      selectedSeriesNumbers.append(int(seriesNumber))

    self.seriesMap = selectedSeries

    progress.delete()

    logging.debug('Selected series: '+str(selectedSeries)+', reference: '+str(ref))
    #self.cvLogic = CompareVolumes.CompareVolumesLogic()
    #self.viewNames = [self.seriesMap[str(ref)]['ShortName']]

    self.refSelectorIgnoreUpdates = False

    self.checkForMultiVolumes()
    self.checkForFiducials()
    return True

  def onStep3Selected(self):
    self.setCrosshairEnabled(False)
    self.editorParameterNode.SetParameter('effect', 'DefaultTool')
    return True

  def checkForFiducials(self):
    self.targetsDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'Targets')
    if not os.path.exists(self.targetsDir):
      return
    mostRecent = ""
    storedTimeStamp = 0
    for filename in [f for f in os.listdir(self.targetsDir) if re.match(self.getSetting('UserName')+"-[0-9]*.fcsv", f)]:
      actualFileName = filename.split(".")[0]
      timeStamp = int(actualFileName.split("-")[1])
      if timeStamp > storedTimeStamp:
        mostRecent = filename
        storedTimeStamp = timeStamp
    self.loadMostRecentFiducialList(mostRecent)

  def loadMostRecentFiducialList(self, mostRecent):
    if mostRecent != "":
      path = os.path.join(self.targetsDir, mostRecent)
      if slicer.util.loadMarkupsFiducialList(path):
        self.fiducialsWidget.currentNode = slicer.util.getFirstNodeByName(mostRecent.split(".")[0])

  def checkForMultiVolumes(self):
    multiVolumes = self.getMultiVolumes()
    self.multiVolumeExplorer.showInputMultiVolumeSelector(len(multiVolumes) > 1)
    multiVolume = None
    if len(multiVolumes) == 1:
      multiVolume = multiVolumes[0]
    elif len(multiVolumes) > 1:
      multiVolume = max(multiVolumes, key=lambda mv: mv.GetNumberOfFrames)
      # TODO: set selector
    self.multiVolumeExplorer.setMultiVolume(multiVolume)
    self.showMultiVolumeExplorer(len(multiVolumes) > 0)

  def showMultiVolumeExplorer(self, show):
    if show:
      self.multiVolumeExplorerArea.show()
    else:
      self.multiVolumeExplorerArea.hide()

  def getMultiVolumes(self):
    multiVolumes = []
    for key, val in self.seriesMap.items():
      if 'MultiVolume' in val.keys():
        multiVolumes.append(val['MultiVolume'])
    return multiVolumes

  def showExitStep3Or4Warning(self):
    result = self.confirmOrSaveDialog('Unsaved contours will be lost!\n\nDo you still want to exit?')
    if result == 1:
      self.onSaveClicked()
    return result == 2

  def setCrosshairEnabled(self, enabled):
    if enabled:
      self.crosshairNode.SetCrosshairMode(slicer.vtkMRMLCrosshairNode.ShowSmallBasic)
      self.crosshairNode.SetCrosshairMode(slicer.vtkMRMLCrosshairNode.ShowSmallBasic)
    else:
      self.crosshairNode.SetCrosshairMode(slicer.vtkMRMLCrosshairNode.NoCrosshair)

  def onReferenceChanged(self, id):
    # TODO: when None is selected, viewers and editor should be resetted
    self.labelMapVisibilityButton.checked = False
    self.fiducialLabelPropagateModel = None
    self.removeAllModels()
    if self.refSelectorIgnoreUpdates:
      return
    text = self.refSelector.currentText
    eligible = text not in ["", "None"]
    self.setCrosshairEnabled(eligible)
    logging.debug('Current reference node: '+text)
    if eligible:
      self.refSeriesNumber = string.split(text,':')[0]
      ref = int(self.refSeriesNumber)
    else:
      return

    logging.debug('Reference series selected: '+str(ref))

    # volume nodes ordered by series number
    seriesNumbers= [int(x) for x in self.seriesMap.keys()]
    seriesNumbers.sort()
    self.volumeNodes = [self.seriesMap[str(x)]['Volume'] for x in seriesNumbers if x != ref]
    self.viewNames = [self.seriesMap[str(x)]['ShortName'] for x in seriesNumbers if x != ref]

    self.volumeNodes = [self.seriesMap[str(ref)]['Volume']]+self.volumeNodes
    self.viewNames = [self.seriesMap[str(ref)]['ShortName']]+self.viewNames

    self.sliceNames = [str(x) for x in seriesNumbers if x != ref]
    self.sliceNames = [str(ref)]+self.sliceNames

    try:
      # check if already have a label for this node
      refLabel = self.seriesMap[str(ref)]['Label']
    except KeyError:
      # create a new label
      labelName = self.seriesMap[str(ref)]['ShortName']+'-label'
      refLabel = self.volumesLogic.CreateAndAddLabelVolume(slicer.mrmlScene,self.volumeNodes[0],labelName)
      self.seriesMap[str(ref)]['Label'] = refLabel

    dNode = refLabel.GetDisplayNode()
    dNode.SetAndObserveColorNodeID(self.mpReviewColorNode.GetID())
    logging.debug('Volume nodes: '+str(self.viewNames))
    self.cvLogic = CompareVolumes.CompareVolumesLogic()

    nVolumeNodes = float(len(self.volumeNodes))
    self.rows = 0
    self.cols = 0
    if nVolumeNodes == 1:
      self.rows = 1
    elif nVolumeNodes<=8:
      self.rows = 2 # up to 8
    elif 8 < nVolumeNodes <= 12:
      self.rows = 3 # up to 12
    elif 12 < nVolumeNodes <= 16:
      self.rows = 4
    self.cols = math.ceil(nVolumeNodes/self.rows)

    self.editorWidget.helper.setVolumes(self.volumeNodes[0], self.seriesMap[str(ref)]['Label'])

    self.cvLogic.viewerPerVolume(self.volumeNodes, background=self.volumeNodes[0], label=refLabel,
                                 layout=[self.rows,self.cols],viewNames=self.sliceNames,
                                 orientation=self.currentOrientation)

    # Make sure redslice has the ref image (the others were set with viewerPerVolume)
    redSliceWidget = self.layoutManager.sliceWidget('Red')
    redSliceNode = redSliceWidget.mrmlSliceNode()
    redSliceNode.SetOrientation(self.currentOrientation)
    compositeNode = redSliceWidget.mrmlSliceCompositeNode()
    compositeNode.SetBackgroundVolumeID(self.volumeNodes[0].GetID())

    self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])
    self.setOpacityOnAllSliceWidgets(1.0)
    self.editUtil.setLabelOutline(self.labelMapOutlineButton.checked)

    self.onViewUpdateRequested(self.viewButtonGroup.checkedId())

    logging.debug('Setting master node for the Editor to '+self.volumeNodes[0].GetID())

    self.editorParameterNode.Modified()

    # default to selecting the first available structure for this volume
    if self.editorWidget.helper.structureListWidget.structures.rowCount() > 0:
      self.editorWidget.helper.structureListWidget.selectStructure(0)

    self.updateEditorAvailability()

    self.multiVolumeExplorer.refreshObservers()
    logging.debug('Exiting onReferenceChanged')

  '''
  def updateViews(self):
    lm = slicer.app.layoutManager()
    w = lm.sliceWidget('Red')
    sl = w.sliceLogic()
    ll = sl.GetLabelLayer()
    lv = ll.GetVolumeNode()
    self.cvLogic.viewerPerVolume(self.volumeNodes, background=self.volumeNodes[0], label=lv,
                                 layout=[self.rows,self.cols])

    self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])
    self.setOpacityOnAllSliceWidgets(1.0)
  '''

  def setOrientation(self, orientation):
    if orientation in self.orientations:
      self.currentOrientation = orientation

      if self.refSelector.currentText != 'None':
        # set slice node orientation
        for widget in self.getAllSliceWidgets():
          node = widget.mrmlSliceNode()
          node.SetOrientation(self.currentOrientation)

        self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])

  def onDeleteStructure(self):
    selectionModel = self.structuresView.selectionModel()
    selected = selectionModel.currentIndex().row()
    if selected >= 0:
      selectedModelVol = self.editorWidget.helper.structureListWidget.structures.item(selected,2).text()

      # Confirm with user
      if not slicer.util.confirmOkCancelDisplay("Delete \'%s\' volume?" % selectedModelVol, title="mpReview"):
        return

      # Cleanup files
      import shutil

      # create backup directory if necessary
      backupSegmentationsDir = os.path.join(self.inputDataDir, self.selectedStudyName,
                                            'RESOURCES', self.refSeriesNumber, 'Backup')
      self.logic.createDirectory(backupSegmentationsDir)
      # move relevant nrrd files
      globPath = os.path.join(self.resourcesDir,self.refSeriesNumber,"Segmentations",
                              self.getSetting('UserName')+'-'+selectedModelVol+'-[0-9]*.nrrd')
      previousSegmentations = glob.glob(globPath)

      filesMoved = True
      for file in previousSegmentations:
        try:
          shutil.move(file, backupSegmentationsDir)
        except:
          logging.debug('Unable to move file: '+file)
          filesMoved = False

      # Cleanup mrml scene if we were able to move all of the files
      if filesMoved:
        self.editorWidget.helper.structureListWidget.deleteSelectedStructure(confirm=False)
        slicer.mrmlScene.RemoveNode(slicer.util.getNode('Model*'+selectedModelVol))

      self.updateEditorAvailability()

  def updateEditorAvailability(self):
    if self.editorWidget.helper.structureListWidget.structures.rowCount() == 0:
      self.editorWidget.editLabelMapsFrame.enabled = False
    else:
      self.editorWidget.editLabelMapsFrame.enabled = True

  def onSliderChanged(self, newValue):
    newValue = int(newValue)
    seriesNumber = self.multiVolumeExplorer.getCurrentSeriesNumber()
    if seriesNumber in self.seriesMap.keys():
      multiVolumeNode = self.seriesMap[seriesNumber]['MultiVolume']
      scalarVolumeNode = MVHelper.extractFrame(self.seriesMap[seriesNumber]['Volume'],
                                                               multiVolumeNode,
                                                               newValue)
      scalarVolumeNode.SetName(multiVolumeNode.GetName().split('_multivolume')[0])
      self.seriesMap[seriesNumber]['Volume'] = scalarVolumeNode
      self.seriesMap[seriesNumber]['FrameNumber'] = newValue
      multiVolumeNode.GetDisplayNode().SetFrameComponent(newValue)

  def getCreatedStructures(self):
    # TODO: usually not all structures shall be available for fiducial creation
    itemModel = self.editorWidget.helper.structureListWidget.structures
    structures = []
    for row in range(itemModel.rowCount()):
      item = dict()
      item["Number"] = itemModel.item(row, 0).text()
      item["Name"] = itemModel.item(row, 2).text()
      item["LabelVolume"] = self.editorWidget.helper.structureListWidget.structures.item(row, 3).text()
      structures.append(item)
    return structures

  def getCheckStatesFromStructureFiducialTable(self):
    itemCheckStates = dict()
    for idx in range(self.fiducialLabelPropagateModel.rowCount()):
      item = self.fiducialLabelPropagateModel.item(idx)
      if item.checkState() != 2:
        number = item.text().split(';')[0]
        itemCheckStates[number] = item.checkState()
    return itemCheckStates

  def updateEligibleLabelList(self):
    savedCheckStates = dict()
    if self.fiducialLabelPropagateModel:
      savedCheckStates = self.getCheckStatesFromStructureFiducialTable()
    self.fiducialLabelPropagateModel = qt.QStandardItemModel()
    self.fiducialLabelPropagateModel.setHorizontalHeaderLabels(['Label'])
    items = []
    for structure in self.structures:
      prefix = str(structure["Number"])
      item = qt.QStandardItem(prefix+";"+structure["Name"]+";"+structure["LabelVolume"])
      item.setCheckable(1)
      if prefix in savedCheckStates.keys():
        item.setCheckState(savedCheckStates[prefix])
      else:
        item.setCheckState(2)
      items.append(item)
      self.fiducialLabelPropagateModel.appendRow(item)
    self.fiducialsPromptListView.setModel(self.fiducialLabelPropagateModel)

  def onCreateFiducialsButtonClicked(self):

    self.structures = self.getCreatedStructures()
    if len(self.structures) == 0:
      return

    self.createFiducialsPrompt = qt.QDialog()
    self.createFiducialsPrompt.setWindowFlags(qt.Qt.WindowStaysOnTopHint)
    fiducialsPromptLayout = qt.QVBoxLayout()
    self.createFiducialsPrompt.setLayout(fiducialsPromptLayout)

    fiducialsPromptLayout.addWidget(qt.QLabel("Select structures you wish to create fiducials from "))

    self.fiducialsPromptListView = qt.QListView()
    self.fiducialsPromptListView.setSpacing(3)
    self.fiducialsPromptListView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)

    self.updateEligibleLabelList()
    fiducialsPromptLayout.addWidget(self.fiducialsPromptListView)

    propagateButton = qt.QPushButton('Create Fiducials', self.fiducialsPromptListView)
    propagateButton.clicked.connect(self.onAcceptFiducialsPrompt)
    fiducialsPromptLayout.addWidget(propagateButton)

    self.createFiducialsPrompt.show()
    self.createFiducialsPrompt.finished.connect(self.onFiducialPromptClosed)
    self.structuresView.connect("activated(QModelIndex)", self.onStructureClickedOrAdded)

  def onFiducialPromptClosed(self):
    self.structuresView.disconnect("activated(QModelIndex)", self.onStructureClickedOrAdded)

  def onStructureClickedOrAdded(self):
    structures = self.getCreatedStructures()
    if len(self.structures) != len(structures):
      self.structures = self.getCreatedStructures()
      self.updateEligibleLabelList()

  def onAcceptFiducialsPrompt(self):
    self.createFiducialsPrompt.close()
    fiducialNode = self.fiducialsWidget.getOrCreateFiducialNode()
    addedFiducialIds = []
    for idx in range(self.fiducialLabelPropagateModel.rowCount()):
      item = self.fiducialLabelPropagateModel.item(idx)
      if item.checkState() == 2:
        splitted = item.text().split(';')
        selectedID = splitted[0]
        #name = splitted[1]
        label = slicer.util.getNode(splitted[2])
        try:
          centroid = ModuleLogicMixin.getCentroidForLabel(label, int(selectedID))
          logging.debug("Creating fiducial at position %f, %f, %f" % tuple(centroid))
          addedFiducialIds.append(fiducialNode.AddFiducialFromArray(centroid, label.GetName()))
        except Exception as exc:
          message = "No label object with label %s. \n You might have forgotten to print a label. To prevent the " \
                    "duplication of fiducials, all fiducials of the current creation step will be deleted. " \
                    "For further information see details." % label.GetName()
          slicer.util.errorDisplay(message, detailedText=str(exc.message), windowTitle='mpReview')
          self.removeFiducialIDsFromNode(fiducialNode, addedFiducialIds)
          return

  def removeFiducialIDsFromNode(self, node, ids):
    for idx in reversed(ids):
      node.RemoveMarkup(idx)

  def onPropagateROI(self):
    # Get the selected label map
    (rowIdx, selectedStructure, selectedLabel, selectedLabelID) = self.getSelectedStructure()
    if selectedLabel is None:
      return

    # Get a list of all series numbers currently loaded
    seriesNumbers= [x for x in self.seriesMap.keys()]
    seriesNumbers.sort()
    loadedVolumes = [self.seriesMap[x] for x in seriesNumbers if x != self.refSeriesNumber]

    # See which volumes we want to propagate to
    self.propagatePrompt = qt.QDialog()
    propagatePromptLayout = qt.QVBoxLayout()
    self.propagatePrompt.setLayout(propagatePromptLayout)

    propagateLabel = qt.QLabel('Select which volumes you wish to propagate '+ selectedLabel +' to...',
                               self.propagatePrompt)
    propagatePromptLayout.addWidget(propagateLabel)

    propagateView = qt.QListView()
    propagateView.setSpacing(3)
    propagateView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
    propagateModel = qt.QStandardItemModel()
    propagateModel.setHorizontalHeaderLabels(['Volume'])

    self.propagateItems = []
    for labelNode in loadedVolumes:
        item = qt.QStandardItem(labelNode['ShortName'])
        item.setCheckable(1)
        item.setCheckState(2)
        self.propagateItems.append(item)
        propagateModel.appendRow(item)

    propagateView.setModel(propagateModel)
    propagatePromptLayout.addWidget(propagateView)

    propagateButton = qt.QPushButton('Propagate', propagateView)
    propagateButton.connect('clicked()', self.propagateSelected)
    propagatePromptLayout.addWidget(propagateButton)

    self.propagatePrompt.exec_()

  def propagateSelected(self):
    self.propagatePrompt.close()

    # get list of destination volumes
    propagateInto = []
    for item in self.propagateItems:
      if item.checkState() == 2:
        selectedID = item.text().split(':')[0]
        propagateInto.append(selectedID)

    # get the source structure
    (rowIdx, selectedStructure, selectedLabel, selectedLabelID) = self.getSelectedStructure()
    if selectedLabel is None:
      return

    srcLabel = slicer.util.getNode(selectedLabel)

    # Check to make sure we don't propagate on top of something
    existingStructures = [self.seriesMap[x]['ShortName'] for x in propagateInto if
                          len(slicer.util.getNodes(self.seriesMap[x]['ShortName']+'-'+selectedStructure+'-label*'))!= 0]
    if len(existingStructures) != 0:
      msg = 'ERROR\n\n\'' + selectedStructure + '\' already exists in the following volumes:\n\n'
      for vol in existingStructures:
        msg += vol + '\n'
      msg += '\nCannot propagate on top of existing structures.  Delete the existing structures and try again.\n'
      slicer.util.infoDisplay(msg, windowTitle="mpReview")
      return

    # Create identity transform
    transform = slicer.vtkMRMLLinearTransformNode()
    slicer.mrmlScene.AddNode(transform)

    # Collects empty dstLabel volumes
    emptyDstLabel = []

    # Do the resamples
    progress = self.createProgressDialog(maximum=len(propagateInto))
    nProcessed = 0
    for dstSeries in propagateInto:
      labelName = self.seriesMap[dstSeries]['ShortName']+'-'+selectedStructure+'-label'
      dstLabel = self.volumesLogic.CreateAndAddLabelVolume(slicer.mrmlScene,
                                                           self.seriesMap[dstSeries]['Volume'],labelName)
      # Need to make sure the new label volume has the correct name
      dstLabel.SetName(labelName)
      dstLabel.GetDisplayNode().SetAndObserveColorNodeID(self.mpReviewColorNode.GetID())

      progress.labelText = labelName
      slicer.app.processEvents()

      # Resample srcSeries labels into the space of dstSeries, store result in tmpLabel
      parameters = {}
      parameters["inputVolume"] = srcLabel.GetID()
      parameters["referenceVolume"] = self.seriesMap[dstSeries]['Volume'].GetID()
      parameters["outputVolume"] = dstLabel.GetID()
      # This transformation node will have just been created so it *should* be set to identity at this point
      parameters["warpTransform"] = transform.GetID()
      parameters["pixelType"] = "short"
      parameters["interpolationMode"] = "NearestNeighbor"
      parameters["defaultValue"] = 0
      parameters["numberOfThreads"] = -1

      self.__cliNode = None
      self.__cliNode = slicer.cli.run(slicer.modules.brainsresample, self.__cliNode, parameters,
                                      wait_for_completion=True)

      # Check to make sure we actually got something in the dstLabel volume
      dstLabelAddress = sitkUtils.GetSlicerITKReadWriteAddress(dstLabel.GetName())
      dstLabelImage = sitk.ReadImage(dstLabelAddress)

      ls = sitk.LabelStatisticsImageFilter()
      ls.Execute(dstLabelImage,dstLabelImage)
      bb = ls.GetBoundingBox(selectedLabelID)

      if len(bb) == 0:
        emptyDstLabel.append(dstLabel)
        logging.debug(labelName + " IS EMPTY")

      progress.setValue(nProcessed)
      nProcessed += 1
      slicer.app.processEvents()
      if progress.wasCanceled:
        break

    progress.delete()

    # Delete the transform node
    slicer.mrmlScene.RemoveNode(transform)


    if len(emptyDstLabel) > 0:
      msg = 'NOTICE\n\nThe following volumes did not get a propagated ROI:\n\n'
      for vol in emptyDstLabel:
        msg += vol.GetName() + '\n'
      msg += '\nAttempt reverse-nearest-neighbor propagation?\n'

      if slicer.util.confirmYesNoDisplay(msg, windowTitle="mpReview") == 0:
        # User doesn't want to try RNN, remove the empty label node
        for dstLabel in emptyDstLabel:
          slicer.mrmlScene.RemoveNode(dstLabel)
      else:
        # Attempt RNN

        # Get bounding box on non-zero label voxels in the source label map
        srcLabelAddress = sitkUtils.GetSlicerITKReadWriteAddress(srcLabel.GetName())
        srcLabelImage = sitk.ReadImage(srcLabelAddress)
        ls.Execute(srcLabelImage,srcLabelImage)
        bb = ls.GetBoundingBox(selectedLabelID)

        # Source label map's IJKtoRAS
        IJKtoRAS = vtk.vtkMatrix4x4()
        srcLabel.GetIJKToRASMatrix(IJKtoRAS)

        for dstLabel in emptyDstLabel:

          dstLabelData = dstLabel.GetImageData()

          # Destination label map's IJKtoRAS
          RAStoIJK = vtk.vtkMatrix4x4()
          dstLabel.GetRASToIJKMatrix(RAStoIJK)

          # Copy the voxels
          for i in range(bb[0], bb[1]+1):
            for j in range(bb[2], bb[3]+1):
              for k in range(bb[4], bb[5]+1):

                if srcLabelImage[i,j,k] != 0:

                  # RAS coord of this non-zero voxel in the source
                  ras = IJKtoRAS.MultiplyPoint([i, j, k, 1])[:3]

                  # IJK coord of the corresponding voxel in the destination
                  ijkFloat = RAStoIJK.MultiplyPoint([ras[0], ras[1], ras[2], 1])[:3]
                  ijk = [int(round(element)) for element in ijkFloat]

                  # Set the voxel value in the destination
                  dstLabelData.SetScalarComponentFromDouble(ijk[0],ijk[1],ijk[2], 0, selectedLabelID)

          # Update the dstLabel volume
          dstLabel.GetImageData().GetPointData().GetScalars().Modified()

    # Restore the foreground images that get knocked out by calling a cli
    self.restoreForeground()

    # Re-select the structure in the list
    self.editorWidget.helper.structureListWidget.selectStructure(rowIdx)

  def selectAllSeries(self, selected=False):
    for item in self.seriesItems:
      item.setCheckState(2 if selected else 0)
    self.setTabsEnabled([1], selected)

  def onTranslate(self):
    if self.ignoreTranslate:
      return

    # Get the label node to translate
    (rowIdx, selectedStructure, selectedLabel, selectedLabelID) = self.getSelectedStructure()
    if selectedLabel is None:
      self.resetTranslate()
      return

    labelNode = slicer.util.getNode(selectedLabel)

    # Lock out the editor and ref selector
    self.editorWidget.volumes.enabled = False
    self.editorWidget.editLabelMapsFrame.enabled = False
    self.refSelector.enabled = False
    self.saveButton.enabled = False

    # enable Harden
    self.hardenTransformButton.enabled = True

    # Reset transformnode
    self.transformNode.Reset(None)

    # Get the IJKtoRAS matrix
    IJKtoRAS = vtk.vtkMatrix4x4()
    labelNode.GetIJKToRASMatrix(IJKtoRAS)

    # is this safe to do so many times?
    labelNode.SetAndObserveTransformNodeID(self.transformNode.GetID())

    # create vtkTransform object
    vTransform = vtk.vtkTransform()

    # Figure out the scan order
    order = labelNode.ComputeScanOrderFromIJKToRAS(IJKtoRAS)
    if order == 'IS':
        logging.debug('Using order = IS')
        result = IJKtoRAS.MultiplyPoint((self.translateLR.value, self.translatePA.value, self.translateIS.value, 0))
        vTransform.Translate(result[0],result[1],result[2])
    elif order == 'AP':
        logging.debug('Using order = AP')
        result = IJKtoRAS.MultiplyPoint((self.translateLR.value, self.translateIS.value, self.translatePA.value, 0))
        vTransform.Translate(result[0],result[1],result[2])
    elif order == 'LR':
        logging.debug('Using order = LR')
        result = IJKtoRAS.MultiplyPoint((self.translatePA.value, self.translateIS.value, self.translateLR.value, 0))
        vTransform.Translate(-result[0],result[1],result[2])

    logging.debug(result)

    # Tell the transform node to observe vTransform's matrix
    self.transformNode.SetMatrixTransformToParent(vTransform.GetMatrix())

  def onHardenTransform(self):
    # Get the selected label
    (rowIdx, selectedStructure, selectedLabel, selectedLabelID) = self.getSelectedStructure()
    if selectedLabel is None:
      return

    labelNode = slicer.util.getNode(selectedLabel)

    # do not observe the transform
    labelNode.SetAndObserveTransformNodeID(None)

    # somehow writing the output to the input node does not behave, need a temp
    resampledLabelNode = slicer.modules.volumes.logic().CloneVolume(slicer.mrmlScene,labelNode,"translated")

    # Resample labels to fix the origin
    parameters = {}
    parameters["inputVolume"] = labelNode.GetID()
    parameters["referenceVolume"] = self.seriesMap[self.refSeriesNumber]['Volume'].GetID()
    parameters["outputVolume"] = resampledLabelNode.GetID()
    parameters["warpTransform"] = self.transformNode.GetID()
    parameters["pixelType"] = "short"
    parameters["interpolationMode"] = "NearestNeighbor"
    parameters["defaultValue"] = 0
    parameters["numberOfThreads"] = -1

    self.__cliNode = None
    self.__cliNode = slicer.cli.run(slicer.modules.brainsresample, self.__cliNode, parameters, wait_for_completion=True)

    # get the image data and get rid of the temp
    labelNode.SetAndObserveImageData(resampledLabelNode.GetImageData())
    slicer.mrmlScene.RemoveNode(resampledLabelNode)

    # Reset sliders, button, and restore editor
    self.resetTranslate()

    # Restore the foreground images that get knocked out by calling a cli
    self.restoreForeground()

    # Re-select the structure in the list
    self.editorWidget.helper.structureListWidget.selectStructure(rowIdx)

  def resetTranslate(self):
    # Reset sliders and buttons
    self.ignoreTranslate = True
    self.translateLR.value = 0
    self.translatePA.value = 0
    self.translateIS.value = 0
    self.ignoreTranslate = False
    self.hardenTransformButton.enabled = False

    # Restore out the editor, ref selector, and save
    self.editorWidget.volumes.enabled = True
    self.editorWidget.editLabelMapsFrame.enabled = True
    self.refSelector.enabled = True
    self.saveButton.enabled = True

  # Returns info about the currently selected structure in structuresView
  def getSelectedStructure(self):
    selectedIdx = self.structuresView.currentIndex()
    selectedRow = selectedIdx.row()
    if selectedRow < 0:
      return selectedRow, None, None, None

    selectedLabelID = int(self.editorWidget.helper.structureListWidget.structures.item(selectedRow,0).text())
    selectedStructure = self.editorWidget.helper.structureListWidget.structures.item(selectedRow,2).text()
    selectedLabel = self.editorWidget.helper.structureListWidget.structures.item(selectedRow,3).text()
    return selectedRow, selectedStructure, selectedLabel, selectedLabelID

  def restoreForeground(self):
    # This relies on slice view names and also (apparently) trashes zoom levels
    # Is there a better way to do this?
    for view in self.layoutManager.sliceViewNames():
      widget = self.layoutManager.sliceWidget(view)
      compositeNode = widget.mrmlSliceCompositeNode()
      try:
        compositeNode.SetForegroundVolumeID(self.seriesMap[view]['Volume'].GetID())
      except:
        pass

  # Gets triggered on a click in the structures table
  def onStructureClicked(self,index):
    self.labelMapVisibilityButton.checked = False
    selectedLabelID = int(self.editorWidget.helper.structureListWidget.structures.item(index.row(),0).text())
    selectedLabelVol = self.editorWidget.helper.structureListWidget.structures.item(index.row(),3).text()
    if self.enableJumpToROI.checked:
      logging.debug('calling onJumpToROI '+str(selectedLabelID) + ' ' + selectedLabelVol)
      self.onJumpToROI(selectedLabelID,selectedLabelVol)
    self.updateEditorAvailability()

  def onJumpToROI(self, selectedLabelID, selectedLabelVol):

    logging.debug('Jumping to ROI #' + str(selectedLabelID))
    labelNode = slicer.util.getNode(selectedLabelVol)

    centroid = ModuleLogicMixin.getCentroidForLabel(labelNode, int(selectedLabelID))

    if centroid:
      # Set the appropriate offset based on current orientation
      if self.currentOrientation == 'Axial':
        self.setOffsetOnAllSliceWidgets(centroid[2])
      elif self.currentOrientation == 'Coronal':
        self.setOffsetOnAllSliceWidgets(centroid[1])
      elif self.currentOrientation == 'Sagittal':
        self.setOffsetOnAllSliceWidgets(centroid[0])

      # snap to IJK to try and avoid rounding errors
      sliceLogics = self.layoutManager.mrmlSliceLogics()
      numLogics = sliceLogics.GetNumberOfItems()
      for n in range(numLogics):
        l = sliceLogics.GetItemAsObject(n)
        l.SnapSliceOffsetToIJK()


class mpReviewLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget
  """

  @staticmethod
  def wasmpReviewPreprocessed(directory):
    return len(mpReviewLogic.getStudyNames(directory)) > 0

  @staticmethod
  def getStudyNames(directory):
    def getSubDirectories(currentDirectory):
      return [d for d in os.listdir(currentDirectory) if os.path.isdir(os.path.join(currentDirectory, d))]
    return [d for d in getSubDirectories(directory) if "RESOURCES" in getSubDirectories(os.path.join(directory, d))]

  @staticmethod
  def createDirectory(directory, message=None):
    if message:
      logging.debug(message)
    try:
      os.makedirs(directory)
    except OSError:
      logging.debug('Failed to create the following directory: ' + directory)

  @staticmethod
  def cleanupDir(d):
    if not os.path.exists(d):
      return
    oldFiles = os.listdir(d)
    for f in oldFiles:
      path = os.path.join(d, f)
      if not os.path.isdir(path):
        os.unlink(d+'/'+f)

  @staticmethod
  def isSeriesOfInterest(desc):
    discardThose = ['SAG','COR','PURE','mapping','DWI',
                    'breath','3D DCE','loc','Expo','Map',
                    'MAP','POST','ThreeParameter','AutoAIF',
                    'BAT','-Slope','PkRsqr','Loc','Cal','Body']
    for d in discardThose:
      if string.find(desc,d)>=0:
        return False
    return True

  @staticmethod
  def abbreviateName(meta):
    try:
      description = meta['SeriesDescription']
      seriesNumber = meta['SeriesNumber']
    except:
      description = meta['DerivedSeriesDescription']
      seriesNumber = meta['DerivedSeriesNumber']
    abbr = 'Unknown'

    substrAbbreviation = {'Apparent Diffusion Coeff': 'ADC', 'T2':'T2', 'T1':'T1', 'Ktrans':'Ktrans', 'Ve':'ve',
                          'MaxSlope':'MaxSlope', 'TTP':'TTp', 'Auc':'AUC', }

    for substring, abbreviation in substrAbbreviation.iteritems():
      if substring in description:
        abbr = abbreviation
    if re.search('[a-zA-Z]',description) is None:
      abbr = 'Subtract'
    return seriesNumber+'-'+abbr

  def __init__(self, parent=None):
    ScriptedLoadableModuleLogic.__init__(self, parent)

  @staticmethod
  def loadColorTable(colorFile):
    colorNode = slicer.vtkMRMLColorTableNode()
    colorNode.SetName('mpReview')
    slicer.mrmlScene.AddNode(colorNode)
    colorNode.SetTypeToUser()
    with open(colorFile) as f:
      n = sum(1 for line in f)
    colorNode.SetNumberOfColors(n - 1)
    colorNode.NamesInitialisedOn()
    import csv
    structureNames = []
    with open(colorFile, 'rb') as csvfile:
      reader = csv.DictReader(csvfile, delimiter=',')
      for index, row in enumerate(reader):
        success = colorNode.SetColor(index, row['Label'], float(row['R']) / 255,
                                     float(row['G']) / 255, float(row['B']) / 255, float(row['A']))
        if not success:
          print "color %s could not be set" % row['Label']
        structureNames.append(row['Label'])
    return colorNode, structureNames

  @staticmethod
  def loadMpReviewProcessedData(resourcesDir, updateProgressCallback=None):
    loadFurtherInformation = False # True

    sourceFile = None

    nLoaded = 0
    seriesMap = {}
    for root, dirs, files in os.walk(resourcesDir):
      logging.debug('Root: '+root+', files: '+str(files))
      resourceType = os.path.split(root)[1]
      logging.debug('Resource: '+resourceType)

      if resourceType == 'Reconstructions':
        seriesNumber = None
        seriesDescription = None

        # mpReviewPreprocessor generated tree
        for currentXMLFile in [f for f in files if f.endswith('.xml')]:
          metaFile = os.path.join(root, currentXMLFile)
          logging.debug('Current XML File: ' + metaFile)
          try:
            (seriesNumber, seriesDescription) = mpReviewLogic.getSeriesInfoFromXML(metaFile)
            logging.debug(str(seriesNumber)+' '+seriesDescription)
          except Exception as exc:
            logging.error('Failed to get from XML: %s' % str(exc))
            continue

        # mpReviewPreprocessor2 generated tree
        if seriesNumber is None or seriesDescription is None:
          for currentJSONFile in [f for f in files if f.endswith('.json')]:
            metaFile = os.path.join(root, currentJSONFile)
            try:
              bidsJSON = json.load(open(metaFile))
              seriesNumber = str(bidsJSON["SeriesNumber"])
              seriesDescription = bidsJSON["SeriesDescription"]
            except Exception as exc:
              logging.error('Failed to get from JSON: %s' % str(exc))

          if updateProgressCallback:
            updateProgressCallback(labelText=seriesDescription, value=nLoaded)
          nLoaded += 1

        volumePath = None
        reconDirFiles = os.listdir(root)
        # considering there may be different paths to reconstruction, take the
        # first suitable format
        for f in reconDirFiles:
          type = f[f.find(".")+1:]
          if type in ["nrrd", "nii", "nii.gz"]:
            volumePath = f
            break

        if volumePath is None:
          logging.error("Failed to find reconstructed volume file.")
          continue

        seriesMap[seriesNumber] = {'MetaInfo':None, 'NRRDLocation':volumePath,'LongName':seriesDescription}
        seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+seriesDescription
        if loadFurtherInformation is True:
          sourceFile = metaFile
          loadFurtherInformation = False

      # ignore the PK maps for the purposes of segmentation
      if resourceType == 'OncoQuant' and False:
        for f in files:
          if f.endswith('.json'):
            metaFile = open(os.path.join(root,f))
            metaInfo = json.load(metaFile)
            logging.debug('JSON meta info: '+str(metaInfo))
            try:
              seriesNumber = metaInfo['SeriesNumber']
              seriesDescription = metaInfo['SeriesDescription']
            except:
              seriesNumber = metaInfo['DerivedSeriesNumber']
              seriesDescription = metaInfo['ModelType']+'-'+metaInfo['AIF']+'-'+metaInfo['Parameter']
            volumePath = os.path.join(root,seriesNumber+'.nrrd')
            seriesMap[seriesNumber] = {'MetaInfo':metaInfo, 'NRRDLocation':volumePath,'LongName':seriesDescription}
            seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":" + \
                                                   mpReviewLogic.abbreviateName(seriesMap[seriesNumber]['MetaInfo'])

    logging.debug('All series found: '+str(seriesMap.keys()))
    return seriesMap, sourceFile

  @staticmethod
  def getSeriesInfoFromXML(f):

    def findElement(dom, name):
      els = dom.getElementsByTagName('element')
      for e in els:
        if e.getAttribute('name') == name:
          return e.childNodes[0].nodeValue

    dom = xml.dom.minidom.parse(f)
    number = findElement(dom, 'SeriesNumber')
    name = findElement(dom, 'SeriesDescription').encode('utf-8').strip()
    return number, name.replace('-','').replace('(','').replace(')','')

  def formatDate(self, extractedDate):
    formatted = datetime.date(int(extractedDate[0:4]), int(extractedDate[4:6]), int(extractedDate[6:8]))
    return formatted.strftime("%Y-%b-%d")

  def hasImageData(self,volumeNode):
    """This is a dummy logic method that
    returns true if the passed in volume
    node has valid image data
    """
    if not volumeNode:
      logging.debug('no volume node')
      return False
    if volumeNode.GetImageData() is None:
      logging.debug('no image data')
      return False
    return True


class mpReviewMultiVolumeExplorer(qSlicerMultiVolumeExplorerSimplifiedModuleWidget):

  def __init__(self, parent=None):
    qSlicerMultiVolumeExplorerSimplifiedModuleWidget.__init__(self, parent)

  def getCurrentSeriesNumber(self):
    ref = -1
    if self._bgMultiVolumeNode:
      name = self._bgMultiVolumeNode.GetName()
      ref = string.split(name,':')[0]
    return ref
  def showInputMultiVolumeSelector(self, show):
    if show:
      self._bgMultiVolumeSelectorLabel.show()
      self.bgMultiVolumeSelector.show()
    else:
      self._bgMultiVolumeSelectorLabel.hide()
      self.bgMultiVolumeSelector.hide()

  def setMultiVolume(self, node):
    self.bgMultiVolumeSelector.setCurrentNode(node)

  def setupConnections(self):
    qSlicerMultiVolumeExplorerSimplifiedModuleWidget.setupConnections(self)

  def createChart(self, sliceWidget, position):
    self._multiVolumeIntensityChart.createChart(sliceWidget, position, ignoreCurrentBackground=True)

  def refreshGUIForNewBackgroundImage(self):
    self._multiVolumeIntensityChart.reset()
    self.setFramesEnabled(True)
    self.refreshFrameSlider()
    self._multiVolumeIntensityChart.bgMultiVolumeNode = self._bgMultiVolumeNode

  def onBackgroundInputChanged(self):
    qSlicerMultiVolumeExplorerSimplifiedModuleWidget.onBackgroundInputChanged(self)
    self.popupChartButton.setEnabled(self._bgMultiVolumeNode is not None)

  def onSliderChanged(self, frameId):
    return
