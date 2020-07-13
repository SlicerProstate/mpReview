from __future__ import division
import os, json, xml.dom.minidom, string, glob, re, math
import vtk, qt, ctk, slicer
import logging
import CompareVolumes
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

    # mrml node for invoking command line modules
    self.CLINode = None
    self.logic = mpReviewLogic()
    self.multiVolumeExplorer = None

    # set up temporary directory
    self.tempDir = os.path.join(slicer.app.temporaryPath, 'mpReview-tmp')
    self.logic.createDirectory(self.tempDir, message='Temporary directory location: ' + self.tempDir)
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

    if currentIndex == 2:
      self.editorWidget.installKeyboardShortcuts()
    else:
      self.editorWidget.setActiveEffect(None)
      self.editorWidget.uninstallKeyboardShortcuts()
      self.editorWidget.removeViewObservations()

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

    self.editorWidget = slicer.qMRMLSegmentEditorWidget()
    self.editorWidget.defaultTerminologyEntrySettingsKey = "mpReview/DefaultTerminologyEntry"
    self.editorWidget.setMaximumNumberOfUndoStates(10)
    self.editorWidget.setMRMLScene(slicer.mrmlScene)
    self.editorWidget.unorderedEffectsVisible = False
    self.editorWidget.setEffectNameOrder(["Paint", "Draw", "Erase", "Fill between slices", "Margin"])
    self.editorWidget.jumpToSelectedSegmentEnabled = True
    self.editorWidget.switchToSegmentationsButtonVisible = False

    # Select parameter set node if one is found in the scene, and create one otherwise
    segmentEditorSingletonTag = "mpReviewSegmentEditor"
    segmentEditorNode = slicer.mrmlScene.GetSingletonNode(segmentEditorSingletonTag, "vtkMRMLSegmentEditorNode")
    if segmentEditorNode is None:
      segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
      segmentEditorNode.SetSingletonTag(segmentEditorSingletonTag)
      segmentEditorNode = slicer.mrmlScene.AddNode(segmentEditorNode)
    if self.editorWidget.mrmlSegmentEditorNode() != segmentEditorNode:
      self.editorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

    self.segmentationWidgetLayout.addWidget(self.editorWidget)

    self.modelsVisibilityButton = self.createButton('Hide', checkable=True)
    self.labelMapVisibilityButton = self.createButton('Hide', checkable=True)
    self.labelMapOutlineButton = self.createButton('Outline', checkable=True)
    self.enableJumpToROI = qt.QCheckBox("Jump to ROI")
    self.enableJumpToROI.checked = self.editorWidget.jumpToSelectedSegmentEnabled
    modelsFrame = self.createHLayout([qt.QLabel('Structure Models: '),
                                      self.modelsVisibilityButton, self.labelMapVisibilityButton,
                                      self.labelMapOutlineButton, self.enableJumpToROI])
    self.segmentationWidgetLayout.addWidget(modelsFrame)

  def setupAdvancedSegmentationSettingsUI(self):
    self.advancedSettingsArea = ctk.ctkCollapsibleButton()
    self.advancedSettingsArea.text = "Advanced Settings"
    self.advancedSettingsArea.collapsed = True

    self.setupSingleMultiViewSettingsUI()
    self.setupViewerOrientationSettingsUI()

    advancedSettingsLayout = qt.QFormLayout(self.advancedSettingsArea)
    advancedSettingsLayout.addRow("Show series: ", self.groupWidget)
    advancedSettingsLayout.addRow('View orientation: ', self.orientationBox)
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

    self.dataDirButton.directorySelected.connect(lambda: setattr(self, "inputDataDir", self.dataDirButton.directory))
    self.selectAllSeriesButton.connect('clicked()', lambda: self.selectAllSeries(True))
    self.deselectAllSeriesButton.connect('clicked()', lambda: self.selectAllSeries(False))
    self.modelsVisibilityButton.connect("toggled(bool)", self.onModelsVisibilityButton)
    self.labelMapVisibilityButton.connect("toggled(bool)", self.onLabelMapVisibilityButton)
    self.labelMapOutlineButton.connect('toggled(bool)', self.setLabelOutline)
    self.piradsButton.connect('clicked()', self.onPIRADSFormClicked)
    self.qaButton.connect('clicked()', self.onQAFormClicked)
    self.saveButton.connect('clicked()', self.onSaveClicked)
    for orientation in self.orientations:
      self.orientationButtons[orientation].connect("clicked()", lambda o=orientation: self.setOrientation(o))
    self.viewButtonGroup.connect('buttonClicked(int)', self.onViewUpdateRequested)

    self.enableJumpToROI.connect('toggled(bool)', self.editorWidget.setJumpToSelectedSegmentEnabled)

    self.multiVolumeExplorer.frameSlider.connect('valueChanged(double)', self.onSliderChanged)

    self.studiesView.selectionModel().connect('currentChanged(QModelIndex, QModelIndex)', self.onStudySelected)
    self.seriesView.connect('clicked(QModelIndex)', self.onSeriesSelected)
    self.editorWidget.connect("currentSegmentIDChanged(QString)", self.onStructureClicked)

    self.refSelector.connect('currentIndexChanged(int)', self.onReferenceChanged)
    self.tabWidget.connect('currentChanged(int)',self.onTabWidgetClicked)

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
    self.terminologyFile = os.path.join(self.resourcesPath, "SegmentationCategoryTypeModifier-mpReview.json")
    self.customLUTInfoIcon.show()
    self.customLUTInfoIcon.toolTip = 'Using Default Terminology'

    # Check for custom LUT
    terminologyFileLoc = os.path.join(self.inputDataDir, 'SETTINGS', self.inputDataDir.split(os.sep)[-1] + '-terminology.json')
    logging.debug('Checking for lookup table at : ' + terminologyFileLoc)
    if os.path.isfile(terminologyFileLoc):
      # use custom color table
      self.terminologyFile = terminologyFileLoc
      self.customLUTInfoIcon.toolTip = 'Project-Specific terminology Found'

    tlogic = slicer.modules.terminologies.logic()
    self.terminologyName = tlogic.LoadTerminologyFromFile(self.terminologyFile)

    # Set the first entry in this terminology as the default so that when the user
    # opens the terminoogy selector, the correct list is shown.
    terminologyEntry = slicer.vtkSlicerTerminologyEntry()
    terminologyEntry.SetTerminologyContextName(self.terminologyName)
    tlogic.GetNthCategoryInTerminology(self.terminologyName, 0, terminologyEntry.GetCategoryObject())
    tlogic.GetNthTypeInTerminologyCategory(self.terminologyName, terminologyEntry.GetCategoryObject(), 0, terminologyEntry.GetTypeObject())
    defaultTerminologyEntry = tlogic.SerializeTerminologyEntry(terminologyEntry)
    self.editorWidget.defaultTerminologyEntry = defaultTerminologyEntry

    self.structureNames = []
    numberOfTerminologyTypes = tlogic.GetNumberOfTypesInTerminologyCategory(self.terminologyName, terminologyEntry.GetCategoryObject())
    for terminologyTypeIndex in range(numberOfTerminologyTypes):
      tlogic.GetNthTypeInTerminologyCategory(self.terminologyName, terminologyEntry.GetCategoryObject(), terminologyTypeIndex, terminologyEntry.GetTypeObject())
      self.structureNames.append(terminologyEntry.GetTypeObject().GetCodeMeaning())

    print(self.structureNames)

    # import json
    # with open(self.terminologyFile) as f:
    #   termData = json.load(f)
    # termCategory = termData["SegmentationCodes"]["Category"][0]
    # termType = termCategory["Type"][0]
    # # defaultTerminologyEntry should look something like this:
    # #   "Segmentation category and type - mpReview~SCT^85756007^Tissue~mpReview^1^WholeGland~^^~Anatomic codes - DICOM master list~^^~^^"
    # defaultTerminologyEntry = (termData["SegmentationCategoryTypeContextName"]
    #   + "~" + termCategory["CodingSchemeDesignator"] + "^" + termCategory["CodeValue"] "^" + termCategory["CodeMeaning"]
    #   + "~" + termType["CodingSchemeDesignator"] + "^" + termType["CodeValue"] "^" + termType["CodeMeaning"]
    #   + "~^^"
    #   + "~Anatomic codes - DICOM master list~^^~^^")

    # There should be a way to set default terminology entry in the widget instead of in the global application settings
    #qt.QSettings().setValue("Segmentations/DefaultTerminologyEntry", defaultTerminologyEntry)

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

  def setLabelOutline(self, toggled):
    # Update button text
    if toggled:
      self.labelMapOutlineButton.setText('Filled')
    else:
      self.labelMapOutlineButton.setText('Outline')

    # Set outline on widgets
    self.editorWidget.segmentationNode().GetDisplayNode().SetVisibility2DFill(not toggled)

  def onModelsVisibilityButton(self,toggled):
    if self.refSeriesNumber != '-1':
      ref = self.refSeriesNumber
      refLongName = self.seriesMap[ref]['LongName']

      outHierarchy = None
      numNodes = slicer.mrmlScene.GetNumberOfNodesByClass( "vtkMRMLModelHierarchyNode" )
      for n in range(numNodes):
        node = slicer.mrmlScene.GetNthNodeByClass( n, "vtkMRMLModelHierarchyNode" )
        if node.GetName() == 'mpReview-'+refLongName:
          outHierarchy = node
          break

      if outHierarchy:
        collection = vtk.vtkCollection()
        outHierarchy.GetChildrenModelNodes(collection)
        n = collection.GetNumberOfItems()
        if n != 0:
          for i in range(n):
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

    for structure,fileName in iter(latestSegmentations.items()):
      label = slicer.util.loadSegmentation(fileName)
      logging.debug('Setting loaded label name to '+volumeName)
      label.SetName(volumeName+'-'+structure+'-label')
      #label.RemoveAllDisplayNodeIDs()

      #dNode = slicer.vtkMRMLLabelMapVolumeDisplayNode()
      #slicer.mrmlScene.AddNode(dNode)
      #dNode.SetAndObserveColorNodeID(self.mpReviewColorNode.GetID())
      #label.SetAndObserveDisplayNodeID(dNode.GetID())

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
    return False

  def onStep1Selected(self):
    if self.checkStep2or3Leave() is True:
      return False
    self.setCrosshairEnabled(False)

    self.editorWidget.setActiveEffect(None)
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
      try:
        sItem.setToolTip(self.seriesMap[str(s)]['SeriesTypeAnnotation'])
        print("Setting tooltip "+self.seriesMap[str(s)]['SeriesTypeAnnotation']+" for "+str(s))
      except KeyError:
        pass
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

    # if any volumes have been loaded (we returned back from a previous step)
    # then remove all of them from the scene
    allVolumeNodes = slicer.util.getNodes('vtkMRML*VolumeNode*')
    for node in allVolumeNodes.values():
      slicer.mrmlScene.RemoveNode(node)

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
      print("Loading file from "+fileName)
      volume = slicer.util.loadVolume(fileName)
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
    self.editorWidget.setActiveEffect(None)
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
      multiVolume = max(multiVolumes, key=lambda mv: mv.GetNumberOfFrames())
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
    if self.refSelectorIgnoreUpdates:
      return
    text = self.refSelector.currentText
    eligible = text not in ["", "None"]
    self.setCrosshairEnabled(eligible)
    logging.debug('Current reference node: '+text)
    if eligible:
      self.refSeriesNumber = text.split(':')[0]
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
      refLabel = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", labelName)
      self.seriesMap[str(ref)]['Label'] = refLabel

    # dNode = refLabel.GetDisplayNode()
    # dNode.SetAndObserveColorNodeID(self.mpReviewColorNode.GetID())
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

    self.editorWidget.setSegmentationNode(self.seriesMap[str(ref)]['Label'])
    self.editorWidget.setMasterVolumeNode(self.volumeNodes[0])

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
    self.editorWidget.segmentationNode().GetDisplayNode().SetVisibility2DFill(not self.labelMapOutlineButton.checked)

    self.onViewUpdateRequested(self.viewButtonGroup.checkedId())

    logging.debug('Setting master node for the Editor to '+self.volumeNodes[0].GetID())

    # # default to selecting the first available structure for this volume
    # if self.editorWidget.helper.structureListWidget.structures.rowCount() > 0:
    #   self.editorWidget.helper.structureListWidget.selectStructure(0)

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

  def onFiducialPromptClosed(self):
    pass  #self.structuresView.disconnect("activated(QModelIndex)", self.onStructureClickedOrAdded)

  def onStructureClickedOrAdded(self):
    structures = self.getCreatedStructures()
    if len(self.structures) != len(structures):
      self.structures = self.getCreatedStructures()

  def selectAllSeries(self, selected=False):
    for item in self.seriesItems:
      item.setCheckState(2 if selected else 0)
    self.setTabsEnabled([1], selected)

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
  def onStructureClicked(self, segmentID):
    self.labelMapVisibilityButton.checked = False

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
      if desc.find(d)>=0:
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

    for substring, abbreviation in iter(substrAbbreviation.items()):
      if substring in description:
        abbr = abbreviation
    if re.search('[a-zA-Z]',description) is None:
      abbr = 'Subtract'
    return seriesNumber+'-'+abbr

  def __init__(self, parent=None):
    ScriptedLoadableModuleLogic.__init__(self, parent)


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
              seriesDescription = mpReviewLogic.normalizeSeriesDescription(bidsJSON["SeriesDescription"])
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
          if f.endswith(".nrrd")>0 or f.endswith(".nii")>0 or f.endswith(".nii.gz")>0:
            volumePath = os.path.join(root, f)
            break

        if volumePath is None:
          logging.error("Failed to find reconstructed volume file.")
          continue

        seriesMap[seriesNumber] = {'MetaInfo':None, 'NRRDLocation':volumePath,'LongName':seriesDescription}
        seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+seriesDescription

        canonicalFile = os.path.join(os.path.split(root)[0], "Canonical", seriesNumber+".json")
        try:
          canonicalDict = json.load(open(canonicalFile))
          if "SeriesTypeAnnotation" in canonicalDict.keys():
            seriesMap[seriesNumber]['SeriesTypeAnnotation'] = canonicalDict['SeriesTypeAnnotation']
            print("Setting SeriesTypeAnnotation to "+canonicalDict['SeriesTypeAnnotation']+" for series "+seriesNumber)
        except (OSError, IOError) as e:
          pass

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
    name = self.normalizeSeriesDescription(findElement(dom, 'SeriesDescription').encode('utf-8').strip())
    return number, name

  @staticmethod
  def normalizeSeriesDescription(name):
    import re
    pattern = re.compile('[^a-zA-Z0-9_ ]')
    normalized_name = pattern.sub('_', name)
    return normalized_name

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
      ref = name.split(':')[0]
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
