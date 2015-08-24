from __future__ import division
import os, json, xml.dom.minidom, string, glob, re, math
import unittest
from __main__ import vtk, qt, ctk, slicer
import CompareVolumes
from Editor import EditorWidget
from EditorLib import EditorLib
import SimpleITK as sitk
import sitkUtils
from slicer.ScriptedLoadableModule import *


class PCampReview(ScriptedLoadableModule):

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "PCampReview"
    parent.categories = ["Radiology"]
    parent.dependencies = []
    parent.contributors = ["PCampReview"] # replace with "Firstname Lastname (Org)"
    parent.helpText = """
    """
    parent.acknowledgementText = """
    Supported by NIH U01CA151261 (PI Fennessy)
    """ # replace with organization, grant and thanks.
    self.parent = parent

    # Add this test to the SelfTest module's list for discovery when the module
    # is created.  Since this module may be discovered before SelfTests itself,
    # create the list if it doesn't already exist.
    try:
      slicer.selfTests
    except AttributeError:
      slicer.selfTests = {}
    slicer.selfTests['PCampReview'] = self.runTest


class PCampReviewWidget(ScriptedLoadableModuleWidget):

  VIEWFORM_URL = 'https://docs.google.com/forms/d/1Xwhvjn_HjRJAtgV5VruLCDJ_eyj1C-txi8HWn8VyXa4/viewform'

  @staticmethod
  def makeProgressIndicator(maxVal):
    progressIndicator = qt.QProgressDialog()
    progressIndicator.minimumDuration = 0
    progressIndicator.modal = True
    progressIndicator.setMaximum(maxVal)
    progressIndicator.setValue(0)
    progressIndicator.setWindowTitle("Processing...")
    progressIndicator.show()
    return progressIndicator

  @staticmethod
  def confirmDialog(message):
    result = qt.QMessageBox.question(slicer.util.mainWindow(), 'PCampReview', message,
                                     qt.QMessageBox.Ok | qt.QMessageBox.Cancel)
    return result == qt.QMessageBox.Ok

  @staticmethod
  def yesNoDialog(message):
    result = qt.QMessageBox.question(slicer.util.mainWindow(), 'PCampReview', message,
                                     qt.QMessageBox.Yes | qt.QMessageBox.No)
    return result == qt.QMessageBox.Yes

  @staticmethod
  def confirmOrSaveDialog(message):
    box = qt.QMessageBox(qt.QMessageBox.Question, 'PCampReview', message)
    box.addButton("Exit, discard changes", qt.QMessageBox.AcceptRole)
    box.addButton("Save changes", qt.QMessageBox.ActionRole)
    box.addButton("Cancel", qt.QMessageBox.RejectRole)
    return box.exec_()

  @staticmethod
  def infoPopup(message):
    messageBox = qt.QMessageBox()
    messageBox.information(None, 'Slicer mpMRI review', message)

  @staticmethod
  def createDirectory(directory, message=None):
    if message:
      print message
    try:
      os.makedirs(directory)
    except OSError:
      print('Failed to create the following directory: ' + directory)

  @staticmethod
  def getLayoutManager():
    return slicer.app.layoutManager()

  def __init__(self, parent = None):
    ScriptedLoadableModuleWidget.__init__(self, parent)
    self.resourcesPath = os.path.join(slicer.modules.pcampreview.path.replace(self.moduleName+".py",""), 'Resources')

    inputDataDir = self.getSetting('InputLocation')
    self.inputDataDir = inputDataDir if inputDataDir is not None else ''

    self.webFormURL = ''
    
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
    self.currentStep = 1
    self.logic = PCampReviewLogic()

  def getSetting(self, settingName):
    settings = qt.QSettings()
    return settings.value(self.moduleName + '/' + settingName)

  def setSetting(self, settingName, value):
    settings = qt.QSettings()
    settings.setValue(self.moduleName + '/'+ settingName, value)

  def getAllSliceWidgets(self):
    layoutManager = self.getLayoutManager()
    widgetNames = layoutManager.sliceViewNames()
    return [layoutManager.sliceWidget(wn) for wn in widgetNames]

  def setOffsetOnAllSliceWidgets(self,offset):
    for widget in self.getAllSliceWidgets():
      node = widget.mrmlSliceNode()
      node.SetSliceOffset(offset)

  def linkAllSliceWidgets(self,link):
    for widget in self.getAllSliceWidgets():
      sc = widget.mrmlSliceCompositeNode()
      sc.SetLinkedControl(link)
      sc.SetInteractionFlagsModifier(4+8+16)

  def setOpacityOnAllSliceWidgets(self,opacity):
    for widget in self.getAllSliceWidgets():
      sc = widget.mrmlSliceCompositeNode()
      sc.SetForegroundOpacity(opacity)

  def updateViewRenderers (self):
    for widget in self.getAllSliceWidgets():
      view = widget.sliceView()
      view.scheduleRender()

  def setupIcons(self):
    def createQIconFromPath(path):
      return qt.QIcon(qt.QPixmap(path))

    iconPath = os.path.join(self.resourcesPath, 'Icons')
    self.dataSourceSelectionIcon = createQIconFromPath(os.path.join(iconPath,'icon-dataselection_fit.png'))
    self.studySelectionIcon = createQIconFromPath(os.path.join(iconPath, 'icon-studyselection_fit.png'))
    self.seriesSelectionIcon = createQIconFromPath(os.path.join(iconPath, 'icon-seriesselection_fit.png'))
    self.segmentationIcon = createQIconFromPath(os.path.join(iconPath, 'icon-segmentation_fit.png'))
    self.completionIcon = createQIconFromPath(os.path.join(iconPath, 'icon-completion_fit.png'))

  def setupTabBarNavigation(self):
    self.tabWidget = qt.QTabWidget()
    self.layout.addWidget(self.tabWidget)
    self.tabBar = self.tabWidget.childAt(1, 1)

    self.dataSourceSelectionGroupBox = qt.QGroupBox()
    self.studySelectionGroupBox = qt.QGroupBox()
    self.seriesSelectionGroupBox = qt.QGroupBox()
    self.segmentationGroupBox = qt.QGroupBox()
    self.completionGroupBox = qt.QGroupBox()

    self.dataSourceSelectionGroupBoxLayout = qt.QFormLayout()
    self.studySelectionGroupBoxLayout = qt.QGridLayout()
    self.seriesSelectionGroupBoxLayout = qt.QGridLayout()
    self.segmentationGroupBoxLayout = qt.QFormLayout()
    self.completionGroupBoxLayout = qt.QFormLayout()

    self.dataSourceSelectionGroupBox.setLayout(self.dataSourceSelectionGroupBoxLayout)
    self.studySelectionGroupBox.setLayout(self.studySelectionGroupBoxLayout)
    self.seriesSelectionGroupBox.setLayout(self.seriesSelectionGroupBoxLayout)
    self.segmentationGroupBox.setLayout(self.segmentationGroupBoxLayout)
    self.completionGroupBox.setLayout(self.completionGroupBoxLayout)

    self.tabWidget.setIconSize(qt.QSize(85, 30))

    self.tabWidget.addTab(self.dataSourceSelectionGroupBox,self.dataSourceSelectionIcon, '')
    self.tabWidget.addTab(self.studySelectionGroupBox, self.studySelectionIcon, '')
    self.tabWidget.addTab(self.seriesSelectionGroupBox, self.seriesSelectionIcon, '')
    self.tabWidget.addTab(self.segmentationGroupBox, self.segmentationIcon, '')
    self.tabWidget.addTab(self.completionGroupBox, self.completionIcon, '')
    self.tabWidget.connect('currentChanged(int)',self.onTabWidgetClicked)

    self.setTabsEnabled([1,2,3,4], False)

  def onTabWidgetClicked(self, currentIndex):
    if currentIndex == 0:
      self.onStep1Selected()
    if currentIndex == 1:
      self.onStep2Selected()
    if currentIndex == 2:
      self.onStep3Selected()
    if currentIndex == 3:
      self.onStep4Selected()
    if currentIndex == 4:
      self.onStep5Selected()

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)
    # Instantiate and connect widgets ...

    self.setupIcons()
    self.setupTabBarNavigation()

    self.parameters = {}

    #
    # Step 1: selection of the data directory
    #
    self.dataDirButton = qt.QPushButton(self.inputDataDir)
    self.dataDirButton.connect('clicked()', self.onInputDirSelected)
    self.dataSourceSelectionGroupBoxLayout.addRow("Select data directory:", self.dataDirButton)
    self.customLUTLabel = qt.QLabel()
    self.dataSourceSelectionGroupBoxLayout.addRow(self.customLUTLabel)
    self.inputDirLabel = qt.QLabel()
    self.dataSourceSelectionGroupBoxLayout.addRow(self.inputDirLabel)
    self.resultsDirLabel = qt.QLabel()
    self.dataSourceSelectionGroupBoxLayout.addRow(self.resultsDirLabel)
    self.checkAndSetLUT()

    #
    # Step 2: selection of the study to be analyzed
    #
    # TODO: add here source directory selector
    self.studiesView = qt.QListView()
    self.studiesView.setObjectName('StudiesTable')
    self.studiesView.setSpacing(3)
    self.studiesModel = qt.QStandardItemModel()
    self.studiesModel.setHorizontalHeaderLabels(['Study ID'])
    self.studiesView.setModel(self.studiesModel)
    self.studiesView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
    self.studiesView.connect('clicked(QModelIndex)', self.studySelected)
    self.dataDirLabel = qt.QLabel()
    self.dataDirLabel.text = "Current Data Dir: "
    self.studySelectionGroupBoxLayout.addWidget(self.dataDirLabel)
    self.studySelectionGroupBoxLayout.addWidget(self.studiesView)

    #
    # Step 3: series selection
    #
    self.seriesView = qt.QListView()
    self.seriesView.setObjectName('SeriesTable')
    self.seriesView.setSpacing(3)
    self.seriesModel = qt.QStandardItemModel()
    self.seriesModel.setHorizontalHeaderLabels(['Series ID'])
    self.seriesView.setModel(self.seriesModel)
    self.seriesView.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
    self.seriesView.connect('clicked(QModelIndex)', self.seriesSelected)
    self.seriesView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
    self.seriesSelectionGroupBoxLayout.addWidget(self.seriesView)

    #
    # Step 4: segmentation tools
    #

    # reference node selector
    # TODO: use MRML selector here ?
    self.refSelector = qt.QComboBox()
    self.segmentationGroupBoxLayout.addRow(qt.QLabel("Reference image: "), self.refSelector)
    self.refSelector.connect('currentIndexChanged(int)', self.onReferenceChanged)
    
    self.advancedSettingsArea = ctk.ctkCollapsibleButton()
    self.advancedSettingsArea.text = "Advanced Settings"
    self.advancedSettingsArea.collapsed = True
    advancedSettingsLayout = qt.QFormLayout(self.advancedSettingsArea)
    
    # Show all/reference
    self.viewGroup = qt.QButtonGroup()
    self.multiView = qt.QRadioButton('All')
    self.singleView = qt.QRadioButton('Reference only')
    self.multiView.setChecked(1)
    self.viewGroup.addButton(self.multiView,1)
    self.viewGroup.addButton(self.singleView,2)
    self.viewGroup.connect('buttonClicked(int)', self.onViewUpdateRequested)
    self.groupWidget = qt.QGroupBox()
    self.groupLayout = qt.QFormLayout(self.groupWidget)
    self.groupLayout.addRow(self.multiView, self.singleView)
    advancedSettingsLayout.addRow("Show series: ", self.groupWidget)
    
    # Change viewer orientation
    self.orientationBox = qt.QGroupBox()
    self.orientationBox.setLayout(qt.QFormLayout())
    self.orientationButtons = {}
    self.orientations = ("Axial", "Sagittal", "Coronal")
    for orientation in self.orientations:
      self.orientationButtons[orientation] = qt.QRadioButton()
      self.orientationButtons[orientation].text = orientation
      self.orientationButtons[orientation].connect("clicked()", lambda o=orientation: self.setOrientation(o))
      self.orientationBox.layout().addWidget(self.orientationButtons[orientation])
    self.orientationButtons['Axial'].setChecked(1)
    self.currentOrientation = 'Axial'
    advancedSettingsLayout.addRow('View orientation: ', self.orientationBox)
    
    # Multi-volume frame controller
    self.mvSlider = ctk.ctkSliderWidget()
    self.mvSlider.connect('valueChanged(double)', self.onSliderChanged)
    self.mvSlider.enabled = False
    advancedSettingsLayout.addRow('Frame Number: ', self.mvSlider)
    
    self.segmentationGroupBoxLayout.addRow(self.advancedSettingsArea)
    
    self.translateArea = ctk.ctkCollapsibleButton()
    self.translateArea.text = "Translate Selected Label Map"
    
    translateAreaLayout = qt.QFormLayout(self.translateArea)
    
    self.translateLR = slicer.qMRMLSliderWidget()
    self.translateLR.minimum = -200
    self.translateLR.maximum = 200
    self.translateLR.connect('valueChanged(double)', self.onTranslate)
    
    self.translatePA = slicer.qMRMLSliderWidget()
    self.translatePA.minimum = -200
    self.translatePA.maximum = 200
    self.translatePA.connect('valueChanged(double)', self.onTranslate)
    
    self.translateIS = slicer.qMRMLSliderWidget()
    self.translateIS.minimum = -200
    self.translateIS.maximum = 200
    self.translateIS.connect('valueChanged(double)', self.onTranslate)
    
    translateAreaLayout.addRow("Translate LR: ", self.translateLR)
    translateAreaLayout.addRow("Translate PA: ", self.translatePA)
    translateAreaLayout.addRow("Translate IS: ", self.translateIS)
    
    self.hardenTransformButton = qt.QPushButton("Harden Transform")
    self.hardenTransformButton.enabled = False
    self.hardenTransformButton.connect('clicked(bool)', self.onHardenTransform)
    translateAreaLayout.addRow(self.hardenTransformButton)
    
    self.translateArea.collapsed = 1
    
    self.ignoreTranslate = False
    
    # Create a transform node
    self.transformNode = slicer.vtkMRMLLinearTransformNode()
    self.transformNode.SetName('PCampReview-transform')
    slicer.mrmlScene.AddNode(self.transformNode)
    
    self.segmentationGroupBoxLayout.addRow(self.translateArea)

    editorWidgetParent = slicer.qMRMLWidget()
    editorWidgetParent.setLayout(qt.QVBoxLayout())
    editorWidgetParent.setMRMLScene(slicer.mrmlScene)
    self.editorWidget = EditorWidget(parent=editorWidgetParent)
    self.editorWidget.setup()

    volumesFrame = self.editorWidget.volumes
    # hide unwanted widgets
    for widgetName in ['AllButtonsFrameButton','ReplaceModelsCheckBox',
      'MasterVolumeFrame','MergeVolumeFrame','SplitStructureButton']:
      widget = slicer.util.findChildren(volumesFrame,widgetName)[0]
      widget.hide()

    perStructureFrame = slicer.util.findChildren(volumesFrame,
                        'PerStructureVolumesFrame')[0]
    perStructureFrame.collapsed = False
    
    self.structuresView = slicer.util.findChildren(volumesFrame,'StructuresView')[0]
    self.structuresView.connect("activated(QModelIndex)", self.onStructureClicked)

    buttonsFrame = slicer.util.findChildren(volumesFrame,'ButtonsFrame')[0]
    '''
    updateViewsButton = qt.QPushButton('Update Views')
    buttonsFrame.layout().addWidget(updateViewsButton)
    updateViewsButton.connect("clicked()", self.updateViews)
    '''

    redWidget = self.getLayoutManager().sliceWidget('Red')
    controller = redWidget.sliceController()
    moreButton = slicer.util.findChildren(controller,'MoreButton')[0]
    moreButton.toggle()

    deleteStructureButton = qt.QPushButton('Delete Structure')
    buttonsFrame.layout().addWidget(deleteStructureButton)
    deleteStructureButton.connect('clicked()', self.onDeleteStructure)

    propagateButton = qt.QPushButton('Propagate Structure')
    buttonsFrame.layout().addWidget(propagateButton)
    propagateButton.connect('clicked()', self.onPropagateROI)

    #self.editorWidget.toolsColor.frame.setVisible(False)
    self.editorWidget.toolsColor.colorSpin.setEnabled(False)
    self.editorWidget.toolsColor.colorPatch.setEnabled(False)

    self.editorParameterNode = self.editUtil.getParameterNode()
    self.editorParameterNode.SetParameter('propagationMode',
                             str(slicer.vtkMRMLApplicationLogic.LabelLayer))

    self.segmentationGroupBoxLayout.addRow(editorWidgetParent)

    self.modelsVisibility = True
    modelsFrame = qt.QFrame()
    modelsHLayout = qt.QHBoxLayout(modelsFrame)
    perStructureFrame.layout().addWidget(modelsFrame)

    modelsLabel = qt.QLabel('Structure Models: ')
    modelsHLayout.addWidget(modelsLabel)

    buildModelsButton = qt.QPushButton('Make')
    modelsHLayout.addWidget(buildModelsButton)
    buildModelsButton.connect("clicked()", self.onBuildModels)

    self.modelsVisibilityButton = qt.QPushButton('Hide')
    self.modelsVisibilityButton.checkable = True
    modelsHLayout.addWidget(self.modelsVisibilityButton)
    self.modelsVisibilityButton.connect("toggled(bool)", self.onModelsVisibilityButton)
    
    self.labelMapOutlineButton = qt.QPushButton('Outline')
    self.labelMapOutlineButton.checkable = True
    modelsHLayout.layout().addWidget(self.labelMapOutlineButton)
    self.labelMapOutlineButton.connect('toggled(bool)', self.setLabelOutline)
    
    self.enableJumpToROI = qt.QCheckBox()
    self.enableJumpToROI.setText("Jump to ROI")
    modelsHLayout.addWidget(self.enableJumpToROI)
    
    modelsHLayout.addStretch(1)

    # keep here names of the views created by CompareVolumes logic
    self.viewNames = []

    #
    # Step 6: save results
    #
    #self.step5frame = ctk.ctkCollapsibleButton()
    #self.step5frame.text = "Step 5: Save results"
    #self.layout.addWidget(self.step5frame)

    # Layout within the dummy collapsible button
    #step5Layout = qt.QFormLayout(self.step5frame)
    # TODO: add here source directory selector

    self.qaButton = qt.QPushButton("PI-RADS v2 review form")
    self.completionGroupBoxLayout.addWidget(self.qaButton)
    self.qaButton.connect('clicked()',self.onQAFormClicked)

    self.saveButton = qt.QPushButton("Save")
    self.completionGroupBoxLayout.addWidget(self.saveButton)
    self.saveButton.connect('clicked()', self.onSaveClicked)

    '''
    self.piradsButton = qt.QPushButton("PI-RADS review")
    self.layout.addWidget(self.piradsButton)
    # self.piradsButton.connect('clicked()',self.onPiradsClicked)
    '''

    # Add vertical spacer
    self.layout.addStretch(1)

    self.volumesLogic = slicer.modules.volumes.logic()

    # set up temporary directory
    self.tempDir = os.path.join(slicer.app.temporaryPath, 'PCampReview-tmp')
    self.createDirectory(self.tempDir, message='Temporary directory location: ' + self.tempDir)

    # these are the PK maps that should be loaded
    self.pkMaps = ['Ktrans','Ve','Auc','TTP','MaxSlope']
    self.volumeNodes = {}
    self.refSelectorIgnoreUpdates = False
    self.selectedStudyName = None

    if os.path.exists(self.inputDataDir):
      self.tabWidget.setCurrentIndex(1)

  def enter(self):
    userName = self.getSetting('UserName')
    self.webFormURL = self.getSetting('webFormURL')

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

    if self.webFormURL is None or self.webFormURL == '':
      # prompt the user for the review form
      # Note: it is expected that the module uses the form of the structure as
      # in http://goo.gl/nT1z4L. The known structure of the form is used to
      # pre-populate the fields corresponding to readerName, studyName and
      # lesionID.
      self.URLPrompt = qt.QDialog()
      self.URLPromptLayout = qt.QVBoxLayout()
      self.URLPrompt.setLayout(self.URLPromptLayout)
      self.URLLabel = qt.QLabel('Enter review form URL:', self.URLPrompt)
      # replace this if you are using a different form
      self.URLText = qt.QLineEdit(self.VIEWFORM_URL)
      self.URLButton = qt.QPushButton('OK', self.URLPrompt)
      self.URLButton.connect('clicked()', self.onURLEntered)
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
      print('Setting inputlocation in settings to '+inputLocation)
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

    self.currentStep = 1

  def checkAndSetLUT(self):
    # Default to module color table
    self.colorFile = os.path.join(self.resourcesPath, "Colors/PCampReviewColors.csv")
    self.customLUTLabel.text = 'Using Default LUT'

    # Check for custom LUT
    if os.path.exists(self.inputDataDir):
      lookupTableLoc = os.path.join(self.inputDataDir, 'SETTINGS', self.inputDataDir.split(os.sep)[-1] + '-LUT.csv')
      print('Checking for lookup table at : ' + lookupTableLoc)
      if os.path.isfile(lookupTableLoc):
        # use custom color table
        self.colorFile = lookupTableLoc
        self.customLUTLabel.text = 'Project-Specific LUT Found'

    # Set merge volume in structureListWidget to None so Editor doesn't get confused by missing node
    # This may be the first time we get here, in which case editorWidget is not
    # created yet.  If it has been created, structureListWidget.merge is probably set to
    # something that has been removed from the scene by onStep3Select.
    try:
      self.editorWidget.helper.structureListWidget.merge = None
    except:
      pass
      


    # setup the color table, make sure PCampReview LUT is a singleton
    allColorTableNodes = slicer.util.getNodes('vtkMRMLColorTableNode*').values()
    for ctn in allColorTableNodes:
      if ctn.GetName() == 'PCampReview':
        slicer.mrmlScene.RemoveNode(ctn)
        break

    self.PCampReviewColorNode = slicer.vtkMRMLColorTableNode()
    colorNode = self.PCampReviewColorNode
    colorNode.SetName('PCampReview')
    slicer.mrmlScene.AddNode(colorNode)
    colorNode.SetTypeToUser()
    with open(self.colorFile) as f:
      n = sum(1 for line in f)
    colorNode.SetNumberOfColors(n-1)
    colorNode.NamesInitialisedOn()
    import csv
    self.structureNames = []
    with open(self.colorFile, 'rb') as csvfile:
      reader = csv.DictReader(csvfile, delimiter=',')
      for index,row in enumerate(reader):
        success = colorNode.SetColor(index ,row['Label'],float(row['R'])/255,
                float(row['G'])/255,float(row['B'])/255,float(row['A']))
        if not success:
          print "color %s could not be set" % row['Label']
        self.structureNames.append(row['Label'])
      
  def onNameEntered(self):
    name = self.nameText.text
    if len(name)>0:
      self.setSetting('UserName', name)
      self.namePrompt.close()
      self.parameters['UserName'] = name

  def onURLEntered(self):
    url = self.URLText.text
    if len(url)>0:
      self.setSetting('webFormURL',url)
      self.URLPrompt.close()
      self.webFormURL = url

  def onResultsDirEntered(self):
    path = self.dirButton.directory
    if len(path)>0:
      self.setSetting('ResultsLocation',path)
      self.dirPrompt.close()
      self.parameters['ResultsLocation'] = path

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

  def studySelected(self, modelIndex):
    print('Row selected: '+self.studiesModel.item(modelIndex.row(),0).text())
    selectionModel = self.studiesView.selectionModel()
    print('Selection model says row is selected: '+str(selectionModel.isRowSelected(modelIndex.row(),qt.QModelIndex())))
    print('Row number: '+str(modelIndex.row()))
    self.selectedStudyName = self.studiesModel.item(modelIndex.row(),0).text()
    self.setTabsEnabled([2], True)

  def seriesSelected(self, modelIndex):
    print('Row selected: '+self.seriesModel.item(modelIndex.row(),0).text())
    selectionModel = self.seriesView.selectionModel()
    print('Selection model says row is selected: '+str(selectionModel.isRowSelected(modelIndex.row(),qt.QModelIndex())))
    print('Row number: '+str(modelIndex.row()))
    self.setTabsEnabled([3], True)

  def onQAFormClicked(self):
    self.webView = qt.QWebView()
    self.webView.settings().setAttribute(qt.QWebSettings.DeveloperExtrasEnabled, True)
    self.webView.connect('loadFinished(bool)', self.webViewFormLoadedCallback)
    self.webView.show()
    preFilledURL = self.webFormURL
    preFilledURL += '?entry.1455103354='+self.getSetting('UserName')
    preFilledURL += '&entry.347120626='+self.selectedStudyName
    preFilledURL += '&entry.1734306468='+str(self.editorWidget.toolsColor.colorSpin.value)
    u = qt.QUrl(preFilledURL)
    self.webView.setUrl(u)

  def webViewFormLoadedCallback(self,ok):
    if not ok:
      print('page did not load')
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
    segmentationsDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'Segmentations')
    wlSettingsDir = os.path.join(self.inputDataDir, self.selectedStudyName, 'WindowLevelSettings')

    self.createDirectory(segmentationsDir)
    self.createDirectory(wlSettingsDir)

    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    
    # save all label nodes (there should be only one per volume!)
    labelNodes = slicer.util.getNodes('*-label*')
    print('All label nodes found: '+str(labelNodes))
    savedMessage = 'Segmentations for the following series were saved:\n\n'
    for label in labelNodes.values():

      labelSeries = label.GetName().split(':')[0]
      labelName =  label.GetName().split(':')[1]

      # structure is root -> study -> resources -> series # ->
      # Segmentations/Reconstructions/OncoQuant -> files
      segmentationsDir = os.path.join(self.inputDataDir, self.selectedStudyName,
                                      'RESOURCES', labelSeries, 'Segmentations')
      self.createDirectory(segmentationsDir)

      structureName = labelName[labelName[:-6].rfind("-")+1:-6]
      # Only save labels with known structure names
      if any(structureName == s for s in self.structureNames):
        print "structure name is:" ,structureName
        uniqueID = self.getSetting('UserName')+'-'+structureName+'-'+timestamp

        labelFileName = os.path.join(segmentationsDir,uniqueID+'.nrrd')

        sNode = slicer.vtkMRMLVolumeArchetypeStorageNode()
        sNode.SetFileName(labelFileName)
        sNode.SetWriteFileFormat('nrrd')
        sNode.SetURI(None)
        success = sNode.WriteData(label)
        if success:
          savedMessage = savedMessage + label.GetName()+'\n'
          print(label.GetName()+' has been saved to '+labelFileName)

    # save w/l settings for all non-label volume nodes
    '''
    volumeNodes = slicer.util.getNodes('vtkMRMLScalarVolumeNode*')
    print('All volume nodes: '+str(volumeNodes))
    for key in volumeNodes.keys():
      vNode = volumeNodes[key]
      if vNode.GetAttribute('LabelMap') == '1':
        continue
      seriesNumber = string.split(key,':')[0]
      print('W/L for series '+seriesNumber+' is '+str(vNode.GetDisplayNode().GetWindow()))
      f = open(wlSettingsDir+'/'+seriesNumber+'-wl.txt','w')
      f.write(str(vNode.GetDisplayNode().GetWindow())+' '+str(vNode.GetDisplayNode().GetLevel()))
      f.close()
    '''

    self.infoPopup(savedMessage)

  def onInputDirSelected(self):
    self.inputDataDir = qt.QFileDialog.getExistingDirectory(self.parent,
                                                            'Input data directory',
                                                            self.inputDataDir)
    if self.inputDataDir != "":
      self.dataDirButton.text = self.inputDataDir
      self.setSetting('InputLocation', self.inputDataDir)
      self.checkAndSetLUT()
      print('Directory selected:')
      print(self.inputDataDir)
      print(self.getSetting('InputLocation'))
      self.tabWidget.setCurrentIndex(1)

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
        if node.GetName() == 'PCampReview-'+refLongName:
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
        outHierarchy.SetName( 'PCampReview-'+refLongName )
        slicer.mrmlScene.AddNode( outHierarchy )

      progress = self.makeProgressIndicator(len(labelNodes))
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
          if progress.wasCanceled:
            break

          try:
            modelMaker = slicer.modules.modelmaker
            self.CLINode = slicer.cli.run(modelMaker, self.CLINode,
                           parameters, wait_for_completion=True)
          except AttributeError:
            qt.QMessageBox.critical(slicer.util.mainWindow(),'Editor', 'The ModelMaker module is not available<p>Perhaps it was disabled in the application settings or did not load correctly.')
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
          self.updateViewRenderers()

  def removeAllModels(self):
    modelHierarchyNodes = []
    numNodes = slicer.mrmlScene.GetNumberOfNodesByClass( "vtkMRMLModelHierarchyNode" )
    for n in xrange(numNodes):
      node = slicer.mrmlScene.GetNthNodeByClass( n, "vtkMRMLModelHierarchyNode")
      if node.GetName()[:12] == 'PCampReview-':
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
        if node.GetName() == 'PCampReview-'+refLongName:
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
            if toggled:
              displayNode.SetSliceIntersectionVisibility(0)
              self.modelsVisibilityButton.setText('Show')
            else:
              displayNode.SetSliceIntersectionVisibility(1)
              self.modelsVisibilityButton.setText('Hide')
          self.updateViewRenderers()

  def findElement(self, dom, name):
    els = dom.getElementsByTagName('element')
    for e in els:
      if e.getAttribute('name') == name:
        return e.childNodes[0].nodeValue

  def getSeriesInfoFromXML(self, f):
    dom = xml.dom.minidom.parse(f)
    number = self.findElement(dom, 'SeriesNumber')
    name = self.findElement(dom, 'SeriesDescription')
    name = name.replace('-','')
    name = name.replace('(','')
    name = name.replace(')','')
    return number,name

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
      print('Setting loaded label name to '+volumeName)
      actualFileName = os.path.split(fileName)[1]
      structureID = actualFileName.split("-")[1] # expectation: username-structure-timestamp.nrrd
      label.SetName(volumeName+'-'+structureID+'-label')
      label.RemoveAllDisplayNodeIDs()

      dNode = slicer.vtkMRMLLabelMapVolumeDisplayNode()
      slicer.mrmlScene.AddNode(dNode)
      dNode.SetAndObserveColorNodeID(self.PCampReviewColorNode.GetID())
      label.SetAndObserveDisplayNodeID(dNode.GetID())

      print('Label loaded, storage node is '+label.GetStorageNode().GetID())

    #return (True,label)
    return True

  def setTabsEnabled(self, indexes, enabled):
    for index in indexes:
      self.tabBar.setTabEnabled(index, enabled)

  def checkStep4or5Leave(self):
    if self.currentStep == 4 or self.currentStep == 5:
      continueCurrentStep = self.showExitStep4Or5Warning()
      if continueCurrentStep:
        self.tabWidget.setCurrentIndex(self.currentStep-1)
        return True
      else:
        self.removeAllModels()
    return False

  def onStep1Selected(self):
    if self.checkStep4or5Leave() is True:
      return
    if self.currentStep == 1:
      return
    self.currentStep = 1
    self.setTabsEnabled([2,3,4], False)
    if self.inputDataDir != "":
      self.setTabsEnabled([1], True)

  def onStep2Selected(self):
    if self.checkStep4or5Leave() is True:
      return
    if self.currentStep == 2:
      return
    self.currentStep = 2
    self.setTabsEnabled([1],True)
    self.setTabsEnabled([2,3,4], False)

    studyDirs = []
    # get list of studies
    self.dataDirLabel.text = "Current Data Dir: " + str(self.inputDataDir +"\n")
    if not os.path.exists(self.inputDataDir):
      return

    dirs = os.listdir(self.inputDataDir)
    
    progress = self.makeProgressIndicator(len(dirs))
    nLoaded = 0
    
    for studyName in dirs:
      if os.path.isdir(os.path.join(self.inputDataDir, studyName)) and studyName != 'SETTINGS':
        studyDirs.append(studyName)
        print('Appending '+studyName)
        progress.setValue(nLoaded)
        nLoaded += 1

    self.studiesModel.clear()
    self.studyItems = []
    for s in studyDirs:
      sItem = qt.QStandardItem(s)
      self.studyItems.append(sItem)
      self.studiesModel.appendRow(sItem)
      print('Appended to model study '+s)
    # TODO: unload all volume nodes that are already loaded
    
    progress.delete()

  def onStep3Selected(self):
    if self.checkStep4or5Leave() is True:
      return
    if self.currentStep == 3 or not self.selectedStudyName:
      return

    self.currentStep = 3

    self.setTabsEnabled([2],True)
    self.setTabsEnabled([4], False)
    print('Entering step 3')

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

    self.parameters['StudyName'] = self.selectedStudyName

    self.resourcesDir = os.path.join(self.inputDataDir,self.selectedStudyName,'RESOURCES')

    # Loading progress indicator
    progress = self.makeProgressIndicator(len(os.listdir(self.resourcesDir)))
    nLoaded = 0

    # expect one directory for each processed series, with the name
    # corresponding to the series number
    self.seriesMap = {}
    for root,subdirs,files in os.walk(self.resourcesDir):
      print('Root: '+root+', files: '+str(files))
      resourceType = os.path.split(root)[1]
      print('Resource: '+resourceType)

      if resourceType == 'Reconstructions':
        for f in files:
          print('File: '+f)
          if f.endswith('.xml'):
            metaFile = os.path.join(root,f)
            print('Ends with xml: '+metaFile)
            try:
              (seriesNumber,seriesName) = self.getSeriesInfoFromXML(metaFile)
              print(str(seriesNumber)+' '+seriesName)
            except:
              print('Failed to get from XML')
              continue
              
            progress.labelText = seriesName
            progress.setValue(nLoaded)
            nLoaded += 1
            
            volumePath = os.path.join(root,seriesNumber+'.nrrd')
            self.seriesMap[seriesNumber] = {'MetaInfo':None, 'NRRDLocation':volumePath,'LongName':seriesName}
            self.seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+seriesName
            # self.helper.abbreviateName(self.seriesMap[seriesNumber]['MetaInfo'])

      # ignore the PK maps for the purposes of segmentation
      if resourceType == 'OncoQuant' and False:
        for f in files:
          if f.endswith('.json'):
            metaFile = open(os.path.join(root,f))
            metaInfo = json.load(metaFile)
            print('JSON meta info: '+str(metaInfo))
            try:
              seriesNumber = metaInfo['SeriesNumber']
              seriesName = metaInfo['SeriesDescription']
            except:
              seriesNumber = metaInfo['DerivedSeriesNumber']
              seriesName = metaInfo['ModelType']+'-'+metaInfo['AIF']+'-'+metaInfo['Parameter']
            volumePath = os.path.join(root,seriesNumber+'.nrrd')
            self.seriesMap[seriesNumber] = {'MetaInfo':metaInfo, 'NRRDLocation':volumePath,'LongName':seriesName}
            self.seriesMap[seriesNumber]['ShortName'] = str(seriesNumber)+":"+self.logic.abbreviateName(self.seriesMap[seriesNumber]['MetaInfo'])

    print('All series found: '+str(self.seriesMap.keys()))

    numbers = [int(x) for x in self.seriesMap.keys()]
    numbers.sort()

    tableItems = []
    for num in numbers:
      desc = self.seriesMap[str(num)]['LongName']
      tableItems.append(str(num)+':'+desc)

    self.seriesModel.clear()
    self.seriesItems = []

    for s in numbers:
      seriesText = str(s)+':'+self.seriesMap[str(s)]['LongName']
      sItem = qt.QStandardItem(seriesText)
      self.seriesItems.append(sItem)
      self.seriesModel.appendRow(sItem)
      sItem.setCheckable(1)
      if self.logic.isSeriesOfInterest(seriesText):
        sItem.setCheckState(2)

    progress.delete()
    self.setTabsEnabled([3], True)

  def onStep4Selected(self):
    # set up editor
    if self.currentStep == 4:
      return
    if self.currentStep == 5:
      self.currentStep = 4
      return
    self.currentStep = 4
    self.setTabsEnabled([3,4],True)

    self.editorWidget.enter()
    
    self.resetTranslate()

    checkedItems = [x for x in self.seriesItems if x.checkState()]

    # item.CheckState() != 0

    # if no series selected, go to the previous step
    if len(checkedItems) == 0:
      self.onStep3Selected()
      return

    self.volumeNodes = {}
    self.labelNodes = {}
    selectedSeriesNumbers = []
    self.refSeriesNumber = '-1'

    print('Checked items:')
    ref = None

    self.refSelector.clear()

    # reference selector can have None (initially)
    # user should select reference, which triggers creation of the label and

    # initialization of the editor widget

    self.refSelector.addItem('None')

    # ignore refSelector events until the selector is populated!
    self.refSelectorIgnoreUpdates = True
    
    # Loading progress indicator
    progress = self.makeProgressIndicator(len(checkedItems))
    nLoaded = 0

    # iterate over all selected items and add them to the reference selector
    selectedSeries = {}
    for i in checkedItems:
      text = i.text()
      
      progress.labelText = text
      progress.setValue(nLoaded)
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
          self.seriesMap[seriesNumber]['Volume'] = self.logic.extractFrame(None,
                                                                     self.seriesMap[seriesNumber]['MultiVolume'], 
                                                                     self.seriesMap[seriesNumber]['FrameNumber'])
          
      else:
        print('Failed to load image volume!')
        return
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
      print('Processed '+longName)

      selectedSeriesNumbers.append(int(seriesNumber))

    self.seriesMap = selectedSeries
    
    progress.delete()

    print('Selected series: '+str(selectedSeries)+', reference: '+str(ref))
    #self.cvLogic = CompareVolumes.CompareVolumesLogic()
    #self.viewNames = [self.seriesMap[str(ref)]['ShortName']]

    self.refSelectorIgnoreUpdates = False

  def onStep5Selected(self):
    self.currentStep = 5

  def showExitStep4Or5Warning(self):
    result = self.confirmOrSaveDialog('Unsaved contours will be lost!\n\nDo you still want to exit?')
    if result == 1:
      self.onSaveClicked()
    return result == 2

  def onReferenceChanged(self, id):
    self.removeAllModels()
    if self.refSelectorIgnoreUpdates:
      return
    text = self.refSelector.currentText
    print('Current reference node: '+text)
    if text != 'None' and text != '':
      self.refSeriesNumber = string.split(text,':')[0]
      ref = int(self.refSeriesNumber)
    else:
      return

    print('Reference series selected: '+str(ref))

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
      
    # Check for MultiVolume
    try:
      mvNode = self.seriesMap[str(ref)]['MultiVolume']
      nFrames = mvNode.GetNumberOfFrames()
      self.mvSlider.minimum = 0
      self.mvSlider.maximum = nFrames-1
      self.mvSlider.value = self.seriesMap[str(ref)]['FrameNumber']
      self.mvSlider.enabled = True
    except KeyError:
      self.mvSlider.minimum = 0
      self.mvSlider.maximum = 0
      self.mvSlider.enabled = False
      
    dNode = refLabel.GetDisplayNode()
    dNode.SetAndObserveColorNodeID(self.PCampReviewColorNode.GetID())
    print('Volume nodes: '+str(self.viewNames))
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

    self.cvLogic.viewerPerVolume(self.volumeNodes, background=self.volumeNodes[0], label=refLabel,layout=[self.rows,self.cols],viewNames=self.sliceNames,orientation=self.currentOrientation)

    # Make sure redslice has the ref image (the others were set with viewerPerVolume)
    redSliceWidget = self.getLayoutManager().sliceWidget('Red')
    redSliceNode = redSliceWidget.mrmlSliceNode()
    redSliceNode.SetOrientation(self.currentOrientation)
    compositeNode = redSliceWidget.mrmlSliceCompositeNode()
    compositeNode.SetBackgroundVolumeID(self.volumeNodes[0].GetID())
    
    self.cvLogic.rotateToVolumePlanes(self.volumeNodes[0])
    self.setOpacityOnAllSliceWidgets(1.0)
    self.editUtil.setLabelOutline(self.labelMapOutlineButton.checked)
    
    self.onViewUpdateRequested(self.viewGroup.checkedId())

    print('Setting master node for the Editor to '+self.volumeNodes[0].GetID())

    self.editorParameterNode.Modified()
    
    # default to selecting the first available structure for this volume
    if self.editorWidget.helper.structureListWidget.structures.rowCount() > 0:
      self.editorWidget.helper.structureListWidget.selectStructure(0)

    self.updateEditorAvailability()

    print('Exiting onReferenceChanged')

  '''
  def updateViews(self):
    lm = slicer.app.layoutManager()
    w = lm.sliceWidget('Red')
    sl = w.sliceLogic()
    ll = sl.GetLabelLayer()
    lv = ll.GetVolumeNode()
    self.cvLogic.viewerPerVolume(self.volumeNodes, background=self.volumeNodes[0], label=lv, layout=[self.rows,self.cols])

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
      if not self.confirmDialog( "Delete \'%s\' volume?" % selectedModelVol ):
        return
      
      # Cleanup files
      import shutil

      # create backup directory if necessary
      backupSegmentationsDir = os.path.join(self.inputDataDir, self.selectedStudyName,
                                            'RESOURCES', self.refSeriesNumber, 'Backup')
      self.createDirectory(backupSegmentationsDir)
      # move relevant nrrd files
      globPath = os.path.join(self.resourcesDir,self.refSeriesNumber,"Segmentations",
                              self.getSetting('UserName')+'-'+selectedModelVol+'-[0-9]*.nrrd')
      previousSegmentations = glob.glob(globPath)
              
      filesMoved = True
      for file in previousSegmentations:
        try:
          shutil.move(file, backupSegmentationsDir)
        except:
          print('Unable to move file: '+file)
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
    try:
      self.seriesMap[self.refSeriesNumber]['Volume'] = self.logic.extractFrame(self.seriesMap[self.refSeriesNumber]['Volume'],
                                                                       self.seriesMap[self.refSeriesNumber]['MultiVolume'], 
                                                                       newValue)
      self.seriesMap[self.refSeriesNumber]['FrameNumber'] = newValue
      self.seriesMap[self.refSeriesNumber]['MultiVolume'].GetDisplayNode().SetFrameComponent(newValue)
    except:
      # can get an event on reference switchover from a multivolume
      pass

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
    
    propagateLabel = qt.QLabel('Select which volumes you wish to propagate '+ selectedLabel +' to...', self.propagatePrompt)
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
    existingStructures = [self.seriesMap[x]['ShortName'] for x in propagateInto if len(slicer.util.getNodes(self.seriesMap[x]['ShortName']+'-'+selectedStructure+'-label*')) != 0]
    if len(existingStructures) != 0:
      msg = 'ERROR\n\n\'' + selectedStructure + '\' already exists in the following volumes:\n\n'
      for vol in existingStructures:
        msg += vol + '\n'
      msg += '\nCannot propagate on top of existing structures.  Delete the existing structures and try again.\n'
      self.infoPopup(msg)
      return
      
    # Create identity transform
    transform = slicer.vtkMRMLLinearTransformNode()
    slicer.mrmlScene.AddNode(transform)
    
    # Collects empty dstLabel volumes
    emptyDstLabel = []
    
    # Do the resamples
    progress = self.makeProgressIndicator(len(propagateInto))
    nProcessed = 0
    for dstSeries in propagateInto:
      labelName = self.seriesMap[dstSeries]['ShortName']+'-'+selectedStructure+'-label'
      dstLabel = self.volumesLogic.CreateAndAddLabelVolume(slicer.mrmlScene,self.seriesMap[dstSeries]['Volume'],labelName)
      # Need to make sure the new label volume has the correct name
      dstLabel.SetName(labelName)
      dstLabel.GetDisplayNode().SetAndObserveColorNodeID(self.PCampReviewColorNode.GetID())
      
      progress.labelText = labelName
      
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
      self.__cliNode = slicer.cli.run(slicer.modules.brainsresample, self.__cliNode, parameters, wait_for_completion=True)
      
      # Check to make sure we actually got something in the dstLabel volume
      dstLabelAddress = sitkUtils.GetSlicerITKReadWriteAddress(dstLabel.GetName())
      dstLabelImage = sitk.ReadImage(dstLabelAddress)

      ls = sitk.LabelStatisticsImageFilter()
      ls.Execute(dstLabelImage,dstLabelImage)
      bb = ls.GetBoundingBox(selectedLabelID)
      
      if len(bb) == 0:
        emptyDstLabel.append(dstLabel)
        print(labelName + " IS EMPTY")
      
      progress.setValue(nProcessed)
      nProcessed += 1
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
      
      if self.yesNoDialog(msg) == 0:
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
    self.transformNode.Reset()
      
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
        print('Using order = IS')
        result = IJKtoRAS.MultiplyPoint((self.translateLR.value, self.translatePA.value, self.translateIS.value, 0))
        vTransform.Translate(result[0],result[1],result[2])
    elif order == 'AP':
        print('Using order = AP')
        result = IJKtoRAS.MultiplyPoint((self.translateLR.value, self.translateIS.value, self.translatePA.value, 0))
        vTransform.Translate(result[0],result[1],result[2])
    elif order == 'LR':
        print('Using order = LR')
        result = IJKtoRAS.MultiplyPoint((self.translatePA.value, self.translateIS.value, self.translateLR.value, 0))
        vTransform.Translate(-result[0],result[1],result[2])

    print result
    
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
    layoutManager = self.getLayoutManager()
    for view in layoutManager.sliceViewNames():
      widget = layoutManager.sliceWidget(view)
      compositeNode = widget.mrmlSliceCompositeNode()
      try:
        compositeNode.SetForegroundVolumeID(self.seriesMap[view]['Volume'].GetID())
      except:
        pass

  # Gets triggered on a click in the structures table
  def onStructureClicked(self,index):
    selectedLabelID = int(self.editorWidget.helper.structureListWidget.structures.item(index.row(),0).text())
    selectedLabelVol = self.editorWidget.helper.structureListWidget.structures.item(index.row(),3).text()
    if self.enableJumpToROI.checked:
      print('calling onJumpToROI '+str(selectedLabelID) + ' ' + selectedLabelVol)
      self.onJumpToROI(selectedLabelID,selectedLabelVol)
    self.updateEditorAvailability()

  def onJumpToROI(self, selectedLabelID, selectedLabelVol):
    redSliceWidget = self.getLayoutManager().sliceWidget('Red')
    redSliceNode = redSliceWidget.mrmlSliceNode()
    redSliceOffset = redSliceNode.GetSliceOffset()
    
    print('Jumping to ROI #' + str(selectedLabelID))
    labelNode = slicer.util.getNode(selectedLabelVol)
    print('Using label node '+labelNode.GetID())
    labelAddress = sitkUtils.GetSlicerITKReadWriteAddress(labelNode.GetName())
    labelImage = sitk.ReadImage(labelAddress)

    ls = sitk.LabelStatisticsImageFilter()
    ls.Execute(labelImage,labelImage)
    bb = ls.GetBoundingBox(selectedLabelID)
    
    if len(bb) > 0:
      # Average to get the center of the BB
      i_center = ((bb[0] + bb[1]) / 2)
      j_center = ((bb[2] + bb[3]) / 2)
      k_center = ((bb[4] + bb[5]) / 2)
      print('BB is: ' + str(bb))
      print('i_center = '+str(i_center))
      print('j_center = '+str(j_center))
      print('k_center = '+str(k_center))


      # Now figure out which slice to go to in RAS space based on the i,j,k coords
      # This *works* but I think its either not right or too complicated or both...
      IJKtoRAS = vtk.vtkMatrix4x4()
      labelNode.GetIJKToRASMatrix(IJKtoRAS)

      IJKtoRASDir = vtk.vtkMatrix4x4()
      labelNode.GetIJKToRASDirectionMatrix(IJKtoRASDir)

      RAScoord = IJKtoRAS.MultiplyPoint((i_center, j_center, k_center, 1))
      
      # set these in case we fall through for some reason (like we can't handle that scan order)
      sagittal_offset = redSliceOffset
      coronal_offset = redSliceOffset
      axial_offset = redSliceOffset

      order = labelNode.ComputeScanOrderFromIJKToRAS(IJKtoRAS)
      if order == 'IS':
          RASDir = IJKtoRASDir.MultiplyPoint((RAScoord[0], RAScoord[1], RAScoord[2], 1))
          sagittal_offset = -RASDir[0]
          coronal_offset  = -RASDir[1]
          axial_offset    =  RASDir[2]
      elif order == 'AP':
          RASDir = IJKtoRASDir.MultiplyPoint((RAScoord[0], RAScoord[1], RAScoord[2], 1))
          sagittal_offset = -RASDir[0]
          coronal_offset  = -RASDir[2]
          axial_offset    = -RASDir[1]
      elif order == 'LR':
          RASDir = IJKtoRASDir.MultiplyPoint((RAScoord[2], RAScoord[1], RAScoord[0], 1))
          sagittal_offset =  RASDir[0]
          coronal_offset  = -RASDir[2]
          axial_offset    = -RASDir[1]

      # Set the appropriate offset based on current orientation
      if self.currentOrientation == 'Axial':
        self.setOffsetOnAllSliceWidgets(axial_offset)
      elif self.currentOrientation == 'Coronal':
        self.setOffsetOnAllSliceWidgets(coronal_offset)
      elif self.currentOrientation == 'Sagittal':
        self.setOffsetOnAllSliceWidgets(sagittal_offset)

      # snap to IJK to try and avoid rounding errors
      sliceLogics = self.getLayoutManager().mrmlSliceLogics()
      numLogics = sliceLogics.GetNumberOfItems()
      for n in range(numLogics):
        l = sliceLogics.GetItemAsObject(n)
        l.SnapSliceOffsetToIJK()

  def onSelect(self):
    self.applyButton.enabled = self.inputSelector.currentNode() and self.outputSelector.currentNode()

  def onApplyButton(self):
    logic = PCampReviewLogic()
    print("Run the algorithm")
    logic.run(self.inputSelector.currentNode(), self.outputSelector.currentNode())


class PCampReviewLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget
  """

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
                    'BAT','-Slope','PkRsqr']
    for d in discardThose:
      if string.find(desc,d)>=0:
        return False
    return True

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
    if re.search('[a-zA-Z]',descr) is None:
      abbr = 'Subtract'
    return seriesNumber+'-'+abbr

  # Extract frame from multiVolumeNode and put it into scalarVolumeNode
  @staticmethod
  def extractFrame(scalarVolumeNode, multiVolumeNode, frameId):
    # if no scalar volume given, create one
    if scalarVolumeNode is None:
      scalarVolumeNode = slicer.vtkMRMLScalarVolumeNode()
      scalarVolumeNode.SetScene(slicer.mrmlScene)
      # name = mv node name minus _multivolume
      scalarVolumeName = multiVolumeNode.GetName().split('_multivolume')[0]
      scalarVolumeNode.SetName(scalarVolumeName)
      slicer.mrmlScene.AddNode(scalarVolumeNode)

    # Extract the image data
    mvImage = multiVolumeNode.GetImageData()
    extract = vtk.vtkImageExtractComponents()
    if vtk.VTK_MAJOR_VERSION <= 5:
      extract.SetInput(mvImage)
    else:
      extract.SetInputData(mvImage)
    extract.SetComponents(frameId)
    extract.Update()

    ras2ijk = vtk.vtkMatrix4x4()
    ijk2ras = vtk.vtkMatrix4x4()
    multiVolumeNode.GetRASToIJKMatrix(ras2ijk)
    multiVolumeNode.GetIJKToRASMatrix(ijk2ras)
    scalarVolumeNode.SetRASToIJKMatrix(ras2ijk)
    scalarVolumeNode.SetIJKToRASMatrix(ijk2ras)

    scalarVolumeNode.SetAndObserveImageData(extract.GetOutput())

    # Create display node if missing
    displayNode = scalarVolumeNode.GetDisplayNode()
    if displayNode is None:
      displayNode = slicer.mrmlScene.CreateNodeByClass('vtkMRMLScalarVolumeDisplayNode')
      displayNode.SetReferenceCount(1)
      displayNode.SetScene(slicer.mrmlScene)
      slicer.mrmlScene.AddNode(displayNode)
      displayNode.SetDefaultColorMap()
      scalarVolumeNode.SetAndObserveDisplayNodeID(displayNode.GetID())

    return scalarVolumeNode

  def __init__(self, parent=None):
    ScriptedLoadableModuleLogic.__init__(self, parent)

  def hasImageData(self,volumeNode):
    """This is a dummy logic method that
    returns true if the passed in volume
    node has valid image data
    """
    if not volumeNode:
      print('no volume node')
      return False
    if volumeNode.GetImageData() is None:
      print('no image data')
      return False
    return True

  def run(self,inputVolume,outputVolume):
    """
    Run the actual algorithm
    """
    return True


class PCampReviewTest(ScriptedLoadableModuleTest):

  def setUp(self):
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    self.setUp()
    self.test_PCampReview1()

  def test_PCampReview1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    mainWidget = slicer.modules.pcampreview.widgetRepresentation().self()
    tabWidget = mainWidget.tabWidget.childAt(0,0)

    self.delayDisplay("Starting the test here!")
    #
    # first, get some data
    #
    tabWidget.setCurrentIndex(0)
    self.delayDisplay('1')

    tabWidget.setCurrentIndex(1)
    self.delayDisplay('Study Selection')

    model = mainWidget.studiesModel
    index = model.index(0,0)

    self.assertTrue(index.isValid(), msg="No valid study index available in studytable")
    mainWidget.studySelected(index)
    tabWidget.setCurrentIndex(2)
    self.delayDisplay('Series Selection')

    tabWidget.setCurrentIndex(3)
    self.delayDisplay('Segmentation Processing')

    tabWidget.setCurrentIndex(4)
    mainWidget.saveButton.animateClick()
    self.delayDisplay('Saving')

    self.delayDisplay('Test passed!')
